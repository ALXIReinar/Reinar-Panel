from asyncpg import Connection

from web.arq_worker.data.sql_queries.action_core_proto_sql import BulkActionsQueries
from web.arq_worker.data.sql_queries.metrics_collect_sql import MetricsQueries
from web.arq_worker.data.sql_queries.outbox_sql import OutboxQueries
from web.arq_worker.data.sql_queries.traffic_reset_sql import TrafficResetQueries


class PgSql:
    def __init__(self, conn: Connection):
        self.conn = conn

        self.core_proto_bulk = BulkActionsQueries(conn)

        self.metrics = MetricsQueries(conn)
        self.outbox = OutboxQueries(conn)
        self.traffic_reset = TrafficResetQueries(conn)


    async def slam_refresh_tokens(self):
        query = 'DELETE FROM sessions_admins WHERE exp < now()'
        await self.conn.execute(query)


    async def get_user_tg_notify(self, user_id: int, user_sub_id: int):
        query = '''
        SELECT u.tg_id, us.b64_id FROM users u
        JOIN user_subs us ON us.user_id = u.id
        WHERE u.id = $1 AND us.id = $2
        '''
        return await self.conn.fetchrow(query, user_id, user_sub_id)