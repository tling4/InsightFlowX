import pytest
from httpx import AsyncClient


async def get_auth_token_and_create_workflow(client: AsyncClient):
    await client.post("/api/v1/auth/register", json={
        "username": "interview_test",
        "email": "intv_test@example.com",
        "password": "12345678"
    })
    login_resp = await client.post("/api/v1/auth/login", json={
        "email": "intv_test@example.com",
        "password": "12345678"
    })
    token = login_resp.json()["access_token"]
    wf_resp = await client.post(
        "/api/v1/workflows",
        json={"title": "访谈测试项目"},
        headers={"Authorization": f"Bearer {token}"}
    )
    workflow_id = wf_resp.json()["workflow_id"]
    return token, workflow_id


@pytest.mark.asyncio
async def test_get_empty_interview_history(client: AsyncClient):
    token, workflow_id = await get_auth_token_and_create_workflow(client)
    resp = await client.get(
        f"/api/v1/workflows/{workflow_id}/interview/history",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
