from typing import Literal

from pydantic import BaseModel, Field, field_validator


class GetTmpSchema(BaseModel):
    last_id: int | None = None
    sort_by: Literal['asc', 'desc'] = 'desc'
    limit: int = Field(default=20, gt=0, le=100)


class AddTmpSchema(BaseModel):
    title: str = Field(..., min_length=1, max_length=32, description='Имя шаблона')


class UpdateTmpSchema(BaseModel):
    tmp_id: int = Field(..., gt=0, description='ID шаблона')
    url_tmp: str | None = Field(None, min_length=1, description='Шаблон URL конфиг-ссылки')

    @field_validator('url_tmp')
    @classmethod
    def tmp_url_validator(cls, v):
        if v is not None and '{{node___title}}' not in v:
            raise ValueError('Необходимо обязательно указать {{node___title}}')


        if v is not None and '{{node___address}}' not in v:
            raise ValueError('Необходимо обязательно указать {{node___address}}')

        return v


class DeleteTmpSchema(BaseModel):
    tmp_id: int = Field(..., gt=0, description='ID шаблона')
