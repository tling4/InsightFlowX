import pytest
from httpx import AsyncClient

from app.exceptions import (
    AppException,
    WorkflowNotFoundError,
    InvalidStateTransitionError,
    ConfigIncompleteError,
    InvalidCredentialsError,
    InvalidTokenError,
    DuplicateResourceError,
    ArtifactNotFoundError,
)


# ==========================================================
# Unit: exception class construction
# ==========================================================

class TestExceptionClasses:
    def test_app_exception_base(self):
        e = AppException("TEST_CODE", "test message", 400, {"key": "val"})
        assert e.error_code == "TEST_CODE"
        assert e.message == "test message"
        assert e.status_code == 400
        assert e.details == {"key": "val"}

    def test_app_exception_details_default_none(self):
        e = AppException("X", "msg", 500)
        assert e.details is None

    def test_workflow_not_found_with_id(self):
        e = WorkflowNotFoundError("550e8400-e29b-41d4-a716-446655440000")
        assert e.error_code == "WORKFLOW_NOT_FOUND"
        assert e.status_code == 404
        assert "550e8400" in e.message

    def test_workflow_not_found_without_id(self):
        e = WorkflowNotFoundError()
        assert e.error_code == "WORKFLOW_NOT_FOUND"
        assert "不存在" in e.message

    def test_invalid_state_transition(self):
        e = InvalidStateTransitionError("wf-1", "running", "cancel")
        assert e.error_code == "INVALID_STATE_TRANSITION"
        assert e.status_code == 400
        assert e.details == {
            "workflow_id": "wf-1",
            "current_status": "running",
            "target_action": "cancel",
        }
        assert "running" in e.message
        assert "cancel" in e.message

    def test_config_incomplete_with_missing(self):
        e = ConfigIncompleteError("wf-1", ["target_product", "industry"])
        assert e.error_code == "CONFIG_INCOMPLETE"
        assert e.status_code == 400
        assert "target_product" in e.message
        assert e.details == {
            "workflow_id": "wf-1",
            "missing_fields": ["target_product", "industry"],
        }

    def test_config_incomplete_no_missing_fields(self):
        e = ConfigIncompleteError("wf-1")
        assert "缺少" not in e.message
        assert e.details == {"workflow_id": "wf-1", "missing_fields": None}

    def test_invalid_credentials(self):
        e = InvalidCredentialsError()
        assert e.error_code == "INVALID_CREDENTIALS"
        assert e.status_code == 401

    def test_invalid_token_default(self):
        e = InvalidTokenError()
        assert e.error_code == "INVALID_TOKEN"
        assert e.status_code == 401
        assert "令牌" in e.message

    def test_invalid_token_custom_reason(self):
        e = InvalidTokenError("令牌已过期")
        assert "过期" in e.message

    def test_duplicate_resource(self):
        e = DuplicateResourceError("邮箱", "test@test.com")
        assert e.error_code == "DUPLICATE_RESOURCE"
        assert e.status_code == 409
        assert "test@test.com" in e.message

    def test_artifact_not_found_with_id(self):
        e = ArtifactNotFoundError("art-456")
        assert e.error_code == "ARTIFACT_NOT_FOUND"
        assert e.status_code == 404
        assert "art-456" in e.message

    def test_artifact_not_found_without_id(self):
        e = ArtifactNotFoundError()
        assert "不存在" in e.message


# ==========================================================
# Integration: API error responses via global handlers
# ==========================================================

class TestGlobalExceptionHandler:
    """测试全局异常处理器返回统一的 error_code 响应。"""

    @pytest.mark.asyncio
    async def test_login_invalid_credentials(self, client: AsyncClient):
        """未注册的用户登录应返回 401 + InvalidCredentialsError。"""
        resp = await client.post("/api/v1/auth/login", json={
            "email": "nonexistent@test.com",
            "password": "wrong-password",
        })
        assert resp.status_code == 401
        data = resp.json()
        assert data["error_code"] == "INVALID_CREDENTIALS"
        assert "邮箱或密码错误" in data["message"]

    @pytest.mark.asyncio
    async def test_register_duplicate_email(self, client: AsyncClient):
        """重复邮箱注册应返回 409 + DuplicateResourceError。"""
        payload = {"username": "dupuser", "email": "dup@test.com", "password": "12345678"}
        resp1 = await client.post("/api/v1/auth/register", json=payload)
        assert resp1.status_code == 201

        resp2 = await client.post("/api/v1/auth/register", json=payload)
        assert resp2.status_code == 409
        data = resp2.json()
        assert data["error_code"] == "DUPLICATE_RESOURCE"
        assert "邮箱" in data["message"]

    @pytest.mark.asyncio
    async def test_get_nonexistent_workflow_returns_404(self, client: AsyncClient):
        """查询不存在的工作流应返回 404 + WorkflowNotFoundError。"""
        await client.post("/api/v1/auth/register", json={
            "username": "wftest",
            "email": "wftest@test.com",
            "password": "12345678",
        })
        login_resp = await client.post("/api/v1/auth/login", json={
            "email": "wftest@test.com",
            "password": "12345678",
        })
        token = login_resp.json()["access_token"]

        fake_uuid = "00000000-0000-0000-0000-000000000000"
        resp = await client.get(
            f"/api/v1/workflows/{fake_uuid}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404
        data = resp.json()
        assert data["error_code"] == "WORKFLOW_NOT_FOUND"
        assert "不存在" in data["message"]

    @pytest.mark.asyncio
    async def test_retry_on_non_failed_workflow(self, client: AsyncClient):
        """在非 failed 状态的工作流上调用 retry 应返回 400 + InvalidStateTransitionError。"""
        await client.post("/api/v1/auth/register", json={
            "username": "retrytest",
            "email": "retrytest@test.com",
            "password": "12345678",
        })
        login_resp = await client.post("/api/v1/auth/login", json={
            "email": "retrytest@test.com",
            "password": "12345678",
        })
        token = login_resp.json()["access_token"]

        wf_resp = await client.post(
            "/api/v1/workflows",
            json={"title": "retry-test"},
            headers={"Authorization": f"Bearer {token}"},
        )
        workflow_id = wf_resp.json()["workflow_id"]

        resp = await client.post(
            f"/api/v1/workflows/{workflow_id}/retry/analysis",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400
        data = resp.json()
        assert data["error_code"] == "INVALID_STATE_TRANSITION"
        # 新建工作流状态为 configuring，不允许 retry
        assert "configuring" in data["message"]

    @pytest.mark.asyncio
    async def test_unhandled_exception_returns_500(self, client: AsyncClient):
        """未预期的异常应返回 500 + INTERNAL_ERROR。

        ServerErrorMiddleware 会在发送响应后 re-raise，因此 httpx 默认会抛回异常。
        使用 raise_app_exceptions=False 获取真实响应体。
        """
        from httpx import AsyncClient as HttpxAsyncClient, ASGITransport
        from app.main import app

        await client.post("/api/v1/auth/register", json={
            "username": "err500",
            "email": "err500@test.com",
            "password": "12345678",
        })
        login_resp = await client.post("/api/v1/auth/login", json={
            "email": "err500@test.com",
            "password": "12345678",
        })
        token = login_resp.json()["access_token"]

        async with HttpxAsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client_allow_500:
            # 使用无效 UUID 触发 uuid.UUID() ValueError → ServerErrorMiddleware 调用 handler
            resp = await client_allow_500.get(
                "/api/v1/workflows/not-a-valid-uuid",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 500
        data = resp.json()
        assert data["error_code"] == "INTERNAL_ERROR"
        assert "服务器内部错误" in data["message"]
