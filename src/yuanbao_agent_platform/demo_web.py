from __future__ import annotations

import json
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import Dict, Iterator
from urllib.parse import parse_qs, urlparse


class DemoBusinessState:
    def __init__(self):
        self.notification_enabled = True
        self.orders = []
        self.search_index = [
            {"id": "sku-001", "name": "Yuanbao Pro Keyboard", "price": 199},
            {"id": "sku-002", "name": "Yuanbao Cloud Storage", "price": 99},
            {"id": "sku-003", "name": "Yuanbao AI Assistant", "price": 299},
        ]


class DemoWebHandler(BaseHTTPRequestHandler):
    state = DemoBusinessState()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._json({"status": "ok", "service": "yuanbao-demo-web"})
            return
        if parsed.path == "/api/settings/notification":
            self._json(
                {
                    "status": "ok",
                    "notification_enabled": self.state.notification_enabled,
                    "source": "demo_backend_api",
                }
            )
            return
        if parsed.path == "/login":
            self._html("Login", "<h1>元宝 Demo 登录</h1><button id='login'>登录</button>")
            return
        if parsed.path == "/dashboard":
            self._html("Dashboard", "<h1>我的</h1><a href='/settings'>设置</a><a href='/search'>搜索</a>")
            return
        if parsed.path == "/settings":
            enabled = "开启" if self.state.notification_enabled else "关闭"
            self._html(
                "Settings",
                f"<h1>设置</h1><p id='notification-state'>通知开关：{enabled}</p>"
                "<form method='POST' action='/settings/notification/off'><button>关闭通知</button></form>",
            )
            return
        if parsed.path == "/search":
            keyword = parse_qs(parsed.query).get("q", [""])[0].lower()
            results = [item for item in self.state.search_index if keyword in item["name"].lower()] if keyword else self.state.search_index
            body = "<h1>搜索</h1>" + "".join(
                f"<div class='result'><span>{item['name']}</span><a href='/cart/add?id={item['id']}'>加入购物车</a></div>"
                for item in results
            )
            self._html("Search", body)
            return
        if parsed.path == "/cart/add":
            item_id = parse_qs(parsed.query).get("id", ["sku-001"])[0]
            self.state.orders.append({"item_id": item_id, "status": "created"})
            self._html("Cart", f"<h1>购物车</h1><p>已加入：{item_id}</p><a href='/checkout'>去下单</a>")
            return
        if parsed.path == "/checkout":
            order_id = f"order-{len(self.state.orders):03d}"
            self._json({"status": "submitted", "order_id": order_id, "orders": self.state.orders})
            return
        self._json({"error": "not_found", "path": parsed.path}, status=404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/settings/notification/off":
            self.state.notification_enabled = False
            self._html("Settings", "<h1>设置</h1><p id='notification-state'>通知开关：关闭</p>")
            return
        self._json({"error": "not_found", "path": parsed.path}, status=404)

    def log_message(self, format: str, *args) -> None:
        return

    def _html(self, title: str, body: str, status: int = 200) -> None:
        page = f"<!doctype html><html><head><title>{title}</title></head><body>{body}</body></html>"
        self._write(status, "text/html; charset=utf-8", page.encode("utf-8"))

    def _json(self, body: Dict, status: int = 200) -> None:
        self._write(status, "application/json; charset=utf-8", json.dumps(body, ensure_ascii=False).encode("utf-8"))

    def _write(self, status: int, content_type: str, payload: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


@contextmanager
def run_demo_web_server(host: str = "127.0.0.1", port: int = 0) -> Iterator[str]:
    server = ThreadingHTTPServer((host, port), DemoWebHandler)
    actual_port = server.server_address[1]
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://{host}:{actual_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 8010), DemoWebHandler)
    print("Yuanbao Demo Web listening on http://127.0.0.1:8010")
    server.serve_forever()


if __name__ == "__main__":
    main()
