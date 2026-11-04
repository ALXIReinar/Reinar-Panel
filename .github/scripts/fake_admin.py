"""
Фейковая админка для CI-проверки установки нод-клиента (только stdlib).

Нод-клиент при старте ждёт ответ POST /api/v1/server/nodes/{node_title}/startup и до него не отвечает на /ping.
Сервер отвечает «у этой физической ноды нет виртуальных нод» — этого достаточно, чтобы нод-клиент стартовал.
Запуск: python3 .github/scripts/fake_admin.py [порт]  (по умолчанию 8000, слушает 127.0.0.1)
"""

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote


class StartupHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        parts = self.path.split('/')
        # /api/v1/server/nodes/{node_title}/startup
        if len(parts) == 7 and parts[1:5] == ['api', 'v1', 'server', 'nodes'] and parts[6] == 'startup':
            body = json.dumps({"node_title": unquote(parts[5]), "nodes": [], "missing": []}).encode()
            self.send_response(200)
        else:
            body = json.dumps({"detail": "not found"}).encode()
            self.send_response(404)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    ThreadingHTTPServer(("127.0.0.1", port), StartupHandler).serve_forever()
