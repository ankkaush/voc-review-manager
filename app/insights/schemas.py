from pydantic import BaseModel, Field


class InsightResult(BaseModel):
    insight_text: str = Field(min_length=10, max_length=600)
