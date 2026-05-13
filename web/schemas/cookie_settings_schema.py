from typing import Annotated

from fastapi import Depends
from pydantic import BaseModel
from starlette.requests import Request
from starlette.responses import Response

from web.config_dir.env_modes import AppMode
from web.config_dir.config import env
from web.utils.logger_config import log_event


class AccToken(BaseModel):
    httponly: bool = True
    secure: bool = True if env.app_mode == AppMode.PROD else False
    samesite: str = 'strict'
    max_age: int = 900   # 15 минут


class RtToken(BaseModel):
    httponly: bool = True
    secure: bool = True if env.app_mode == AppMode.PROD else False
    samesite: str = 'strict'
    max_age: int = 15_552_000   # 180 дней

def check_at_factor(request: Request, response: Response):
    if hasattr(request.state, 'new_a_t'):
        log_event(f'Проставили access_token юзеру | admin_id: \033[31m{request.state.admin_id}\033[0m', level='WARNING')
        response.set_cookie('access_token', request.state.new_a_t, **AccToken().model_dump())

JWTCookieDep = Annotated[None, Depends(check_at_factor)]