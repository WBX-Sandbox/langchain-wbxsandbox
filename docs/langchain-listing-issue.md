# Integration listing – text for the LangChain issue form

Submit through the "Integration listing" issue form in the LangChain docs repository
(https://github.com/langchain-ai/docs → New issue → Integration listing) once
`langchain-wbxsandbox` is published on PyPI.

- **Package name:** langchain-wbxsandbox
- **PyPI:** https://pypi.org/project/langchain-wbxsandbox/
- **Component type:** Sandbox (Deep Agents `SandboxBackendProtocol`)
- **Class:** `WBXSandbox` (`from langchain_wbxsandbox import WBXSandbox`)
- **Documentation:** https://github.com/WBX-Sandbox/langchain-wbxsandbox#readme
- **Repository:** https://github.com/WBX-Sandbox/langchain-wbxsandbox
- **Maintained by:** KXCOMM s.r.o., the company that operates WBX Sandbox
- **Standard tests:** `SandboxIntegrationTests` from langchain-tests 1.1.9 run in CI against
  real sandboxes; 7 tests are non-strict xfail because they also fail for a plain
  `BaseSandbox` with deepagents 0.7.x (`write()` overwrite and absolute `glob()` paths).
- **Short description:** WBX Sandbox backend for Deep Agents – runs agent commands and file
  operations in Firecracker microVMs, each with its own Linux kernel and disk.
