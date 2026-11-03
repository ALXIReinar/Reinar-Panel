from asyncpg import Connection

from web.arq_worker.utils.anything import CoreProtoActions, VnodeRegStatuses


class TrafficResetQueries:
    def __init__(self, conn: Connection):
        self.conn = conn

    async def reset_user_traffic_per_day(self):
        query = '''
        -- 1. Пользователи, которых нужно подключить вновь
        WITH users_to_proto_cores AS (
            UPDATE user_subs us
            SET traffic_used_day_mb = 0, is_limited = false
            FROM users u
            WHERE us.user_id = u.id
              AND us.is_active = true
              AND u.is_deleted = false
            RETURNING us.id AS user_sub_id, us.sub_plan_id, us.uuid
        ),
        -- 2. Outbox фиксация
        insert_outbox AS (
            INSERT INTO sub_nodes_outbox (user_uuid, user_sub_id, operation, node_proto_id)
            SELECT upc.uuid, upc.user_sub_id, $1, vsp.node_proto_id
            FROM users_to_proto_cores upc
            JOIN vnodes_sub_plans vsp ON vsp.sub_plan_id = upc.sub_plan_id
            RETURNING id AS event_id, user_sub_id, user_uuid, node_proto_id
        ),
        -- 3. Пре-агрегация! Теперь у нас по одной записи на каждый node_proto_id с готовым JSON-массивом пользователей
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
        -- 4. Финальный джойн. 
        SELECT np.id AS node_proto_id, n.private_ip, n.api_port, np.metrics_port, 
            pt.constant_user_data_obj, pt.required_user_data_obj,
            pt.bulk_add_script_custom_params, np.constant_node_data_obj,
            COALESCE(pau.users, '[]'::json) AS users
        FROM pre_aggregated_users pau
        JOIN nodes_protocols np ON np.id = pau.node_proto_id AND np.user_visible = true AND np.reg_status = $2
        JOIN nodes n ON np.node_id = n.id AND n.is_active = true 
        JOIN proto_templates pt ON np.tmp_id = pt.id
        '''  # noqa: W291
        return await self.conn.fetch(query, CoreProtoActions.add, VnodeRegStatuses.success)
