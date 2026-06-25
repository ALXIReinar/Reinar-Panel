from typing import Literal, Annotated

from fastapi import APIRouter, HTTPException
from fastapi.params import Query
from starlette.requests import Request

from web.api.users.handlers import put_to_arq_bg
from web.config_dir.config import ArqDep
from web.data.postgres import PgSqlDep
from web.schemas.cookie_settings_schema import JWTCookieDep
from web.schemas.user_schema import (
    UserBulkCreateSchema,
    UserBulkUpdateSchema,
    UserBulkDeleteSchema
)
from web.utils.anything import CoreProtoActions
from web.utils.logger_config import log_event

router = APIRouter(prefix='/private/users', tags=['Users Management'])



@router.get('/get')
async def get_users(request: Request, db: PgSqlDep, _: JWTCookieDep,
    last_id: int | None = None,
    sort_by: Literal['asc', 'desc'] = 'desc',
    limit: int = 50
):
    """Получить список пользователей с пагинацией"""
    users = await db.users.all(last_id, sort_by, limit)
    log_event(f'Отдали пользователей | records: {len(users)}; sort_by: \033[32m{sort_by}\033[0m; last_id: \033[35m{last_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)
    return {'success': True, 'users': users}


@router.get('/get_by_id')
async def get_user(order_id: Annotated[int, Query(alias='oid')], request: Request, db: PgSqlDep, _: JWTCookieDep):
    user = await db.users.get_by_id(order_id)
    if not user:
        log_event(f'Не удалось найти пользователя | payed_subs.id: \033[32m{order_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request, level='WARNING')
        raise HTTPException(status_code=404, detail={'success': False, 'message': 'Пользователь не найден'})

    log_event(f'Выдали Extent Юзера | payed_subs.id: \033[32m{order_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)
    return {'success': True, 'user': user}



@router.post('/bulk_add')
async def bulk_create_users(body: UserBulkCreateSchema, request: Request, db: PgSqlDep, arq: ArqDep, _: JWTCookieDep):
    """
    Bulk создание пользователей с подписками
    """
    log_event(f'Bulk create пользователей | users_len: {len(body.users)}; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)

    "1. Вставка на уровне данных"
    users_data = [user.model_dump() for user in body.users]
    created_users, users_for_arq_bg = await db.users.bulk_create_with_subs(users_data)

    "2. Вставка на впн-ядрах"
    users_for_arq_bg = [dict(arq_u) for arq_u in users_for_arq_bg]
    await put_to_arq_bg(arq, users_for_arq_bg, CoreProtoActions.word_add)

    log_event(f'Создано пользователей | created_users_len: {len(created_users)}; admin_id: \033[32m{request.state.admin_id}\033[0m', request=request,)
    return {'success': True, 'message': f'Пользователи созданы!', 'users': created_users}


@router.put('/bulk_update')
async def bulk_update_users(body: UserBulkUpdateSchema, request: Request, db: PgSqlDep, arq: ArqDep, _: JWTCookieDep):
    """
    Bulk операции над пользователями:
    - activate: активация подписок
    - deactivate: деактивация подписок
    - reset_traffic: сброс дневного трафика
    """
    log_event(f'Bulk update пользователей | action: \033[35m{body.action}\033[0m; users_affected: {len(body.user_ids)}; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)

    "1. Исполняем 'action' на уровне данных"
    affected_users = await db.users.bulk_update_action(body.user_ids, body.action)

    "2. Пробрасываем фоновую задачу на исполнение 'action' на ядрах"
    job_id = await put_to_arq_bg(arq, affected_users, body.action)

    log_event(f'Обновлено пользователей ({len(affected_users)}). Закинули исполнение операции в фон | job_id: \033[31m{job_id}\033[0m; action: \033[32m{body.action}\033[0m; admin_id: \033[32m{request.state.admin_id}\033[0m', request=request)
    return {'success': True, 'message': f'Bulk Операция ({body.action}) выполнена', 'affected_count': len(affected_users), 'arq_job_id': job_id}


@router.delete('/bulk_delete')
async def bulk_delete_users(body: UserBulkDeleteSchema, request: Request, db: PgSqlDep, arq: ArqDep, _: JWTCookieDep):
    """
    Bulk удаление пользователей 
    """
    log_event(f'Bulk delete пользователей | count: {len(body.user_ids)}; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)

    "1. Удаление на уровне данных"
    deleted_users = await db.users.bulk_delete(body.user_ids)

    "2. Удаление на впн-ядрах"
    # TODO Доделать запрос, чтобы аутбокс делал и возвращал (order_id, sub_plan_id, user_id)
    users_for_arq_bg = [dict(arq_u) for arq_u in deleted_users]
    await put_to_arq_bg(arq, users_for_arq_bg, CoreProtoActions.word_delete)

    log_event(f'Удалено пользователей: {len(deleted_users)}; admin_id: \033[32m{request.state.admin_id}\033[0m', request=request, level='WARNING')
    return {'success': True, 'message': f'Пользователи удалены!', 'deleted_count': len(deleted_users)}
