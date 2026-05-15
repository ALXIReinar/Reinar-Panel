from typing import Annotated

from asyncpg import Connection
from fastapi.params import Depends
from starlette.requests import Request

from web.data.sql_queries.admins_sql import AdminsQueries, AuthQueries
from web.data.sql_queries.nodes_protocols_sql import NodesProtocolsQueries
from web.data.sql_queries.nodes_sql import NodesQueries
from web.data.sql_queries.proto_cmds_sql import ProtocolCommandsQueries
from web.data.sql_queries.protocols_sql import ProtocolsQueries
from web.data.sql_queries.whitelist_sql import WhitelistQueries
from web.data.sql_queries.users_sql import UsersQueries
from web.data.sql_queries.sub_plans_sql import SubPlansQueries
from web.data.sql_queries.proto_templates_sql import ProtoTemplatesQueries
from web.data.sql_queries.template_spec_params_sql import TemplateSpecParamsQueries
from web.data.sql_queries.remote_execute_history_sql import RemoteCommandHistoryQueries


class PgSql:
    def __init__(self, conn: Connection):
        self.conn = conn
        self.admins = AdminsQueries(conn)
        self.auth = AuthQueries(conn)

        self.nodes = NodesQueries(conn)
        self.nodes_protocols = NodesProtocolsQueries(conn)
        self.protocols = ProtocolsQueries(conn)
        self.protocol_commands = ProtocolCommandsQueries(conn)
        self.whitelist_cmd = WhitelistQueries(conn)
        self.remote_command_history = RemoteCommandHistoryQueries(conn)

        self.proto_templates = ProtoTemplatesQueries(conn)
        self.template_spec_params = TemplateSpecParamsQueries(conn)

        self.users = UsersQueries(conn)
        self.sub_plans = SubPlansQueries(conn)


async def get_pg_pool(request: Request):
    async with request.app.state.pg_pool.acquire() as conn:
        yield conn

async def get_custom_pgsql(conn: Annotated[Connection, Depends(get_pg_pool)]):
    yield PgSql(conn)

PgSqlDep = Annotated[PgSql, Depends(get_custom_pgsql)]