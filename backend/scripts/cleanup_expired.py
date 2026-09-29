"""Delete expired sessions and login attempts past retention.

Run periodically, e.g. daily via cron (from backend/):
    uv run python -m scripts.cleanup_expired
Safe to run any time and to repeat (idempotent).
"""

import asyncio

from app.auth.maintenance import delete_expired_auth_data
from app.db import SessionFactory, engine


async def main() -> None:
    try:
        async with SessionFactory() as session:
            result = await delete_expired_auth_data(session)
        print(
            f"Deleted {result.expired_sessions} expired sessions and "
            f"{result.old_login_attempts} old login attempts."
        )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
