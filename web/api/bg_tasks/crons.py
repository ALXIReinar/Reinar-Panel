from fastapi import APIRouter
from starlette.requests import Request

from web.data.postgres import PgSqlDep
from web.utils.logger_config import log_event

router = APIRouter(prefix="/crons", tags=["cron"])


"Очистка просроченных rT"
@router.delete('/flush_refresh-tokens')
async def flush_expired_rT(request: Request, db: PgSqlDep):
    log_event('Очистка рефреш_токенов', request=request, level='WARNING')
    await db.auth.slam_refresh_tokens()
    log_event("Истёкшие сессии удалены", request=request, level='WARNING')

