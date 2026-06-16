from typing import Any

from pydantic import BaseModel, Field, field_validator

from web.utils.logger_config import log_event


class GetSpecValuesSchema(BaseModel):
    node_proto_id: int


class SpecKeySchema(BaseModel):
    key_id: int = Field(0, description='0 - ставить для ключей для добавления')
    key_name: str

class SpecKeysSetSchema(BaseModel):
    """Схема для bulk добавления spec параметров"""
    tmp_id: int = Field(..., gt=0, description='ID шаблона')
    add_keys: list[SpecKeySchema] = Field(description='Список ключей в конфиг-ссылке для добавления')
    update_keys: list[SpecKeySchema] = Field(description='Список ключей в конфиг-ссылке для обновления')
    del_keys: list[int] = Field(description='Список ключей в конфиг-ссылке для каскадного удаления вместе с значениями по этим ключам')

    @field_validator('update_keys', mode='after')
    @classmethod
    def check_uniq_upd_keys(cls, v):

        key_names_uniq = set(v_obj.key_name for v_obj in v)
        if len(key_names_uniq) != len(v):
            raise ValueError('Названия ключей должны быть уникальными!')
        return v



class SpecKeyValueSchema(BaseModel):
    spec_key_id: int = Field(0)
    value: Any

class SpecValuesSetSchema(BaseModel):
    node_proto_id: int
    spec_param_values: list[SpecKeyValueSchema] # [{"spec_key_id": 1, "value": "flow-xtls-rprx"}, {"spec_key_id": 2, "value": "public_key"}]
