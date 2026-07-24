from typing import Annotated

from asyncpg import Connection
from fastapi import Depends
from starlette.requests import Request

from web.sub.data.sql_queries.payment_sql import PaymentQueries
from web.sub.data.sql_queries.sub_sql import SubscriptionQueries
from web.sub.data.sql_queries.tg_routing_sql import TgRoutingQueries


class PgSql:
    def __init__(self, conn: Connection):
        self.conn = conn

        self.sub = SubscriptionQueries(conn)
        self.users_subs = PaymentQueries(conn)

        self.tg_routing = TgRoutingQueries(conn)

async def get_pg_pool(request: Request):
    async with request.app.state.pg_pool.acquire() as conn:
        yield conn

def get_custom_pgsql(conn: Annotated[Connection, Depends(get_pg_pool)]):
    return PgSql(conn)

PgSqlDep = Annotated[PgSql, Depends(get_custom_pgsql)]