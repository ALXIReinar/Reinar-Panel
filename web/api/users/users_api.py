from typing import Literal

from fastapi import APIRouter
from starlette.requests import Request

from web.data.postgres import PgSqlDep
from web.schemas.cookie_settings_schema import JWTCookieDep
from web.schemas.user_schema import (
    UserBulkCreateSchema,
    UserBulkUpdateSchema,
    UserBulkDeleteSchema
)
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


@router.post('/bulk_create')
async def bulk_create_users(body: UserBulkCreateSchema, request: Request, db: PgSqlDep, _: JWTCookieDep):
    """
    Bulk создание пользователей с подписками
    """
    log_event(f'Bulk create пользователей | users_len: {len(body.users)}; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)

    users_data = [user.model_dump() for user in body.users]
    created_users, failed_users = await db.users.bulk_create_with_subs(users_data)

    log_event(
        f'Создано пользователей | created_users_len: {len(created_users)}; failed_users_len: \033[33m{len(failed_users)}\033[0m; admin_id: \033[32m{request.state.admin_id}\033[0m', request=request,
        level='CRITICAL' if failed_users else 'INFO'
    )
    return {'success': True, 'message': f'Пользователи созданы!', 'users': created_users, 'failed_users': failed_users}


@router.put('/bulk_update')
async def bulk_update_users(body: UserBulkUpdateSchema, request: Request, db: PgSqlDep, _: JWTCookieDep):
    """
    Bulk операции над пользователями:
    - activate: активация подписок
    - deactivate: деактивация подписок
    - reset_traffic: сброс дневного трафика
    """
    log_event(f'Bulk update пользователей | action: \033[35m{body.action}\033[0m; users_affected: {len(body.user_ids)}; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)

    affected_count = await db.users.bulk_update_action(body.user_ids, body.action)

    log_event(f'Обновлено пользователей: {affected_count}; action: \033[32m{body.action}\033[0m; admin_id: \033[32m{request.state.admin_id}\033[0m', request=request)
    return {'success': True, 'message': f'Bulk Операция ({body.action}) выполнена', 'affected_count': affected_count}


@router.delete('/bulk_delete')
async def bulk_delete_users(body: UserBulkDeleteSchema, request: Request, db: PgSqlDep, _: JWTCookieDep):
    """
    Bulk удаление пользователей (CASCADE удалит связанные подписки)
    """
    log_event(f'Bulk delete пользователей | count: {len(body.user_ids)}; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)

    deleted_count = await db.users.bulk_delete(body.user_ids)

    log_event(f'Удалено пользователей: {deleted_count}; admin_id: \033[32m{request.state.admin_id}\033[0m', request=request, level='WARNING')
    return {'success': True, 'message': f'Пользователи удалены!', 'deleted_count': deleted_count}
