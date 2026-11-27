from .panel_api import Http

REINIT = "/api/v1/server/node/reinit"
METRICS = "/api/v1/server/node/metrics"


class NodeClient:
    def __init__(self, url: str, http: Http):
        self.url = url
        self.http = http

    def check_reinit(self) -> None:
        schema = self.http.json("GET", self.url, "/openapi.json")
        for path in (REINIT, METRICS):
            if "post" not in schema.get("paths", {}).get(path, {}):
                raise RuntimeError(f"В OpenAPI нод-клиента отсутствует POST {path}")

    def reinit(self, node_proto_id: int) -> None:
        data = self.http.json("POST", self.url, REINIT, json={"node_proto_ids": [node_proto_id]})
        if node_proto_id not in data.get("registered", []):
            raise RuntimeError(f"Нод-клиент не зарегистрировал ноду {node_proto_id}")

    def metrics(self, node_proto_id: int, metrics_port: int) -> dict:
        return self.http.json(
            "POST", self.url, METRICS, json={"node_proto_id": node_proto_id, "metrics_port": metrics_port}
        )
