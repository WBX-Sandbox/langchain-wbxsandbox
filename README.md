# langchain-wbxsandbox

[WBX Sandbox](https://sandbox.wbx.cz) backend for [Deep Agents](https://docs.langchain.com/oss/python/deepagents/overview).
It lets a deep agent run shell commands and work with files inside a WBX sandbox instead of
on your own machine. WBX Sandbox is listed among the sandbox integrations in the LangChain
documentation.

Each WBX sandbox is a Firecracker microVM with its own Linux kernel and disk, started from
a template (for example `base`, Debian with Python) on servers in Europe. Network access follows
your team's network rules and can be restricted per sandbox (no network, or allowed destinations
only). The sandbox and its data are destroyed when you kill it or when its lifetime runs out.

What the agent gets:

- the `execute` tool and the file tools (`ls`, `read_file`, `write_file`, `edit_file`, `glob`,
  `grep`), all running inside the microVM – root access, `pip`, `npm` and `apt` available
- templates for Python, data analysis, a real browser, Node.js and more
  ([templates](https://sandbox.wbx.cz/docs/templates))
- network control: full internet, an allowlist or no network at all
  ([network](https://sandbox.wbx.cz/docs/sandboxes/network))
- billing per second of vCPU and memory ([pricing](https://sandbox.wbx.cz/pricing))
- the `wbx` sandbox provider for [Deep Agents Code](#deep-agents-code-dcode) (`dcode --sandbox wbx`)

Beyond this backend, the same account gives you background jobs and batches with price limits,
signed execution receipts, public HTTPS URLs, metrics and an MCP server for AI assistants – see
the [documentation](https://sandbox.wbx.cz/docs).

## Install

```bash
pip install langchain-wbxsandbox
```

Requires Python 3.11+. Installs `deepagents` and the WBX Sandbox Python SDK (`wbxsandbox`).

## Set up your API key

Create an API key in the WBX Sandbox portal (API keys) and set it in the environment:

```bash
export WBXSANDBOX_API_KEY="..."
# optional, defaults to https://sandbox.wbx.cz
export WBXSANDBOX_URL="https://sandbox.wbx.cz"
```

## Use with a deep agent

```python
from deepagents import create_deep_agent
from langchain_wbxsandbox import WBXSandbox

# Creates a sandbox from the "base" template; it is destroyed when the block ends.
with WBXSandbox.create(template="base", lifetime=1800) as sandbox:
    agent = create_deep_agent(
        model="anthropic:claude-sonnet-4-6",
        system_prompt="You are a coding assistant. Use the sandbox to run code.",
        backend=sandbox,
    )
    result = agent.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": "Write fib.py that prints the first 10 Fibonacci numbers and run it.",
                }
            ]
        }
    )
    print(result["messages"][-1].content)
```

The model string needs the matching LangChain provider package, for example
`pip install langchain-anthropic` and `ANTHROPIC_API_KEY`.

The agent gets the `execute` tool and the file tools (`ls`, `read_file`, `write_file`,
`edit_file`, `glob`, `grep`), all running inside the sandbox.

## Sandbox lifecycle

```python
from langchain_wbxsandbox import WBXSandbox

# Create: template, lifetime (seconds until automatic destruction) and the default
# limit for one command (seconds). Other options go to wbxsandbox.Sandbox.create(),
# for example internet=False, allow=["pypi.org"], env={...}, metadata={...},
# name="my-project" with on_timeout="pause" (the sandbox falls asleep with its files
# instead of being destroyed), from_snapshot="snap_...", ip="dual" or
# compute_class="performance" – see https://sandbox.wbx.cz/docs/sdk.
sandbox = WBXSandbox.create(template="base", lifetime=3600, timeout=600)
print(sandbox.id)

# Run a command directly.
result = sandbox.execute("python3 --version")
print(result.exit_code, result.output)

# Reattach later (for example in the next turn of a conversation).
same = WBXSandbox.connect(sandbox.id)

# Destroy the sandbox with its disk and memory.
sandbox.kill()
```

You can also wrap a sandbox created with the SDK:

```python
import wbxsandbox
from langchain_wbxsandbox import WBXSandbox

sb = wbxsandbox.Sandbox.create(template="code-interpreter", timeout=900)
backend = WBXSandbox(sandbox=sb)
```

Start agents from a prepared environment with a snapshot:

```python
setup = WBXSandbox.create(template="fullstack")
setup.execute(
    "pip install -q pandas && git clone https://github.com/you/project /home/user/project"
)
snap = setup.sandbox.snapshot(name="ready")  # disk copy, kept until you delete it
setup.kill()

sandbox = WBXSandbox.create(from_snapshot=snap.id)  # starts with everything installed
```

Behaviour worth knowing:

- `execute()` runs the command with `/bin/sh -c`. Output is stdout followed by stderr,
  marked as `<stderr>…</stderr>`. A command that exceeds its timeout is stopped and returns
  exit code `124`. `timeout=0` means no limit.
- Commands run as root inside the sandbox. A file without any read permission bit is reported
  as `permission_denied` by `download_files()`, as on a system where the agent runs as an
  unprivileged user.
- Uploads create missing parent directories. Relative paths are rejected with `invalid_path`.

## Deep Agents Code (`dcode`)

The package registers the `wbx` sandbox provider for
[Deep Agents Code](https://docs.langchain.com/oss/python/deepagents/cli/remote-sandboxes), so
after installing it next to `deepagents-code` no configuration is needed:

```bash
pip install langchain-wbxsandbox
export WBXSANDBOX_API_KEY="..."

dcode --sandbox wbx                               # new sandbox, deleted when the session ends
dcode --sandbox wbx --sandbox-id sb_...           # work in an existing sandbox (it is kept)
dcode --sandbox wbx --sandbox-snapshot-name ready # start from a snapshot (name or snap_...)
dcode --sandbox wbx --sandbox-setup setup.sh      # run a setup script first
```

- New sandboxes use the `fullstack` template (Python, Node.js, git); the working directory is
  `/home/user`. Set `WBXSANDBOX_TEMPLATE` for another template.
- A sandbox lives two hours and then falls asleep instead of being destroyed; the next
  command wakes it, so a long session keeps working. A sandbox left behind (for example
  after a crash) is deleted one day after it falls asleep.
- `WBXSANDBOX_API_KEY` and `WBXSANDBOX_URL` can also be set with the `DEEPAGENTS_CODE_` prefix.
- Options for `wbxsandbox.Sandbox.create()` go to `~/.deepagents/config.toml`:

  ```toml
  [sandboxes.providers.wbx.params]
  compute_class = "performance"
  internet = true
  ```

Deep Agents Code needs Python 3.14; the backend itself works from Python 3.11.

## Pricing

Sandboxes are billed by the WBX Sandbox platform – see https://sandbox.wbx.cz/pricing.

## Development

```bash
pip install -e . --group test --group lint
pytest tests/unit_tests --disable-socket --allow-unix-socket   # offline
WBXSANDBOX_API_KEY=... pytest tests/integration_tests          # creates and kills real sandboxes
ruff check . && ruff format --check .
```

The integration tests run the LangChain standard sandbox suite (`SandboxIntegrationTests`)
against a real sandbox and destroy it afterwards. On Python 3.14 the `test` group also installs
`deepagents-code`, and the tests of the `wbx` provider run too (offline and against real
sandboxes).

## License

MIT – see [LICENSE](LICENSE).
