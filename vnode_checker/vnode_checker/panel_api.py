import os

import httpx

from .config import Config

STARTUP = "/api/v1/server/nodes/{node_title}/startup"


class Http:
    def __init__(self, timeout: int):
        self.client = httpx.Client(timeout=timeout, trust_env=False)

    def close(self) -> None:
        self.client.close()

    def request(self, method: str, base: str, path: str, **kwargs) -> httpx.Response:
        try:
            return self.client.request(method, base.rstrip("/") + path, **kwargs)
        except httpx.RequestError as exc:
            raise RuntimeError(f"{method} {base}: {type(exc).__name__}") from None

    def response(self, method: str, base: str, path: str, **kwargs) -> httpx.Response:
        response = self.request(method, base, path, **kwargs)
        if not response.is_success:
            raise RuntimeError(f"{method} {base}: HTTP {response.status_code}")
        return response

    def json(self, method: str, base: str, path: str, **kwargs) -> dict:
        response = self.response(method, base, path, **kwargs)
        try:
            data = response.json()
        except ValueError:
            raise RuntimeError(f"{method} {base}: ожидался JSON") from None
        if not isinstance(data, dict) or data.get("success") is False:
            raise RuntimeError(f"{method} {base}: ответ отклонён")
        return data


class Panel:
    def __init__(self, cfg: Config):
        self.url = cfg.admin_url
        self._http = Http(cfg.timeouts.http_s)
        request = httpx.Request("GET", self.url)
        for key in ("access_token", "refresh_token"):
            token = os.getenv(f"VNODE_CHECKER_{key.upper()}")
            if token:
                response = httpx.Response(200, headers={"Set-Cookie": f"{key}={token}; Path=/"}, request=request)
                self._http.client.cookies.extract_cookies(response)

    def close(self) -> None:
        self._http.close()

    def check_startup(self) -> None:
        schema = self._http.json("GET", self.url, "/openapi.json")
        if "post" not in schema.get("paths", {}).get(STARTUP, {}):
            raise RuntimeError(f"В OpenAPI админки отсутствует POST {STARTUP}")

    def set_visible(self, node_proto_id: int, visible: bool) -> None:
        self._http.json(
            "PUT",
            self.url,
            f"/api/v1/private/nodes/protocols/{node_proto_id}",
            json={"user_visible": visible},
        )

    def add_vnode(self, plan_id: int, node_proto_id: int) -> None:
        self._http.json(
            "PUT",
            self.url,
            f"/api/v1/private/subscriptions/plans/{plan_id}/locations",
            json={"add_vnodes": [node_proto_id]},
        )

    def remove_vnode(self, plan_id: int, node_proto_id: int) -> None:
        self._http.json(
            "PUT",
            self.url,
            f"/api/v1/private/subscriptions/plans/{plan_id}/locations",
            json={"remove_vnodes": [node_proto_id]},
        )

    def subscription_usage(self, user_id: int, sub_id: int) -> int:
        data = self._http.json(
            "GET",
            self.url,
            "/api/v1/private/users/all",
            params={"sort_by": "desc", "last_id": user_id + 1, "limit": 1},
        )
        for user in data["users"]:
            if user["user_id"] == user_id:
                for sub in user["subscriptions"]:
                    if sub["sub_id"] == sub_id:
                        return int(sub["traffic_used_total"])
        raise RuntimeError(f"Админка не вернула подписку {sub_id} пользователя {user_id}")
