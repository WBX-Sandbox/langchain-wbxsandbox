"""Offline tests for the Deep Agents Code provider (`dcode --sandbox wbx`)."""

from __future__ import annotations

import importlib.metadata
from unittest.mock import MagicMock, patch

import pytest
import wbxsandbox

pytest.importorskip("deepagents_code")

from deepagents_code.integrations.sandbox_provider import (
    SandboxNotFoundError,
    SandboxProvider,
)

from langchain_wbxsandbox import WBXSandbox
from langchain_wbxsandbox.dcode import (
    DEFAULT_TEMPLATE,
    KEEP_DAYS,
    SESSION_LIFETIME,
    WBXSandboxProvider,
)


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch) -> WBXSandboxProvider:
    for name in ("WBXSANDBOX_API_KEY", "WBXSANDBOX_URL", "WBXSANDBOX_TEMPLATE"):
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(f"DEEPAGENTS_CODE_{name}", raising=False)
    monkeypatch.setenv("WBXSANDBOX_API_KEY", "k")
    return WBXSandboxProvider()


def _sdk(sandbox_id: str = "sb_new") -> MagicMock:
    sdk = MagicMock(spec=wbxsandbox.Sandbox)
    sdk.id = sandbox_id
    return sdk


def _err(status: int) -> wbxsandbox.SandboxError:
    return wbxsandbox.SandboxError(status, "nope")


def test_entry_point_is_registered() -> None:
    eps = importlib.metadata.entry_points(group="deepagents_code.sandbox_providers")
    ep = next(e for e in eps if e.name == "wbx")
    assert ep.load() is WBXSandboxProvider


def test_registry_discovers_the_provider(provider: WBXSandboxProvider) -> None:
    from deepagents_code.integrations.sandbox_registry import SandboxRegistry

    registry = SandboxRegistry.load()
    assert "wbx" in registry.available_providers()
    meta = registry.provider_metadata("wbx")
    assert meta.working_dir == "/home/user"
    assert meta.supports_sandbox_id
    assert meta.supports_snapshot_name
    assert isinstance(registry.create_provider("wbx"), SandboxProvider)


def test_create_uses_defaults(provider: WBXSandboxProvider) -> None:
    with patch.object(wbxsandbox.Sandbox, "create", return_value=_sdk()) as create:
        backend = provider.get_or_create()
    assert isinstance(backend, WBXSandbox)
    assert backend.id == "sb_new"
    kw = create.call_args.kwargs
    assert kw["template"] == DEFAULT_TEMPLATE
    assert kw["timeout"] == SESSION_LIFETIME
    assert kw["on_timeout"] == "pause"
    assert kw["keep_days"] == KEEP_DAYS
    assert kw["api_key"] == "k"
    assert kw["metadata"] == {"created_by": "deepagents-code"}


def test_create_with_template_env_and_params(
    provider: WBXSandboxProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WBXSANDBOX_TEMPLATE", "code-interpreter")
    with patch.object(wbxsandbox.Sandbox, "create", return_value=_sdk()) as create:
        provider.get_or_create(compute_class="performance", internet=False)
    kw = create.call_args.kwargs
    assert kw["template"] == "code-interpreter"
    assert kw["compute_class"] == "performance"
    assert kw["internet"] is False


def test_create_from_snapshot_id_and_name(provider: WBXSandboxProvider) -> None:
    snap = MagicMock(spec=wbxsandbox.Snapshot)
    snap.id = "snap_abc"
    with (
        patch.object(wbxsandbox.Snapshot, "get", return_value=snap),
        patch.object(wbxsandbox.Sandbox, "create", return_value=_sdk()) as create,
    ):
        provider.get_or_create(snapshot="snap_abc", template="base")
    kw = create.call_args.kwargs
    assert kw["from_snapshot"] == "snap_abc"
    assert kw["template"] is None

    old, new = MagicMock(), MagicMock()
    old.id, old.name, old.created_at = "snap_old", "ready", "2026-11-01T00:00:00Z"
    new.id, new.name, new.created_at = "snap_new", "ready", "2026-11-20T00:00:00Z"
    other = MagicMock(id="snap_x", created_at="2026-11-25T00:00:00Z")
    other.name = "other"
    with (
        patch.object(wbxsandbox.Snapshot, "list", return_value=[old, new, other]),
        patch.object(wbxsandbox.Sandbox, "create", return_value=_sdk()) as create,
    ):
        provider.get_or_create(snapshot="ready")
    assert create.call_args.kwargs["from_snapshot"] == "snap_new"


def test_missing_snapshot_raises_not_found(provider: WBXSandboxProvider) -> None:
    with (
        patch.object(wbxsandbox.Snapshot, "list", return_value=[]),
        pytest.raises(SandboxNotFoundError),
    ):
        provider.get_or_create(snapshot="nothing")
    with (
        patch.object(wbxsandbox.Snapshot, "get", side_effect=_err(404)),
        pytest.raises(SandboxNotFoundError),
    ):
        provider.get_or_create(snapshot="snap_gone")


def test_snapshot_image_is_rejected(provider: WBXSandboxProvider) -> None:
    with pytest.raises(TypeError, match="cannot build snapshots"):
        provider.get_or_create(snapshot="x", snapshot_image="python:3.12")


def test_reattach_by_id(provider: WBXSandboxProvider) -> None:
    with patch.object(wbxsandbox.Sandbox, "connect", return_value=_sdk("sb_old")) as connect:
        backend = provider.get_or_create(sandbox_id="sb_old")
    assert backend.id == "sb_old"
    connect.assert_called_once_with("sb_old", url=None, api_key="k")
    with (
        patch.object(wbxsandbox.Sandbox, "connect", side_effect=_err(404)),
        pytest.raises(SandboxNotFoundError),
    ):
        provider.get_or_create(sandbox_id="sb_gone")


def test_create_error_is_runtime_error(provider: WBXSandboxProvider) -> None:
    with (
        patch.object(wbxsandbox.Sandbox, "create", side_effect=_err(429)),
        pytest.raises(RuntimeError, match="Could not create"),
    ):
        provider.get_or_create()


def test_delete_kills_and_ignores_missing(provider: WBXSandboxProvider) -> None:
    sdk = _sdk("sb_old")
    with patch.object(wbxsandbox.Sandbox, "connect", return_value=sdk):
        provider.delete(sandbox_id="sb_old")
    sdk.kill.assert_called_once_with()
    with patch.object(wbxsandbox.Sandbox, "connect", side_effect=_err(404)):
        provider.delete(sandbox_id="sb_gone")
    with (
        patch.object(wbxsandbox.Sandbox, "connect", side_effect=_err(500)),
        pytest.raises(wbxsandbox.SandboxError),
    ):
        provider.delete(sandbox_id="sb_err")


def test_missing_key_fails_on_use_not_on_discovery(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("WBXSANDBOX_API_KEY", "DEEPAGENTS_CODE_WBXSANDBOX_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    p = WBXSandboxProvider()  # discovery must not fail
    assert p.metadata.name == "wbx"
    with pytest.raises(ValueError, match="WBXSANDBOX_API_KEY"):
        p.get_or_create()


def test_prefixed_key_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WBXSANDBOX_API_KEY", "plain")
    monkeypatch.setenv("DEEPAGENTS_CODE_WBXSANDBOX_API_KEY", "prefixed")
    p = WBXSandboxProvider()
    with patch.object(wbxsandbox.Sandbox, "create", return_value=_sdk()) as create:
        p.get_or_create()
    assert create.call_args.kwargs["api_key"] == "prefixed"
