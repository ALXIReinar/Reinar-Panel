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
