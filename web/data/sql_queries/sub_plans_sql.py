from asyncpg import Connection, ForeignKeyViolationError

from web.schemas.sub_plan_schema import SubPlanOfferSchema
from web.utils.anything import CoreProtoActions
from web.utils.logger_config import log_event


class SubPlansQueries:
    def __init__(self, conn: Connection):
        self.conn = conn

    async def create(self, title: str):
        """Создание группы подписок"""
        query = """
        INSERT INTO sub_plans (title, position) 
        VALUES ($1, COALESCE((SELECT MAX(position) FROM sub_plans), 0) + 1) 
        ON CONFLICT DO NOTHING 
        RETURNING id
        """
        return await self.conn.fetchval(query, title)


    async def update(
        self,
        plan_id: int,
        offers: list[SubPlanOfferSchema],
        title: str | None = None,
        description: str | None = None,
        is_active: bool | None = None,
        position: int | None = None,
    ):
        """Обновление группы подписок"""
        sub_plan_updates, offer_updates = [], []
        sub_plan_params, offer_params = [], []
        sp_param_idx, o_param_idx = 1, 1

        if title is not None:
            sub_plan_updates.append(f"title = ${sp_param_idx}")
            sub_plan_params.append(title)
            sp_param_idx += 1

        if description is not None:
            sub_plan_updates.append(f"description = ${sp_param_idx}")
            sub_plan_params.append(description)
            sp_param_idx += 1

        if position is not None:
            sub_plan_updates.append(f"position = ${sp_param_idx}")
            sub_plan_params.append(position)
            sp_param_idx += 1

        if is_active is not None:
            sub_plan_updates.append(f"is_active = ${sp_param_idx}")
            sub_plan_params.append(is_active)
            sp_param_idx += 1


        query_sub_plan = f"""
        UPDATE sub_plans
        SET {', '.join(sub_plan_updates)}
        WHERE id = ${sp_param_idx}
        RETURNING id
        """
        "1. Обновляем параметры плана, если были"
        sub_plan_upd = None
        if sub_plan_params:
            sub_plan_params.append(plan_id)
            sub_plan_upd = await self.conn.fetchrow(query_sub_plan, *sub_plan_params)

        offer_upd_count = 0
        for offer in offers:
            if offer.ttl_days is not None:
                offer_updates.append(f"ttl_days = ${o_param_idx}")
                offer_params.append(offer.ttl_days)
                o_param_idx += 1

            if offer.cost is not None:
                offer_updates.append(f"cost = ${o_param_idx}")
                offer_params.append(offer.cost)
                o_param_idx += 1

            if offer.traffic_limit_day is not None:
                offer_updates.append(f"traffic_limit_day_mb = ${o_param_idx}")
                offer_params.append(offer.traffic_limit_day)
                o_param_idx += 1

            if offer.is_active is not None:
                offer_updates.append(f"is_active = ${o_param_idx}")
                offer_params.append(offer.is_active)
                o_param_idx += 1

            if offer.traffic_limit_total is not None:
                offer_updates.append(f"traffic_limit_mb = ${o_param_idx}")
                offer_params.append(offer.traffic_limit_total)
                o_param_idx += 1

            if offer.infinite_traffic is not None:
                offer_updates.append(f"infinite_traffic = ${o_param_idx}")
                offer_params.append(offer.infinite_traffic)
                o_param_idx += 1

            if offer.infinite_expire is not None:
                offer_updates.append(f"infinite_expire = ${o_param_idx}")
                offer_params.append(offer.infinite_expire)
                o_param_idx += 1

            if offer.position is not None:
                offer_updates.append(f"position = ${o_param_idx}")
                offer_params.append(offer.position)
                o_param_idx += 1

            query_offer = f'''
            UPDATE sub_plan_offers
            SET {', '.join(offer_updates)}
            WHERE id = ${o_param_idx}
            RETURNING id
            '''
            if offer_params:
                offer_params.append(offer.id)
                offer_upd = await self.conn.fetchrow(query_offer, *offer_params)

                if offer_upd:
                    offer_upd_count += 1
                    sub_plan_upd = True

        return sub_plan_upd, offer_upd_count


    async def attach_vnodes(self, sub_plan_id: int, node_proto_ids: list[int]):
        """Привязать виртуальные ноды к группе"""
        if not node_proto_ids:
            return 0

        query = """
        INSERT INTO vnodes_sub_plans (sub_plan_id, node_proto_id)
        SELECT $1, UNNEST($2::integer[])
        ON CONFLICT (sub_plan_id, node_proto_id) DO NOTHING
        RETURNING id
        """
        try:
            result = await self.conn.fetch(query, sub_plan_id, node_proto_ids)
            return 200, f"Успешно прикрепили {len(result)} нод к тарифному плану"
        except ForeignKeyViolationError as e:
            return 404, f"Некоторые ноды не существуют: {e}"


    async def detach_vnodes(self, sub_plan_id: int, node_proto_ids: list[int]):
        """Отвязать виртуальные ноды от группы"""
        if not node_proto_ids:
            return 0

        query = "DELETE FROM vnodes_sub_plans WHERE sub_plan_id = $1 AND node_proto_id = ANY($2) RETURNING node_proto_id"
        result = await self.conn.fetch(query, sub_plan_id, node_proto_ids)

        inp_nodes_len = len(node_proto_ids)
        if len(result) != inp_nodes_len:
            return 409, f"Некоторые ноды не были откреплены. successful_detache: {[rec['node_proto_id'] for rec in result]}"
        return 200, f'Успешно открепили ноды ({inp_nodes_len})'


    async def delete(self, plan_id: int):
        """Удаление группы подписок (CASCADE удалит связи в vnodes_sub_plans)"""
        query = "DELETE FROM sub_plans WHERE id = $1"
        await self.conn.execute(query, plan_id)


    async def all(self, limit: int, offset: int):
        """Получить список всех групп подписок"""
        query = """
        SELECT sp.id, sp.title, sp.is_active, COUNT(vsp.id) AS sub_nodes_count, COUNT(spo.id) AS offers_count
        FROM sub_plans sp
        LEFT JOIN vnodes_sub_plans vsp ON vsp.sub_plan_id = sp.id 
        LEFT JOIN sub_plan_offers spo ON sp.id = spo.sub_plan_id
        GROUP BY sp.id
        LIMIT $1 OFFSET $2
        """
        return await self.conn.fetch(query, limit, offset)

    async def get_by_id(self, plan_id: int):
        """Получить одну группу подписок с привязанными виртуальными нодами"""
        query = """
        WITH plan_vnodes AS (
            SELECT 
                vsp.sub_plan_id,
                json_agg(
                    json_build_object( 
                        'link_id', vsp.id, 
                        'node_proto_id', vsp.node_proto_id,
                        'node_id', np.node_id,
                        'proto_id', np.proto_id,
                        'proto_title', np.title,
                        'config_link', np.config_link,
                        'node_title', n.title,
                        'node_ip', n.ip
                    )
                ) AS vnodes_json
            FROM vnodes_sub_plans vsp
            LEFT JOIN nodes_protocols np ON np.id = vsp.node_proto_id
            LEFT JOIN nodes n ON n.id = np.node_id
            LEFT JOIN protocols p ON p.id = np.proto_id
            WHERE vsp.sub_plan_id = $1
            GROUP BY vsp.sub_plan_id
        ),
        plan_offers AS (
            SELECT 
                spo.sub_plan_id,
                json_agg(
                    json_build_object(
                        'offer_id', spo.id,
                        'cost', spo.cost,
                        'ttl_days', spo.ttl_days,
                        'traffic_day_limit', spo.traffic_limit_day_mb,
                        'traffic_limit', spo.traffic_limit_mb,
                        'infinite_expire', spo.infinite_expire,
                        'infinite_traffic', spo.infinite_traffic,
                        'position', spo.position,
                        'is_active', spo.is_active
                    )
                ) AS offers_json
            FROM sub_plan_offers spo
            WHERE spo.sub_plan_id = $1
            GROUP BY spo.sub_plan_id
        )
        SELECT 
            sp.id AS sub_plan_id, 
            sp.title, 
            sp.description, 
            sp.is_active, 
            sp.position,
            COALESCE(pv.vnodes_json, '[]'::json) AS vnodes,
            COALESCE(po.offers_json, '[]'::json) AS offers
        FROM sub_plans sp
        LEFT JOIN plan_vnodes pv ON pv.sub_plan_id = sp.id
        LEFT JOIN plan_offers po ON po.sub_plan_id = sp.id
        WHERE sp.id = $1
        """
        return await self.conn.fetchrow(query, plan_id)


    async def edit_vnodes_set(self, sub_plan_id: int, add_vnodes, remove_vnodes) -> tuple[list[int], list[int]]:
        """
        Сначала обновление связей, затем оутбокс для удаления
        """
        query = """
        WITH locations_edit AS (
            {edit_query}
            RETURNING sub_plan_id, node_proto_id
        )
        INSERT INTO sub_nodes_outbox (user_uuid, operation, user_sub_id, node_proto_id)
        SELECT us.uuid, $3, us.id, le.node_proto_id
        FROM user_subs us
        JOIN locations_edit le ON le.sub_plan_id = us.sub_plan_id
        JOIN nodes_protocols np ON np.id = le.node_proto_id AND np.user_visible = true
        JOIN nodes n ON n.id = np.node_id AND n.is_active = true
        RETURNING sub_nodes_outbox.id
        """
        query_add = """
        INSERT INTO vnodes_sub_plans (sub_plan_id, node_proto_id) 
        SELECT $1, np_id FROM UNNEST($2::integer[]) AS t(np_id)
        ON CONFLICT DO NOTHING
        """
        query_remove = """
        DELETE FROM vnodes_sub_plans WHERE sub_plan_id = $1 AND node_proto_id = ANY($2)
        """

        "Прикрепляем локации"
        add_outbox_ids = []
        if add_vnodes:
            add_outbox_ids = await self.conn.fetch(
                query.format(edit_query=query_add), sub_plan_id, add_vnodes, CoreProtoActions.add
            )
            log_event(f'К тарифному плану добавлены ноды | sub_plan_id: \033[34m{sub_plan_id}\033[0m; node_proto_ids: \033[33m{add_vnodes}\033[0m; total_adds: \033[32m{len(add_outbox_ids)}\033[0m')

        "Открепляем локации"
        remove_outbox_ids = []
        if remove_vnodes:
            remove_outbox_ids = await self.conn.fetch(
                query.format(edit_query=query_remove), sub_plan_id, remove_vnodes, CoreProtoActions.delete
            )
            log_event(f'Из тарифного плана удалены ноды | sub_plan_id: \033[35m{sub_plan_id}\033[0m; node_proto_ids: \033[32m{remove_vnodes}\033[0m; total_dels: \033[31m{len(remove_outbox_ids)}\033[0m')

        return [rec['id'] for rec in add_outbox_ids], [rec['id'] for rec in remove_outbox_ids]
