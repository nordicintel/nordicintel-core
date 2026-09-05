"""Common model configuration."""

from pydantic import BaseModel, ConfigDict


class CoreModel(BaseModel):
    """Strict base for public contracts."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)
