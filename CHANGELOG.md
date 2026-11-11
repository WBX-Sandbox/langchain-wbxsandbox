# Changelog

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
