"""LangChain standard sandbox tests against a real WBX sandbox.

Needs WBXSANDBOX_API_KEY (and optionally WBXSANDBOX_URL / WBXSANDBOX_TEMPLATE).
A fresh sandbox is created for the test class and always destroyed afterwards.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest
from langchain_tests.integration_tests import SandboxIntegrationTests

from langchain_wbxsandbox import WBXSandbox

if TYPE_CHECKING:
    from collections.abc import Iterator

    from deepagents.backends.protocol import SandboxBackendProtocol

pytestmark = pytest.mark.skipif(
    not os.environ.get("WBXSANDBOX_API_KEY"), reason="WBXSANDBOX_API_KEY is not set"
)


class TestWBXSandboxStandard(SandboxIntegrationTests):
    @pytest.fixture(scope="class")
    def sandbox(self) -> Iterator[SandboxBackendProtocol]:
        backend = WBXSandbox.create(
            template=os.environ.get("WBXSANDBOX_TEMPLATE", "base"),
            lifetime=1800,
            timeout=300,
            metadata={"purpose": "langchain-wbxsandbox-ci"},
        )
        try:
            yield backend
        finally:
            backend.kill()
