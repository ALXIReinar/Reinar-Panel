from asyncpg import Connection, ForeignKeyViolationError


class PaymentQueries:
    def __init__(self, conn: Connection):
        self.conn = conn


    async def order_subscription(self, user_id: int, sub_plan_id: int):
        query = 'INSERT INTO payed_subs (user_id, sub_plan_id) VALUES ($1, $2) RETURNING id'
        try:
            return await self.conn.fetchval(query, user_id, sub_plan_id)
        except ForeignKeyViolationError:
            return None


    async def activate_subscription(self, order_id: int, ttl_days: int, user_id: int):
        query = '''
        WITH deactivate_old AS (
            UPDATE payed_subs SET is_active = false WHERE user_id = $3
        )
        UPDATE payed_subs SET is_active = true, expire_date = created_at + ($2 || ' days')::interval 
        WHERE id = $1
        '''
        await self.conn.execute(query, order_id, ttl_days, user_id)


    async def get_user_info(self, user_id: int):
        query = 'SELECT uuid, tg_username FROM users WHERE id = $1'
        return await self.conn.fetchrow(query, user_id)


    async def get_stuck_actions(self):
        query = '''
        WITH retrieve_upd AS (
            UPDATE sub_nodes_outbox SET is_retried = true WHERE is_retried = false AND created_at > now() - interval '1 hour'
            RETURNING id, user_uuid, tg_username, order_id, operation
        )
        SELECT * FROM retrieve_upd
        ORDER BY operation DESC -- Сначала удаляем, затем добавляем
        '''
        return await self.conn.fetch(query)
