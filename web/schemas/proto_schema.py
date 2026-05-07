from datetime import datetime
from pydantic import BaseModel, Field


class ProtocolCreateSchema(BaseModel):
    """Схема для создания протокола"""
    name: str = Field(..., min_length=1, max_length=100, description="Название протокола")


class ProtocolSchema(BaseModel):
    """Схема протокола"""
    id: int
    name: str
    created_at: datetime

class ProtoPagenSchema(BaseModel):
    offset: int = Field(0)
    limit: int = Field(le=15)