from typing import Any

from .config import Config

Row = dict[str, Any]


class Database:
    def __init__(self, cfg: Config):
        self.cfg = cfg

    def _select(self, sql: str, *params: object) -> list[Row]:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError:
            raise RuntimeError("Для чтения PostgreSQL установите зависимости из requirements.txt") from None
        timeout = self.cfg.timeouts.db_s
        settings = self.cfg.db_connection_params()
        try:
            with psycopg.connect(
                **settings,
                row_factory=dict_row,
                connect_timeout=max(2, timeout),
                options=f"-c default_transaction_read_only=on -c statement_timeout={timeout * 1000}",
            ) as conn:
                conn.read_only = True
                return conn.execute(sql, params).fetchall()
        except psycopg.Error as exc:
            raise RuntimeError(f"Ошибка чтения PostgreSQL ({exc.sqlstate or type(exc).__name__})") from None

    def _one(self, sql: str, *params: object) -> Row | None:
        rows = self._select(sql, *params)
        return rows[0] if rows else None

    def template_titles(self) -> list[str]:
        """Возвращает имена шаблонов."""
        return [row["title"] for row in self._select("SELECT title FROM proto_templates ORDER BY title")]

    def template(self, title: str) -> Row | None:
        """Возвращает метаданные шаблона по имени."""
        return self._one(
            """
            SELECT id, title, url_tmp, config2json_script, json2config_script, conf_converter_libs,
                   sub_prepare_script, metrics_command
            FROM proto_templates
            WHERE title = %s
            """,
            title,
        )

    def physical_node(self, title: str) -> Row | None:
        """Возвращает физическую ноду стенда."""
        return self._one("SELECT id, title, is_active FROM nodes WHERE title = %s", title)

    def vnode(self, node_proto_id: int) -> Row | None:
        """Возвращает виртуальную ноду вместе с именем шаблона."""
        return self._one(
            """
            SELECT np.*, pt.title AS template
            FROM nodes_protocols AS np JOIN proto_templates AS pt ON pt.id = np.tmp_id
            WHERE np.id = %s
            """,
            node_proto_id,
        )

    def installed(self, node_id: int, template_id: int) -> Row | None:
        """Возвращает последнюю успешно зарегистрированную ноду шаблона на стенде."""
        return self._one(
            """
            SELECT np.*, pt.title AS template
            FROM nodes_protocols AS np JOIN proto_templates AS pt ON pt.id = np.tmp_id
            WHERE np.node_id = %s AND np.tmp_id = %s AND np.reg_status = 2
            ORDER BY np.id DESC LIMIT 1
            """,
            node_id,
            template_id,
        )

    def by_run_title(self, node_id: int, title: str) -> list[Row]:
        """Возвращает регистрации по уникальному заголовку прогона на стенде."""
        return self._select(
            """
            SELECT np.*, pt.title AS template
            FROM nodes_protocols AS np JOIN proto_templates AS pt ON pt.id = np.tmp_id
            WHERE np.node_id = %s AND np.title = %s
            ORDER BY np.id
            """,
            node_id,
            title,
        )

    def subscription(self, user_id: int, plan_id: int) -> Row | None:
        """Возвращает тестовую подписку пользователя и состояние плана."""
        return self._one(
            """
            SELECT us.id, us.uuid, us.b64_id, us.used_mb, us.is_active, sp.is_active AS plan_active
            FROM user_subs AS us JOIN sub_plans AS sp ON sp.id = us.sub_plan_id
            WHERE us.user_id = %s AND us.sub_plan_id = %s
            """,
            user_id,
            plan_id,
        )

    def visible_nodes(self, node_id: int) -> list[Row]:
        """Возвращает видимые виртуальные ноды физической ноды."""
        return self._select(
            "SELECT id, service_name FROM nodes_protocols WHERE node_id = %s AND user_visible IS TRUE ORDER BY id",
            node_id,
        )

    def node_units(self, node_id: int) -> list[Row]:
        """Возвращает точные имена зарегистрированных unit физической ноды."""
        return self._select(
            "SELECT id, service_name FROM nodes_protocols WHERE node_id = %s AND service_name IS NOT NULL",
            node_id,
        )

    def attached_plans(self, node_proto_id: int) -> list[int]:
        """Возвращает планы, к которым привязана виртуальная нода."""
        return [
            row["sub_plan_id"]
            for row in self._select("SELECT sub_plan_id FROM vnodes_sub_plans WHERE node_proto_id = %s", node_proto_id)
        ]

    def plan_vnodes(self, plan_id: int) -> list[int]:
        return [
            row["node_proto_id"]
            for row in self._select("SELECT node_proto_id FROM vnodes_sub_plans WHERE sub_plan_id = %s", plan_id)
        ]
