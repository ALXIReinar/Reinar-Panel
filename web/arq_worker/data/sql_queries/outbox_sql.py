from asyncpg import Connection


class OutboxQueries:
    def __init__(self, conn: Connection):
        self.conn = conn

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


    async def get_nodes_to_core_proto_action(self, user_sub_id: int):
        query = '''
        SELECT np.id as node_proto_id, n.private_ip, n.api_port, np.metrics_port, pt.proto_python_lib,
           pt.api_add_user_script, pt.api_delete_user_script, pt.reload_core_command, np.config_path, pt.flatten_json_users_key, pt.required_user_data_obj,
           pt.constant_user_data_obj,pt.flatten_user_identifier_key, pt.add_script_custom_params, pt.delete_script_custom_params
        FROM user_subs us
        JOIN vnodes_sub_plans vsp ON vsp.sub_plan_id = us.sub_plan_id
        JOIN nodes_protocols np ON np.id = vsp.node_proto_id AND np.user_visible = true
        JOIN protocols p ON np.proto_id = p.id
        JOIN nodes n ON np.node_id = n.id AND n.is_active = true
        JOIN proto_templates pt ON p.tmp_id = pt.id
        WHERE us.id = $1
        '''
        return await self.conn.fetch(query, user_sub_id)
