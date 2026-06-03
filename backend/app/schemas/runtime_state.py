from typing import TypedDict


class RuntimeState(TypedDict, total=False):
    """Reusable graph runtime state.

    data is owned by business agents; control is owned by runtime gates;
    runtime is initialized once per run; errors are appended by NodeRunner.
    """

    data: dict
    control: dict
    runtime: dict
    errors: list[dict]
