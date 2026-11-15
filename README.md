# AEGIS-HRP · Astronaut Physiology & Spaceflight Telemetry Monitor

A local NASA Space Apps prototype with a FastAPI 1 Hz telemetry simulator, NASA imagery APIs, a local SQLite crew check-in store, configurable Gemini/Ollama analysis, and a React/TypeScript mission console. Rule-based warnings combine simulated mission telemetry with crew-entered vitals and wellbeing check-ins. Telemetry and thresholds are illustrative prototype data, not clinical limits or operational flight rules; the app does not access individual astronaut medical records from NASA.

## Run the prototype

### 1. Start Ollama and pull the model (optional; Gemini can be selected in the console)

```bash
ollama serve
# In a second terminal:
ollama pull qwen2.5:7b
```

### 2. Start FastAPI

```bash
cd nasa-space-app/backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Set `NASA_API_KEY`, `AI_PROVIDER=gemini`, and `GEMINI_API_KEY` in `backend/.env` to connect NASA APOD and Gemini. The NASA Image and Video Library is also used for image search. Provider can be switched from the console. SQLite creates `backend/aegis_telemetry.db` and `backend/crew_wellbeing.db` automatically.

### 3. Start Vite

```bash
cd nasa-space-app/frontend
npm install
npm run dev
```

Open `http://localhost:5173`. API docs are at `http://localhost:8000/docs`.

## API

- `GET /api/stream` — Server-Sent Events with live telemetry and status flags
- `POST /api/phase/{phase_name}` — set a mission phase
- `POST /api/anomaly/{anomaly_name}` — inject or clear an anomaly (`NONE` clears)
- `POST /api/flight-surgeon/analyze` — produce a typed analysis or deterministic fallback
- `GET /api/agent/alerts` — current rule-based health, telemetry, sleep, and wellbeing warnings
- `GET/POST /api/health/vitals` and `/api/health/mood` — crew-entered health and wellbeing check-ins
- `POST /api/chat` — supportive crew assistant using Gemini or Ollama when configured
- `GET /api/apod` and `/api/nasa/images` — NASA imagery endpoints
- `GET /api/nasa/spaceflight-research` — NASA OSDR human spaceflight research metadata
- `GET /api/nasa/space-weather` — cached NASA DONKI solar energetic particle events
- `POST /api/config/provider` — body `{"provider":"ollama"}` or `{"provider":"gemini"}`
- `GET /api/health` — API and local storage configuration status

The warning service evaluates locally defined prototype thresholds every ten seconds in the dashboard. It prompts a human flight surgeon to review concerning values and check-ins; it does not diagnose, take medical action, or replace mission procedures. NASA APIs provide public spaceflight research, imagery, and near-Earth space-weather observations, not an individual crew member's live medical telemetry or radiation dose.
