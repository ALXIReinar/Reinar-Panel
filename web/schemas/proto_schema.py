from pydantic import BaseModel, Field


class ProtocolCreateSchema(BaseModel):
    """Схема для создания протокола"""
    name: str = Field(..., min_length=1, max_length=100, description="Название протокола")
    tmp_id: int


class ProtoPagenSchema(BaseModel):
    tmp_id: int | None = None
    offset: int = Field(0)
    limit: int = Field(15, le=15)