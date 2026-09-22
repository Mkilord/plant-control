"""Поддельный Home Assistant: WebSocket-сервер с тем же протоколом.

Позволяет проверить клиента без настоящего HA.
"""

import asyncio
from typing import Any

from aiohttp import WSMsgType, web
from aiohttp.test_utils import TestServer

TOKEN = "good-token"


class FakeHomeAssistant:
    def __init__(self) -> None:
        self.states: dict[str, dict[str, Any]] = {}
        self.service_calls: list[tuple[str, str, str]] = []
        self.fail_services = False
        self.connections: list[web.WebSocketResponse] = []
        self.subscriptions: dict[web.WebSocketResponse, int] = {}
        app = web.Application()
        app.router.add_get("/api/websocket", self._handle)
        self.server = TestServer(app)

    @property
    def url(self) -> str:
        return str(self.server.make_url("/api/websocket"))

    def add_entity(self, entity_id: str, state: str, name: str | None = None) -> None:
        attributes = {"friendly_name": name} if name else {}
        self.states[entity_id] = {"entity_id": entity_id, "state": state, "attributes": attributes}

    async def set_state(self, entity_id: str, state: str) -> None:
        """Изменить состояние и разослать событие подписчикам, как HA."""
        self.states[entity_id]["state"] = state
        for ws, sub_id in list(self.subscriptions.items()):
            await ws.send_json(
                {
                    "id": sub_id,
                    "type": "event",
                    "event": {
                        "event_type": "state_changed",
                        "data": {"entity_id": entity_id, "new_state": self.states[entity_id]},
                    },
                }
            )

    async def drop_connections(self) -> None:
        for ws in list(self.connections):
            await ws.close()

    async def _handle(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        await ws.send_json({"type": "auth_required"})
        auth = await ws.receive_json()
        if auth.get("access_token") != TOKEN:
            await ws.send_json({"type": "auth_invalid", "message": "Invalid access token"})
            await ws.close()
            return ws
        await ws.send_json({"type": "auth_ok"})
        self.connections.append(ws)
        try:
            async for message in ws:
                if message.type is not WSMsgType.TEXT:
                    continue
                await self._command(ws, message.json())
        finally:
            self.connections.remove(ws)
            self.subscriptions.pop(ws, None)
        return ws

    async def _command(self, ws: web.WebSocketResponse, data: dict[str, Any]) -> None:
        message_id = data["id"]
        match data["type"]:
            case "get_states":
                await self._ok(ws, message_id, list(self.states.values()))
            case "subscribe_events":
                self.subscriptions[ws] = message_id
                await self._ok(ws, message_id, None)
            case "call_service":
                entity_id = data["target"]["entity_id"]
                if self.fail_services:
                    await ws.send_json(
                        {
                            "id": message_id,
                            "type": "result",
                            "success": False,
                            "error": {"code": "home_assistant_error", "message": "device offline"},
                        }
                    )
                    return
                self.service_calls.append((data["domain"], data["service"], entity_id))
                await self._ok(ws, message_id, None)
                if entity_id in self.states:
                    new = "on" if data["service"] == "turn_on" else "off"
                    await asyncio.sleep(0)
                    await self.set_state(entity_id, new)
            case "silent":
                pass  # не отвечать: проверка таймаута

    async def _ok(self, ws: web.WebSocketResponse, message_id: int, result: Any) -> None:
        await ws.send_json({"id": message_id, "type": "result", "success": True, "result": result})
