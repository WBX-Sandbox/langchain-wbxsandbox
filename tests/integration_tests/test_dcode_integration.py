"""The Deep Agents Code provider against real WBX sandboxes.

Needs WBXSANDBOX_API_KEY and `deepagents-code` (Python 3.14). Every sandbox and
snapshot the tests create is deleted at the end.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import wbxsandbox

pytest.importorskip("deepagents_code")

from deepagents_code.integrations.sandbox_factory import create_sandbox
from deepagents_code.integrations.sandbox_provider import SandboxNotFoundError

from langchain_wbxsandbox.dcode import WBXSandboxProvider

pytestmark = pytest.mark.skipif(
    not os.environ.get("WBXSANDBOX_API_KEY"), reason="WBXSANDBOX_API_KEY is not set"
)


def test_factory_creates_runs_setup_and_deletes(tmp_path: Path) -> None:
    """The path `dcode --sandbox wbx --sandbox-setup setup.sh` takes."""
    setup = tmp_path / "setup.sh"
    setup.write_text("echo from-setup > /home/user/setup.txt\n")
    with create_sandbox("wbx", setup_script_path=str(setup)) as backend:
        sandbox_id = backend.id
        r = backend.execute("cat /home/user/setup.txt; pwd; node --version")
        assert r.exit_code == 0, r.output
        assert r.output.startswith("from-setup\n/home/user\nv")
        backend.write("/home/user/a.py", "print(1 + 1)\n")
        assert backend.execute("python3 /home/user/a.py").output.strip() == "2"
    with pytest.raises(wbxsandbox.SandboxError) as e:
        wbxsandbox.Sandbox.connect(sandbox_id)
    assert e.value.status == 404


def test_reattach_and_snapshot_by_name() -> None:
    provider = WBXSandboxProvider()
    first = provider.get_or_create(template="base")
    created = [first.id]
    snap = None
    try:
        first.execute("echo kept > /home/user/state.txt && sync")
        again = provider.get_or_create(sandbox_id=first.id)
        assert again.execute("cat /home/user/state.txt").output.strip() == "kept"

        snap = first.sandbox.snapshot(name="dcode-it-snap")
        second = provider.get_or_create(snapshot="dcode-it-snap")
        created.append(second.id)
        assert second.execute("cat /home/user/state.txt").output.strip() == "kept"
    finally:
        for sid in created:
            provider.delete(sandbox_id=sid)
        if snap is not None:
            snap.delete()
    with pytest.raises(SandboxNotFoundError):
        provider.get_or_create(sandbox_id=first.id)
