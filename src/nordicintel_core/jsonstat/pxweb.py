"""Cross-reference validation for the typed PxWeb Dataset extensions."""

from .dataset import JsonStatDataset, check_positions


def check_notes(flags: dict[str, bool] | None, notes: list[str] | None) -> None:
    if flags is not None:
        check_positions(flags, len(notes or []))


def validate_pxweb_dataset(dataset: JsonStatDataset) -> None:
    root = dataset.extension
    if root is not None:
        check_notes(root.note_mandatory, dataset.note)
        if root.px is not None:
            placement = (root.px.heading or []) + (root.px.stub or [])
            if len(placement) != len(set(placement)) or not set(placement) <= set(dataset.id):
                raise ValueError("PxWeb heading/stub must reference distinct existing dimensions")
    for dimension in dataset.dimension.values():
        ext = dimension.extension
        if ext is None:
            continue
        codes = set(dimension.category.codes)
        check_notes(ext.note_mandatory, dimension.note)
        for mapping in (
            ext.category_note_mandatory,
            ext.refperiod,
            ext.measuring_type,
            ext.price_type,
            ext.adjustment,
            ext.base_period,
            ext.alternative_text,
        ):
            if mapping is not None and not set(mapping) <= codes:
                raise ValueError("PxWeb category extension references an unknown category")
        for code, flags in (ext.category_note_mandatory or {}).items():
            check_notes(flags, (dimension.category.note or {}).get(code))
        if ext.elimination_value_code is not None and ext.elimination_value_code not in codes:
            raise ValueError("eliminationValueCode must reference an existing category")
