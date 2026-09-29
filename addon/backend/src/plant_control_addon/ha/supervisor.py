"""Вопросы к Supervisor о самом add-on'е.

Внутри add-on'а Supervisor доступен по адресу http://supervisor с токеном
из SUPERVISOR_TOKEN. При разработке его нет, и ответы просто отсутствуют.
"""

import logging

import aiohttp

log = logging.getLogger(__name__)

SUPERVISOR_SELF_INFO_URL = "http://supervisor/addons/self/info"


async def panel_path(token: str) -> str | None:
    """Путь панели add-on'а в интерфейсе HA: /hassio/ingress/<slug>. None - не узнать."""
    if not token:
        return None
    headers = {"Authorization": f"Bearer {token}"}
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with (
            aiohttp.ClientSession(timeout=timeout, headers=headers) as session,
            session.get(SUPERVISOR_SELF_INFO_URL) as response,
        ):
            if response.status != 200:
                log.info("supervisor did not describe the add-on (http %s)", response.status)
                return None
            body = await response.json()
    except Exception as error:
        log.warning("cannot ask supervisor about the add-on: %s", error)
        return None
    slug = (body.get("data") or {}).get("slug")
    return f"/hassio/ingress/{slug}" if slug else None
