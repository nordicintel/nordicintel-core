"""Validate the complete wire document against the published JSON-stat schema."""

import json
import re
from datetime import datetime
from functools import lru_cache
from importlib.resources import files
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


@lru_cache(maxsize=1)
def schema_validator() -> Draft202012Validator:
    schema = json.loads(
        files("nordicintel_core.jsonstat")
        .joinpath("dataset.schema.json")
        .read_text(encoding="utf-8")
    )
    checker = FormatChecker()

    @checker.checks("uri")
    def uri(value: Any) -> bool:
        return not isinstance(value, str) or bool(
            re.fullmatch(r"[A-Za-z][A-Za-z0-9+.-]*:[^\s]*", value)
        )

    @checker.checks("date-time", raises=ValueError)
    def timestamp(value: Any) -> bool:
        if not isinstance(value, str):
            return True
        return (
            "T" in value.upper()
            and datetime.fromisoformat(value.upper().replace("Z", "+00:00")).tzinfo is not None
        )

    return Draft202012Validator(schema, format_checker=checker)


def validate_wire(value: dict[str, Any]) -> None:
    error = next(schema_validator().iter_errors(value), None)
    if error is not None:
        path = "/" + "/".join(str(part) for part in error.absolute_path)
        raise ValueError(f"JSON-stat {path}: {error.message}")
