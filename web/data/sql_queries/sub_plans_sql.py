from asyncpg import Connection, ForeignKeyViolationError


class SubPlansQueries:
    def __init__(self, conn: Connection):
        self.conn = conn

    async def create(self, title: str):
        """Создание группы подписок"""
        query = "INSERT INTO sub_plans (title) VALUES ($1) ON CONFLICT DO NOTHING RETURNING id"
        return await self.conn.fetchval(query, title)


    async def update(
        self,
        plan_id: int,
        title: str | None = None,
        description: str | None = None,
        ttl_days: int | None = None,
        cost: int | None = None,
        traffic_limit_day: int | None = None,
        is_active: bool | None = None
    ):
        """Обновление группы подписок"""
        updates = []
        params = []
        param_idx = 1

        if title is not None:
            updates.append(f"title = ${param_idx}")
            params.append(title)
            param_idx += 1

        if description is not None:
            updates.append(f"description = ${param_idx}")
            params.append(description)
            param_idx += 1

        if ttl_days is not None:
            updates.append(f"ttl_days = ${param_idx}")
            params.append(ttl_days)
            param_idx += 1

        if cost is not None:
            updates.append(f"cost = ${param_idx}")
            params.append(cost)
            param_idx += 1

        if traffic_limit_day is not None:
            updates.append(f"traffic_limit_day = ${param_idx}")
            params.append(traffic_limit_day)
            param_idx += 1

        if is_active is not None:
            updates.append(f"is_active = ${param_idx}")
            params.append(is_active)
            param_idx += 1

        if not updates:
            return None

        query = f"""
        UPDATE sub_plans
        SET {', '.join(updates)}
        WHERE id = ${param_idx}
        RETURNING id
        """
        params.append(plan_id)

        return await self.conn.fetchrow(query, *params)


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


    async def all(self, limit: int):
        """Получить список всех групп подписок"""
        query = """
        SELECT id, title, cost, ttl_days, traffic_limit_day, is_active
        FROM sub_plans
        LIMIT $1
        """
        return await self.conn.fetch(query, limit)

    async def get_by_id(self, plan_id: int):
        """Получить одну группу подписок с привязанными виртуальными нодами"""
        query = "SELECT title, description, ttl_days, cost, traffic_limit_day, is_active FROM sub_plans WHERE id = $1"

        plan = await self.conn.fetchrow(query, plan_id)

        if not plan:
            return None

        # Получаем привязанные виртуальные ноды
        vnodes_query = """
        SELECT vsp.id as link_id, np.id as node_proto_id, np.node_id, np.proto_id, np.config_link, n.title as node_title,n.ip as node_ip,np.title as proto_title
        FROM vnodes_sub_plans vsp
        JOIN nodes_protocols np ON np.id = vsp.node_proto_id
        JOIN nodes n ON n.id = np.node_id
        JOIN protocols p ON p.id = np.proto_id
        WHERE vsp.sub_plan_id = $1
        """
        vnodes = await self.conn.fetch(vnodes_query, plan_id)

        return {
            'plan': dict(plan),
            'vnodes': [dict(vnode) for vnode in vnodes]
        }
