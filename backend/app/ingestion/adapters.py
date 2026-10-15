from app.ingestion.core import SourceAdapter

ADAPTERS: dict[str, SourceAdapter] = {}


def register_adapter(adapter: SourceAdapter) -> None:
    if adapter.source_id in ADAPTERS:
        raise ValueError(f"an adapter is already registered for {adapter.source_id!r}")
    ADAPTERS[adapter.source_id] = adapter
