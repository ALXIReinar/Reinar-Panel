from typing import Annotated

from asyncpg import Connection
from fastapi.params import Depends
from starlette.requests import Request

from web.data.sql_queries.admins_sql import AdminsQueries, AuthQueries
from web.data.sql_queries.vpn_protocols_sql import (
    ProtocolsQueries, 
    ProtocolCommandsQueries, 
    NodesQueries, 
    ProtoConfigsQueries
)


class PgSql:
    def __init__(self, conn: Connection):
        self.conn = conn
        self.admins = AdminsQueries(conn)
        self.auth = AuthQueries(conn)

        self.nodes = NodesQueries(conn)
        self.protocols = ProtocolsQueries(conn)
        self.protocol_commands = ProtocolCommandsQueries(conn)
        self.proto_configs = ProtoConfigsQueries(conn)


async def get_pg_pool(request: Request):
    async with request.app.state.pg_pool.acquire() as conn:
        yield conn

async def get_custom_pgsql(conn: Annotated[Connection, Depends(get_pg_pool)]):
    yield PgSql(conn)

PgSqlDep = Annotated[PgSql, Depends(get_custom_pgsql)]