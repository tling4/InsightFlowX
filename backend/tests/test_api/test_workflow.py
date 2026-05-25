import pytest
from httpx import AsyncClient


async def get_auth_token(client: AsyncClient):
    await client.post("/api/v1/auth/register", json={
        "username": "workflow_test",
        "email": "wf_test@example.com",
        "password": "12345678"
    })
    login_resp = await client.post("/api/v1/auth/login", json={
        "email": "wf_test@example.com",
        "password": "12345678"
    })
    return login_resp.json()["access_token"]


@pytest.mark.asyncio
async def test_create_workflow(client: AsyncClient):
    token = await get_auth_token(client)
    resp = await client.post(
        "/api/v1/workflows",
        json={"title": "测试竞品分析项目"},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "workflow_id" in data
    assert data["status"] == "configuring"


@pytest.mark.asyncio
async def test_list_workflows(client: AsyncClient):
    token = await get_auth_token(client)
    await client.post("/api/v1/workflows", json={"title": "项目1"}, headers={"Authorization": f"Bearer {token}"})
    await client.post("/api/v1/workflows", json={"title": "项目2"}, headers={"Authorization": f"Bearer {token}"})
    resp = await client.get("/api/v1/workflows", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert len(resp.json()) >= 2
