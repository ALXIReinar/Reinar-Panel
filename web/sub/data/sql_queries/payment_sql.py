from datetime import datetime, timedelta

from asyncpg import Connection, ForeignKeyViolationError

from web.sub.anything import PayStatuses, CoreProtoActions


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
            -- 1. Обновляем статус заказа на "Оплачен" (допустим, status = 2)
            UPDATE pay_orders SET status = $5 
            WHERE id = $1 
            RETURNING id, user_id
        )
        -- 2. Вставляем или обновляем состояние подписки (Upsert)
        INSERT INTO user_subs (order_id, user_id, sub_plan_id, is_active, expire_date)
        VALUES ($1, $2, $3, true, NOW() + $4::interval)
        ON CONFLICT (user_id, sub_plan_id) 
        DO UPDATE SET 
            -- Если подписка уже есть (живая или мертвая), обновляем:
            order_id = EXCLUDED.order_id, -- Привязываем к новому платежу!
            is_active = true, 
            is_limited = false,
            expire_date = CASE 
                -- Если она жива и еще не истекла -> плюсуем к остатку
                WHEN user_subs.is_active = true AND user_subs.expire_date > NOW() 
                THEN user_subs.expire_date + $4::interval
                -- Если она истекла или выключена -> начинаем отсчет от сейчас
                ELSE NOW() + $4::interval
            END
        RETURNING id, expire_date
        """
        await self.conn.fetchrow(query, order_id, user_id, sub_plan_id, timedelta(days=sub_days), PayStatuses.success)


    async def get_user_info(self, user_id: int):
        query = 'SELECT uuid, tg_username FROM users WHERE id = $1 AND is_deleted = false'
        return await self.conn.fetchrow(query, user_id)


    async def get_stuck_actions(self):
        query = '''
        WITH retrieve_upd AS (
            UPDATE sub_nodes_outbox SET is_retried = true WHERE is_retried = false AND created_at < now() - interval '1 hour'
            RETURNING id, user_uuid, tg_username, user_sub_id, operation
        )
        SELECT * FROM retrieve_upd
        ORDER BY id
        '''
        return await self.conn.fetch(query)


    async def reset_traffic_by_users(self, users: list[dict]):
        # order_ids, sub_plan_ids, user_ids = zip(*tuple(u.values() for u in user_ids))
        order_ids, sub_plan_ids, user_ids = zip(
            *tuple(tuple(u['user_sub_id'], u['sub_plan_id'], u['user_id']) for u in users)
        )
        query = '''
        WITH users_to_proto_cores AS (
            SELECT user_sub_id, sub_plan_id, user_id 
            FROM UNNEST($1::bigint[], $2::integer[], $3::bigint[]) AS t(user_sub_id, sub_plan_id, user_id)
        ),
        -- 3. Собираем информацию о нодах для этих подписок
        expired_nodes_info AS (
            SELECT u.uuid, u.tg_username, upc.user_sub_id, vsp.id AS sub_node_id,
                   vsp.node_proto_id, n.private_ip, n.api_port, np.metrics_port, pt.proto_python_lib, pt.api_bulk_add_user_script,
                   pt.bulk_add_script_custom_params, pt.flatten_json_users_key, pt.flatten_user_identifier_key, pt.reload_core_command,
                   np.config_path, pt.constant_user_data_obj, pt.required_user_data_obj
            FROM users_to_proto_cores upc
            JOIN users u ON u.id = upc.user_id AND u.is_deleted = false
            JOIN vnodes_sub_plans vsp ON vsp.sub_plan_id = upc.sub_plan_id 
            JOIN nodes_protocols np ON np.id = vsp.node_proto_id AND np.user_visible = true 
            JOIN nodes n ON np.node_id = n.id AND n.is_active = true 
            JOIN protocols p ON np.proto_id = p.id 
            JOIN proto_templates pt ON p.tmp_id = pt.id 
        )
        -- 5. Группируем пользователей по нодам для пакетной отправки
        SELECT node_proto_id, private_ip, api_port, metrics_port, proto_python_lib, api_bulk_add_user_script, 
               flatten_json_users_key, flatten_user_identifier_key, reload_core_command, config_path, constant_user_data_obj,
               required_user_data_obj, bulk_add_script_custom_params,
               COALESCE(
                   json_agg(
                       json_build_object( 
                           'uuid', uuid, 
                           'tg_username', tg_username,
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
        return await self.conn.fetch(query, order_ids, sub_plan_ids, user_ids)


    async def reset_user_traffic_per_day(self):
        query = '''
        WITH zero_traffic AS (
            UPDATE users SET traffic_used_day_mb = 0 WHERE is_deleted = false
        ),
        users_to_proto_cores AS (
            UPDATE user_subs SET is_limited = false
            WHERE is_active = true AND is_limited = true
            RETURNING id AS user_sub_id, sub_plan_id, user_id
        ),
        -- 3. Собираем информацию о нодах для этих подписок
        expired_nodes_info AS (
            SELECT u.uuid, u.tg_username, upc.user_sub_id, vsp.id AS sub_node_id,
                   vsp.node_proto_id, n.private_ip, n.api_port, np.metrics_port, pt.proto_python_lib, pt.api_bulk_add_user_script,
                   pt.bulk_add_script_custom_params, pt.flatten_json_users_key, pt.flatten_user_identifier_key, pt.reload_core_command,
                   np.config_path, pt.constant_user_data_obj, pt.required_user_data_obj
            FROM users_to_proto_cores upc
            JOIN users u ON u.id = upc.user_id AND u.is_deleted = false
            JOIN vnodes_sub_plans vsp ON vsp.sub_plan_id = upc.sub_plan_id 
            JOIN nodes_protocols np ON np.id = vsp.node_proto_id AND np.user_visible = true 
            JOIN nodes n ON np.node_id = n.id AND n.is_active = true 
            JOIN protocols p ON np.proto_id = p.id 
            JOIN proto_templates pt ON p.tmp_id = pt.id 
        ),
        -- 4. Фиксируем операцию удаления в outbox (двухэтапный ack)
        insert_outbox AS (
            INSERT INTO sub_nodes_outbox (user_uuid, tg_username, user_sub_id, operation, node_proto_id)
            SELECT uuid, tg_username, user_sub_id, $1, sub_node_id
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
                           'tg_username', tg_username,
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