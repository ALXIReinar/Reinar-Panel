from typing import Literal

from fastapi import APIRouter, HTTPException
from starlette.requests import Request

from web.api.users.handlers import put_to_arq_bg_bulk, put_to_arq_bg_single
from web.config_dir.config import ArqDep
from web.data.postgres import PgSqlDep
from web.schemas.cookie_settings_schema import JWTCookieDep
from web.schemas.user_schema import (
    UserBulkCreateSchema,
    UserBulkUpdateSchema,
    UserBulkDeleteSchema, UserSubsUpdateSchema, UserUpdateSchema
)
from web.utils.anything import CoreProtoActions
from web.utils.logger_config import log_event

router = APIRouter(prefix='/private/users', tags=['Users Management'])



@router.get('/all')
async def get_users(request: Request, db: PgSqlDep, _: JWTCookieDep,
    last_id: int | None = None,
    sort_by: Literal['asc', 'desc'] = 'desc',
    limit: int = 50
):
    """Получить список пользователей с пагинацией"""
    users = await db.users.all(last_id, sort_by, limit)
    log_event(f'Отдали пользователей | records: {len(users)}; sort_by: \033[32m{sort_by}\033[0m; last_id: \033[35m{last_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)
    return {'success': True, 'users': users}


@router.get('/{user_id}')
async def get_user(user_id: int, request: Request, db: PgSqlDep, _: JWTCookieDep):
    user, subs = await db.users.get_by_id(user_id)
    if not user:
        log_event(f'Не удалось найти пользователя | user_id: \033[32m{user_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request, level='WARNING')
        raise HTTPException(status_code=404, detail={'success': False, 'message': 'Пользователь не найден'})

    log_event(f'Выдали Extent Юзера | user_id: \033[32m{user_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)
    return {'success': True, 'user': user, 'subscriptions': subs}



@router.post('/bulk/add')
async def bulk_create_users(body: UserBulkCreateSchema, request: Request, db: PgSqlDep, _: JWTCookieDep):
    """Bulk создание пользователей"""
    log_event(f'Bulk create пользователей | users_len: {len(body.users)}; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)

    users_data = [user.model_dump() for user in body.users]
    created_users = await db.users.bulk_create(users_data)

    log_event(f'Создано пользователей | created_users_len: {len(created_users)}; admin_id: \033[32m{request.state.admin_id}\033[0m', request=request,)
    return {'success': True, 'message': f'Пользователи созданы!', 'users': created_users}


@router.put('/bulk/update')
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
    job_ids = None
    if affected_users:  # Вызываем ARQ только если есть пользователи
        affected_event_ids = [ae['event_id'] for ae in affected_users]
        job_ids = await put_to_arq_bg_bulk(arq, affected_event_ids, body.action)

    log_event(f'Обновлено пользователей ({len(affected_users)}). Закинули исполнение операции в фон | job_ids: \033[31m{job_ids}\033[0m; action: \033[32m{body.action}\033[0m; admin_id: \033[32m{request.state.admin_id}\033[0m', request=request)
    return {'success': True, 'message': f'Bulk Операция ({body.action}) выполнена', 'affected_count': len(affected_users), 'arq_job_ids': job_ids}


@router.delete('/bulk/delete')
async def bulk_delete_users(body: UserBulkDeleteSchema, request: Request, db: PgSqlDep, arq: ArqDep, _: JWTCookieDep):
    """
    Bulk удаление пользователей 
    """
    log_event(f'Bulk delete пользователей | count: {len(body.user_ids)}; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)

    "1. Удаление на уровне данных"
    delete_events = await db.users.bulk_delete(body.user_ids)

    "2. Удаление на впн-ядрах"
    job_ids = []
    if delete_events:  # Вызываем ARQ только если есть пользователи
        delete_events_ids = [de['event_id'] for de in delete_events]
        job_ids = await put_to_arq_bg_bulk(arq, delete_events_ids, CoreProtoActions.word_delete)

    log_event(f'Удалено пользователей: {len(delete_events)}; admin_id: \033[32m{request.state.admin_id}\033[0m', request=request, level='WARNING')
    return {'success': True, 'message': f'Пользователи удалены!', 'deleted_count': len(delete_events), 'arq_job_ids': job_ids}


@router.put('/meta/{user_id}')
async def edit_user(user_id: int, body: UserUpdateSchema, request: Request, db: PgSqlDep, arq: ArqDep, _: JWTCookieDep):
    status_code, upd = await db.users.update(
        user_id=user_id,
        tg_username=body.tg_username,
        tg_id=body.tg_id,
        registered_at=body.registered_at,
    )
    if status_code == 409:
        log_event(f'Ограничение уникальности | err: \033[31m{upd}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request, level='WARNING')
        raise HTTPException(status_code=409, detail={'success': False, 'message': 'Ограничение уникальности', 'err': upd})

    if not upd:
        log_event(f'Не удалось обновить пользователя, не существует | upd_body: \033[34m{repr(body)}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)
        raise HTTPException(status_code=404, detail={'success': False, 'message': 'Пользователь не существует'})

    return {'success': True, 'message': 'Пользователь обновлён'}


@router.put('/subs/{user_id}')
async def edit_user_sub(user_id: int, body: UserSubsUpdateSchema, request: Request, db: PgSqlDep, arq: ArqDep, _: JWTCookieDep):
    user_subs_del, users_subs_add, users_sub_ids_upd = await db.users.edit_user_subs(
        user_id=user_id,
        upd_subs=body.user_subs_to_update,
        del_sub_ids=body.user_subs_to_delete,
        add_subs=body.user_subs_to_add,
    )
    add_jobs, del_jobs = [], []

    "Фоновая на удаления из впн-ядер"
    if user_subs_del:
        del_jobs = await put_to_arq_bg_single(arq, user_subs_del, CoreProtoActions.word_delete)
        log_event(f'\033[35m[User Subs Editor]\033[0m Отправка удаления впн-пользователей в фон | user_id: \033[34m{user_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)

    "Фоновая на вставку в впн-ядра"
    if users_subs_add:
        log_event(f'\033[35m[User Subs Editor]\033[0m Отправка вставок подписок пользователя в фон на впн-ядра | user_id: \033[34m{user_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)
        add_jobs = await put_to_arq_bg_single(arq, users_subs_add, CoreProtoActions.word_add)

    return {
        'success': True,
        'updated_subs_ids': users_sub_ids_upd,
        'added_subs_ids': [
            {'user_sub_id': us_add['user_sub_id'], 'sub_plan_id': us_add['sub_plan_id']}
            for us_add in users_subs_add
        ],
        'deleted_subs_ids': [
            {'user_sub_id': us_del['user_sub_id'], 'sub_plan_id': us_del['sub_plan_id']}
            for us_del in user_subs_del
        ],
        'add_jobs': add_jobs,
        'del_jobs': del_jobs,
    }