from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """One shape for every response.

    Success: data populated, error null. Failure: error populated, data null
    (rendered by the exception handlers in app/core/errors.py).
    """

    data: T | None = None
    meta: dict[str, Any] = Field(default_factory=dict)
    error: dict[str, Any] | None = None