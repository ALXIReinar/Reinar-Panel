from pydantic import BaseModel


class WhitelistUpdateSchema(BaseModel):
    """Схема для bulk update статусов команд"""
    set_as_active: list[int] = []
    set_as_inactive: list[int] = []


class WhitelistAddSchema(BaseModel):
    """Схема для bulk add команд"""
    commands: list[str]


class WhitelistDeleteSchema(BaseModel):
    """Схема для bulk delete команд"""
    ids: list[int]