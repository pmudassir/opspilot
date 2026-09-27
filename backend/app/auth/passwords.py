import logging
from functools import cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from starlette.concurrency import run_in_threadpool

logger = logging.getLogger(__name__)

# argon2id with the library's RFC 9106 defaults (~64 MiB memory per hash).
_hasher = PasswordHasher()


@cache
def _dummy_hash() -> str:
    return _hasher.hash("opspilot-timing-equalizer")


def _verify_sync(password_hash: str | None, password: str) -> bool:
    try:
        _hasher.verify(password_hash or _dummy_hash(), password)
    except VerifyMismatchError:
        return False
    except InvalidHashError:
        logger.error("Stored password hash is malformed; login rejected")
        return False
    return password_hash is not None


# Hashing is deliberately slow CPU work. Running it on the event loop would stall
# every concurrent request, so it runs in a worker thread.


async def hash_password(password: str) -> str:
    return await run_in_threadpool(_hasher.hash, password)


async def verify_password(password_hash: str | None, password: str) -> bool:
    """Verify a password. Pass `None` when the user doesn't exist: a dummy hash is
    checked anyway so response time doesn't reveal whether an email is registered."""
    return await run_in_threadpool(_verify_sync, password_hash, password)
