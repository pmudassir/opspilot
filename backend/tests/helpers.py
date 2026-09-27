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


API = "/api/v1"


def org_url(org_id: str, suffix: str = "") -> str:
    return f"{API}/orgs/{org_id}{suffix}"


async def signup_org(client: AsyncClient, *, email: str, organization_name: str) -> str:
    """Sign up (client becomes that org's admin) and return the new organization id."""
    response = await signup(client, email=email, organization_name=organization_name)
    assert response.status_code == 201, response.text
    return response.json()["memberships"][0]["organization_id"]


async def add_member(
    admin: AsyncClient,
    org_id: str,
    *,
    email: str,
    role: str = "agent",
    password: str = DEFAULT_PASSWORD,
) -> Response:
    return await admin.post(
        org_url(org_id, "/members"),
        json={"email": email, "full_name": email.split("@")[0].title(), "password": password, "role": role},
    )


async def add_member_id(admin: AsyncClient, org_id: str, *, email: str, role: str = "agent") -> str:
    response = await add_member(admin, org_id, email=email, role=role)
    assert response.status_code == 201, response.text
    return response.json()["membership_id"]


async def create_department(admin: AsyncClient, org_id: str, name: str) -> Response:
    return await admin.post(org_url(org_id, "/departments"), json={"name": name})


async def create_department_id(admin: AsyncClient, org_id: str, name: str) -> str:
    response = await create_department(admin, org_id, name)
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def logged_in(client: AsyncClient, email: str) -> AsyncClient:
    response = await login(client, email=email)
    assert response.status_code == 200, response.text
    return client
