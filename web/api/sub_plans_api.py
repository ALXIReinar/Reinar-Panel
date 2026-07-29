from fastapi import APIRouter, HTTPException
from starlette.requests import Request

from web.config_dir.config import ArqDep
from web.data.postgres import PgSqlDep
from web.schemas.cookie_settings_schema import JWTCookieDep
from web.schemas.sub_plan_schema import SubPlanCreateSchema, SubPlanUpdateSchema, SubPlanVnodesSetSchema
from web.utils.anything import CoreProtoActions

from web.utils.logger_config import log_event

router = APIRouter(prefix='/private/subscriptions/plans', tags=['Subscription Plans'])


@router.post('/create')
async def create_sub_plan(body: SubPlanCreateSchema, request: Request, db: PgSqlDep, _: JWTCookieDep):
    """Создание группы подписок"""
    plan_id = await db.sub_plans.create(body.title)
    if not plan_id:
        log_event(f'Подписка с таким названием уже существует | plan_name: \033[32m{body.title}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request, level='WARNING')
        raise HTTPException(status_code=409, detail={'success': False, 'message': 'Подписка с таким именем уже существует'})

    log_event(f'Группа подписок создана | plan_id: \033[32m{plan_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)
    return {'success': True, 'message': 'Группа подписок создана', 'plan': plan_id}


@router.put('/{plan_id}')
async def update_sub_plan(plan_id: int, body: SubPlanUpdateSchema, request: Request, db: PgSqlDep, _: JWTCookieDep):
    """
    Обновление группы подписок

    Есть понятие
    - дневной лимит
    - общий лимит

    Чтобы назначить - укажите значение в мегабайтах
    Чтобы отключить - оставить нетронутым/указать null
    """
    log_event(f'Обновление группы подписок | plan_id: \033[35m{plan_id}\033[0m; body: \033[37m{repr(body)}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)

    # Обновляем основные поля группы
    plan_updated, offers_upd_count = await db.sub_plans.update(
        plan_id=plan_id,
        title=body.title,
        description=body.description,
        position=body.position,
        is_active=body.is_active,
        offers=body.offers,
    )

    if not plan_updated and (not body.add_node_proto_ids and not body.remove_node_proto_ids):
        log_event(f'Группа подписок не найдена | plan_id: \033[33m{plan_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request, level='WARNING')
        raise HTTPException(status_code=404, detail={'success': False, 'message': 'Группа подписок не найдена'})

    log_event(f'Группа подписок обновлена | plan_id: \033[32m{plan_id}\033[0m; admin_id: \033[32m{request.state.admin_id}\033[0m', request=request)
    return {
        'success': True, 
        'message': 'Группа подписок обновлена', 
        "offer_update_count": offers_upd_count,
    }


@router.delete('/{plan_id}')
async def delete_sub_plan(plan_id: int, request: Request, db: PgSqlDep, _: JWTCookieDep):
    """Удаление группы подписок (CASCADE удалит связи)"""
    log_event(f'Удаление группы подписок | plan_id: \033[35m{plan_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)

    await db.sub_plans.delete(plan_id)

    log_event(f'Группа подписок удалена | plan_id: \033[32m{plan_id}\033[0m; admin_id: \033[32m{request.state.admin_id}\033[0m', request=request, level='WARNING')
    return {'success': True, 'message': 'Группа подписок удалена'}


@router.get('/all')
async def get_all_sub_plans(request: Request, db: PgSqlDep, _: JWTCookieDep, limit: int = 20, offset: int = 0):
    """
    Получить список всех групп подписок

    !Добавить флаг-возможность скрывать настройки конфига от пользователя!
    """
    plans = await db.sub_plans.all(limit, offset)
    log_event(f'Отдали список групп подписок | plans_len: \033[32m{len(plans)}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)
    return {'success': True, 'plans': plans}


@router.get('/{plan_id}')
async def get_sub_plan(plan_id: int, request: Request, db: PgSqlDep, _: JWTCookieDep):
    """Получить одну группу подписок с привязанными виртуальными нодами"""
    plan = await db.sub_plans.get_by_id(plan_id)

    if not plan:
        log_event(f"Не нашли группу подписок | plan_id: \033[31m{plan_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m", request=request, level='WARNING')
        raise HTTPException(status_code=404, detail='Группа подписок не найдена')

    log_event(f'Отдали группу подписок | plan_id: \033[32m{plan_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m', request=request)
    return {'success': True, 'plan': plan}



@router.put('/{plan_id}/locations')
async def edit_vnodes_loadout(plan_id: int, body: SubPlanVnodesSetSchema, request: Request, db: PgSqlDep, _: JWTCookieDep, arq: ArqDep):
    """
    Работаем от оутбокс айди.
    1. В эндпоинте выбираются все пользователи тарифного плана, фиксируются.
    2. В фон летят айди-метки
    3. В фоне всё распихивается как надо
    """
    attached, detached = await db.sub_plans.edit_vnodes_set(plan_id, body.add_vnodes, body.remove_vnodes)
    add_job, del_job = None, None

    # Редачим связки локаций(виртуальные ноды) с тарифным планом
    if attached:
        job = await arq.enqueue_job('pointed_bulk_action', attached, CoreProtoActions.word_add)
        log_event(f"Закинули в фон вставку впн-пользователей на новые ноды(локации) | sub_plan_id: \033[35m{plan_id}\033[0m; job_id: \033[31m{job.job_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m", request=request)
        add_job = job.job_id

    if detached:
        job = await arq.enqueue_job('pointed_bulk_action', detached, CoreProtoActions.word_delete)
        log_event(f"Закинули в фон удаление впн-пользователей с только что удалённых локаций | sub_plan_id: \033[36m{plan_id}\033[0m; job_id: \033[31m{job.job_id}\033[0m; admin_id: \033[31m{request.state.admin_id}\033[0m", request=request)
        del_job = job.job_id

    return {"success": True, "attache_job_id": add_job, "detache_job_id": del_job}
