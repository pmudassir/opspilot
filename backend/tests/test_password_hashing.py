import pytest
from argon2 import PasswordHasher

from app.auth.passwords import build_password_hasher


@pytest.mark.parametrize("environment", ["production", "local"])
def test_non_test_environments_use_full_argon2_cost(environment: str) -> None:
    hasher = build_password_hasher(environment)
    defaults = PasswordHasher()

    assert (hasher.time_cost, hasher.memory_cost, hasher.parallelism) == (
        defaults.time_cost,
        defaults.memory_cost,
        defaults.parallelism,
    )


def test_test_environment_uses_cheap_but_valid_argon2id() -> None:
    hasher = build_password_hasher("test")
    hashed = hasher.hash("correct-horse-battery-staple")

    assert hashed.startswith("$argon2id$")
    assert hasher.verify(hashed, "correct-horse-battery-staple")
    assert hasher.memory_cost < PasswordHasher().memory_cost
