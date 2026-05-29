from typing import Literal

from pydantic import BaseModel, Field


class ModuleStatusResponse(BaseModel):
    module: str
    status: Literal["ready"]
    message: str
    available_endpoints: list[str] = Field(default_factory=list)

