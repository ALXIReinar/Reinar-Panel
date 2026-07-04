from typing import Literal
from uuid import uuid4

from asyncpg import Connection
import secrets
import base64

from web.utils.anything import CoreProtoActions
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
        """Bulk создание пользователей с подписками"""
        insert_users_query = """
        WITH input_data AS (
            SELECT t.tg_id, t.b64_id, t.tg_username, t.uuid, t.sub_plan_id
            FROM UNNEST($1::bigint[], $2::varchar[], $3::varchar[], $4::varchar[], $5::integer[]) AS t(tg_id, b64_id, tg_username, uuid, sub_plan_id)
        ),
        inserted AS (
            INSERT INTO users (tg_id, b64_id, tg_username, uuid)
            SELECT tg_id, b64_id, tg_username, uuid
            FROM input_data
            ON CONFLICT DO NOTHING
            RETURNING id, b64_id, tg_username
        )
        SELECT ins.id, ins.b64_id, ins.tg_username, inp.sub_plan_id
        FROM inserted ins
        JOIN input_data inp ON ins.b64_id = inp.b64_id
        """

        "1. Вставка"
        users_count = len(users_data)

        # Генерируем b64_ids
        b64_ids = self.generate_b64_id(users_count)
        tg_ids = tuple(u['tg_id'] for u in users_data)
        tg_usernames = tuple(u['tg_username'] for u in users_data)
        uuids = tuple(str(uuid4()) for _ in range(users_count))
        sub_plan_ids = tuple(u['sub_plan_id'] for u in users_data)
        "Вставка"
        created_users = await self.conn.fetch(insert_users_query,tg_ids, b64_ids, tg_usernames, uuids, sub_plan_ids)
        log_event(f'Успешно создали Пользователей и b64 подписки | users_len: {len(created_users)}')

        "2. Создаём подписки для созданных пользователей + фиксация в outbox"
        insert_subs_query = """
        WITH ins_subs AS (
            INSERT INTO payed_subs (user_id, sub_plan_id, is_active, created_at, expire_date)
            SELECT t.user_id, t.sub_plan_id, t.is_active, NOW(), NOW() + (t.ttl_days || ' days')::interval
            FROM UNNEST($1::bigint[], $2::integer[], $3::boolean[], $4::integer[]) AS t(user_id, sub_plan_id, is_active, ttl_days)
            RETURNING id AS order_id, sub_plan_id, user_id, is_active
        ),
        sub_nodes_info AS (
            SELECT u.uuid, u.tg_username, ins_subs.order_id, ins_subs.user_id, ins_subs.sub_plan_id, np.id AS sub_node_id
            FROM ins_subs
            JOIN users u ON u.id = ins_subs.user_id
            JOIN vnodes_sub_plans vsp ON vsp.sub_plan_id = ins_subs.sub_plan_id 
            JOIN nodes_protocols np ON np.id = vsp.node_proto_id AND np.user_visible = true 
            JOIN nodes n ON np.node_id = n.id AND n.is_active = true 
            WHERE ins_subs.is_active = true
        ),
        inserted_outbox AS (
            INSERT INTO sub_nodes_outbox (user_uuid, tg_username, order_id, operation, sub_node_id)
            SELECT uuid, tg_username, order_id, $5, sub_node_id
            FROM sub_nodes_info
            RETURNING order_id
        )
        SELECT sni.order_id, sni.sub_plan_id, sni.user_id
        FROM sub_nodes_info sni
        """

        "Создаём маппинг для связи созданных пользователей с исходными данными"
        # ВАЖНО: dict сохраняет порядок вставки (Python 3.7+), но перезаписывает дубликаты
        # Поэтому берём только первое вхождение каждого tg_username
        seen_usernames = set()
        unique_users_data = []
        for u in users_data:
            if u['tg_username'] not in seen_usernames:
                unique_users_data.append(u)
                seen_usernames.add(u['tg_username'])
        
        data_map = {u['tg_username']: u for u in unique_users_data}

        user_ids = tuple(u['id'] for u in created_users)
        sub_plan_ids = tuple(data_map[u['tg_username']]['sub_plan_id'] for u in created_users)
        is_actives = tuple(data_map[u['tg_username']]['is_active'] for u in created_users)
        ttl_days_list = tuple(data_map[u['tg_username']]['ttl_days'] for u in created_users)
        user_for_arq_bg = await self.conn.fetch(insert_subs_query, user_ids, sub_plan_ids, is_actives, ttl_days_list, CoreProtoActions.add)

        return created_users, user_for_arq_bg


    async def bulk_update_action(self, user_ids: list[int], action: str):
        """3 upd-варианта"""
        "Активируем подписки"
        query_activate = """
        UPDATE payed_subs SET is_active = true FROM (
            SELECT u2.user_id, u.uuid, u.tg_username
            FROM (SELECT UNNEST($1::bigint[]) AS user_id) AS u2
            JOIN users u ON u.id = u2.user_id AND u.is_deleted = false
        ) AS input_users
        WHERE payed_subs.user_id = input_users.user_id AND is_active = false AND is_limited = false
        RETURNING id AS order_id, sub_plan_id, payed_subs.user_id, input_users.uuid, input_users.tg_username
        """

        "Деактивируем подписки"
        query_deactivate = """
        UPDATE payed_subs SET is_active = false FROM (
            SELECT u2.user_id, u.uuid, u.tg_username
            FROM (SELECT UNNEST($1::bigint[]) AS user_id) AS u2
            JOIN users u ON u.id = u2.user_id AND u.is_deleted = false
        ) AS input_users
        WHERE payed_subs.user_id = input_users.user_id AND is_active = true AND is_limited = false
        RETURNING id AS order_id, sub_plan_id, payed_subs.user_id, input_users.uuid, input_users.tg_username
        """

        "Сброс трафика"
        query_reset_traffic = """
        UPDATE users SET traffic_used_day_mb = 0 FROM (
            SELECT ps.id AS order_id, u2.user_id, ps.sub_plan_id, ps.is_limited
            FROM (SELECT UNNEST($1::bigint[]) AS user_id) AS u2
            JOIN payed_subs ps ON ps.user_id = u2.user_id
            WHERE ps.is_active = true
        ) AS input_users
        WHERE users.id = input_users.user_id AND users.is_deleted = false
        RETURNING input_users.order_id, input_users.sub_plan_id, input_users.user_id, users.uuid, users.tg_username, input_users.is_limited
        """

        "Outbox-фиксация перед отправкой в фон"
        action_map = {
            'activate': (query_activate, CoreProtoActions.add, ''),
            'deactivate': (query_deactivate, CoreProtoActions.delete, ''),
            'reset_traffic': (query_reset_traffic, CoreProtoActions.add, 'WHERE a.is_limited = true'),
        }
        action_query, action_param, is_limited_filter = action_map[action]
        base_query = f'''
        WITH action AS (
            {action_query}
        ),
        sub_nodes_info AS (
            SELECT a.uuid, a.tg_username, a.order_id, a.user_id, a.sub_plan_id, np.id AS sub_node_id
            FROM action a
            JOIN vnodes_sub_plans vsp ON vsp.sub_plan_id = a.sub_plan_id 
            JOIN nodes_protocols np ON np.id = vsp.node_proto_id AND np.user_visible = true 
            JOIN nodes n ON np.node_id = n.id AND n.is_active = true 
            {is_limited_filter}
        ),
        inserted AS (
            INSERT INTO sub_nodes_outbox (user_uuid, tg_username, order_id, operation, sub_node_id)
            SELECT uuid, tg_username, order_id, $2, sub_node_id
            FROM sub_nodes_info
            RETURNING order_id
        )
        SELECT sni.order_id, sni.sub_plan_id, sni.user_id
        FROM sub_nodes_info sni
        '''
        return await self.conn.fetch(base_query, user_ids, action_param)


    async def bulk_delete(self, user_ids: list[int]):
        """Удаление пользователей"""
        query = """
        WITH sub_off AS (
            UPDATE payed_subs SET is_active = false
            WHERE user_id = ANY($1) AND is_active = true
            RETURNING user_id
        ),
        del_users AS (
            UPDATE users SET is_deleted = true 
            WHERE id = ANY($1) AND is_deleted = false
            RETURNING id AS user_id, tg_username, uuid
        ),
        sub_nodes_info AS (
            SELECT du.uuid, du.tg_username, ps.id AS order_id, du.user_id, ps.sub_plan_id, np.id AS sub_node_id
            FROM del_users du
            JOIN sub_off so ON du.user_id = so.user_id
            JOIN payed_subs ps ON ps.user_id = so.user_id AND ps.is_limited = false -- Сборный фильтр, который поставит удаляться в фон только тех пользователей, которые точно есть в впн-ядрах
            -- Это те пользователи, которые не удалены из-за лимита (is_limited = false) и те, у которых была активна подписка(is_active = true)
            JOIN vnodes_sub_plans vsp ON vsp.sub_plan_id = ps.sub_plan_id 
            JOIN nodes_protocols np ON np.id = vsp.node_proto_id AND np.user_visible = true 
            JOIN nodes n ON np.node_id = n.id AND n.is_active = true 
        ),
        inserted_outbox AS (
            INSERT INTO sub_nodes_outbox (user_uuid, tg_username, order_id, operation, sub_node_id)
            SELECT uuid, tg_username, order_id, $2, sub_node_id
            FROM sub_nodes_info
            RETURNING order_id
        )
        SELECT sni.order_id, sni.sub_plan_id, sni.user_id
        FROM sub_nodes_info sni
        """
        return await self.conn.fetch(query, user_ids, CoreProtoActions.delete)


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
        WHERE u.is_deleted = false AND {cursor_condition}
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
        WHERE ps.id = $1 AND u.is_deleted = false
        '''
        return await self.conn.fetchrow(query, order_id)