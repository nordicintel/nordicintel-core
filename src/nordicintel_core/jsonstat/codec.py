"""Lossless Decimal encoding and decoding of complete Dataset documents."""

import simplejson

from .dataset import JsonStatDataset


def loads(value: str | bytes) -> JsonStatDataset:
    return JsonStatDataset.model_validate(
        simplejson.loads(value, use_decimal=True, allow_nan=False)
    )


def dumps(dataset: JsonStatDataset) -> str:
    # Nested containers are mutable: revalidate before publishing a response.
    accepted = JsonStatDataset.from_mapping(dataset.to_mapping())
    return simplejson.dumps(
        accepted.to_mapping(), use_decimal=True, allow_nan=False, ensure_ascii=False
    )
