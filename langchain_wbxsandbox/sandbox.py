"""WBX Sandbox backend for Deep Agents."""

from __future__ import annotations

import json
import logging
import shlex
from typing import TYPE_CHECKING, Any

import wbxsandbox
from deepagents.backends.protocol import (
    ExecuteResponse,
    FileDownloadResponse,
    FileOperationError,
    FileUploadResponse,
)
from deepagents.backends.sandbox import BaseSandbox

if TYPE_CHECKING:
    from types import TracebackType
    from typing import Self

logger = logging.getLogger(__name__)

DEFAULT_COMMAND_TIMEOUT = 30 * 60
"""Default limit for one command in seconds, used when `execute()` gets no timeout."""

DEFAULT_LIFETIME = 30 * 60
"""Default sandbox lifetime in seconds for `WBXSandbox.create()`."""

TIMEOUT_EXIT_CODE = 124
"""Exit code reported for a command stopped by its timeout (as GNU `timeout` does)."""

_STAT_TIMEOUT = 60
"""Limit in seconds for the batched path check that precedes downloads."""

# Classifies the paths to download in one round trip. Reads a JSON list of paths
# on stdin and prints a JSON list of error codes (null = the file can be read).
# Commands run as root in a WBX sandbox, and root can read any file; a file
# without any read permission bit is reported as `permission_denied`, the same
# signal an agent gets on a system that runs it as an unprivileged user.
_STAT_SCRIPT = """\
import json, os, stat, sys
out = []
for p in json.load(sys.stdin):
    try:
        st = os.stat(p)
    except (FileNotFoundError, NotADirectoryError):
        out.append("file_not_found")
        continue
    except PermissionError:
        out.append("permission_denied")
        continue
    except (OSError, ValueError):
        out.append("invalid_path")
        continue
    if stat.S_ISDIR(st.st_mode):
        out.append("is_directory")
    elif not stat.S_ISREG(st.st_mode):
        out.append("invalid_path")
    elif not st.st_mode & 0o444:
        out.append("permission_denied")
    else:
        out.append(None)
print(json.dumps(out))
"""

_STATUS_ERRORS: dict[int, FileOperationError] = {
    400: "invalid_path",
    403: "permission_denied",
    404: "file_not_found",
}
"""HTTP status of the files API → error an agent can act on. Other statuses raise."""

_ERRORS: frozenset[str] = frozenset(
    {"file_not_found", "permission_denied", "is_directory", "invalid_path"}
)
"""Error codes the in-sandbox path check may return."""


def _format_output(stdout: str, stderr: str) -> str:
    """Combine stdout and stderr into one string (stderr marked, as in other backends)."""
    err = stderr.strip()
    if not err:
        return stdout
    tagged = f"<stderr>{err}</stderr>"
    return f"{stdout}\n{tagged}" if stdout else tagged


class WBXSandbox(BaseSandbox):
    """WBX Sandbox implementation of `SandboxBackendProtocol`.

    Each WBX sandbox is a Firecracker microVM with its own Linux kernel and disk.
    Commands run through the WBX Sandbox API; the file operations (`ls`, `read`,
    `write`, `edit`, `glob`, `grep`) come from `BaseSandbox` and run inside the
    sandbox with `python3`, which every WBX template provides.

    Create a sandbox with `WBXSandbox.create()`, reattach to one with
    `WBXSandbox.connect()`, or wrap a `wbxsandbox.Sandbox` you already have.
    Call `kill()` (or use a `with` block) to destroy the sandbox when done.
    """

    def __init__(
        self,
        *,
        sandbox: wbxsandbox.Sandbox,
        timeout: int = DEFAULT_COMMAND_TIMEOUT,
    ) -> None:
        """Wrap an existing WBX sandbox.

        Args:
            sandbox: A `wbxsandbox.Sandbox` from the WBX Sandbox Python SDK.
            timeout: Default limit for one command in seconds, used when
                `execute()` is called without a timeout. `0` means no limit.
        """
        self._sandbox = sandbox
        self._default_timeout = timeout

    # ------------------------------------------------------------ lifecycle

    @classmethod
    def create(
        cls,
        *,
        template: str = "base",
        lifetime: int = DEFAULT_LIFETIME,
        timeout: int = DEFAULT_COMMAND_TIMEOUT,
        url: str | None = None,
        api_key: str | None = None,
        **kwargs: Any,
    ) -> WBXSandbox:
        """Create a new sandbox and return a backend for it.

        Args:
            template: Sandbox template, for example `"base"` (Debian with Python).
            lifetime: Seconds until the sandbox is destroyed automatically.
            timeout: Default limit for one command in seconds (`0` = no limit).
            url: API address. Defaults to `WBXSANDBOX_URL`, then
                `https://sandbox.wbx.cz`.
            api_key: API key. Defaults to `WBXSANDBOX_API_KEY`.
            **kwargs: Passed to `wbxsandbox.Sandbox.create()`, for example
                `metadata`, `env`, `internet`, `allow` or `compute_class`.
        """
        sandbox = wbxsandbox.Sandbox.create(
            template=template, timeout=lifetime, url=url, api_key=api_key, **kwargs
        )
        return cls(sandbox=sandbox, timeout=timeout)

    @classmethod
    def connect(
        cls,
        sandbox_id: str,
        *,
        timeout: int = DEFAULT_COMMAND_TIMEOUT,
        url: str | None = None,
        api_key: str | None = None,
    ) -> WBXSandbox:
        """Attach to a running sandbox by its ID (for example in a later session)."""
        sandbox = wbxsandbox.Sandbox.connect(sandbox_id, url=url, api_key=api_key)
        return cls(sandbox=sandbox, timeout=timeout)

    def kill(self) -> None:
        """Destroy the sandbox with its disk and memory. No error if it is already gone."""
        self._sandbox.kill()

    def __enter__(self) -> Self:
        """Return the backend; the sandbox is destroyed when the block ends."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Destroy the sandbox without hiding an exception raised inside the block."""
        try:
            self.kill()
        except wbxsandbox.SandboxError:
            if exc is None:
                raise
            logger.warning("Could not destroy sandbox %s", self.id, exc_info=True)

    @property
    def sandbox(self) -> wbxsandbox.Sandbox:
        """The underlying `wbxsandbox.Sandbox` (ports, timeout, pause/resume)."""
        return self._sandbox

    # ------------------------------------------------------------ protocol

    @property
    def id(self) -> str:
        """Return the WBX sandbox ID."""
        return self._sandbox.id

    def execute(
        self,
        command: str,
        *,
        timeout: int | None = None,
    ) -> ExecuteResponse:
        """Execute a shell command (`/bin/sh -c`) inside the sandbox.

        Args:
            command: Shell command to execute.
            timeout: Limit in seconds. `None` uses the backend default, `0`
                means no limit. A command that runs longer is stopped and
                reported with exit code 124.
        """
        effective = timeout if timeout is not None else self._default_timeout
        result = self._sandbox.run(command, timeout=effective or None)
        output = _format_output(result.stdout, result.stderr)
        if result.timed_out:
            note = f"Command timed out after {effective} seconds"
            return ExecuteResponse(
                output=f"{note}\n{output}" if output else note,
                exit_code=TIMEOUT_EXIT_CODE,
                truncated=result.truncated,
            )
        return ExecuteResponse(
            output=output, exit_code=result.exit_code, truncated=result.truncated
        )

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        """Upload files into the sandbox. Missing parent directories are created.

        Results are returned in input order. Relative paths are rejected with
        `invalid_path`; the other errors an agent can fix are reported per file.
        """
        responses: list[FileUploadResponse] = []
        for path, content in files:
            if not path.startswith("/"):
                responses.append(FileUploadResponse(path=path, error="invalid_path"))
                continue
            try:
                self._sandbox.files.write(path, content)
            except wbxsandbox.SandboxError as e:
                responses.append(FileUploadResponse(path=path, error=_file_error(e)))
                continue
            responses.append(FileUploadResponse(path=path, error=None))
        return responses

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        """Download files from the sandbox, returned in input order.

        All absolute paths are checked in one round trip first, so a missing
        file, a directory or an unreadable file is reported without a failed
        download (`file_not_found`, `is_directory`, `permission_denied`).
        Relative paths are rejected with `invalid_path`.
        """
        responses: list[FileDownloadResponse | None] = [None] * len(paths)
        absolute: list[int] = []
        for i, path in enumerate(paths):
            if path.startswith("/"):
                absolute.append(i)
            else:
                responses[i] = FileDownloadResponse(path=path, error="invalid_path")

        checks = self._check_paths([paths[i] for i in absolute])
        for i, check in zip(absolute, checks, strict=True):
            path = paths[i]
            if check is not None:
                responses[i] = FileDownloadResponse(path=path, error=check)
                continue
            try:
                content = self._sandbox.files.read(path)
            except wbxsandbox.SandboxError as e:
                responses[i] = FileDownloadResponse(path=path, error=_file_error(e))
                continue
            responses[i] = FileDownloadResponse(path=path, content=content, error=None)

        return [r for r in responses if r is not None]

    def _check_paths(self, paths: list[str]) -> list[FileOperationError | None]:
        """Classify paths before downloading; `None` = the file can be read.

        If the check itself cannot run, every path is reported readable and
        the download maps the files API error instead (nothing is lost).
        """
        if not paths:
            return []
        result = self._sandbox.run(
            f"python3 -c {shlex.quote(_STAT_SCRIPT)}",
            stdin=json.dumps(paths),
            timeout=_STAT_TIMEOUT,
        )
        try:
            checks = json.loads(result.stdout) if result.exit_code == 0 else None
        except ValueError:
            checks = None
        if not isinstance(checks, list) or len(checks) != len(paths):
            logger.warning(
                "Path check failed in sandbox %s: %s", self.id, result.stderr.strip()[:500]
            )
            return [None] * len(paths)
        return [c if c in _ERRORS else None for c in checks]


def _file_error(e: wbxsandbox.SandboxError) -> FileOperationError:
    """Map a files API error to an error code, or re-raise errors an agent cannot fix."""
    if e.status == 400 and "directory" in str(e.message).lower():
        return "is_directory"
    code = _STATUS_ERRORS.get(e.status)
    if code is None:
        raise e
    return code
