from httpx import AsyncClient, Response

from app.auth.dependencies import SESSION_COOKIE_NAME

DEFAULT_PASSWORD = "correct-horse-battery-staple"


async def signup(
    client: AsyncClient,
    *,
    email: str = "alice@example.com",
    password: str = DEFAULT_PASSWORD,
    full_name: str = "Alice Example",
    organization_name: str = "Hotel A",
) -> Response:
    return await client.post(
        "/api/v1/auth/signup",
        json={
            "email": email,
            "password": password,
            "full_name": full_name,
            "organization_name": organization_name,
        },
    )


async def login(
    client: AsyncClient, *, email: str = "alice@example.com", password: str = DEFAULT_PASSWORD
) -> Response:
    return await client.post("/api/v1/auth/login", json={"email": email, "password": password})


def session_cookie(client: AsyncClient) -> str | None:
    return client.cookies.get(SESSION_COOKIE_NAME)
