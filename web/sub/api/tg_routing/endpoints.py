from typing import Annotated

from fastapi import APIRouter, Query
from starlette.requests import Request
from starlette.responses import Response

from web.sub.anything import TgRoutingAccessDep
from web.sub.config_dir.logger_config import log_event
from web.sub.data.postgres import PgSqlDep
from web.sub.schemas.tg_routing_schema import UserAddSchema

router = APIRouter(dependencies=[TgRoutingAccessDep])

@router.post('/users/add')
async def add_tg_user(body: UserAddSchema, request: Request, db: PgSqlDep):
    insert_success, user_info = await db.tg_routing.add_tg_user(body.tg_id, body.tg_username, body.return_data)
    log_event(f'\033[36m[Tg Routing]\033[0m Попытка создать пользователя | insert_res: {insert_success}; user_id: \033[33m{user_info.get("user_id")}\033[0m', request=request)
    if body.return_data:
        return {'insert_success': insert_success, **user_info}
    return Response(status_code=204)

@router.get('/users/get')
async def get_tg_user(tg_id: Annotated[int, Query()], request: Request, db: PgSqlDep):
    user_info = await db.tg_routing.tg_user_profile(tg_id)
    log_event(f'\033[36m[Tg Routing]\033[0m Отдали профиль инфо | user_id: {user_info['id']}')
    return user_info

@router.get('/users/subs/all')
async def get_tg_user_subs(tg_id: Annotated[int, Query()], request: Request, db: PgSqlDep):
    user_subs = await db.tg_routing.get_tg_user_subs(tg_id)
    log_event(f'\033[36m[Tg Routing]\033[0m Отдали подписки юзера | user_sub_len: {len(user_subs)}; tg_id: {tg_id}', request=request)
    return {'user_subs': user_subs}


@router.get('/sub_plans/all')
async def get_shop_sub_plans(request: Request, db: PgSqlDep):
    sub_plans = await db.tg_routing.get_shop_sub_plans()
    log_event(f'\033[36m[Tg Routing]\033[0m Отдали тарифные планы | sub_plans_len: {len(sub_plans)}', request=request)
    return {'sub_plans': sub_plans}