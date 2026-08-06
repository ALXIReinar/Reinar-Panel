from asyncpg import Connection

from web.arq_worker.utils.anything import CoreProtoActions


class MetricsQueries:
    def __init__(self, conn: Connection):
        self.conn = conn

    async def get_all_nodes_for_metrics_cron(self):
        query = '''
        SELECT np.id, n.ip, n.private_ip, n.api_port, np.metrics_port, pt.metrics_command, pt.api_metrics_script, pt.proto_python_lib,
               pt.metrics_parser_code, pt.metrics_parser_libs
        FROM nodes n
        JOIN nodes_protocols np ON np.node_id = n.id AND np.user_visible = true
        JOIN protocols p ON np.proto_id = p.id
        JOIN proto_templates pt ON p.tmp_id = pt.id
        WHERE n.is_active = true AND np.metrics_port IS NOT NULL
        '''
        return await self.conn.fetch(query)



    async def get_vnodes_by_outbox_events(self, outbox_ids: list[int]):
        query = '''
        -- 1. Собираем информацию о нодах по событиям
        WITH limited_nodes_info AS (
            SELECT us.uuid, us.id AS user_sub_id, sno.node_proto_id, n.private_ip, n.api_port, np.metrics_port,
                   pt.proto_python_lib, pt.api_bulk_delete_user_script, pt.flatten_json_users_key, pt.flatten_user_identifier_key,
                   pt.reload_core_command, np.config_path, pt.bulk_delete_script_custom_params,
                   pt.constant_user_data_obj, pt.required_user_data_obj, pt.process_user_item_script, pt.process_user_libs
            FROM (SELECT UNNEST($1::bigint[]) AS outbox_id) AS limited_outbox_events
            JOIN sub_nodes_outbox sno ON sno.id = limited_outbox_events.outbox_id
            JOIN user_subs us ON us.id = sno.user_sub_id
            JOIN nodes_protocols np ON np.id = sno.node_proto_id AND np.user_visible = true 
            JOIN nodes n ON np.node_id = n.id AND n.is_active = true 
            JOIN protocols p ON np.proto_id = p.id 
            JOIN proto_templates pt ON p.tmp_id = pt.id 
        )
        -- 2. Группируем пользователей по нодам для пакетной отправки
        SELECT node_proto_id, private_ip, api_port, metrics_port, proto_python_lib, api_bulk_delete_user_script, 
               flatten_json_users_key, flatten_user_identifier_key, reload_core_command, config_path, bulk_delete_script_custom_params,
               constant_user_data_obj, required_user_data_obj, process_user_item_script, process_user_libs,
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
        FROM limited_nodes_info
        GROUP BY node_proto_id, private_ip, api_port, metrics_port, proto_python_lib, api_bulk_delete_user_script, 
                 flatten_json_users_key, flatten_user_identifier_key, reload_core_command, config_path, bulk_delete_script_custom_params,
                 constant_user_data_obj, required_user_data_obj, process_user_item_script, process_user_libs
        '''
        return await self.conn.fetch(query, outbox_ids)

    async def update_traffic(self, user_sub_ids: list[str], traffic_add_mbs: list[int]):
        """
        Обновление трафика и блокировка подписок при превышении лимитов.
        Использует два последовательных запроса в рамках одной транзакции (READ COMMITTED).
        """
        # Запрос 1: Обновляем трафик
        query_update_traffic = """
        UPDATE user_subs us
        SET used_mb = us.used_mb + t.traffic_add,
            traffic_used_day_mb = us.traffic_used_day_mb + t.traffic_add
        FROM (
            SELECT UNNEST($1::bigint[]) AS user_sub_id, UNNEST($2::bigint[]) AS traffic_add
        ) AS t
        WHERE us.id = t.user_sub_id AND us.is_active = true
       """

        # Запрос 2: Блокируем превысившие лимиты и пишем в outbox
        query_block_and_outbox = """
        WITH subs_to_disable AS (
            UPDATE user_subs us
            SET is_limited = true
            FROM users u
            WHERE us.user_id = u.id
              AND us.is_active = true
              AND us.is_limited = false
              AND u.is_deleted = false
              AND us.id = ANY($1::bigint[])
              AND (
                  -- Проверка превышения общего лимита
                  (us.infinite_traffic = false AND us.used_mb_limit IS NOT NULL AND us.used_mb >= us.used_mb_limit)
                  OR
                  -- Проверка превышения дневного лимита
                  (us.infinite_traffic = false AND us.traffic_limit_day IS NOT NULL AND us.traffic_used_day_mb >= us.traffic_limit_day)
              )
            RETURNING us.id AS user_sub_id, us.uuid, us.sub_plan_id
        )
        INSERT INTO sub_nodes_outbox (user_uuid, user_sub_id, operation, node_proto_id)
        SELECT std.uuid, std.user_sub_id, $2, vsp.node_proto_id
        FROM subs_to_disable std
        JOIN vnodes_sub_plans vsp ON std.sub_plan_id = vsp.sub_plan_id
        JOIN nodes_protocols np ON vsp.node_proto_id = np.id AND np.user_visible = true
        RETURNING sub_nodes_outbox.id
        """
        await self.conn.execute(query_update_traffic, user_sub_ids, traffic_add_mbs)
        return await self.conn.fetch(query_block_and_outbox, user_sub_ids, CoreProtoActions.delete)
