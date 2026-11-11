"""Known upstream mismatch in the standard sandbox suite.

`langchain-tests` 1.1.9 (May 2026) still expects the older `BaseSandbox` behaviour:
`write()` refusing to overwrite an existing file and `glob()` returning paths
relative to the search root. `deepagents` 0.7.x overwrites existing files
("creating or overwriting it if it already exists") and returns absolute paths.
Both methods come from `BaseSandbox` itself, not from this package - the same
tests fail for a plain local `BaseSandbox` with no WBX code. They are marked as
non-strict xfail so they start passing once the two packages agree again.
"""

from __future__ import annotations

import pytest

_UPSTREAM_MISMATCH = {
    "test_write_existing_file_fails",
    "test_glob",
    "test_glob_basic_pattern",
    "test_glob_with_directories",
    "test_glob_hidden_files_explicitly",
    "test_glob_with_character_class",
    "test_glob_with_question_mark",
}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if getattr(item, "originalname", item.name) in _UPSTREAM_MISMATCH:
            item.add_marker(
                pytest.mark.xfail(
                    reason="deepagents 0.7.x BaseSandbox vs langchain-tests 1.1.9 expectations",
                    strict=False,
                )
            )
