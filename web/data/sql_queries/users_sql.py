from datetime import datetime
from typing import Literal
from asyncpg import Connection, UniqueViolationError
import secrets
import base64

from web.schemas.user_schema import UserSubUpdItem, UserSubAddItem
from web.utils.anything import CoreProtoActions
from web.config_dir.config import env
from web.utils.logger_config import log_event


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
        )
        INSERT INTO sub_nodes_outbox (user_uuid, user_sub_id, operation, node_proto_id)
        SELECT uuid, user_sub_id, $2, node_proto_id
        FROM sub_nodes_info
        RETURNING id AS event_id
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
        )
        INSERT INTO sub_nodes_outbox (user_uuid, user_sub_id, operation, node_proto_id)
        SELECT uuid, user_sub_id, $2, node_proto_id
        FROM sub_nodes_info
        RETURNING id AS event_id
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
        SELECT us.id AS user_sub_id, us.order_id, us.b64_id, us.uuid, us.traffic_used_day_mb, us.traffic_limit_day AS traffic_limit_day, 
               us.used_mb AS traffic_used_mb, us.used_mb_limit AS traffic_limit_mb,
               us.infinite_traffic, us.expire_date, us.infinite_expire, us.is_active, us.is_limited, po.timestamp AS sub_bought_at,
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


        query = f'UPDATE users SET {','.join(updates)} WHERE id = $1 AND is_deleted = false RETURNING id'
        try:
            return 200, await self.conn.fetchval(query, user_id, *params)
        except UniqueViolationError as e:
            return 409, repr(e)


    async def edit_user_subs(
            self,
            user_id: int,
            upd_subs: list[UserSubUpdItem],
            del_sub_ids: list[int],
            add_subs: list[UserSubAddItem],
    ):
        deleted_subs, add_sub_ids, upd_sub_ids = [], [], []

        query = '''
        -- 1. Вставка с возвратом. Может по уникальным индексам упасть => только часть операций в ноды пойдёт
        WITH sub_changes AS (
            {edit_query}
            -- Обязательные поля для возврата ins/del запросов
            RETURNING id AS user_sub_id, uuid, sub_plan_id 
        ),
        -- 2. Собираем outbox набор с сохранением sub_plan_id
        outbox_with_metadata AS (
            SELECT sc.uuid, sc.user_sub_id, sc.sub_plan_id, vsp.node_proto_id
            FROM sub_changes sc
            JOIN vnodes_sub_plans vsp ON vsp.sub_plan_id = sc.sub_plan_id
            JOIN nodes_protocols np ON vsp.node_proto_id = np.id AND np.user_visible = true
            JOIN nodes n ON n.id = np.node_id AND n.is_active = true
        ),
        insert_outbox AS (
            INSERT INTO sub_nodes_outbox (user_uuid, user_sub_id, operation, node_proto_id)
            SELECT uuid, user_sub_id, $1, node_proto_id
            FROM outbox_with_metadata
            RETURNING id AS event_id, user_sub_id, user_uuid, node_proto_id
        ),
        -- 4.1. Пре-агрегация впн-пользователей с sub_plan_id. Максимум 10 записей
        pre_agg_users AS (
            SELECT owm.node_proto_id,
                   json_agg(
                        json_build_object(
                            'event_id', io.event_id,
                            'uuid', io.user_uuid,
                            'user_sub_id', io.user_sub_id,
                            'sub_plan_id', owm.sub_plan_id
                        )
                   ) AS users
            FROM insert_outbox io
            JOIN outbox_with_metadata owm ON io.user_sub_id = owm.user_sub_id AND io.node_proto_id = owm.node_proto_id
            GROUP BY owm.node_proto_id
        ),
        -- 4.2. Пре агрегация инжекторов. До 2000-3000 записей, так что последняя
        pre_agg_user_injectors AS (
            SELECT tmp_id,
               json_agg(
                   json_build_object(
                       'flatten_array_cursor', flatten_array_cursor,
                       'extractor_script', extractor_script,
                       'libs', libs
                   )
               ) AS user_injectors
            FROM templates_users_extractors
            GROUP BY tmp_id
        )
        -- 5. Ноды для вставки пользователя (подписки, впн-пользователя)
        SELECT np.id AS node_proto_id, n.private_ip, n.api_port, np.metrics_port, pt.proto_python_lib, pt.api_bulk_delete_user_script, 
               pt.reload_core_command, np.config_path, pt.bulk_delete_script_custom_params, pt.constant_user_data_obj, pt.required_user_data_obj,
               pt.api_bulk_add_user_script, pt.bulk_add_script_custom_params,
               pau.users,
               COALESCE(aui.user_injectors, '[]'::json) AS user_injectors
        FROM nodes_protocols np
        JOIN nodes n ON n.id = np.node_id AND n.is_active = true
        JOIN protocols p ON p.id = np.proto_id
        JOIN pre_agg_users pau ON pau.node_proto_id = np.id
        JOIN proto_templates pt ON p.tmp_id = pt.id 
        LEFT JOIN pre_agg_user_injectors aui ON aui.tmp_id = pt.id 
        WHERE np.user_visible = true
        '''
        add_query = '''
        INSERT INTO user_subs (
            order_id, user_id, sub_plan_id, is_active, is_limited, expire_date,
            traffic_used_day_mb, infinite_traffic, uuid, b64_id, infinite_expire,
            traffic_limit_day, used_mb, used_mb_limit
        ) 
        SELECT order_id, $15 AS user_id, sub_plan_id, is_active, is_limited, expire_date,
            traffic_used_day_mb, infinite_traffic, uuid, b64_id, infinite_expire,
            traffic_limit_day, used_mb, used_mb_limit
        FROM UNNEST(
            $2::bigint[], $3::integer[], $4::boolean[], $5::boolean[], $6::timestamptz[],
            $7::bigint[], $8::boolean[], $9::varchar[], $10::varchar[], $11::boolean[],
            $12::bigint[], $13::bigint[], $14::bigint[]
        ) AS t(
            order_id, sub_plan_id, is_active, is_limited, expire_date,
            traffic_used_day_mb, infinite_traffic, b64_id, uuid, infinite_expire,
            traffic_limit_day, used_mb, used_mb_limit
        )
        ON CONFLICT DO NOTHING
        '''

        del_query = '''
        DELETE FROM user_subs WHERE user_id = $2 AND id = ANY($3)
        '''

        "Удаление (выполняется первым, чтобы освободить constraint UNIQUE (user_id, sub_plan_id))"
        if del_sub_ids:
            deleted_subs = await self.conn.fetch(
                query.format(edit_query=del_query), CoreProtoActions.delete, user_id, del_sub_ids
            )
            log_event(f'Удалили подписки пользователя | user_sub_ids: \033[31m{del_sub_ids}\033[0m; user_id: \033[35m{user_id}\033[0m', level='WARNING')

        "Обновление"
        if upd_subs:
            for item in upd_subs:
                updates, params, param_idx = [], [], 3

                if item.b64_id is not None:
                    updates.append(f'b64_id = ${param_idx}')
                    params.append(item.b64_id)
                    param_idx += 1

                if item.traffic_used_mb is not None:
                    updates.append(f'used_mb = ${param_idx}')
                    params.append(item.traffic_used_mb)
                    param_idx += 1

                if item.traffic_used_day_mb is not None:
                    updates.append(f'traffic_used_day_mb = ${param_idx}')
                    params.append(item.traffic_used_day_mb)
                    param_idx += 1

                if item.traffic_limit_day_mb != 0:
                    updates.append(f'traffic_limit_day = ${param_idx}')
                    params.append(item.traffic_limit_day_mb)
                    param_idx += 1

                if item.traffic_limit_mb is not None:
                    updates.append(f'used_mb_limit = ${param_idx}')
                    params.append(item.traffic_limit_mb)
                    param_idx += 1

                if item.infinite_traffic is not None:
                    updates.append(f'infinite_traffic = ${param_idx}')
                    params.append(item.infinite_traffic)
                    param_idx += 1

                if item.expire_date is not None:
                    updates.append(f'expire_date = ${param_idx}')
                    params.append(item.expire_date)
                    param_idx += 1

                if item.infinite_expire is not None:
                    updates.append(f'infinite_expire = ${param_idx}')
                    params.append(item.infinite_expire)
                    param_idx += 1

                if item.order_id != 0:
                    updates.append(f'order_id = ${param_idx}')
                    params.append(item.order_id)
                    param_idx += 1

                upd_query = f'''
                UPDATE user_subs SET {', '.join(updates)}
                WHERE user_id = $1 AND id = $2
                RETURNING id
                '''
                if params:
                    sub_upd_id = await self.conn.fetchval(upd_query, user_id, item.user_sub_id, *params)
                    upd_sub_ids.append(sub_upd_id)
                    log_event(f'Обновили параметры подписки пользователя | user_sub_id: \033[33m{item.user_sub_id}\033[0m; upd_params: \033[34m{list(zip(updates, params))}\033[0m')

        "Вставка (выполняется последней, после освобождения constraint через DELETE)"
        if add_subs:
            log_event(f'\033[34m{add_subs[0].model_dump()}\033[0m', level='DEBUG')
            "Явная распаковка полей для соответствия порядку в UNNEST"
            order_ids, sub_plan_ids, is_actives, is_limiteds, exp_dates, traf_ud_mb, inf_traf, b64_ids, uuids, inf_exp, traf_ld_mb, traf_u_mb, traf_l_mb = zip(
                *[(
                    item.order_id, item.sub_plan_id, item.is_active, item.is_limited, item.expire_date,
                    item.traffic_used_day_mb, item.infinite_traffic, item.b64_id, item.uuid, item.infinite_expire,
                    item.traffic_limit_day_mb, item.traffic_used_mb, item.traffic_limit_mb
                ) for item in add_subs]
            )
            add_sub_ids = await self.conn.fetch(
                query.format(edit_query=add_query), CoreProtoActions.add,
                order_ids, sub_plan_ids, is_actives, is_limiteds, exp_dates,
                traf_ud_mb, inf_traf, b64_ids, uuids, inf_exp,
                traf_ld_mb, traf_u_mb, traf_l_mb, user_id
            )
            # Извлекаем user_sub_id из JSON поля 'users' (массив пользователей на нодах)
            added_user_sub_ids = set([
                user['user_sub_id']
                for node in add_sub_ids
                for user in node['users']
            ])
            log_event(f'Добавили новую подписку пользователю | user_sub_ids: \033[34m{added_user_sub_ids}\033[0m; user_id: \033[32m{user_id}\033[0m')

        return deleted_subs, add_sub_ids, upd_sub_ids
