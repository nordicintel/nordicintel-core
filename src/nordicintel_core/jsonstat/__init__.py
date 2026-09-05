"""Core-owned JSON-stat 2.0 Dataset model, PxWeb extensions, and JSON codec."""

from .codec import dumps, loads
from .dataset import Category, Dimension, JsonStatDataset, Link, Role, Unit
from .extensions import (
    CatalogLink,
    CodelistInformation,
    Contact,
    DatasetExtension,
    DimensionExtension,
    LinkExtension,
    PxProperties,
)

__all__ = [
    "CatalogLink",
    "Category",
    "CodelistInformation",
    "Contact",
    "DatasetExtension",
    "Dimension",
    "DimensionExtension",
    "JsonStatDataset",
    "Link",
    "LinkExtension",
    "PxProperties",
    "Role",
    "Unit",
    "dumps",
    "loads",
]
