from typing import Any

from pydantic import BaseModel, Field


class SpecParamsBulkAddSchema(BaseModel):
    """Схема для bulk добавления spec параметров"""
    tmp_id: int = Field(..., gt=0, description='ID шаблона')
    keys: list[str] = Field(..., min_length=1, description='Список ключей параметров')


class SpecParamsBulkDeleteSchema(BaseModel):
    """Схема для bulk удаления spec параметров"""
    param_ids: list[int] = Field(..., min_length=1, description='ID параметров для удаления')


class SpecValuesAddDeleteSchema(BaseModel):
    node_proto_id: int
    spec_param_values: dict[int, Any] # {"spec_key_id1": "Secure_key", "spec_key_id2": "flow-xtls-rprx"}]

class SpecValuesBulkDeleteSchema(BaseModel):
    value_ids: list[int] = Field(min_length=1)
    node_proto_id: int
