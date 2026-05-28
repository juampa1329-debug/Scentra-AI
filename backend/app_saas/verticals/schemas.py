from __future__ import annotations

from pydantic import BaseModel, Field


class VerticalApplyIn(BaseModel):
    industry_code: str = Field(default="general", min_length=1, max_length=80)
    create_agents: bool = False

