# Changelog

## 0.2.0

- **Deep Agents Code:** the `wbx` sandbox provider (`dcode --sandbox wbx`), registered under the
  `deepagents_code.sandbox_providers` entry point – no configuration needed. New sandboxes use
  the `fullstack` template (`WBXSANDBOX_TEMPLATE` for another), live two hours and then fall
  asleep instead of being destroyed; `--sandbox-id` reattaches, `--sandbox-snapshot-name` starts
  from a snapshot (name or `snap_...` ID), config `params` go to `wbxsandbox.Sandbox.create()`.
- Requires `wbxsandbox` 0.20 or newer (was `<0.16`), so the current SDK – snapshots, clones,
  sleep with memory, published apps – installs alongside.
- `WBXSandbox.create()`: `template` defaults to `None` (the SDK still uses `base`), so
  `from_snapshot="snap_..."` works without a template conflict.
- Tested on Python 3.11, 3.13 and 3.14; standard sandbox suite from langchain-tests 1.2.0.

## 0.1.0

- First release: `WBXSandbox`, a Deep Agents sandbox backend (`BaseSandbox`) for WBX Sandbox.
- `execute()` with per-command timeout (exit code 124 on timeout), stdout and stderr in one
  output (stderr marked), `truncated` from the platform.
- `upload_files()` / `download_files()` through the WBX files API, results in input order,
  errors normalized to `file_not_found`, `is_directory`, `permission_denied`, `invalid_path`.
- Lifecycle helpers: `WBXSandbox.create()`, `WBXSandbox.connect()`, `kill()`, `with` block.
- Passes the LangChain standard sandbox suite (`SandboxIntegrationTests`, langchain-tests
  1.1.9) except seven tests that also fail for a plain `BaseSandbox` with deepagents 0.7.x
  (marked as non-strict xfail, see `tests/integration_tests/conftest.py`).
