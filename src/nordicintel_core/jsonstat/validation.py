"""Validate the complete wire document against the published JSON-stat schema.

``dataset.schema.json`` is kept as a verbatim copy of the published JSON-stat 2.0 Dataset
Schema, so it can be diffed against json-stat.org. The one adjustment this project needs
is applied here instead, where it can carry its reason.
"""

import json
import re
from copy import deepcopy
from datetime import datetime
from functools import lru_cache
from importlib.resources import files
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

# The published schema types every string array, notes included, as ``uniqueItems``.
# A PxWeb note is not a bare string: it is text plus a mandatory flag, carried on the wire
# as a positional ``note`` array alongside ``extension.noteMandatory``/
# ``categoryNoteMandatory``, which address notes by index. Two notes may therefore share
# their text and differ in whether they are mandatory, and PxApi v2's own schema types
# ``note`` as a plain string array with no uniqueness rule. Deduplicating such an array
# would not remove a repetition; it would delete a note and silently shift the flags of
# every note after it.
#
# Only notes are relaxed. ``id``, ``role``, ``category.index`` and ``category.child`` are
# also unique-by-spec, and a duplicate in any of those is a structurally broken document.
_NOTE_ARRAY = {"type": "array", "items": {"type": "string"}}


def _pxweb_profile(schema: dict[str, Any]) -> dict[str, Any]:
    """Return the published schema with note uniqueness lifted, and nothing else."""
    profile = deepcopy(schema)
    definitions = profile["$defs"]
    definitions["note"] = dict(_NOTE_ARRAY)
    definitions["category"]["properties"]["note"]["additionalProperties"] = dict(_NOTE_ARRAY)
    return profile


@lru_cache(maxsize=1)
def schema_validator() -> Draft202012Validator:
    schema = _pxweb_profile(
        json.loads(
            files("nordicintel_core.jsonstat")
            .joinpath("dataset.schema.json")
            .read_text(encoding="utf-8")
        )
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
