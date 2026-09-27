from alembic import command
from alembic.config import Config


def test_models_and_migrations_are_in_sync(alembic_config: Config) -> None:
    """Fails if a model changed without a matching migration."""
    command.check(alembic_config)
