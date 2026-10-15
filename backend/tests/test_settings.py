import pytest
from pydantic import ValidationError

from app.settings import Settings


def test_settings_accept_local_service_urls() -> None:
    settings = Settings(
        database_url="postgresql://nfd:local@localhost:5432/nfd",
        redis_url="redis://localhost:6379/0",
    )

    assert settings.nfd_env == "development"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("database_url", "https://not-a-database.example"),
        ("redis_url", "https://not-redis.example"),
    ],
)
def test_settings_reject_unsupported_service_urls(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        Settings(**{field: value})
