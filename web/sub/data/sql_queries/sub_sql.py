
from asyncpg import Connection

from web.sub.anything import CoreProtoActions


class SubscriptionQueries:
    def __init__(self, conn: Connection):
        self.conn = conn


    async def get_sub_links(self, b64_string: str):
        query_sub_meta = '''
        SELECT 
            us.sub_plan_id, sp.title, sp.description, (COALESCE(us.traffic_limit_day, us.used_mb_limit, 0)) AS sub_plan_limit, us.user_id, us.uuid AS user_uuid,
            COALESCE(us.traffic_used_day_mb, us.used_mb) AS traffic_used_day_mb, us.id AS user_sub_id,
            (CASE WHEN us.infinite_expire = true THEN null ELSE us.expire_date END) AS expire_date
        FROM users u
        JOIN user_subs us ON us.user_id = u.id
        JOIN sub_plans sp ON sp.id = us.sub_plan_id
        WHERE us.is_active = true 
          AND u.is_deleted = false
          AND (
                  -- Проверка превышения общего лимита
                  (us.infinite_traffic OR (us.used_mb_limit IS NOT NULL AND us.used_mb < us.used_mb_limit))
                  OR
                  -- Проверка превышения дневного лимита (если он включен)
                  (us.infinite_traffic OR (us.traffic_limit_day IS NOT NULL AND us.traffic_used_day_mb < us.traffic_limit_day))
          )
          AND (us.infinite_expire = true OR us.expire_date > now())
          AND us.b64_id = $1
        '''
        sub_meta = await self.conn.fetchrow(query_sub_meta, b64_string)
        if not sub_meta:
            return None, []

        query_locations = '''
        SELECT pt.sub_prepare_script, pt.sub_required_libs as required_libs, np.config_link, np.id AS node_proto_id, 
               vsp.id AS sub_node_id, pt.required_user_data_obj, pt.constant_user_data_obj, np.constant_node_data_obj
        FROM sub_plans sp
        JOIN vnodes_sub_plans vsp ON vsp.sub_plan_id = sp.id
        JOIN nodes_protocols np ON np.id = vsp.node_proto_id AND np.user_visible = true
        JOIN nodes n ON np.node_id = n.id AND n.is_active = true
        JOIN protocols p ON p.id = np.proto_id
        JOIN proto_templates pt ON p.tmp_id = pt.id
        WHERE sp.id = $1
        '''
        locations = await self.conn.fetch(query_locations, sub_meta['sub_plan_id'])
        return sub_meta, locations


    async def get_core_proto_deps_by_user_id(
            self, user_sub_id: int, operation: CoreProtoActions | int
    ):
        """
        Получить ноды для действия над пользователем в ядре протокола + зафиксировать в outbox
        
        Использует Outbox pattern:
        1. Читает ноды из подписки
        2. Вставляет записи в sub_nodes_outbox
        3. Возвращает полные данные нод для обработки
        """
        query = '''
        WITH insert_outbox AS (
            INSERT INTO sub_nodes_outbox (user_uuid, user_sub_id, operation, node_proto_id)
            SELECT us.uuid, us.id, $2, vsp.node_proto_id
            FROM user_subs us
            JOIN vnodes_sub_plans vsp ON vsp.sub_plan_id = us.sub_plan_id
            JOIN nodes_protocols np ON np.id = vsp.node_proto_id AND np.user_visible = true
            JOIN nodes n ON n.id = np.node_id AND n.is_active = true
            WHERE us.is_active = true AND us.id = $1
            RETURNING id AS event_id, user_sub_id, user_uuid, node_proto_id
        ),
        -- 5.1. Пре агрегация инжекторов
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
        SELECT np.id AS node_proto_id, n.private_ip, n.api_port, np.metrics_port, pt.proto_python_lib, pt.api_bulk_delete_user_script, 
               pt.api_bulk_add_user_script, pt.bulk_add_script_custom_params, COALESCE(np.reload_core_command, pt.reload_core_command) AS reload_core_command, 
               np.config_path, pt.bulk_delete_script_custom_params, pt.constant_user_data_obj, pt.required_user_data_obj, np.constant_node_data_obj,
               pt.config_format,
               COALESCE(aui.user_injectors, '[]'::json) AS user_injectors, io.event_id
        FROM nodes_protocols np
        JOIN nodes n ON n.id = np.node_id AND n.is_active = true
        JOIN protocols p ON p.id = np.proto_id
        JOIN proto_templates pt ON p.tmp_id = pt.id 
        LEFT JOIN pre_agg_user_injectors aui ON aui.tmp_id = pt.id
        JOIN insert_outbox io ON io.node_proto_id = np.id
        WHERE np.user_visible = true
        '''
        return await self.conn.fetch(query, user_sub_id, operation)
