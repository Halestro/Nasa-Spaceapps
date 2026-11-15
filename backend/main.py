import asyncio
import json
import time
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import aiosqlite
import httpx
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from ai_service import analyze, crew_chat, diet_polish, settings
from auth import check_password, create_session, hash_password, read_session
from nasa_physiology import ANOMALIES, CHANNELS, PHASES
from nasa_standards import personalize, summary_targets, STANDARDS
from simulator import engine
from supabase_client import (
    configured as supabase_configured,
    insert_chat,
    insert_mood,
    insert_save,
    insert_vitals,
    list_chat,
    list_mood,
    list_saves,
    list_vitals,
)

HEALTH_DB = Path(__file__).with_name("crew_wellbeing.db")
db: aiosqlite.Connection | None = None
_solar_cache: dict = {"expires_at": 0.0, "events": [], "error": None}


@asynccontextmanager
async def lifespan(app):
    global db
    await engine.start()
    db = await aiosqlite.connect(HEALTH_DB)
    db.row_factory = aiosqlite.Row
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS astronaut_vitals (
          id INTEGER PRIMARY KEY, astronaut_id TEXT NOT NULL, recorded_at TEXT NOT NULL,
          heart_rate REAL, blood_pressure_systolic REAL, blood_pressure_diastolic REAL,
          oxygen_saturation REAL, body_temperature REAL, radiation_exposure REAL, notes TEXT
        );
        CREATE TABLE IF NOT EXISTS mood_logs (
          id INTEGER PRIMARY KEY, astronaut_id TEXT NOT NULL, recorded_at TEXT NOT NULL,
          mood TEXT NOT NULL, stress_level INTEGER, anxiety_level INTEGER, sleep_hours REAL, notes TEXT
        );
        CREATE TABLE IF NOT EXISTS saved_discoveries (
          id INTEGER PRIMARY KEY, date TEXT UNIQUE NOT NULL, title TEXT NOT NULL,
          url TEXT, explanation TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS chat_messages (
          id INTEGER PRIMARY KEY, astronaut_id TEXT NOT NULL, role TEXT NOT NULL,
          content TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS operator_accounts (
          id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, password_salt TEXT NOT NULL,
          password_hash TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_vitals_astro_time ON astronaut_vitals(astronaut_id, recorded_at DESC);
        CREATE INDEX IF NOT EXISTS idx_mood_astro_time ON mood_logs(astronaut_id, recorded_at DESC);
        CREATE TABLE IF NOT EXISTS operator_profile (
          user_id INTEGER PRIMARY KEY, name TEXT NOT NULL DEFAULT '', age INTEGER,
          sex TEXT NOT NULL DEFAULT 'm', height_cm REAL, weight_kg REAL, updated_at TEXT NOT NULL
        );
    """)
    await db.commit()
    yield
    if db:
        await db.close()
    await engine.close()


app = FastAPI(title="AEGIS-HRP Crew Health & NASA Data API", version="1.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin, "http://localhost:5173", "http://127.0.0.1:5173",
                   "http://localhost:5174", "http://127.0.0.1:5174"],
    allow_methods=["GET", "POST"], allow_headers=["*"], allow_credentials=True,
)

def get_db() -> aiosqlite.Connection:
    if db is None:
        raise HTTPException(503, "Crew health store is starting")
    return db


class AccountInput(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=8, max_length=256)


def current_user_id(request: Request) -> int | None:
    # The prototype runs in open demo mode, so personal records use one stable
    # local operator when no login session is present.
    return read_session(request.cookies.get("aegis_session"), settings.app_secret_key) or 1


def set_session_cookie(response: Response, user_id: int):
    response.set_cookie("aegis_session", create_session(user_id, settings.app_secret_key),
                        max_age=12 * 60 * 60, httponly=True, secure=False,
                        samesite="lax", path="/")


@app.get("/api/auth/status")
async def auth_status(request: Request):
    rows = await get_db().execute_fetchall("SELECT id,email FROM operator_accounts ORDER BY id LIMIT 1")
    user_id = current_user_id(request)
    active = next((row for row in rows if row["id"] == user_id), None)
    return {"setup_required": not bool(rows), "authenticated": bool(active),
            "operator": active["email"] if active else None}


@app.post("/api/auth/setup")
async def auth_setup(body: AccountInput, response: Response):
    email = body.email.strip().lower()
    if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
        raise HTTPException(422, "Enter a valid email address")
    connection = get_db()
    existing = await connection.execute_fetchall("SELECT id FROM operator_accounts LIMIT 1")
    if existing:
        raise HTTPException(409, "An account already exists. Sign in instead.")
    salt, digest = hash_password(body.password)
    cursor = await connection.execute(
        "INSERT INTO operator_accounts(email,password_salt,password_hash,created_at) VALUES(?,?,?,?)",
        (email, salt, digest, datetime.now(timezone.utc).isoformat()))
    await connection.commit()
    set_session_cookie(response, cursor.lastrowid)
    return {"authenticated": True, "operator": email}


@app.post("/api/auth/login")
async def auth_login(body: AccountInput, response: Response):
    email = body.email.strip().lower()
    rows = await get_db().execute_fetchall("SELECT * FROM operator_accounts WHERE email=?", (email,))
    if not rows or not check_password(body.password, rows[0]["password_salt"], rows[0]["password_hash"]):
        raise HTTPException(401, "Email or password did not match")
    set_session_cookie(response, rows[0]["id"])
    return {"authenticated": True, "operator": email}


@app.post("/api/auth/logout")
async def auth_logout(response: Response):
    response.delete_cookie("aegis_session", path="/")
    return {"authenticated": False}


PUBLIC_GET_PREFIXES = ("/api/auth/", "/api/health", "/api/apod", "/api/nasa", "/api/config",
                       "/api/stream", "/api/agent/alerts", "/api/standards", "/api/session")


async def nasa_get(url: str, params: dict | None = None):
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(502, f"NASA service returned HTTP {exc.response.status_code}") from exc
    except (httpx.RequestError, ValueError) as exc:
        raise HTTPException(502, "NASA data is temporarily unavailable") from exc


@app.get("/api/health")
async def health():
    sqlite = "ok"
    try:
        await get_db().execute_fetchall("SELECT 1")
        async with engine._db.execute("SELECT 1") as cur:
            await cur.fetchone()
    except Exception:
        sqlite = "unavailable"
    gemini = "configured" if settings.gemini_api_key else "missing_key"
    return {"status": "ok" if sqlite == "ok" else "degraded", "sqlite": sqlite,
            "nasa": "configured" if settings.nasa_api_key else "demo_key",
            "gemini": gemini, "provider": settings.ai_provider}


@app.get("/api/stream")
async def stream():
    """Telemetry only flows while monitoring is switched on. When it is off the
    stream sends a low-frequency standby beacon instead of readings."""
    async def events():
        while True:
            if engine.active:
                yield f"data: {json.dumps(engine.snapshot())}\n\n"
                await asyncio.sleep(1)
            else:
                yield "data: {\"standby\": true}\n\n"
                await asyncio.sleep(5)
    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/session")
async def session_status():
    snap = engine.snapshot()
    return {"active": engine.active, "standby": snap.get("standby", False),
            "phase": engine.phase, "phase_label": snap["phase_label"], "anomaly": engine.anomaly}


@app.post("/api/session/start")
async def session_start(request: Request):
    engine.active = True
    engine.operator = await _operator_name(current_user_id(request))
    return {"active": True, "operator": engine.operator, "phase": engine.phase, "phase_label": engine.snapshot()["phase_label"]}


@app.post("/api/session/stop")
async def session_stop():
    engine.active = False
    return {"active": False}


async def _operator_name(user_id: int | None) -> str:
    if user_id is None:
        return ""
    rows = await get_db().execute_fetchall("SELECT name FROM operator_profile WHERE user_id=?", (user_id,))
    return (row_dict(rows[0]) or {}).get("name", "") if rows else ""


@app.post("/api/phase/{phase_name}")
async def phase(phase_name: str):
    try:
        return await engine.set_phase(phase_name)
    except ValueError as exc:
        raise HTTPException(404, "Unknown mission phase") from exc


@app.post("/api/anomaly/{anomaly_name}")
async def anomaly(anomaly_name: str):
    try:
        return await engine.set_anomaly(anomaly_name)
    except ValueError as exc:
        raise HTTPException(404, "Unknown anomaly") from exc


@app.post("/api/flight-surgeon/analyze")
async def flight_surgeon():
    return (await analyze(engine.snapshot(), settings.ai_provider)).model_dump()


class ProviderConfig(BaseModel):
    provider: str


@app.post("/api/config/provider")
async def provider_config(body: ProviderConfig):
    if body.provider not in {"ollama", "gemini"}:
        raise HTTPException(400, "Provider must be ollama or gemini")
    settings.ai_provider = body.provider
    return {"provider": settings.ai_provider}


@app.get("/api/config")
def config():
    return {"provider": settings.ai_provider, "phases": PHASES,
            "channels": {k: {"label": v.label, "unit": v.unit, "earth": v.earth, "nominal": v.nominal,
                            "caution": v.caution, "critical": v.critical, "countermeasure": v.countermeasure}
                         for k, v in CHANNELS.items()}, "anomalies": ANOMALIES}


@app.get("/api/apod")
async def apod(day: date = Query(alias="date")):
    date_code = day.strftime("%y%m%d")
    try:
        data = await nasa_get(f"https://science.nasa.gov/wp-json/wp/v2/apod-basic/{date_code}")
    except HTTPException:
        data = {}
    if not data.get("hdurl") and not data.get("url"):
        # Science.nasa.gov occasionally 502s or lacks the requested date; the
        # public APOD API still gives us a valid image to show.
        fallback = await nasa_get("https://api.nasa.gov/planetary/apod",
                                 {"api_key": settings.nasa_api_key})
        return {"date": fallback.get("date"), "title": fallback.get("title", "NASA Astronomy Picture of the Day"),
                "explanation": fallback.get("explanation", ""), "url": fallback.get("url"),
                "hdurl": fallback.get("hdurl"), "media_type": fallback.get("media_type", "image"),
                "copyright": fallback.get("copyright") or fallback.get("credit")}
    return {"date": data.get("date"), "title": data.get("title", "NASA Astronomy Picture of the Day"),
            "explanation": data.get("explanation", ""), "url": data.get("permalink") or data.get("url"),
            "hdurl": data.get("hdurl"), "media_type": data.get("media_type", "image"),
            "copyright": data.get("copyright") or data.get("credit")}


@app.get("/api/nasa/images")
async def nasa_images(q: str = "earth from space", limit: int = Query(6, ge=1, le=20)):
    data = await nasa_get("https://images-api.nasa.gov/search", {"q": q, "media_type": "image", "page_size": limit})
    results = []
    for item in data.get("collection", {}).get("items", []):
        meta = (item.get("data") or [{}])[0]
        links = item.get("links") or []
        preview = next((x.get("href") for x in links if x.get("rel") == "preview"), None)
        results.append({"nasa_id": meta.get("nasa_id"), "title": meta.get("title", "NASA image"),
                        "description": meta.get("description", ""), "date_created": meta.get("date_created"), "url": preview})
    return {"results": results}


@app.get("/api/nasa/spaceflight-research")
async def nasa_spaceflight_research():
    """Fetch a public NASA OSDR human spaceflight research record, not live crew medical data."""
    accession = "OSD-343"
    data = await nasa_get(f"https://visualization.osdr.nasa.gov/biodata/api/v2/dataset/{accession}/")
    matches: list[dict[str, str]] = []
    wanted = ("title", "description", "mission", "organism", "study subject")

    def collect(node, depth=0):
        if depth > 8 or len(matches) >= 6:
            return
        if isinstance(node, dict):
            for key, value in node.items():
                label = str(key).replace("_", " ").strip()
                if isinstance(value, str) and any(term in label.lower() for term in wanted):
                    if value.strip():
                        matches.append({"label": label, "value": value.strip()[:360]})
                elif isinstance(value, (dict, list)):
                    collect(value, depth + 1)
        elif isinstance(node, list):
            for value in node[:40]:
                collect(value, depth + 1)

    collect(data)
    return {"accession": accession, "title": "NASA spaceflight biology research", "metadata": matches,
            "url": f"https://osdr.nasa.gov/bio/repo/data/studies/{accession}",
            "note": "Published research metadata; not live crew telemetry, an individual medical record, or clinical guidance."}


async def solar_particle_events() -> tuple[list[dict], str | None]:
    """NASA DONKI SEP events, cached to keep dashboard polling within API limits."""
    if time.monotonic() < _solar_cache["expires_at"]:
        return _solar_cache["events"], _solar_cache["error"]
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=6)
    try:
        data = await nasa_get("https://api.nasa.gov/DONKI/SEP", {
            "startDate": start.isoformat(), "endDate": end.isoformat(), "api_key": settings.nasa_api_key,
        })
        events = [{"id": event.get("sepID") or event.get("eventTime", "NASA-SEP"),
                   "time": event.get("eventTime"), "link": event.get("link"),
                   "instruments": [x.get("displayName") for x in event.get("instruments", []) if x.get("displayName")]}
                  for event in (data if isinstance(data, list) else [])]
        _solar_cache.update(expires_at=time.monotonic() + 900, events=events, error=None)
    except HTTPException as exc:
        _solar_cache.update(expires_at=time.monotonic() + 60, events=[], error=exc.detail)
    return _solar_cache["events"], _solar_cache["error"]


@app.get("/api/nasa/space-weather")
async def nasa_space_weather():
    events, error = await solar_particle_events()
    return {"source": "NASA DONKI Solar Energetic Particle catalog", "events": events,
            "error": error, "note": "Near-Earth space-weather observations; not an onboard radiation dose or crew medical reading."}


class VitalInput(BaseModel):
    astronaut_id: str = Field(min_length=1, max_length=80)
    heart_rate: float | None = None
    blood_pressure_systolic: float | None = None
    blood_pressure_diastolic: float | None = None
    oxygen_saturation: float | None = None
    body_temperature: float | None = None
    radiation_exposure: float | None = None
    notes: str = Field(default="", max_length=2000)


class MoodInput(BaseModel):
    astronaut_id: str = Field(min_length=1, max_length=80)
    mood: str
    stress_level: int | None = Field(default=None, ge=0, le=10)
    anxiety_level: int | None = Field(default=None, ge=0, le=10)
    sleep_hours: float | None = Field(default=None, ge=0, le=24)
    notes: str = Field(default="", max_length=2000)


def row_dict(row):
    return dict(row) if row else None


@app.get("/api/health/vitals")
async def get_vitals(astronaut_id: str = "commander", limit: int = Query(20, ge=1, le=100)):
    if supabase_configured():
        data = await list_vitals(astronaut_id, limit)
        if data is not None:
            return data
    rows = await get_db().execute_fetchall("SELECT * FROM astronaut_vitals WHERE astronaut_id=? ORDER BY recorded_at DESC LIMIT ?", (astronaut_id, limit))
    return [row_dict(row) for row in rows]


@app.post("/api/health/vitals")
async def add_vitals(body: VitalInput):
    connection = get_db()
    timestamp = datetime.now(timezone.utc).isoformat()
    columns = ("astronaut_id", "recorded_at", "heart_rate", "blood_pressure_systolic", "blood_pressure_diastolic", "oxygen_saturation", "body_temperature", "radiation_exposure", "notes")
    values = (body.astronaut_id, timestamp, body.heart_rate, body.blood_pressure_systolic, body.blood_pressure_diastolic, body.oxygen_saturation, body.body_temperature, body.radiation_exposure, body.notes)
    cursor = await connection.execute(f"INSERT INTO astronaut_vitals ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})", values)
    await connection.commit()
    row = await connection.execute_fetchall("SELECT * FROM astronaut_vitals WHERE id=?", (cursor.lastrowid,))
    if supabase_configured():
        await insert_vitals({k: v for k, v in zip(columns, values)})
    return row_dict(row[0])


@app.get("/api/health/mood")
async def get_mood(astronaut_id: str = "commander", limit: int = Query(20, ge=1, le=100)):
    if supabase_configured():
        data = await list_mood(astronaut_id, limit)
        if data is not None:
            return data
    rows = await get_db().execute_fetchall("SELECT * FROM mood_logs WHERE astronaut_id=? ORDER BY recorded_at DESC LIMIT ?", (astronaut_id, limit))
    return [row_dict(row) for row in rows]


@app.post("/api/health/mood")
async def add_mood(body: MoodInput):
    if body.mood not in {"great", "good", "neutral", "poor", "critical"}:
        raise HTTPException(422, "Mood must be great, good, neutral, poor, or critical")
    connection = get_db()
    timestamp = datetime.now(timezone.utc).isoformat()
    cursor = await connection.execute("INSERT INTO mood_logs(astronaut_id,recorded_at,mood,stress_level,anxiety_level,sleep_hours,notes) VALUES(?,?,?,?,?,?,?)",
        (body.astronaut_id, timestamp, body.mood, body.stress_level, body.anxiety_level, body.sleep_hours, body.notes))
    await connection.commit()
    rows = await connection.execute_fetchall("SELECT * FROM mood_logs WHERE id=?", (cursor.lastrowid,))
    if supabase_configured():
        await insert_mood({
            "astronaut_id": body.astronaut_id, "recorded_at": timestamp, "mood": body.mood,
            "stress_level": body.stress_level, "anxiety_level": body.anxiety_level,
            "sleep_hours": body.sleep_hours, "notes": body.notes,
        })
    return row_dict(rows[0])


# ---------------------------------------------------------------------------
# Personal profile — every plan and greeting is built from this.
# ---------------------------------------------------------------------------
class ProfileInput(BaseModel):
    name: str = Field(default="", max_length=60)
    age: int | None = Field(default=None, ge=18, le=70)
    sex: str = Field(default="m", max_length=1)
    height_cm: float | None = Field(default=None, ge=120, le=220)
    weight_kg: float | None = Field(default=None, ge=40, le=150)


@app.get("/api/profile")
async def get_profile(request: Request):
    user_id = current_user_id(request)
    if user_id is None:
        raise HTTPException(401, "Sign in to access your profile.")
    rows = await get_db().execute_fetchall("SELECT * FROM operator_profile WHERE user_id=?", (user_id,))
    return row_dict(rows[0]) if rows else {"user_id": user_id, "name": "", "age": None,
                                           "sex": "m", "height_cm": None, "weight_kg": None}


@app.post("/api/profile")
async def save_profile(body: ProfileInput, request: Request):
    user_id = current_user_id(request)
    if user_id is None:
        raise HTTPException(401, "Sign in to save your profile.")
    sex = "m" if body.sex.lower().startswith("m") else "f"
    conn = get_db()
    await conn.execute(
        "INSERT INTO operator_profile(user_id,name,age,sex,height_cm,weight_kg,updated_at) VALUES(?,?,?,?,?,?,?) "
        "ON CONFLICT(user_id) DO UPDATE SET name=excluded.name,age=excluded.age,sex=excluded.sex,"
        "height_cm=excluded.height_cm,weight_kg=excluded.weight_kg,updated_at=excluded.updated_at",
        (user_id, body.name.strip(), body.age, sex, body.height_cm, body.weight_kg,
         datetime.now(timezone.utc).isoformat()))
    await conn.commit()
    engine.operator = body.name.strip()
    rows = await conn.execute_fetchall("SELECT * FROM operator_profile WHERE user_id=?", (user_id,))
    return row_dict(rows[0])


@app.get("/api/standards")
async def standards():
    """NASA-derived reference standards used across the tracker (public, cited)."""
    return {"groups": STANDARDS, "rows": summary_targets(), "sources": [
        "NASA-STD-3001, Volume 2 (NASA Technical Standards)",
        "NASA Human Research Program — Spaceflight Nutrition evidence base",
        "NASA HRP Evidence Reports: Bone, Behavioral Health, Cognitive Performance",
    ]}


@app.post("/api/diet/plan")
async def diet_plan(request: Request):
    """Personal daily plan grounded in NASA standards; Gemini polishes wording only."""
    user_id = current_user_id(request)
    if user_id is None:
        raise HTTPException(401, "Sign in to generate your plan.")
    rows = await get_db().execute_fetchall("SELECT * FROM operator_profile WHERE user_id=?", (user_id,))
    profile = row_dict(rows[0]) if rows else {"name": "", "age": 35, "sex": "m", "height_cm": 175.0, "weight_kg": 70.0}
    plan = personalize(profile)
    note = await diet_polish(plan)
    events, _ = await solar_particle_events()
    if events:
        plan["space_weather_note"] = (f"NASA DONKI reports {len(events)} solar particle event(s) in the last "
                                      "7 days — keep hydration up and follow the radiation officer's brief.")
    plan["gemini_note"] = note
    plan["generated_at"] = datetime.now(timezone.utc).isoformat()
    plan["disclaimer"] = "Derived from published NASA standards for demonstration. Not medical advice."
    return plan


@app.get("/api/agent/alerts")
async def agent_alerts(astronaut_id: str = "commander"):
    """Rule-based warning layer: flags come from the backend; never treats AI prose as telemetry."""
    snapshot = engine.snapshot()
    alerts = []
    order = {"CRITICAL": 0, "CAUTION": 1, "ADVISORY": 2}
    # Simulated telemetry alerts only apply while monitoring is switched on.
    if engine.active:
        for key, status in snapshot["status"].items():
            if status != "NOMINAL":
                channel = CHANNELS[key]
                alerts.append({"id": key, "level": status, "title": channel.label.title(),
                               "message": f"Telemetry is {status.lower()} ({snapshot['telemetry'][key]:.1f} {channel.unit}).",
                               "action": channel.countermeasure, "source": "simulated mission telemetry"})
    vital_rows = await get_db().execute_fetchall(
        "SELECT * FROM astronaut_vitals WHERE astronaut_id=? ORDER BY recorded_at DESC LIMIT 1", (astronaut_id,)
    )
    if vital_rows:
        latest_vital = row_dict(vital_rows[0])
        crew_channels = {
            "heart_rate": ("heart_rate_bpm", "Heart rate"),
            "oxygen_saturation": ("spo2_pct", "Oxygen saturation"),
            "body_temperature": ("core_temp_c", "Body temperature"),
            "radiation_exposure": ("cumulative_radiation_msv", "Radiation exposure"),
        }
        for field, (channel_key, label) in crew_channels.items():
            value = latest_vital.get(field)
            if value is None:
                continue
            status = engine.flag(channel_key, float(value))
            if status != "NOMINAL":
                channel = CHANNELS[channel_key]
                alerts.append({"id": f"crew_{field}", "level": status, "title": f"{label} check-in",
                               "message": f"The latest crew-entered value is {float(value):.1f} {channel.unit} ({status.lower()} within illustrative prototype ranges).",
                               "action": "Confirm the measurement and contact the flight surgeon for operational guidance.",
                               "source": "crew-entered vitals"})
    if engine.active and snapshot["anomaly"] != "NONE":
        alerts.append({"id": "mission_anomaly", "level": "CRITICAL" if any(x["level"] == "CRITICAL" for x in alerts) else "CAUTION",
                       "title": "Mission anomaly active", "message": snapshot["anomaly"].replace("_", " ").title(),
                       "action": "Follow mission procedures and confirm readings with flight control.", "source": "simulated mission telemetry"})
    solar_events, solar_error = await solar_particle_events()
    for event in solar_events:
        event_time = f" at {event['time']}" if event.get("time") else ""
        alerts.append({"id": f"nasa_sep_{event['id']}", "level": "ADVISORY", "title": "NASA solar particle event reported",
                       "message": f"NASA DONKI reports a solar energetic particle event{event_time}.",
                       "action": "Ask the radiation officer to assess mission-specific exposure and follow flight rules.",
                       "source": "NASA DONKI · near-Earth event catalog", "url": event.get("link")})
    conn = get_db()
    rows = await conn.execute_fetchall("SELECT * FROM mood_logs WHERE astronaut_id=? ORDER BY recorded_at DESC LIMIT 3", (astronaut_id,))
    moods = [row_dict(row) for row in rows]
    if moods:
        latest = moods[0]
        poor_count = sum(m["mood"] in {"poor", "critical"} for m in moods)
        stress = latest["stress_level"]
        anxiety = latest["anxiety_level"]
        if latest["mood"] == "critical" or poor_count >= 2 or (stress is not None and stress >= 8) or (anxiety is not None and anxiety >= 8):
            alerts.append({"id": "wellbeing_checkin", "level": "ADVISORY", "title": "Wellbeing check-in suggested",
                           "message": "Recent self-reported check-ins suggest the crew member may benefit from a private conversation.",
                           "action": "Offer a confidential check-in with the flight surgeon or behavioral health support.",
                           "source": "self-reported check-ins", "privacy": "Share only with appropriate care staff."})
        if latest["sleep_hours"] is not None and latest["sleep_hours"] < 5:
            alerts.append({"id": "sleep_checkin", "level": "ADVISORY", "title": "Rest opportunity", "message": "The latest check-in reports under five hours of sleep.",
                           "action": "Review workload and protect the next scheduled sleep opportunity.", "source": "self-reported check-in"})
    alerts.sort(key=lambda item: order.get(item["level"], 3))
    return {"generated_at": datetime.now(timezone.utc).isoformat(), "alerts": alerts,
            "data_note": "Prototype telemetry is simulated. Vitals and mood are self-reported; NASA solar events are near-Earth context, not crew dose. This system does not diagnose or replace flight-surgeon care.",
            "nasa_space_weather_error": solar_error}


class ChatInput(BaseModel):
    astronaut_id: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=4000)


@app.post("/api/chat")
async def chat(body: ChatInput):
    conn = get_db()
    vital_rows = await conn.execute_fetchall("SELECT * FROM astronaut_vitals WHERE astronaut_id=? ORDER BY recorded_at DESC LIMIT 3", (body.astronaut_id,))
    mood_rows = await conn.execute_fetchall("SELECT * FROM mood_logs WHERE astronaut_id=? ORDER BY recorded_at DESC LIMIT 3", (body.astronaut_id,))
    context = {
        "simulated_telemetry": engine.snapshot()["telemetry"],
        "latest_self_reported_vitals": [
            {key: row_dict(row)[key] for key in ("recorded_at", "heart_rate", "oxygen_saturation", "body_temperature", "radiation_exposure")}
            for row in vital_rows
        ],
        "latest_self_reported_mood": [
            {key: row_dict(row)[key] for key in ("recorded_at", "mood", "stress_level", "anxiety_level", "sleep_hours")}
            for row in mood_rows
        ],
    }
    now = datetime.now(timezone.utc).isoformat()
    await conn.execute("INSERT INTO chat_messages(astronaut_id,role,content,created_at) VALUES(?,?,?,?)", (body.astronaut_id, "user", body.message, now))
    reply, used = await crew_chat(body.message, context)
    await conn.execute("INSERT INTO chat_messages(astronaut_id,role,content,created_at) VALUES(?,?,?,?)", (body.astronaut_id, "assistant", reply, datetime.now(timezone.utc).isoformat()))
    await conn.commit()
    if supabase_configured():
        await insert_chat({"astronaut_id": body.astronaut_id, "role": "user", "content": body.message, "created_at": now})
        await insert_chat({"astronaut_id": body.astronaut_id, "role": "assistant", "content": reply, "created_at": datetime.now(timezone.utc).isoformat()})
    return {"reply": reply, "provider": used, "gemini_configured": bool(settings.gemini_api_key)}


class SaveInput(BaseModel):
    date: str
    title: str
    url: str | None = None
    explanation: str | None = None


@app.post("/api/saves")
async def save_discovery(body: SaveInput):
    conn = get_db()
    await conn.execute("INSERT INTO saved_discoveries(date,title,url,explanation,created_at) VALUES(?,?,?,?,?) ON CONFLICT(date) DO UPDATE SET title=excluded.title,url=excluded.url,explanation=excluded.explanation",
                       (body.date, body.title, body.url, body.explanation, datetime.now(timezone.utc).isoformat()))
    await conn.commit()
    if supabase_configured():
        await insert_save({"date": body.date, "title": body.title, "url": body.url, "explanation": body.explanation})
    return {"saved": True, "date": body.date}
