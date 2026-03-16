"""Dataset loading and validation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evalops_kit.errors import DatasetLoadError


@dataclass(frozen=True)
class DatasetCase:
    """One dataset case from JSONL."""

    case_id: str
    payload: dict[str, Any]


def load_dataset(path: Path) -> list[DatasetCase]:
    """Load a JSONL dataset with line-numbered validation errors."""
    if not path.exists():
        raise DatasetLoadError(f"Dataset file not found: {path}")
    if not path.is_file():
        raise DatasetLoadError(f"Dataset path is not a file: {path}")

    cases: list[DatasetCase] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue

            try:
                item = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise DatasetLoadError(
                    f"Invalid JSON in {path} at line {line_number}: {exc.msg}."
                ) from exc

            if not isinstance(item, dict):
                raise DatasetLoadError(
                    f"Invalid dataset record in {path} at line {line_number}: expected object."
                )

            case_id = item.get("id")
            if not isinstance(case_id, str) or case_id.strip() == "":
                raise DatasetLoadError(
                    f"Invalid dataset record in {path} at line {line_number}: "
                    "key 'id' must be a non-empty string."
                )

            case_input = item.get("input")
            if not isinstance(case_input, dict):
                raise DatasetLoadError(
                    f"Invalid dataset record in {path} at line {line_number}: "
                    "key 'input' must be an object."
                )

            cases.append(DatasetCase(case_id=case_id, payload=item))

    return cases
