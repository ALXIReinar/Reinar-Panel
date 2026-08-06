from asyncpg import Connection

from web.arq_worker.utils.anything import CoreProtoActions


class TrafficResetQueries:
    def __init__(self, conn: Connection):
        self.conn = conn

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
                   pt.required_user_data_obj, pt.process_user_item_script, pt.process_user_libs
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
               required_user_data_obj, bulk_add_script_custom_params, process_user_item_script, process_user_libs,
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
                 required_user_data_obj, bulk_add_script_custom_params, process_user_item_script, process_user_libs
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
                   pt.required_user_data_obj, pt.process_user_item_script, pt.process_user_libs
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
               required_user_data_obj, bulk_add_script_custom_params, process_user_item_script, process_user_libs,
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
                 required_user_data_obj, bulk_add_script_custom_params, process_user_item_script, process_user_libs
        '''
        return await self.conn.fetch(query, CoreProtoActions.add)
