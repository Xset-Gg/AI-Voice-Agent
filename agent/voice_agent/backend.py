"""Client for the platform's internal API. All business logic and permission checks live there."""

import asyncio
import logging

import httpx

logger = logging.getLogger("voice-agent.backend")


class BackendClient:
    def __init__(self, base_url: str, token: str, call_id: str):
        self.call_id = call_id
        self._http = httpx.AsyncClient(
            base_url=f"{base_url.rstrip('/')}/api/internal/calls/{call_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=httpx.Timeout(10.0, connect=3.0),
        )
        self._background: set[asyncio.Task] = set()

    async def _request(self, method: str, path: str, retries: int = 2, **kw) -> dict:
        for attempt in range(retries + 1):
            try:
                r = await self._http.request(method, path, **kw)
                r.raise_for_status()
                return r.json()
            except (httpx.TransportError, httpx.HTTPStatusError) as e:
                retryable = isinstance(e, httpx.TransportError) or e.response.status_code >= 500
                if attempt == retries or not retryable:
                    raise
                await asyncio.sleep(0.2 * (attempt + 1))
        raise RuntimeError("unreachable")

    async def context(self) -> dict:
        return await self._request("GET", "/context", retries=3)

    async def answered(self) -> None:
        await self._request("POST", "/answered")

    async def tool(self, name: str, arguments: dict) -> dict:
        # Tool calls mutate state: no automatic retries (the backend is not idempotent for bookings).
        try:
            return await self._request("POST", f"/tools/{name}", retries=0, json={"arguments": arguments})
        except Exception as e:
            logger.exception("tool request failed", extra={"tool": name})
            return {"ok": False, "error": f"The system is temporarily unavailable ({e.__class__.__name__})."}

    async def event(self, type_: str, data: dict) -> dict:
        return await self._request("POST", "/events", json={"type": type_, "data": data})

    async def end(self, reason: str, metrics: dict) -> None:
        await self._request("POST", "/end", retries=3, json={"reason": reason[:64], "metrics": metrics})

    # --- fire-and-forget helpers: never block the audio pipeline on logging ---

    def spawn(self, coro) -> None:
        task = asyncio.create_task(self._safe(coro))
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    async def _safe(self, coro):
        try:
            await coro
        except Exception as e:
            logger.warning("background backend call failed: %s", e)

    def transcript(self, role: str, text: str, interrupted: bool = False, confidence: float | None = None) -> None:
        self.spawn(self._request("POST", "/transcript", json={
            "role": role, "text": text[:8000], "interrupted": interrupted, "confidence": confidence,
        }))

    def emit(self, type_: str, data: dict) -> None:
        self.spawn(self.event(type_, data))

    async def aclose(self) -> None:
        if self._background:
            await asyncio.wait(self._background, timeout=5)
        await self._http.aclose()
