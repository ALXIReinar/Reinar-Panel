from typing import Annotated

from asyncpg import Connection
from fastapi import Depends
from starlette.requests import Request


class PgSql:
    def __init__(self, conn: Connection):
        self.conn = conn


    async def get_sub_links(self, b64_string: str):
        query_sub_meta = '''
        SELECT 
            ps.sub_plan_id, sp.title, sp.traffic_limit_day AS sub_plan_limit, u.id AS user_id, u.uuid AS user_uuid,
            u.traffic_used_day_mb, ps.expire_date
        FROM users u
        JOIN payed_subs ps ON ps.user_id = u.id
        JOIN sub_plans sp ON sp.id = ps.sub_plan_id
        WHERE u.b64_id = $1 AND ps.expire_date > now() AND ps.is_active = true 
        '''
        sub_meta = await self.conn.fetchrow(query_sub_meta, b64_string)
        if not sub_meta:
            return None, []


        query_locations = '''
        SELECT pt.sub_prepare_script, pt.sub_required_libs as required_libs, np.config_link, np.id AS node_proto_id
        FROM sub_plans sp
        JOIN vnodes_sub_plans vsp ON vsp.sub_plan_id = sp.id
        JOIN nodes_protocols np ON np.id = vsp.node_proto_id AND np.user_visible = true
        JOIN protocols p ON p.id = np.proto_id
        JOIN proto_templates pt ON p.proto_tmp_id = pt.id
        WHERE sp.id = $1
        '''
        locations = await self.conn.fetch(query_locations, sub_meta['sub_plan_id'])
        return sub_meta, locations



async def get_pg_pool(request: Request):
    async with request.app.state.pg_pool.acquire() as conn:
        yield conn

async def get_custom_pgsql(conn: Annotated[Connection, Depends(get_pg_pool)]):
    yield PgSql(conn)

PgSqlDep = Annotated[PgSql, Depends(get_custom_pgsql)]