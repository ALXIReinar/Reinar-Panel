from datetime import datetime

from asyncpg import Connection, ForeignKeyViolationError

from web.sub.anything import PayStatuses


class PaymentQueries:
    def __init__(self, conn: Connection):
        self.conn = conn


    async def order_subscription(self, user_id: int, sub_plan_id: int):
        query = '''
        WITH order_ins AS (
            INSERT INTO payed_subs (user_id, sub_plan_id) VALUES ($1, $2) RETURNING id, user_id
        ),
        old_sub AS (
            SELECT ps.user_id, ps.expire_date AS old_expire_date FROM payed_subs ps WHERE user_id = $1 AND ps.is_active = true
        )
        SELECT oi.id AS order_id, COALESCE(os.old_expire_date, NOW()) AS old_expire_date
        FROM order_ins oi
        LEFT JOIN old_sub os ON os.user_id = oi.user_id
        '''
        try:
            return await self.conn.fetchrow(query, user_id, sub_plan_id)
        except ForeignKeyViolationError:
            return None


    async def activate_subscription(self, order_id: int, expire_date: datetime, user_id: int):
        """READ COMMITTED - оставляем только потому, что у платёжки есть механика идемпотентности. По-хорошему блокировки и REPEATABLE READ"""
        query_deactivate = 'UPDATE payed_subs SET is_active = false WHERE user_id = $1'
        query_activate = 'UPDATE payed_subs SET is_active = true, expire_date = $2, status = $3 WHERE id = $1'
        async with self.conn.transaction():
            await self.conn.execute(query_deactivate, user_id)
            await self.conn.execute(query_activate, order_id, expire_date, PayStatuses.success)


    async def get_user_info(self, user_id: int):
        query = 'SELECT uuid, tg_username FROM users WHERE id = $1'
        return await self.conn.fetchrow(query, user_id)


    async def get_stuck_actions(self):
        query = '''
        WITH retrieve_upd AS (
            UPDATE sub_nodes_outbox SET is_retried = true WHERE is_retried = false AND created_at < now() - interval '1 hour'
            RETURNING id, user_uuid, tg_username, order_id, operation
        )
        SELECT * FROM retrieve_upd
        ORDER BY id
        '''
        return await self.conn.fetch(query)


    async def reset_user_traffic_per_day(self):
        query = 'UPDATE users SET traffic_used_day_mb = 0'
        await self.conn.execute(query)


    async def get_all_nodes_for_metrics(self):
        query = '''
        SELECT np.id, n.ip, n.private_ip, n.api_port, np.metrics_port, pt.metrics_command, pt.api_metrics_script, pt.proto_python_lib,
               pt.metrics_script_custom_params, pt.metrics_parser_code, pt.sub_required_libs
        FROM nodes n
        JOIN nodes_protocols np ON np.node_id = n.id AND np.user_visible = true
        JOIN protocols p ON np.proto_id = p.id
        JOIN proto_templates pt ON p.proto_tmp_id = pt.id
        WHERE n.is_active = true AND np.metrics_port IS NOT NULL
        '''
        return await self.conn.fetch(query)