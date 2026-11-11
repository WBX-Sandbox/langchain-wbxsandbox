"""WBX Sandbox integration for Deep Agents."""

from importlib.metadata import PackageNotFoundError, version

from langchain_wbxsandbox.sandbox import WBXSandbox

try:
    __version__ = version("langchain-wbxsandbox")
except PackageNotFoundError:  # running from a source checkout without install
    __version__ = "0.0.0"

__all__ = ["WBXSandbox", "__version__"]
