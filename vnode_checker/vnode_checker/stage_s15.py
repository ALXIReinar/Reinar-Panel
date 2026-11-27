import base64
import json
from urllib.parse import parse_qsl, unquote, urlsplit

from node_client.utils.tmp_url_render import generate_link_from_json

from .db import Row
from .isolation import Stand, unit_name
from .node_config import NodeConfig, leaves
from .stage_s1 import check, stage
from .sub_service import SubService


def structural_checks(link: str, port: int) -> list[dict]:
    checks = [check("placeholders", "{" not in link and "}" not in link, "Шаблонные скобки")]
    scheme, separator, payload = link.partition("://")
    checks.append(check("uri_scheme", bool(scheme and separator), scheme))
    try:
        uri = urlsplit(link)
        host, uri_port = uri.hostname, uri.port
    except ValueError:
        host, uri_port = None, None
    if host and uri_port is not None:
        keys = [key for key, value in parse_qsl(uri.query, keep_blank_values=True) if not value]
        checks.extend([check("query_values", not keys, keys), check("link_port", uri_port == port, uri_port)])
        return checks
    encoded = payload.split("#", 1)[0]
    try:
        obj = json.loads(base64.b64decode(encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True))
        if not isinstance(obj, dict):
            raise ValueError
    except ValueError:
        checks.append(dict(name="link_port", status="unverified", evidence="Не удалось разобрать хост и порт"))
        return checks
    checks.append(check("json_values", all(value not in (None, "") for value in leaves(obj)), "Проверены листья JSON"))
    checks.append(check("link_port", str(obj.get("port")) == str(port), obj.get("port")))
    return checks


def run_s15(stand: Stand, service: SubService, node: Row, template: Row, subscription: Row) -> dict:
    unit = unit_name(node)
    node_id = node["id"]
    config = NodeConfig(node, template)
    before = stand.os.show(unit, "MainPID").get("MainPID")
    stand.panel.set_visible(node_id, True)
    stand.panel.add_vnode(stand.cfg.test_sub_plan_id, node_id)
    data, waited = config.wait_user(subscription, True, stand.cfg.timeouts.bind_wait_s)
    after = stand.os.show(unit, "MainPID").get("MainPID")
    checks = [
        check(
            "user_in_config",
            data is not None,
            "Пользователь найден" if data is not None else "Проверьте реинициализацию нод-клиента после confirm",
        )
    ]
    result = {
        "main_pid_before": before,
        "main_pid_after": after,
        "waited_s": waited,
        "note": "Принятие клиентом проверяет S2",
    }
    if data is None:
        return result | stage(checks)
    latest = stand.db.vnode(node_id)
    if not latest:
        raise RuntimeError(f"Нода {node_id} исчезла из БД")
    links = service.links(subscription["b64_id"])
    by_title = [(unquote(link.rpartition("#")[2]), link) for link in links if "#" in link]
    matched = [link for title, link in by_title if title == latest["title"]]
    checks.append(check("subscription_link", len(matched) == 1, [title for title, _ in by_title]))
    if len(matched) == 1:
        result["link"] = matched[0]
        checks.extend(structural_checks(matched[0], latest["proto_port"]))
    _, rendered = generate_link_from_json(template["url_tmp"], data)
    saved = latest["config_link"]
    checks.append(
        check(
            "recomputed_link",
            rendered == saved,
            None
            if rendered == saved
            else {
                "db": saved,
                "recomputed": rendered,
            },
        )
    )
    return result | stage(checks)
