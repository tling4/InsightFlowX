"""Workflow state contract.

The workflow now uses the reusable runtime state shape. Keep WorkflowState as
an alias for imports that conceptually refer to the active graph state.
"""

from app.schemas.runtime_state import RuntimeState as WorkflowState

__all__ = ["WorkflowState"]
