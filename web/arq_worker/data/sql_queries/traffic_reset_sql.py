from asyncpg import Connection

from web.arq_worker.utils.anything import CoreProtoActions


class TrafficResetQueries:
    def __init__(self, conn: Connection):
        self.conn = conn

    async def reset_user_traffic_per_day(self):
        query = '''
        -- 1. Хватаем инжекторы по шаблонам
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
        -- 2. Пользователи, которых нужно подключить вновь
        users_to_proto_cores AS (
            UPDATE user_subs us
            SET traffic_used_day_mb = 0, is_limited = false
            FROM users u
            WHERE us.user_id = u.id
              AND us.is_active = true
              AND u.is_deleted = false
            RETURNING us.id AS user_sub_id, us.sub_plan_id, us.uuid
        ),
        -- 4. Outbox фиксация
        insert_outbox AS (
            INSERT INTO sub_nodes_outbox (user_uuid, user_sub_id, operation, node_proto_id)
            SELECT upc.uuid, upc.user_sub_id, $1, vsp.node_proto_id
            FROM users_to_proto_cores upc
            JOIN vnodes_sub_plans vsp ON vsp.sub_plan_id = upc.sub_plan_id
            RETURNING id AS event_id, user_sub_id, user_uuid, node_proto_id
        ),
        -- 5. Пре-агрегация! Теперь у нас по одной записи на каждый node_proto_id с готовым JSON-массивом пользователей
        pre_aggregated_users AS (
            SELECT node_proto_id,
                json_agg(
                    json_build_object( 
                        'uuid', user_uuid, 
                        'user_sub_id', user_sub_id,
                        'event_id', event_id
                    )
                ) AS users
            FROM insert_outbox
            GROUP BY node_proto_id
        )
        -- 6. Финальный джойн. 
        -- Декартово произведение не раздувает записи, экономия ресурсов
        SELECT np.id AS node_proto_id, n.private_ip, n.api_port, np.metrics_port, 
            pt.proto_python_lib, COALESCE(np.reload_core_command, pt.reload_core_command) AS reload_core_command, -- Предпочтение индивидуальной команде, фоллбек на шаблонную
            np.config_path, pt.constant_user_data_obj, pt.json2config_script, pt.config2json_script, pt.conf_converter_libs,
            pt.required_user_data_obj, pt.api_bulk_add_user_script, pt.bulk_add_script_custom_params, np.constant_node_data_obj,
            COALESCE(aui.user_injectors, '[]'::json) AS user_injectors,
            COALESCE(pau.users, '[]'::json) AS users
        FROM pre_aggregated_users pau
        JOIN nodes_protocols np ON np.id = pau.node_proto_id AND np.user_visible = true 
        JOIN nodes n ON np.node_id = n.id AND n.is_active = true 
        JOIN protocols p ON np.proto_id = p.id 
        JOIN proto_templates pt ON p.tmp_id = pt.id
        LEFT JOIN pre_agg_user_injectors aui ON pt.id = aui.tmp_id
        '''
        return await self.conn.fetch(query, CoreProtoActions.add)
