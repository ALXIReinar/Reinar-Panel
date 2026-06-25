from datetime import datetime

from asyncpg import Connection, ForeignKeyViolationError

from web.sub.anything import PayStatuses, CoreProtoActions


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


    async def reset_traffic_by_users(self, users: list[dict]):
        # order_ids, sub_plan_ids, user_ids = zip(*tuple(u.values() for u in user_ids))
        order_ids, sub_plan_ids, user_ids = zip(
            *tuple(tuple(u['order_id'], u['sub_plan_id'], u['user_id']) for u in users)
        )
        query = '''
        WITH users_to_proto_cores AS (
            SELECT order_id, sub_plan_id, user_id 
            FROM UNNEST($1::bigint[], $2::integer[], $3::bigint[]) AS t(order_id, sub_plan_id, user_id)
        ),
        -- 3. Собираем информацию о нодах для этих подписок
        expired_nodes_info AS (
            SELECT u.uuid, u.tg_username, upc.order_id, vsp.id AS sub_node_id,
                   vsp.node_proto_id, n.private_ip, n.api_port, np.metrics_port, pt.proto_python_lib, pt.api_bulk_add_user_script,
                   pt.bulk_add_script_custom_params, pt.flatten_json_users_key, pt.flatten_user_identifier_key, pt.reload_core_command,
                   np.config_path, pt.constant_user_data_obj, pt.required_user_data_obj
            FROM users_to_proto_cores upc
            JOIN users u ON u.id = upc.user_id
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
                           'order_id', order_id,
                           'sub_node_id', sub_node_id
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
            UPDATE users SET traffic_used_day_mb = 0
        ),
        users_to_proto_cores AS (
            UPDATE payed_subs SET is_limited = false
            WHERE is_active = true AND is_limited = true
            RETURNING id AS order_id, sub_plan_id, user_id
        ),
        -- 3. Собираем информацию о нодах для этих подписок
        expired_nodes_info AS (
            SELECT u.uuid, u.tg_username, upc.order_id, vsp.id AS sub_node_id,
                   vsp.node_proto_id, n.private_ip, n.api_port, np.metrics_port, pt.proto_python_lib, pt.api_bulk_add_user_script,
                   pt.bulk_add_script_custom_params, pt.flatten_json_users_key, pt.flatten_user_identifier_key, pt.reload_core_command,
                   np.config_path, pt.constant_user_data_obj, pt.required_user_data_obj
            FROM users_to_proto_cores upc
            JOIN users u ON u.id = upc.user_id
            JOIN vnodes_sub_plans vsp ON vsp.sub_plan_id = upc.sub_plan_id 
            JOIN nodes_protocols np ON np.id = vsp.node_proto_id AND np.user_visible = true 
            JOIN nodes n ON np.node_id = n.id AND n.is_active = true 
            JOIN protocols p ON np.proto_id = p.id 
            JOIN proto_templates pt ON p.tmp_id = pt.id 
        ),
        -- 4. Фиксируем операцию удаления в outbox (двухэтапный ack)
        insert_outbox AS (
            INSERT INTO sub_nodes_outbox (user_uuid, tg_username, order_id, operation, sub_node_id)
            SELECT uuid, tg_username, order_id, $1, sub_node_id
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
                           'order_id', order_id,
                           'sub_node_id', sub_node_id
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


    async def get_all_nodes_for_metrics(self):
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