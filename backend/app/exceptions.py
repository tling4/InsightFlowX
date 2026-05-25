class AppException(Exception):
    """业务异常基类。

    与 FastAPI exception_handler 配合，自动转换为带 error_code 的统一 JSON 响应。
    继承体系：所有业务异常继承此类，子类在 __init__ 中固化 error_code / status_code。
    """

    def __init__(self, error_code: str, message: str, status_code: int, details: dict | None = None):
        self.error_code = error_code
        self.message = message
        self.status_code = status_code
        self.details = details
        super().__init__(message)


class WorkflowNotFoundError(AppException):
    def __init__(self, workflow_id: str | None = None):
        super().__init__(
            error_code="WORKFLOW_NOT_FOUND",
            message=f"工作流不存在: {workflow_id}" if workflow_id else "工作流不存在",
            status_code=404,
        )


class InvalidStateTransitionError(AppException):
    def __init__(self, workflow_id: str, current_status: str, target_action: str):
        super().__init__(
            error_code="INVALID_STATE_TRANSITION",
            message=f"工作流 {workflow_id} 当前状态 '{current_status}' 不允许执行 '{target_action}'",
            status_code=400,
            details={"workflow_id": workflow_id, "current_status": current_status, "target_action": target_action},
        )


class ConfigIncompleteError(AppException):
    def __init__(self, workflow_id: str, missing_fields: list[str] | None = None):
        msg = "工作流配置未完成"
        if missing_fields:
            msg += f" (缺少: {', '.join(missing_fields)})"
        super().__init__(
            error_code="CONFIG_INCOMPLETE",
            message=msg,
            status_code=400,
            details={"workflow_id": workflow_id, "missing_fields": missing_fields},
        )


class InvalidCredentialsError(AppException):
    def __init__(self):
        super().__init__(
            error_code="INVALID_CREDENTIALS",
            message="邮箱或密码错误",
            status_code=401,
        )


class InvalidTokenError(AppException):
    def __init__(self, reason: str = "无效或过期的令牌"):
        super().__init__(
            error_code="INVALID_TOKEN",
            message=reason,
            status_code=401,
        )


class DuplicateResourceError(AppException):
    def __init__(self, resource: str, identifier: str):
        super().__init__(
            error_code="DUPLICATE_RESOURCE",
            message=f"该{resource}已被使用: {identifier}",
            status_code=409,
            details={"resource": resource, "identifier": identifier},
        )


class ArtifactNotFoundError(AppException):
    def __init__(self, artifact_id: str | None = None):
        super().__init__(
            error_code="ARTIFACT_NOT_FOUND",
            message=f"产物不存在: {artifact_id}" if artifact_id else "产物不存在",
            status_code=404,
        )
