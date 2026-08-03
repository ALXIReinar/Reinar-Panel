from datetime import timedelta, datetime, UTC

from asyncpg import Connection

from web.sub.config_dir.logger_config import log_event


class TgRoutingQueries:
    def __init__(self, conn: Connection):
        self.conn = conn

    async def add_tg_user(self, tg_id: int, tg_username: str, return_data: bool):
        query = """
        INSERT INTO users (tg_id, tg_username) VALUES ($1, $2)
        ON CONFLICT (tg_id) WHERE is_deleted = false
        DO UPDATE SET tg_username = $2
        RETURNING id, registered_at
        """
        insert_res = await self.conn.fetchrow(query, tg_id, tg_username)

        "Зарегался только что, значит подписок ещё нет => у него ещё нет подписок"
        if insert_res['registered_at'] + timedelta(minutes=1) > datetime.now(UTC):
            return True, {'sub_count': 0, 'user_id': insert_res['id'], 'registered_at': datetime.now()}

        "Если нужны данные"
        if return_data:
            user_info = await self.tg_user_profile(tg_id)
            return False, {**user_info, 'user_id': insert_res['id']}

        log_event(f'\033[36m[Tg Routing]\033[0m Обновили tg_username | user_id: \033[32m{insert_res['id']}\033[0m')
        return None, None


    async def tg_user_profile(self, tg_id: int):
        query = """
        SELECT u.id, u.registered_at, COUNT(us.id) AS sub_count FROM users u
        LEFT JOIN user_subs us ON us.user_id = u.id
        WHERE u.tg_id = $1
        GROUP BY u.id
        """
        return await self.conn.fetchrow(query, tg_id)


    async def get_tg_user_subs(self, tg_id: int):
        query = '''
        WITH vnode_counts AS (
            SELECT vsp.sub_plan_id, COUNT(DISTINCT vsp.id) AS sub_nodes_count
            FROM vnodes_sub_plans vsp
            JOIN nodes_protocols np ON np.id = vsp.node_proto_id AND np.user_visible = true
            GROUP BY vsp.sub_plan_id
        )
        SELECT 
            sp.id, 
            sp.title, 
            sp.description, 
            COALESCE(vc.sub_nodes_count, 0) AS sub_nodes_count,
            COALESCE(
                json_agg(
                    json_build_object(
                        'offer_id', spo.id,
                        'cost', spo.cost,
                        'ttl_days', spo.ttl_days,
                        'traffic_day_limit', spo.traffic_limit_day_mb,
                        'traffic_limit', spo.traffic_limit_mb,
                        'infinite_expire', spo.infinite_expire,
                        'infinite_traffic', spo.infinite_traffic
                    ) ORDER BY spo.position
                ) FILTER (WHERE spo.id IS NOT NULL),
                '[]'::json
            ) AS offer_prices
        FROM sub_plans sp
        LEFT JOIN vnode_counts vc ON vc.sub_plan_id = sp.id
        LEFT JOIN sub_plan_offers spo ON spo.sub_plan_id = sp.id AND spo.is_active = true
        JOIN user_subs us ON us.sub_plan_id = sp.id
        JOIN users u ON us.user_id = u.id
        WHERE u.tg_id = $1 AND u.is_deleted = false
        GROUP BY sp.id, sp.position, vc.sub_nodes_count
        ORDER BY sp.position
        '''
        return await self.conn.fetch(query, tg_id)

    async def get_shop_sub_plans(self):
        """Получить активные планы подписок для магазина с их офферами и количеством локаций"""
        query = '''
        WITH vnode_counts AS (
            SELECT vsp.sub_plan_id, COUNT(DISTINCT vsp.id) AS sub_nodes_count
            FROM vnodes_sub_plans vsp
            JOIN nodes_protocols np ON np.id = vsp.node_proto_id AND np.user_visible = true
            GROUP BY vsp.sub_plan_id
        )
        SELECT 
            sp.id, 
            sp.title, 
            sp.description, 
            COALESCE(vc.sub_nodes_count, 0) AS sub_nodes_count,
            COALESCE(
                json_agg(
                    json_build_object(
                        'offer_id', spo.id,
                        'cost', spo.cost,
                        'ttl_days', spo.ttl_days,
                        'traffic_day_limit', spo.traffic_limit_day_mb,
                        'traffic_limit', spo.traffic_limit_mb,
                        'infinite_expire', spo.infinite_expire,
                        'infinite_traffic', spo.infinite_traffic
                    ) ORDER BY spo.position
                ) FILTER (WHERE spo.id IS NOT NULL),
                '[]'::json
            ) AS offer_prices
        FROM sub_plans sp
        LEFT JOIN vnode_counts vc ON vc.sub_plan_id = sp.id
        LEFT JOIN sub_plan_offers spo ON spo.sub_plan_id = sp.id AND spo.is_active = true
        WHERE sp.is_active = true
        GROUP BY sp.id, sp.position, vc.sub_nodes_count
        ORDER BY sp.position
        '''
        return await self.conn.fetch(query)