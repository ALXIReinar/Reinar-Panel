from fastapi import APIRouter
from starlette.requests import Request

from web.data.postgres import PgSqlDep
from web.schemas.cookie_settings_schema import JWTCookieDep
from web.utils.logger_config import log_event

router = APIRouter(prefix='/cmd_center/history', tags=['Command Center History'])


@router.get('/all')
async def exec_history_all(request: Request, db: PgSqlDep, _: JWTCookieDep,
    last_id: int | None = None,
    sort_by: str = 'desc',
    limit: int = 20
):
    records = await db.remote_command_history.get_history_all(last_id, sort_by, limit)
    log_event(f'Отдали Историю команд | admin_id: \033[31m{request.state.admin_id}\033[0m')
    return {'records': records}