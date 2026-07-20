import base64
import secrets
from datetime import datetime, timedelta
from uuid import uuid4

from asyncpg import Connection, ForeignKeyViolationError

from web.sub.anything import PayStatuses, CoreProtoActions
from web.sub.config_dir.config import env


class PaymentQueries:
    def __init__(self, conn: Connection):
        self.conn = conn


    async def order_subscription(self, user_id: int):
        query = 'INSERT INTO pay_orders (user_id, status) VALUES ($1, $2) RETURNING id'
        try:
            return await self.conn.fetchval(query, user_id, PayStatuses.pending)
        except ForeignKeyViolationError:
            return None


    async def activate_subscription(self, order_id: int, user_id: int, sub_plan_id: int, sub_days: int):
        query = """
        WITH updated_order AS (
            -- 1. Обновляем статус заказа
            UPDATE pay_orders SET status = $7 WHERE id = $1 RETURNING id, user_id
        ),
        inp AS (
            -- 2. Собираем наши входные переменные в "таблицу" из одной строки.
            SELECT 
                $1::bigint AS order_id, 
                $2::bigint AS user_id, 
                $3::text AS uuid, 
                $4::text AS b64_id, 
                $5::int AS sub_plan_id, 
                true AS is_active, 
                (NOW() + $6::interval) AS exp_date
        )
        -- 3. Вставляем или обновляем состояние подписки (Upsert)
        INSERT INTO user_subs (
            order_id, user_id, uuid, b64_id, sub_plan_id, 
            is_active, expire_date, infinite_expire, 
            infinite_traffic, traffic_limit_day, used_mb_limit
        )
        SELECT 
            inp.order_id, inp.user_id, inp.uuid, inp.b64_id, inp.sub_plan_id, 
            inp.is_active, inp.exp_date, sp.infinite_expire, 
            sp.infinite_traffic, sp.traffic_limit_day, sp.traffic_limit_total
        FROM inp
        JOIN sub_plans sp ON sp.id = inp.sub_plan_id 
        ON CONFLICT (user_id, sub_plan_id) 
        DO UPDATE SET 
            -- Обновляем привязку к новому заказу
            order_id = EXCLUDED.order_id,
            is_active = true, 
            is_limited = false,
            expire_date = CASE 
                WHEN user_subs.is_active = true AND user_subs.expire_date > NOW() 
                THEN user_subs.expire_date + $6::interval
                ELSE NOW() + $6::interval
            END
        -- 4. Возвращаем uuid прямо из таблицы user_subs (если подписка продлевается - вернется старый, если покупка - новый)
        RETURNING id, uuid
        """
        uuid = str(uuid4())
        b64_id = base64.urlsafe_b64encode(secrets.token_bytes(env.sub_link_bytes)).decode('utf-8').rstrip('=')
        return await self.conn.fetchrow(
            query, order_id, user_id, uuid, b64_id, sub_plan_id, timedelta(days=sub_days), PayStatuses.success
        )

    async def get_stuck_actions(self):
        query = '''
        WITH retrieve_upd AS (
            UPDATE sub_nodes_outbox SET is_retried = true WHERE is_retried = false AND created_at < now() - interval '1 hour'
            RETURNING id, user_uuid, user_sub_id, operation
        )
        SELECT * FROM retrieve_upd
        ORDER BY id
        '''
        return await self.conn.fetch(query)


    async def reset_traffic_by_users(self, users: list[dict]):
        # order_ids, sub_plan_ids, user_ids = zip(*tuple(u.values() for u in user_ids))
        order_ids, sub_plan_ids, user_uuids = zip(
            *tuple(tuple(u['user_sub_id'], u['sub_plan_id'], u['uuid']) for u in users)
        )
        query = '''
        -- 1. Входные данные
        WITH users_to_proto_cores AS (
            SELECT user_sub_id, sub_plan_id, uuid 
            FROM UNNEST($1::bigint[], $2::integer[], $3::bigint[]) AS t(user_sub_id, sub_plan_id, uuid)
        ),
        -- 2. Собираем информацию о нодах для этих подписок
        expired_nodes_info AS (
            SELECT upc.uuid, upc.user_sub_id, vsp.node_proto_id, n.private_ip, n.api_port, np.metrics_port, pt.proto_python_lib,
                   pt.api_bulk_add_user_script, pt.bulk_add_script_custom_params, pt.flatten_json_users_key, 
                   pt.flatten_user_identifier_key, pt.reload_core_command, np.config_path, pt.constant_user_data_obj, 
                   pt.required_user_data_obj
            FROM users_to_proto_cores upc
            JOIN vnodes_sub_plans vsp ON vsp.sub_plan_id = upc.sub_plan_id 
            JOIN nodes_protocols np ON np.id = vsp.node_proto_id AND np.user_visible = true 
            JOIN nodes n ON np.node_id = n.id AND n.is_active = true 
            JOIN protocols p ON np.proto_id = p.id 
            JOIN proto_templates pt ON p.tmp_id = pt.id 
        )
        -- 3. Группируем пользователей по нодам для пакетной отправки
        SELECT node_proto_id, private_ip, api_port, metrics_port, proto_python_lib, api_bulk_add_user_script, 
               flatten_json_users_key, flatten_user_identifier_key, reload_core_command, config_path, constant_user_data_obj,
               required_user_data_obj, bulk_add_script_custom_params,
               COALESCE(
                   json_agg(
                       json_build_object( 
                           'uuid', uuid, 
                           'user_sub_id', user_sub_id,
                           'node_proto_id', node_proto_id
                       )
                   ),
                   '[]'::json
               ) AS users
        FROM expired_nodes_info
        GROUP BY node_proto_id, private_ip, api_port, metrics_port, proto_python_lib, api_bulk_add_user_script, 
                 flatten_json_users_key, flatten_user_identifier_key, reload_core_command, config_path, constant_user_data_obj,
                 required_user_data_obj, bulk_add_script_custom_params
        '''
        return await self.conn.fetch(query, order_ids, sub_plan_ids, user_uuids)


    async def reset_user_traffic_per_day(self):
        query = '''
        -- 1. Обнуляем дневной трафик всем активным подпискам
        WITH users_to_proto_cores AS (
            UPDATE user_subs us
            SET traffic_used_day_mb = 0, is_limited = false
            FROM users u
            WHERE us.user_id = u.id
              AND us.is_active = true
              AND u.is_deleted = false
            RETURNING us.id AS user_sub_id, us.sub_plan_id, us.uuid
        ),
        -- 3. Собираем информацию о нодах для этих подписок
        expired_nodes_info AS (
            SELECT upc.uuid, upc.user_sub_id, vsp.node_proto_id, n.private_ip, n.api_port, np.metrics_port, pt.proto_python_lib,
                   pt.api_bulk_add_user_script, pt.bulk_add_script_custom_params, pt.flatten_json_users_key, 
                   pt.flatten_user_identifier_key, pt.reload_core_command, np.config_path, pt.constant_user_data_obj,
                   pt.required_user_data_obj
            FROM users_to_proto_cores upc
            JOIN vnodes_sub_plans vsp ON vsp.sub_plan_id = upc.sub_plan_id 
            JOIN nodes_protocols np ON np.id = vsp.node_proto_id AND np.user_visible = true 
            JOIN nodes n ON np.node_id = n.id AND n.is_active = true 
            JOIN protocols p ON np.proto_id = p.id 
            JOIN proto_templates pt ON p.tmp_id = pt.id 
        ),
        -- 4. Фиксируем операцию удаления в outbox (двухэтапный ack)
        insert_outbox AS (
            INSERT INTO sub_nodes_outbox (user_uuid, user_sub_id, operation, node_proto_id)
            SELECT uuid, user_sub_id, $1, node_proto_id
            FROM expired_nodes_info
        )
        -- 5. Группируем пользователей по нодам для пакетной отправки
        SELECT node_proto_id, private_ip, api_port, metrics_port, proto_python_lib, api_bulk_add_user_script, 
               flatten_json_users_key, flatten_user_identifier_key, reload_core_command, config_path, constant_user_data_obj,
               required_user_data_obj, bulk_add_script_custom_params,
               COALESCE(
                   json_agg(
                       json_build_object( 
                           'uuid', uuid, 
                           'user_sub_id', user_sub_id,
                           'node_proto_id', node_proto_id
                       )
                   ),
                   '[]'::json
               ) AS users
        FROM expired_nodes_info
        GROUP BY node_proto_id, private_ip, api_port, metrics_port, proto_python_lib, api_bulk_add_user_script, 
                 flatten_json_users_key, flatten_user_identifier_key, reload_core_command, config_path, constant_user_data_obj,
                 required_user_data_obj, bulk_add_script_custom_params
        '''
        return await self.conn.fetch(query, CoreProtoActions.add)


    async def get_all_nodes_for_metrics_cron(self):
        query = '''
        SELECT np.id, n.ip, n.private_ip, n.api_port, np.metrics_port, pt.metrics_command, pt.api_metrics_script, pt.proto_python_lib,
               pt.metrics_parser_code, pt.sub_required_libs
        FROM nodes n
        JOIN nodes_protocols np ON np.node_id = n.id AND np.user_visible = true
        JOIN protocols p ON np.proto_id = p.id
        JOIN proto_templates pt ON p.tmp_id = pt.id
        WHERE n.is_active = true AND np.metrics_port IS NOT NULL
        '''
        return await self.conn.fetch(query)