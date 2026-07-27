from datetime import datetime
from typing import Literal
from asyncpg import Connection
import secrets
import base64

from web.schemas.user_schema import UserSubItem
from web.utils.anything import CoreProtoActions
from web.config_dir.config import env


class UsersQueries:
    def __init__(self, conn: Connection):
        self.conn = conn


    async def bulk_create(
        self, users_data: list[dict]  # [{tg_username, tg_id}, ...]
    ):
        """Bulk создание пользователей"""
        query = """
        INSERT INTO users (tg_id, tg_username)
        SELECT t.tg_id, t.tg_username
        FROM UNNEST($1::bigint[], $2::varchar[]) AS t(tg_id, tg_username)
        ON CONFLICT DO NOTHING
        RETURNING id, tg_username
        """
        tg_ids = tuple(u['tg_id'] for u in users_data)
        tg_usernames = tuple(u['tg_username'] for u in users_data)

        return await self.conn.fetch(query,tg_ids, tg_usernames)


    async def bulk_update_action(self, user_ids: list[int], action: str):
        """3 upd-варианта"""
        "Активируем подписки"
        query_activate = """
        UPDATE user_subs SET is_active = true FROM (
            SELECT u2.user_id
            FROM (SELECT UNNEST($1::bigint[]) AS user_id) AS u2
            JOIN users u ON u.id = u2.user_id AND u.is_deleted = false
        ) AS input_users
        WHERE user_subs.user_id = input_users.user_id AND is_active = false AND is_limited = false
        RETURNING id AS user_sub_id, sub_plan_id, uuid
        """

        "Деактивируем подписки"
        query_deactivate = """
        UPDATE user_subs SET is_active = false FROM (
            SELECT u2.user_id
            FROM (SELECT UNNEST($1::bigint[]) AS user_id) AS u2
            JOIN users u ON u.id = u2.user_id AND u.is_deleted = false
        ) AS input_users
        WHERE user_subs.user_id = input_users.user_id AND is_active = true
        RETURNING id AS user_sub_id, sub_plan_id, uuid, is_limited
        """

        "Сброс трафика"
        query_reset_traffic = """
        UPDATE user_subs SET traffic_used_day_mb = 0 FROM (
            SELECT u2.user_id
            FROM (SELECT UNNEST($1::bigint[]) AS user_id) AS u2
            JOIN users u ON u.id = u2.user_id AND u.is_deleted = false
        ) AS input_users
        WHERE user_subs.user_id = input_users.user_id
        RETURNING id AS user_sub_id, sub_plan_id, uuid, is_limited
        """

        "Outbox-фиксация перед отправкой в фон"
        action_map = {
            'activate': (query_activate, CoreProtoActions.add, ''),
            'deactivate': (query_deactivate, CoreProtoActions.delete, 'WHERE a.is_limited = false'), # ограниченные пользователи уже удалены из ядер
            'reset_traffic': (query_reset_traffic, CoreProtoActions.add, 'WHERE a.is_limited = true'), # Те, кто не блокнут и так в ядрах
        }
        action_query, action_param, is_limited_filter = action_map[action]
        base_query = f'''
        WITH action AS (
            {action_query}
        ),
        sub_nodes_info AS (
            SELECT a.uuid, a.user_sub_id, a.sub_plan_id, np.id AS node_proto_id
            FROM action a
            JOIN vnodes_sub_plans vsp ON vsp.sub_plan_id = a.sub_plan_id 
            JOIN nodes_protocols np ON np.id = vsp.node_proto_id AND np.user_visible = true 
            JOIN nodes n ON np.node_id = n.id AND n.is_active = true 
            {is_limited_filter}
        ),
        inserted AS (
            INSERT INTO sub_nodes_outbox (user_uuid, user_sub_id, operation, node_proto_id)
            SELECT uuid, user_sub_id, $2, node_proto_id
            FROM sub_nodes_info
            RETURNING user_sub_id
        )
        SELECT sni.user_sub_id, sni.sub_plan_id, sni.uuid
        FROM sub_nodes_info sni
        '''
        return await self.conn.fetch(base_query, user_ids, action_param)


    async def bulk_delete(self, user_ids: list[int]):
        """Удаление пользователей"""
        query = """
        WITH sub_off AS (
            UPDATE user_subs SET is_active = false
            WHERE user_id = ANY($1) AND is_active = true
            RETURNING id AS user_sub_id, uuid, user_id 
        ),
        del_users AS (
            UPDATE users SET is_deleted = true 
            WHERE id = ANY($1) AND is_deleted = false
            RETURNING id AS user_id
        ),
        sub_nodes_info AS (
            SELECT so.uuid, so.user_sub_id, so.user_id, us.sub_plan_id, np.id AS node_proto_id
            FROM sub_off so
            JOIN del_users du ON du.user_id = so.user_id
            JOIN user_subs us ON us.user_id = so.user_id AND us.is_limited = false -- Сборный фильтр, который поставит удаляться в фон только тех пользователей, которые точно есть в впн-ядрах
            -- Это те пользователи, которые не удалены из-за лимита (is_limited = false) и те, у которых была активна подписка(is_active = true)
            JOIN vnodes_sub_plans vsp ON vsp.sub_plan_id = us.sub_plan_id 
            JOIN nodes_protocols np ON np.id = vsp.node_proto_id AND np.user_visible = true 
            JOIN nodes n ON np.node_id = n.id AND n.is_active = true 
        ),
        inserted_outbox AS (
            INSERT INTO sub_nodes_outbox (user_uuid, user_sub_id, operation, node_proto_id)
            SELECT uuid, user_sub_id, $2, node_proto_id
            FROM sub_nodes_info
            RETURNING user_sub_id
        )
        SELECT sni.user_sub_id, sni.sub_plan_id, sni.uuid
        FROM sub_nodes_info sni
        """
        return await self.conn.fetch(query, user_ids, CoreProtoActions.delete)


    async def all(self, last_id: int | None, sort_by: Literal['asc', 'desc'], limit: int) -> list:
        """Получить список пользователей с пагинацией"""
        
        # Курсор для пагинации
        if last_id is None:
            cursor_condition = 'TRUE'  # Первая страница
            params = (limit,)
        else:
            cursor_condition = 'u.id > $2' if sort_by == 'asc' else 'u.id < $2'
            params = (limit, last_id)
        
        query = f'''
        WITH user_subscriptions AS (
            SELECT 
                us.user_id,
                json_agg(
                    json_build_object(
                        'sub_id', us.id,
                        'sub_plan_title', sp.title,
                        'is_active', us.is_active,
                        'is_limited', us.is_limited,
                        'expire_date', us.expire_date,
                        'traffic_used_total', us.used_mb,
                        'traffic_used_today', us.traffic_used_day_mb,
                        'infinite_traffic', us.infinite_traffic,
                        'infinite_expire', us.infinite_expire
                    ) ORDER BY us.is_active DESC, us.id DESC
                ) AS subscriptions
            FROM user_subs us
            JOIN sub_plans sp ON sp.id = us.sub_plan_id
            GROUP BY us.user_id
        )
        SELECT u.id AS user_id, u.tg_username, u.online_status, u.updated_at AS last_activity, u.registered_at,
               COALESCE(subs.subscriptions, '[]'::json) AS subscriptions
        FROM users u
        LEFT JOIN user_subscriptions subs ON subs.user_id = u.id
        WHERE u.is_deleted = false AND {cursor_condition}
        ORDER BY u.id {sort_by}
        LIMIT $1
        '''
        return await self.conn.fetch(query, *params)


    async def get_by_id(self, user_id: int):
        query_user_info = '''
        SELECT id AS user_id, tg_username, tg_id, online_status, updated_at AS last_activity, registered_at FROM users
        WHERE id = $1 AND is_deleted = false
        '''
        query_subs = '''
        SELECT us.id AS user_sub_id, us.order_id, us.b64_id, us.uuid, us.traffic_used_day_mb, us.traffic_limit_day, us.infinite_traffic,
               us.expire_date, us.infinite_expire, us.is_active, us.is_limited, po.timestamp AS sub_bought_at,
               us.sub_plan_id, sp.title AS sub_plan_title, sp.is_active AS sub_plan_active
        FROM user_subs us
        JOIN sub_plans sp ON sp.id = us.sub_plan_id
        JOIN pay_orders po ON po.id = us.order_id
        WHERE us.user_id = $1
        '''

        "Инфо пользователя"
        user = await self.conn.fetchrow(query_user_info, user_id)
        if not user:
            return None, None

        "Подписки пользователя"
        user_subs = await self.conn.fetch(query_subs, user_id)
        return user, user_subs


    async def update(
            self,
            user_id: int,
            tg_username: str | None = None,
            tg_id: int | None = None,
            registered_at: datetime | None = None
    ):
        params, updates, param_idx = [], [], 2

        if tg_id is not None:
            updates.append(f'tg_id = ${param_idx}')
            params.append(tg_id)
            param_idx += 1

        if registered_at is not None:
            updates.append(f'registered_at = ${param_idx}')
            params.append(registered_at)
            param_idx += 1

        if tg_username is not None:
            updates.append(f'tg_username = ${param_idx}')
            params.append(tg_username)
            param_idx += 1


        query = f'UPDATE users SET {','.join(updates)} WHERE id = $1 AND is_deleted = false'
        return await self.conn.fetchrow(query, user_id, *params)


    async def edit_user_subs(
            self,
            user_id: int,
            subs_upd_ids: list[UserSubItem],
            subs_del_ids: list[int],
            subs_add_ids: list[UserSubItem],
    ):
        del_sub_ids, add_sub_ids, upd_sub_ids = None, None, None

        add_query = '''
        -- 1. Вставка в user_subs
        -- 2. Поиск нод по подписке, вставка в оутбокс
        -- 3. Возврат саб_айди для арка
        
        -- *. Если не указано ничего кроме саб плана, то перетягиваем поля из sub_plan_offers
        '''

        del_query = '''
        -- 1. Деактивация(не удаление) подписки
        -- 2. Оутбокс по нодам подписки
        -- 3. Возврат саб_айди для арка
        '''

        upd_query = '''
        -- 1. Не принимаем на апдейт саб_план_айди - слишком мучительно. Удали подписку просто и добавь новую
        -- 2. Типикал if поле is not None...
        ---- 2.1. А как с траффик-полями быть... Что-то другое нужно туда класть
        '''
