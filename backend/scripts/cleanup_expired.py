"""Delete expired sessions and login attempts past retention; expire stale AI proposals.

Run periodically, e.g. daily via cron (from backend/):
    uv run python -m scripts.cleanup_expired
Safe to run any time and to repeat (idempotent).
"""

import asyncio

from app.ai.proposals.service import expire_stale_proposals
from app.auth.maintenance import delete_expired_auth_data
from app.db import SessionFactory, engine


async def main() -> None:
    try:
        async with SessionFactory() as session:
            result = await delete_expired_auth_data(session)
            expired_proposals = await expire_stale_proposals(session)
        print(
            f"Deleted {result.expired_sessions} expired sessions and "
            f"{result.old_login_attempts} old login attempts; expired {expired_proposals} AI proposals."
        )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
