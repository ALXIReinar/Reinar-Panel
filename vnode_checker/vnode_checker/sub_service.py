import base64
import binascii
from urllib.parse import quote

from .panel_api import Http


def decode_sub(body: str) -> list[str]:
    raw = "".join(body.split())
    raw += "=" * (-len(raw) % 4)
    try:
        decoded = base64.b64decode(raw, altchars=b"-_", validate=True).decode("utf-8")
    except (ValueError, binascii.Error):
        raise ValueError("Саб-сервис вернул подписку с неверной кодировкой") from None
    return [line.strip() for line in decoded.splitlines() if line.strip()]


class SubService:
    def __init__(self, url: str, http: Http):
        self.url = url
        self.http = http

    def links(self, token: str) -> list[str]:
        path = f"/api/v1/public/sub/{quote(token, safe='')}"
        return decode_sub(self.http.response("GET", self.url, path).text)
