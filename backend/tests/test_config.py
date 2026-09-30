import pytest

from app.config import Settings


@pytest.mark.parametrize("value", ["", "   "])
def test_an_empty_ai_key_means_ai_is_off(value: str) -> None:
    # e2e runs set GROQ_API_KEY="" to override a developer's real key in backend/.env.
    assert Settings(groq_api_key=value).groq_api_key is None  # type: ignore[arg-type]


def test_a_real_ai_key_is_kept_secret() -> None:
    settings = Settings(groq_api_key="gsk_test")  # type: ignore[arg-type]
    assert settings.groq_api_key is not None
    assert settings.groq_api_key.get_secret_value() == "gsk_test"
    assert "gsk_test" not in repr(settings)
