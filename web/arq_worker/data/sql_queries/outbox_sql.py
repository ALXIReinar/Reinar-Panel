from asyncpg import Connection


class OutboxQueries:
    def __init__(self, conn: Connection):
        self.conn = conn

    async def get_stuck_actions_with_nodes(self):
        query = '''
        WITH retrieve_upd AS (
            UPDATE sub_nodes_outbox 
            SET is_retried = true 
            WHERE is_retried = false AND created_at < now() - interval '1 hour'
            RETURNING id, user_uuid, user_sub_id, operation
        )
        SELECT ru.id, ru.user_uuid, ru.user_sub_id, ru.operation,
            COALESCE(
                jsonb_agg(
                    jsonb_build_object(
                        'node_proto_id', np.id,
                        'private_ip', n.private_ip,
                        'api_port', n.api_port,
                        'metrics_port', np.metrics_port,
                        'proto_python_lib', pt.proto_python_lib,
                        'api_add_user_script', pt.api_add_user_script,
                        'api_delete_user_script', pt.api_delete_user_script,
                        'reload_core_command', pt.reload_core_command,
                        'config_path', np.config_path,
                        'flatten_json_users_key', pt.flatten_json_users_key,
                        'required_user_data_obj', pt.required_user_data_obj,
                        'constant_user_data_obj', pt.constant_user_data_obj,
                        'flatten_user_identifier_key', pt.flatten_user_identifier_key,
                        'add_script_custom_params', pt.add_script_custom_params,
                        'delete_script_custom_params', pt.delete_script_custom_params,
                        'process_user_item_script', pt.process_user_item_script,
                        'process_user_libs', pt.process_user_libs
                    )
                ), 
                '[]'::jsonb
            ) AS sub_nodes
        FROM retrieve_upd ru
        LEFT JOIN user_subs us ON us.id = ru.user_sub_id
        LEFT JOIN vnodes_sub_plans vsp ON vsp.sub_plan_id = us.sub_plan_id
        LEFT JOIN nodes_protocols np ON np.id = vsp.node_proto_id AND np.user_visible = true
        LEFT JOIN protocols p ON np.proto_id = p.id
        LEFT JOIN nodes n ON np.node_id = n.id AND n.is_active = true
        LEFT JOIN proto_templates pt ON p.tmp_id = pt.id
        GROUP BY ru.id, ru.user_uuid, ru.user_sub_id, ru.operation
        ORDER BY ru.id
        '''
        return await self.conn.fetch(query)
