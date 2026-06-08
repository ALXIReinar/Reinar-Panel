from pydantic import BaseModel, Field


class SpecParamsBulkAddSchema(BaseModel):
    """Схема для bulk добавления spec параметров"""
    tmp_id: int = Field(..., gt=0, description='ID шаблона')
    keys: list[str] = Field(..., min_length=1, description='Список ключей параметров')


class SpecParamsBulkDeleteSchema(BaseModel):
    """Схема для bulk удаления spec параметров"""
    param_ids: list[int] = Field(..., min_length=1, description='ID параметров для удаления')
