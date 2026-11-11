"""Offline tests for WBXSandbox - the WBX SDK sandbox is mocked, no network is used."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
import wbxsandbox
from deepagents.backends.protocol import (
    ExecuteResponse,
    FileDownloadResponse,
    FileUploadResponse,
    SandboxBackendProtocol,
)

import langchain_wbxsandbox
from langchain_wbxsandbox import WBXSandbox
from langchain_wbxsandbox.sandbox import DEFAULT_COMMAND_TIMEOUT, TIMEOUT_EXIT_CODE


def _result(
    stdout: str = "", stderr: str = "", exit_code: int = 0, **kw: object
) -> wbxsandbox.CommandResult:
    return wbxsandbox.CommandResult(exit_code=exit_code, stdout=stdout, stderr=stderr, **kw)


def _backend(**kw: object) -> tuple[WBXSandbox, MagicMock]:
    sdk = MagicMock(spec=wbxsandbox.Sandbox)
    sdk.id = "sb_n01_test"
    sdk.files = MagicMock()
    return WBXSandbox(sandbox=sdk, **kw), sdk


# ---------------------------------------------------------------- basics


def test_import_and_protocol() -> None:
    backend, _ = _backend()
    assert isinstance(backend, SandboxBackendProtocol)
    assert backend.id == "sb_n01_test"
    assert langchain_wbxsandbox.__all__ == ["WBXSandbox", "__version__"]


# ---------------------------------------------------------------- execute


def test_execute_returns_stdout_and_exit_code() -> None:
    backend, sdk = _backend()
    sdk.run.return_value = _result("hello\n")
    assert backend.execute("echo hello") == ExecuteResponse(
        output="hello\n", exit_code=0, truncated=False
    )
    sdk.run.assert_called_once_with("echo hello", timeout=DEFAULT_COMMAND_TIMEOUT)


def test_execute_marks_stderr_and_keeps_nonzero_exit() -> None:
    backend, sdk = _backend()
    sdk.run.return_value = _result("out", "  boom \n", exit_code=2)
    r = backend.execute("false")
    assert r.output == "out\n<stderr>boom</stderr>"
    assert r.exit_code == 2


def test_execute_stderr_only_has_no_leading_newline() -> None:
    backend, sdk = _backend()
    sdk.run.return_value = _result("", "err", exit_code=1)
    assert backend.execute("x").output == "<stderr>err</stderr>"


def test_execute_passes_truncated_flag() -> None:
    backend, sdk = _backend()
    sdk.run.return_value = _result("x" * 10, truncated=True)
    assert backend.execute("yes").truncated is True


def test_execute_timeout_reports_124_with_partial_output() -> None:
    backend, sdk = _backend()
    sdk.run.return_value = _result("started\n", exit_code=-1, timed_out=True)
    r = backend.execute("sleep 99", timeout=3)
    assert r.exit_code == TIMEOUT_EXIT_CODE
    assert r.output == "Command timed out after 3 seconds\nstarted\n"
    sdk.run.assert_called_once_with("sleep 99", timeout=3)


def test_execute_timeout_without_output() -> None:
    backend, sdk = _backend()
    sdk.run.return_value = _result(exit_code=-1, timed_out=True)
    assert backend.execute("sleep 99", timeout=1).output == "Command timed out after 1 seconds"


def test_execute_default_and_zero_timeout() -> None:
    backend, sdk = _backend(timeout=42)
    sdk.run.return_value = _result()
    backend.execute("a")
    backend.execute("b", timeout=0)  # 0 = no limit → SDK gets None
    assert [c.kwargs["timeout"] for c in sdk.run.call_args_list] == [42, None]


def test_execute_sdk_error_propagates() -> None:
    backend, sdk = _backend()
    sdk.run.side_effect = wbxsandbox.SandboxError(404, "sandbox not found")
    with pytest.raises(wbxsandbox.SandboxError):
        backend.execute("ls")


async def test_aexecute_uses_execute() -> None:
    backend, sdk = _backend()
    sdk.run.return_value = _result("async\n")
    r = await backend.aexecute("echo async", timeout=5)
    assert r.output == "async\n"
    sdk.run.assert_called_once_with("echo async", timeout=5)


# ---------------------------------------------------------------- upload


def test_upload_order_and_errors() -> None:
    backend, sdk = _backend()

    def write(path: str, data: bytes) -> None:
        if path == "/ro/x":
            raise wbxsandbox.SandboxError(403, "permission denied")
        if path == "/dir":
            raise wbxsandbox.SandboxError(400, "Is a directory (os error 21)")

    sdk.files.write.side_effect = write
    res = backend.upload_files(
        [("/a.txt", b"a"), ("rel.txt", b"r"), ("/ro/x", b"x"), ("/dir", b"d")]
    )
    assert res == [
        FileUploadResponse(path="/a.txt", error=None),
        FileUploadResponse(path="rel.txt", error="invalid_path"),
        FileUploadResponse(path="/ro/x", error="permission_denied"),
        FileUploadResponse(path="/dir", error="is_directory"),
    ]
    assert [c.args for c in sdk.files.write.call_args_list] == [
        ("/a.txt", b"a"),
        ("/ro/x", b"x"),
        ("/dir", b"d"),
    ]


def test_upload_server_error_raises() -> None:
    backend, sdk = _backend()
    sdk.files.write.side_effect = wbxsandbox.SandboxError(500, "disk full")
    with pytest.raises(wbxsandbox.SandboxError):
        backend.upload_files([("/a", b"a")])


# ---------------------------------------------------------------- download


def test_download_checks_paths_in_one_call_then_reads() -> None:
    backend, sdk = _backend()
    sdk.run.return_value = _result(
        json.dumps([None, "file_not_found", "is_directory", "permission_denied"])
    )
    sdk.files.read.return_value = b"\x89PNG"
    paths = ["/ok.png", "/missing", "rel/path", "/a/dir", "/secret"]
    res = backend.download_files(paths)
    assert res == [
        FileDownloadResponse(path="/ok.png", content=b"\x89PNG", error=None),
        FileDownloadResponse(path="/missing", error="file_not_found"),
        FileDownloadResponse(path="rel/path", error="invalid_path"),
        FileDownloadResponse(path="/a/dir", error="is_directory"),
        FileDownloadResponse(path="/secret", error="permission_denied"),
    ]
    # one batched check with the absolute paths on stdin, one download
    assert sdk.run.call_count == 1
    assert json.loads(sdk.run.call_args.kwargs["stdin"]) == [
        "/ok.png",
        "/missing",
        "/a/dir",
        "/secret",
    ]
    assert sdk.run.call_args.args[0].startswith("python3 -c ")
    sdk.files.read.assert_called_once_with("/ok.png")


def test_download_only_relative_paths_skips_check() -> None:
    backend, sdk = _backend()
    assert backend.download_files(["a", "b/c"]) == [
        FileDownloadResponse(path="a", error="invalid_path"),
        FileDownloadResponse(path="b/c", error="invalid_path"),
    ]
    sdk.run.assert_not_called()
    assert backend.download_files([]) == []


@pytest.mark.parametrize(
    "check",
    [
        _result("", "python3: not found", exit_code=127),
        _result("not json"),
        _result(json.dumps([None])),
    ],
    ids=["check-fails", "bad-json", "wrong-length"],
)
def test_download_falls_back_to_files_api_errors(check: wbxsandbox.CommandResult) -> None:
    backend, sdk = _backend()
    sdk.run.return_value = check

    def read(path: str) -> bytes:
        return {
            "/ok": lambda: b"data",
            "/missing": lambda: (_ for _ in ()).throw(wbxsandbox.SandboxError(404, "No such file")),
            "/dir": lambda: (_ for _ in ()).throw(
                wbxsandbox.SandboxError(400, "the path is a directory")
            ),
        }[path]()

    sdk.files.read.side_effect = read
    assert backend.download_files(["/ok", "/missing", "/dir"]) == [
        FileDownloadResponse(path="/ok", content=b"data", error=None),
        FileDownloadResponse(path="/missing", error="file_not_found"),
        FileDownloadResponse(path="/dir", error="is_directory"),
    ]


def test_download_unknown_check_value_is_treated_as_readable() -> None:
    backend, sdk = _backend()
    sdk.run.return_value = _result(json.dumps(["something_else"]))
    sdk.files.read.return_value = b"x"
    assert backend.download_files(["/f"]) == [
        FileDownloadResponse(path="/f", content=b"x", error=None)
    ]


def test_download_server_error_raises() -> None:
    backend, sdk = _backend()
    sdk.run.return_value = _result(json.dumps([None]))
    sdk.files.read.side_effect = wbxsandbox.SandboxError(502, "node unreachable")
    with pytest.raises(wbxsandbox.SandboxError):
        backend.download_files(["/f"])


async def test_async_file_transfer_uses_sync_methods() -> None:
    backend, sdk = _backend()
    sdk.run.return_value = _result(json.dumps([None]))
    sdk.files.read.return_value = b"abc"
    assert await backend.aupload_files([("/f", b"abc")]) == [
        FileUploadResponse(path="/f", error=None)
    ]
    assert await backend.adownload_files(["/f"]) == [
        FileDownloadResponse(path="/f", content=b"abc", error=None)
    ]


# ---------------------------------------------------------------- lifecycle


def test_create_passes_template_lifetime_and_options() -> None:
    sdk = MagicMock(spec=wbxsandbox.Sandbox)
    sdk.id = "sb_new"
    with patch.object(wbxsandbox.Sandbox, "create", return_value=sdk) as create:
        backend = WBXSandbox.create(
            template="code-interpreter",
            lifetime=600,
            timeout=90,
            url="https://example.test",
            api_key="k",
            internet=False,
        )
    create.assert_called_once_with(
        template="code-interpreter",
        timeout=600,
        url="https://example.test",
        api_key="k",
        internet=False,
    )
    assert backend.id == "sb_new"
    assert backend.sandbox is sdk
    sdk.run.return_value = _result()
    backend.execute("true")
    assert sdk.run.call_args.kwargs["timeout"] == 90


def test_connect_attaches_by_id() -> None:
    sdk = MagicMock(spec=wbxsandbox.Sandbox)
    sdk.id = "sb_old"
    with patch.object(wbxsandbox.Sandbox, "connect", return_value=sdk) as connect:
        backend = WBXSandbox.connect("sb_old", api_key="k")
    connect.assert_called_once_with("sb_old", url=None, api_key="k")
    assert backend.id == "sb_old"


def test_context_manager_kills_sandbox() -> None:
    backend, sdk = _backend()
    with backend as b:
        assert b is backend
    sdk.kill.assert_called_once_with()


def test_context_manager_does_not_hide_original_error() -> None:
    backend, sdk = _backend()
    sdk.kill.side_effect = wbxsandbox.SandboxError(0, "cannot connect")
    with pytest.raises(ValueError, match="original"), backend:
        raise ValueError("original")


def test_context_manager_reports_kill_error_without_original() -> None:
    backend, sdk = _backend()
    sdk.kill.side_effect = wbxsandbox.SandboxError(500, "kill failed")
    with pytest.raises(wbxsandbox.SandboxError), backend:
        pass
