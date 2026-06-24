from typing import Literal
from uuid import uuid4

from asyncpg import Connection
import secrets
import base64

from web.utils.logger_config import log_event
from web.config_dir.config import env


class UsersQueries:
    def __init__(self, conn: Connection):
        self.conn = conn

    @staticmethod
    def generate_b64_id(quantity: int) -> list[str]:
        """Генерация массива уникальных base64 токенов для subscription link"""
        while True:
            b64_ids = {
                base64.urlsafe_b64encode(secrets.token_bytes(env.sub_link_bytes)).decode('utf-8').rstrip('=')
                for _ in range(quantity)
            }
            if len(b64_ids) == quantity:
                break
        return list(b64_ids)

    async def bulk_create_with_subs(
        self, users_data: list[dict]  # [{tg_username, tg_id, sub_plan_id, ttl_days, is_active}, ...]
    ):
        """
        Bulk создание пользователей с подписками
        С retry-логикой для конфликтов b64_id
        """
        insert_users_query = """
        INSERT INTO users (tg_id, b64_id, tg_username, uuid)
        SELECT t.tg_id, t.b64_id, t.tg_username, t.uuid
        FROM UNNEST($1::bigint[], $2::varchar[], $3::varchar[], $4::varchar[]) AS t(tg_id, b64_id, tg_username, uuid)
        ON CONFLICT (b64_id) DO NOTHING
        RETURNING id, b64_id, tg_username
        """


        "1. Вставка"
        users_count = len(users_data)

        # Генерируем b64_ids
        b64_ids = self.generate_b64_id(users_count)
        tg_ids = tuple(u['tg_id'] for u in users_data)
        tg_usernames = tuple(u['tg_username'] for u in users_data)
        uuids = tuple(str(uuid4()) for _ in range(users_count))

        "Вставка"
        created_users = await self.conn.fetch(insert_users_query,tg_ids, b64_ids, tg_usernames, uuids)
        log_event(f'Успешно создали Пользователей и b64 подписки | users_len: {len(created_users)}')


        "2. Создаём подписки для созданных пользователей"
        insert_subs_query = """
        INSERT INTO payed_subs (user_id, sub_plan_id, is_active, created_at, expire_date)
        SELECT t.user_id, t.sub_plan_id, t.is_active, NOW(), NOW() + (t.ttl_days || ' days')::interval
        FROM UNNEST($1::bigint[], $2::integer[], $3::boolean[], $4::integer[]) AS t(user_id, sub_plan_id, is_active, ttl_days)
        """

        "Создаём маппинг для связи созданных пользователей с исходными данными"
        data_map = {u['tg_username']: u for u in users_data}

        user_ids = tuple(u['id'] for u in created_users)
        sub_plan_ids = tuple(data_map[u['tg_username']]['sub_plan_id'] for u in users_data)
        is_actives = tuple(data_map[u['tg_username']]['is_active'] for u in users_data)
        ttl_days_list = tuple(data_map[u['tg_username']]['ttl_days'] for u in users_data)
        await self.conn.execute(insert_subs_query, user_ids, sub_plan_ids, is_actives, ttl_days_list)

        return created_users


    async def bulk_update_action(self, user_ids: list[int], action: str) -> int:
        """Активация подписок пользователей"""
        query_activate = "UPDATE payed_subs SET is_active = true WHERE user_id = ANY($1) AND is_active = false RETURNING id"
        query_deactivate = "UPDATE payed_subs SET is_active = false WHERE user_id = ANY($1) AND is_active = true RETURNING id"
        query_reset_traffic = "UPDATE users SET traffic_used_day_mb = 0 WHERE id = ANY($1) RETURNING id"

        action_map = {'activate': query_activate, 'deactivate': query_deactivate, 'reset_traffic': query_reset_traffic,}
        res = await self.conn.fetch(action_map[action], user_ids)
        return len(res)


    async def bulk_delete(self, user_ids: list[int]) -> int:
        """Удаление пользователей (CASCADE удалит связанные подписки)"""
        query = "DELETE FROM users WHERE id = ANY($1) RETURNING id"
        result = await self.conn.fetch(query, user_ids)
        return len(result)


    async def all(self, last_id: int | None, sort_by: Literal['asc', 'desc'], limit: int) -> list:
        """Получить список пользователей с пагинацией - ровно одна запись на пользователя"""
        
        # Курсор для пагинации
        if last_id is None:
            cursor_condition = 'TRUE'  # Первая страница
            params = (limit,)
        else:
            cursor_condition = 'u.id > $2' if sort_by == 'asc' else 'u.id < $2'
            params = (limit, last_id)
        
        query = f'''
        WITH latest_sub AS (
            SELECT DISTINCT ON (user_id)
                id AS sub_id,
                user_id,
                sub_plan_id,
                expire_date,
                created_at,
                is_active,
                is_limited
            FROM payed_subs
            ORDER BY user_id, is_active DESC, id DESC
        )
        SELECT u.id AS user_id, ls.sub_id AS order_id, u.tg_username, u.traffic_used_day_mb, u.online_status, u.updated_at AS last_activity,
               sp.traffic_limit_day, ls.expire_date, ls.created_at, ls.is_active AS sub_active, ls.is_limited AS sub_limited
        FROM users u
        JOIN latest_sub ls ON ls.user_id = u.id
        JOIN sub_plans sp ON sp.id = ls.sub_plan_id
        WHERE {cursor_condition}
        ORDER BY u.id {sort_by}
        LIMIT $1
        '''
        return await self.conn.fetch(query, *params)


    async def get_by_id(self, order_id: int):
        query = '''
        SELECT u.id AS user_id, u.uuid, ps.id AS order_id, u.b64_id, u.tg_username, sp.id AS sub_plan_id, sp.title AS sub_plan_name,
               u.traffic_used_day_mb, sp.traffic_limit_day AS total_traffic_day, u.online_status, u.updated_at AS last_activity,
               u.registered_at, ps.expire_date, ps.created_at AS sub_created_at, ps.is_active AS sub_active, ps.is_limited AS sub_limited
        FROM users u
        JOIN payed_subs ps ON ps.user_id = u.id
        JOIN sub_plans sp ON sp.id = ps.sub_plan_id
        WHERE ps.id = $1
        '''
        return await self.conn.fetchrow(query, order_id)