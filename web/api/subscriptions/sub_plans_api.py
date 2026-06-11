from fastapi import APIRouter, HTTPException
from starlette.requests import Request

from web.data.postgres import PgSqlDep
from web.schemas.cookie_settings_schema import JWTCookieDep
from web.schemas.sub_plan_schema import (
    SubPlanCreateSchema,
    SubPlanUpdateSchema,
    SubPlanDeleteSchema
)
from web.utils.logger_config import log_event

router = APIRouter(prefix='/private/subscriptions/plans', tags=['Subscription Plans'])


@router.post('/create')
async def create_sub_plan(body: SubPlanCreateSchema, request: Request, db: PgSqlDep, _: JWTCookieDep):
    """Создание группы подписок"""
    plan_id = await db.sub_plans.create(body.title)
    log_event(f'Группа подписок создана | plan_id: \033[32m{plan_id}\033[0m; admin_id: \033[32m{request.state.admin_id}\033[0m', request=request)
    return {'success': True, 'message': 'Группа подписок создана', 'plan': plan_id}


@router.put('/update')
async def update_sub_plan(body: SubPlanUpdateSchema, request: Request, db: PgSqlDep, _: JWTCookieDep):
    """Обновление группы подписок"""
    log_event(f'Обновление группы подписок | plan_id: \033[35m{body.id}\033[0m; body: \033[37m{repr(body)}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)

    # Обновляем основные поля группы
    plan = await db.sub_plans.update(
        plan_id=body.id,
        title=body.title,
        description=body.description,
        ttl_days=body.ttl_days,
        cost=body.cost,
        traffic_limit_day=body.traffic_limit_day,
        is_active=body.is_active
    )

    if not plan:
        log_event(f'Группа подписок не найдена | plan_id: \033[33m{body.id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request, level='WARNING')
        raise HTTPException(status_code=404, detail={'success': False, 'message': 'Группа подписок не найдена'})

    # Редачим связки локаций(виртуальные ноды-протоколы) с группой подписок
    attached_count, detached_count = 0, 0
    if body.add_node_proto_ids:
        attached_count = await db.sub_plans.attach_vnodes(body.id, body.add_node_proto_ids)

    if body.remove_node_proto_ids:
        detached_count = await db.sub_plans.detach_vnodes(body.id, body.remove_node_proto_ids)

    log_event(f'Группа подписок обновлена | plan_id: \033[32m{body.id}\033[0m; attached: {attached_count}; detached: {detached_count}; admin_id: \033[32m{request.state.admin_id}\033[0m', request=request)
    return {
        'success': True, 'message': 'Группа подписок обновлена',
        'plan': plan,
        'attached_count': attached_count,
        'detached_count': detached_count
    }


@router.delete('/delete')
async def delete_sub_plan(body: SubPlanDeleteSchema, request: Request, db: PgSqlDep, _: JWTCookieDep):
    """Удаление группы подписок (CASCADE удалит связи)"""
    log_event(f'Удаление группы подписок | plan_id: \033[35m{body.id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)

    await db.sub_plans.delete(body.id)

    log_event(f'Группа подписок удалена | plan_id: \033[32m{body.id}\033[0m; admin_id: \033[32m{request.state.admin_id}\033[0m', request=request, level='WARNING')
    return {'success': True, 'message': 'Группа подписок удалена'}


@router.get('/all')
async def get_all_sub_plans(request: Request, db: PgSqlDep, _: JWTCookieDep, limit: int = 20):
    """Получить список всех групп подписок"""
    plans = await db.sub_plans.all(limit)
    log_event(f'Отдали список групп подписок | plans_len: \033[32m{len(plans)}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)
    return {'success': True, 'plans': plans}


@router.get('/get/{plan_id}')
async def get_sub_plan(plan_id: int, request: Request, db: PgSqlDep, _: JWTCookieDep):
    """Получить одну группу подписок с привязанными виртуальными нодами"""
    result = await db.sub_plans.get_by_id(plan_id)

    if not result:
        log_event(f"Не нашли группу подписок | plan_id: \033[31m{plan_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m", request=request, level='WARNING')
        raise HTTPException(status_code=404, detail='Группа подписок не найдена')

    log_event(f'Отдали группу подписок | plan_id: \033[32m{plan_id}\033[0m; vnodes_count: {len(result["vnodes"])}; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)
    return {'success': True, **result}
