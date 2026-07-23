from datetime import timedelta, datetime

from asyncpg import Connection

from web.sub.config_dir.logger_config import log_event


class TgRoutingQueries:
    def __init__(self, conn: Connection):
        self.conn = conn

    async def add_tg_user(self, tg_id: int, tg_username: str, return_data: bool):
        query = """
        INSERT INTO users (tg_id, tg_username) VALUES ($1, $2)
        ON CONFLICT (tg_id) WHERE is_deleted = false
        DO UPDATE SET tg_username = EXCLUDED.$2
        RETURNING id, registered_at
        """
        insert_res = await self.conn.fetchrow(query, tg_id, tg_username)

        "Зарегался только что, значит подписок ещё нет => у него ещё нет подписок"
        if insert_res['registered_at'] + timedelta(minutes=10) < datetime.now():
            return True, {'sub_count': 0, 'user_id': insert_res['id']}

        "Если нужны данные"
        if return_data:
            user_info = await self.tg_user_profile(tg_id)
            return False, {**user_info, 'user_id': insert_res['id']}

        log_event(f'\033[36m[Tg Routing]\033[0m Обновили tg_username | user_id: \033[32m{insert_res['id']}\033[0m')
        return None, None


    async def tg_user_profile(self, tg_id: int):
        query = """
        SELECT COUNT(us.id) AS sub_count FROM users u
        JOIN user_subs us ON us.user_id = u.id
        WHERE u.tg_id = $1
        """
        return await self.conn.fetchrow(query, tg_id)


    async def get_tg_user_subs(self, tg_id: int):
        query = '''
        SELECT us.id AS user_sub_id, us.sub_plan_id, us.is_active, us.is_limited, us.expire_date, 
               us.traffic_used_day_mb, us.infinite_traffic, us.b64_id, us.infinite_expire,
               us.traffic_limit_day, us.used_mb, us.used_mb_limit, us.created_at, sp.title,
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
                       ) ORDER BY spo.cost
                   ),
                   '[]'::json
               ) AS offer_prices
        FROM user_subs us
        JOIN sub_plans sp ON sp.id = us.sub_plan_id
        JOIN users u ON us.user_id = u.id
        LEFT JOIN sub_plan_offers spo ON spo.sub_plan_id = us.sub_plan_id AND spo.is_active = true
        WHERE u.tg_id = $1 AND u.is_deleted = false
        GROUP BY us.id, sp.title
        ORDER BY us.id
        '''
        return await self.conn.fetch(query, tg_id)

    async def get_shop_sub_plans(self):
        query = '''
        SELECT sp.id, sp.title, sp.description,
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
                   ),
                   '[]'::json
               ) AS offer_prices
        FROM sub_plans sp
        LEFT JOIN sub_plan_offers spo ON spo.sub_plan_id = sp.id AND spo.is_active = true
        WHERE sp.is_active = true
        GROUP BY sp.id, sp.position
        ORDER BY sp.position
        '''
        return await self.conn.fetch(query)