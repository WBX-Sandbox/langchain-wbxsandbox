"""WBX Sandbox provider for Deep Agents Code (`dcode --sandbox wbx`).

Registered under the `deepagents_code.sandbox_providers` entry-point group, so
after `pip install langchain-wbxsandbox` the provider is available without any
configuration:

    export WBXSANDBOX_API_KEY=...
    dcode --sandbox wbx
    dcode --sandbox wbx --sandbox-id sb_...            # reattach to a sandbox
    dcode --sandbox wbx --sandbox-snapshot-name ready  # start from a snapshot (name or snap_...)

Settings (environment, also with the `DEEPAGENTS_CODE_` prefix):

- `WBXSANDBOX_API_KEY` (required) and `WBXSANDBOX_URL` (default https://sandbox.wbx.cz)
- `WBXSANDBOX_TEMPLATE`: template for new sandboxes (default `fullstack`: Python, Node.js, git)

Config-declared parameters (`[sandboxes.providers.wbx.params]` in
`~/.deepagents/config.toml`) are passed to `wbxsandbox.Sandbox.create()`, for
example `compute_class`, `vcpu`, `mem_mb`, `internet` or `allow`.

This module imports `deepagents_code`; it is only loaded by Deep Agents Code.
"""

from __future__ import annotations

import os
from typing import Any

import wbxsandbox
from deepagents_code.integrations.sandbox_provider import (
    SandboxInstallHint,
    SandboxNotFoundError,
    SandboxProvider,
    SandboxProviderMetadata,
)

from langchain_wbxsandbox.sandbox import DEFAULT_COMMAND_TIMEOUT, WBXSandbox

PROVIDER_NAME = "wbx"
DEFAULT_TEMPLATE = "fullstack"
WORKING_DIR = "/home/user"

SESSION_LIFETIME = 2 * 3600
"""Lifetime of a new sandbox in seconds. When it runs out the sandbox falls asleep
(files and running programs kept) and wakes on the next command, so a longer
session keeps working."""

KEEP_DAYS = 1
"""A sandbox left behind (Deep Agents Code did not get to delete it) is kept this
many days asleep, then deleted with its files."""


def _env(name: str) -> str | None:
    """Read a setting the way Deep Agents Code does (`DEEPAGENTS_CODE_` prefix wins)."""
    try:
        from deepagents_code.model_config import resolve_env_var
    except ImportError:  # pragma: no cover - older deepagents-code
        return os.environ.get(f"DEEPAGENTS_CODE_{name}") or os.environ.get(name) or None
    return resolve_env_var(name) or None


class WBXSandboxProvider(SandboxProvider):
    """Creates, reattaches and deletes WBX sandboxes for Deep Agents Code."""

    def __init__(self) -> None:
        """Read the API key and address (checked on first use, so discovery never fails)."""
        self._api_key = _env("WBXSANDBOX_API_KEY")
        self._url = _env("WBXSANDBOX_URL")

    def _key(self) -> str:
        if not self._api_key:
            msg = (
                "No WBX Sandbox API key found. Set WBXSANDBOX_API_KEY "
                "(or DEEPAGENTS_CODE_WBXSANDBOX_API_KEY). Create a key in the portal "
                "at https://sandbox.wbx.cz (API keys)."
            )
            raise ValueError(msg)
        return self._api_key

    @property
    def metadata(self) -> SandboxProviderMetadata:
        """Static description used by the Deep Agents Code registry."""
        return SandboxProviderMetadata(
            name=PROVIDER_NAME,
            working_dir=WORKING_DIR,
            install=SandboxInstallHint(kind="package", name="langchain-wbxsandbox"),
            supports_sandbox_id=True,
            supports_snapshot_name=True,
            backend_module="langchain_wbxsandbox",
        )

    def get_or_create(
        self,
        *,
        sandbox_id: str | None = None,
        timeout: int = 180,
        snapshot: str | None = None,
        snapshot_image: str | None = None,
        **kwargs: Any,
    ) -> WBXSandbox:
        """Reattach to a sandbox by ID, or create a new one.

        Args:
            sandbox_id: ID of an existing sandbox (`sb_...`). A sleeping sandbox
                wakes up on the first command.
            timeout: Accepted for parity with other providers; a WBX sandbox is
                ready when the create call returns.
            snapshot: Snapshot to start from: its ID (`snap_...`) or its name.
            snapshot_image: Not supported - WBX snapshots are taken from a
                sandbox (`sandbox.snapshot()`), not built from an image.
            **kwargs: Passed to `wbxsandbox.Sandbox.create()` (for example
                `template`, `compute_class`, `vcpu`, `mem_mb`, `internet`, `allow`).

        Returns:
            A `WBXSandbox` backend.

        Raises:
            SandboxNotFoundError: The sandbox or snapshot does not exist.
            TypeError: `snapshot_image` was given.
            RuntimeError: The sandbox could not be created.
            ValueError: No API key is set.
        """
        del timeout
        if snapshot_image:
            msg = (
                "The wbx provider cannot build snapshots from an image. Take a snapshot of a "
                "prepared sandbox (sandbox.snapshot(name=...)) and pass its name or ID."
            )
            raise TypeError(msg)
        if sandbox_id:
            try:
                return WBXSandbox.connect(sandbox_id, url=self._url, api_key=self._key())
            except wbxsandbox.SandboxError as e:
                if e.status == 404:
                    raise SandboxNotFoundError(f"WBX sandbox {sandbox_id} not found") from e
                raise

        create: dict[str, Any] = {
            "lifetime": SESSION_LIFETIME,
            "on_timeout": "pause",
            "keep_days": KEEP_DAYS,
            "metadata": {"created_by": "deepagents-code"},
        }
        create.update(kwargs)
        if snapshot:
            create.pop("template", None)
            create["from_snapshot"] = self._resolve_snapshot(snapshot)
        else:
            create.setdefault("template", _env("WBXSANDBOX_TEMPLATE") or DEFAULT_TEMPLATE)
        try:
            return WBXSandbox.create(
                url=self._url,
                api_key=self._key(),
                timeout=DEFAULT_COMMAND_TIMEOUT,
                **create,
            )
        except wbxsandbox.SandboxError as e:
            msg = f"Could not create a WBX sandbox: {e}"
            raise RuntimeError(msg) from e

    def delete(self, *, sandbox_id: str, **kwargs: Any) -> None:
        """Destroy a sandbox with its files. No error when it is already gone."""
        del kwargs
        try:
            sandbox = wbxsandbox.Sandbox.connect(sandbox_id, url=self._url, api_key=self._key())
        except wbxsandbox.SandboxError as e:
            if e.status == 404:
                return
            raise
        sandbox.kill()

    def _resolve_snapshot(self, ref: str) -> str:
        """Snapshot ID for an ID or a name (the newest snapshot with that name)."""
        if ref.startswith("snap_"):
            try:
                return wbxsandbox.Snapshot.get(ref, url=self._url, api_key=self._key()).id
            except wbxsandbox.SandboxError as e:
                if e.status == 404:
                    raise SandboxNotFoundError(f"WBX snapshot {ref} not found") from e
                raise
        named = [
            s for s in wbxsandbox.Snapshot.list(url=self._url, api_key=self._key()) if s.name == ref
        ]
        if not named:
            msg = (
                f"No WBX snapshot named {ref!r}. Take one with sandbox.snapshot(name={ref!r}) "
                "or pass a snapshot ID (snap_...)."
            )
            raise SandboxNotFoundError(msg)
        return max(named, key=lambda s: s.created_at).id
