"""Validated, provenance-preserving ingestion primitives."""

from app.ingestion.core import DatasetDescription, DatasetValidationSpec, SourceAdapter
from app.ingestion.runner import IngestionReport, run_ingestion

__all__ = [
    "DatasetDescription",
    "DatasetValidationSpec",
    "IngestionReport",
    "SourceAdapter",
    "run_ingestion",
]
