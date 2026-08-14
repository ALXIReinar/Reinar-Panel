from asyncpg import Connection


class OutboxQueries:
    def __init__(self, conn: Connection):
        self.conn = conn

    async def get_stuck_actions_by_chronology(self):
        query = '''
        WITH pre_agg_user_injectors AS (
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
        ),    
        retrieve_upd AS (
            UPDATE sub_nodes_outbox 
            SET is_retried = true 
            WHERE is_retried = false AND created_at < now() - interval '1 hour'
            -- Сразу забираем node_proto_id из аутбокса, никаких лишних джойнов!
            RETURNING id AS event_id, user_uuid, user_sub_id, operation, node_proto_id
        ),
        -- Группируем ТОЛЬКО по ноде. Операции сохраняем в хронологическом порядке.
        pre_agg_events AS (
            SELECT 
                node_proto_id, 
                json_agg(
                    json_build_object(
                        'event_id', event_id,
                        'uuid', user_uuid,
                        'user_sub_id', user_sub_id,
                        'operation', operation
                    ) ORDER BY event_id ASC
                ) AS events_timeline
            FROM retrieve_upd
            GROUP BY node_proto_id
        )
        -- Финальный SELECT. 
        -- Без GROUP BY, получаем ровно 1 строку на комбинацию (Нода + Тип операции)
        SELECT pae.node_proto_id, n.private_ip, n.api_port, np.metrics_port, pt.proto_python_lib,
               pt.api_bulk_add_user_script,  pt.api_bulk_delete_user_script, pt.reload_core_command, np.config_path,
               pt.required_user_data_obj, pt.constant_user_data_obj, pt.bulk_add_script_custom_params, pt.bulk_delete_script_custom_params,
               pae.events_timeline,
               COALESCE(aui.user_injectors, '[]'::json) AS user_injectors
        FROM pre_agg_events pae
        JOIN nodes_protocols np ON np.id = pae.node_proto_id AND np.user_visible = true
        JOIN nodes n ON np.node_id = n.id AND n.is_active = true
        JOIN protocols p ON np.proto_id = p.id
        JOIN proto_templates pt ON p.tmp_id = pt.id
        LEFT JOIN pre_agg_user_injectors aui ON aui.tmp_id = pt.id
        '''
        return await self.conn.fetch(query)
