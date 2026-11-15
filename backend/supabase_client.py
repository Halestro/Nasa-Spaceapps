"""Supabase REST client for crew health data persistence.

Uses the server-side Supabase key (never exposed to the browser). Falls back to
SQLite when SUPABASE_URL / SUPABASE_KEY are not configured.

Configuration is read from pydantic `settings` (which parses backend/.env) rather
than os.environ, because pydantic-settings does not export .env values to the
process environment.
"""
from typing import Any

import httpx

from ai_service import settings


def _url() -> str:
    return (settings.supabase_url or "").rstrip("/")


def _key() -> str:
    return settings.supabase_service_key or ""


def _headers() -> dict[str, str]:
    key = _key()
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def configured() -> bool:
    return bool(_url() and _key())


async def request(
    method: str,
    table: str,
    path: str = "",
    params: dict | None = None,
    json: Any = None,
    timeout: float = 15.0,
) -> Any:
    if not configured():
        return None
    url = f"{_url()}/rest/v1/{table}{path}"
    headers = _headers()
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.request(method, url, headers=headers, params=params, json=json)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(f"Supabase {method} {table} failed: {exc.response.status_code} {exc.response.text[:200]}") from exc
    if response.status_code == 204 or not response.content:
        return None
    return response.json()


# ---- astronaut_vitals ----
async def insert_vitals(payload: dict) -> Any:
    return await request("POST", "astronaut_vitals", json=payload)


async def list_vitals(astronaut_id: str, limit: int = 50) -> Any:
    params = {
        "astronaut_id": f"eq.{astronaut_id}",
        "order": "recorded_at.desc",
        "limit": str(limit),
    }
    return await request("GET", "astronaut_vitals", params=params)


# ---- mood_logs ----
async def insert_mood(payload: dict) -> Any:
    return await request("POST", "mood_logs", json=payload)


async def list_mood(astronaut_id: str, limit: int = 50) -> Any:
    params = {
        "astronaut_id": f"eq.{astronaut_id}",
        "order": "recorded_at.desc",
        "limit": str(limit),
    }
    return await request("GET", "mood_logs", params=params)


# ---- chat_messages ----
async def insert_chat(payload: dict) -> Any:
    return await request("POST", "chat_messages", json=payload)


async def list_chat(astronaut_id: str, limit: int = 50) -> Any:
    params = {
        "astronaut_id": f"eq.{astronaut_id}",
        "order": "created_at.asc",
        "limit": str(limit),
    }
    return await request("GET", "chat_messages", params=params)


# ---- saved_discoveries ----
async def insert_save(payload: dict) -> Any:
    return await request("POST", "saved_discoveries", json=payload)


async def list_saves(limit: int = 50) -> Any:
    params = {"order": "created_at.desc", "limit": str(limit)}
    return await request("GET", "saved_discoveries", params=params)
