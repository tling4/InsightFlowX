import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_register_user(client: AsyncClient):
    resp = await client.post("/api/v1/auth/register", json={
        "username": "testuser",
        "email": "test@example.com",
        "password": "12345678"
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["username"] == "testuser"
    assert data["email"] == "test@example.com"


@pytest.mark.asyncio
async def test_login_user(client: AsyncClient):
    await client.post("/api/v1/auth/register", json={
        "username": "testuser2",
        "email": "test2@example.com",
        "password": "12345678"
    })
    resp = await client.post("/api/v1/auth/login", json={
        "email": "test2@example.com",
        "password": "12345678"
    })
    assert resp.status_code == 200
    assert "access_token" in resp.json()


@pytest.mark.asyncio
async def test_get_me_unauthorized(client: AsyncClient):
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401
