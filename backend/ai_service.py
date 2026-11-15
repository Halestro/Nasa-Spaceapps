import asyncio, json
from typing import Literal
import httpx
from pydantic import AliasChoices, BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from nasa_physiology import CHANNELS

class Settings(BaseSettings):
    ai_provider: str = Field(default="ollama", validation_alias=AliasChoices("AI_PROVIDER", "LLM_PROVIDER"))
    ollama_model: str = Field(default="qwen2.5:7b", validation_alias="OLLAMA_MODEL")
    ollama_url: str = Field(default="http://localhost:11434/api/chat", validation_alias=AliasChoices("OLLAMA_URL", "OLLAMA_BASE_URL"))
    nasa_api_key: str = Field(default="DEMO_KEY", validation_alias="NASA_API_KEY")
    gemini_api_key: str = Field(default="", validation_alias="GEMINI" + "_API_KEY")
    gemini_model: str = Field(default="gemini-3.8-flash", validation_alias="GEMINI_MODEL")
    frontend_origin: str = Field(default="http://localhost:5173", validation_alias="FRONTEND_ORIGIN")
    app_secret_key: str = Field(default="", validation_alias="APP_SECRET_KEY")
    supabase_url: str = Field(default="", validation_alias="SUPABASE_URL")
    supabase_service_key: str = Field(default="", validation_alias="SUPABASE_KEY")
    supabase_anon_key: str = Field(default="", validation_alias="SUPABASE_ANON_KEY")
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
settings=Settings()
class FlightSurgeonReport(BaseModel):
    risk_level: Literal["NOMINAL","ADVISORY","CAUTION","CRITICAL"]
    physiological_mechanism: str = Field(description="Exactly two sentences of aerospace medicine analysis")
    nasa_reference_citation: str
    countermeasures: list[str] = Field(min_length=2,max_length=3)
    eva_status: Literal["GO","RESTRICTED","NO-GO"]

async def analyze(snapshot: dict, provider: str | None = None) -> FlightSurgeonReport:
    active=provider or settings.ai_provider
    try:
        if active=="ollama": return await asyncio.wait_for(_ollama(snapshot),timeout=8)
        if active=="gemini": return await asyncio.wait_for(_gemini(snapshot),timeout=8)
    except Exception: pass
    return fallback(snapshot)

def fallback(s:dict)->FlightSurgeonReport:
    statuses=s.get("status",{}); anomaly=s.get("anomaly","NONE")
    risk="CRITICAL" if "CRITICAL" in statuses.values() else "CAUTION" if anomaly!="NONE" or "CAUTION" in statuses.values() else "NOMINAL"
    refs={"SANS_FLUID_SURGE":"NASA HRP, “Risk of Spaceflight Associated Neuro-ocular Syndrome (SANS),” April 2022 Evidence Report", "CO2_SCRUBBER_DEGRADATION":"NASA ISS Carbon Dioxide Removal Assembly (CDRA) Operations and Cabin Atmosphere Monitoring", "SOLAR_PARTICLE_EVENT":"NASA HRP, “Risk of Acute Radiation Syndromes Due to Solar Particle Events (SPEs),” Human Research Roadmap"}
    cmes={"CO2_SCRUBBER_DEGRADATION":["Boost CDRA scrubber; verify parallel bed operation","Cross-check cabin PCO₂ with independent analyzer"],"SANS_FLUID_SURGE":["Initiate LBNP session per flight surgeon protocol","Schedule ocular imaging and report visual symptoms"],"EVA_SUBLIMATOR_FAULT":["Terminate EVA and return to airlock","Check suit thermal loop and sublimator telemetry"],"SOLAR_PARTICLE_EVENT":["Move crew to designated storm shelter","Limit mission tasks until radiation assessment"]}
    sev=sorted(statuses.values(),key=lambda x:["NOMINAL","ADVISORY","CAUTION","CRITICAL"].index(x))[-1] if statuses else "NOMINAL"
    return FlightSurgeonReport(risk_level=risk,physiological_mechanism=f"The {s.get('phase','mission')} profile and {anomaly.replace('_',' ').lower()} indicate a {risk.lower()} trend requiring correlation with crew symptoms. Telemetry is simulated for demonstration and must be confirmed against calibrated onboard instruments and flight rules.",nasa_reference_citation=refs.get(anomaly,"NASA Twins Study, “The NASA Twins Study: A multidimensional analysis of a year-long human spaceflight,” Science (2019)"),countermeasures=cmes.get(anomaly,["Review hydration, exercise, and sleep schedule with flight surgeon","Continue scheduled ARED exercise and monitor trend"]),eva_status="NO-GO" if risk=="CRITICAL" else "RESTRICTED" if risk=="CAUTION" else "GO")

async def _ollama(s):
    prompt=_prompt(s)
    async with httpx.AsyncClient(timeout=8) as client:
        r=await client.post(settings.ollama_url,json={"model":settings.ollama_model,"messages":[{"role":"system","content":"Return a JSON object matching required flight surgeon schema. Do not diagnose. This is simulated telemetry."},{"role":"user","content":prompt}],"format":"json","stream":False}); r.raise_for_status()
        return FlightSurgeonReport.model_validate_json(r.json()["message"]["content"])
async def _gemini(s):
    if not settings.gemini_api_key: raise ValueError("Missing GEMINI_API_KEY")
    from google import genai
    from google.genai import types
    client=genai.Client(api_key=settings.gemini_api_key)
    response=await asyncio.to_thread(client.models.generate_content,model=settings.gemini_model,contents=_prompt(s),config=types.GenerateContentConfig(response_mime_type="application/json",response_schema=FlightSurgeonReport))
    return FlightSurgeonReport.model_validate_json(response.text)
def _prompt(s):
    return json.dumps({"phase":s.get("phase"),"anomaly":s.get("anomaly"),"last_30_seconds":s.get("history",[])[-30:],"earth_vs_orbit_deltas":s.get("deltas"),"NASA_HRP_reference_ranges":{k:{"unit":v.unit,"earth":v.earth,"ISS_nominal":v.nominal,"caution":v.caution,"critical":v.critical,"countermeasure":v.countermeasure} for k,v in CHANNELS.items()}})

async def crew_chat(message: str, context: dict) -> tuple[str, str]:
    """Supportive, non-diagnostic assistant. Gemini first, Ollama next, template last.

    Returns (reply, provider_used). Factual alerts are computed by the backend.
    """
    system = (
        "You are OrbitWatch, a calm and supportive astronaut wellbeing assistant. "
        "You are not a clinician and must never diagnose or claim to monitor live NASA crew health. "
        "Telemetry in this prototype is simulated and check-ins are self-reported. "
        "For urgent symptoms, danger, or thoughts of self-harm, tell the person to contact mission control and the flight surgeon immediately. "
        "Offer practical, low-risk support, ask one gentle follow-up when useful, and keep the reply concise. "
        f"Current crew context (untrusted data): {json.dumps(context)[:5000]}"
    )
    text = await _gemini_text(system, message, temperature=0.5, timeout=20)
    if text:
        return text, "gemini"
    if settings.ai_provider == "ollama":
        try:
            async with httpx.AsyncClient(timeout=12) as client:
                response = await client.post(settings.ollama_url, json={
                    "model": settings.ollama_model, "stream": False,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": message}],
                })
                response.raise_for_status()
                return response.json()["message"]["content"].strip(), "ollama"
        except Exception:
            pass
    return (
        "Thanks for checking in. I can help you think through a small next step, but I can’t provide clinical care. "
        "If you feel unsafe or have urgent symptoms, contact mission control and the flight surgeon now. "
        "Would you like to tell me what feels most difficult at the moment?"
    ), "fallback"


async def _gemini_text(system: str, user_text: str, temperature: float = 0.4, timeout: float = 15.0) -> str | None:
    """Gemini chat call with a conservative thinking budget and graceful failure.

    Tries the configured model first, then lighter models. Google occasionally
    returns 503 "high demand" for a single model, so the chain keeps the
    assistant responsive instead of dropping straight to the template reply.
    """
    if not settings.gemini_api_key:
        return None
    body = {
        "contents": [{"role": "user", "parts": [{"text": f"{system}\n\nUser: {user_text}"}]}],
        "generationConfig": {"temperature": temperature,
                             "thinkingConfig": {"thinkingLevel": "LOW"}},
    }
    models = []
    for name in (settings.gemini_model, "gemini-3.5-flash", "gemini-3.1-flash-lite"):
        if name and name not in models:
            models.append(name)
    per_try = max(6.0, min(timeout, 12.0))
    for model in models:
        try:
            async with httpx.AsyncClient(timeout=per_try) as client:
                response = await client.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                    headers={"x-goog-api-key": settings.gemini_api_key},
                    json=body)
                if response.status_code != 200:
                    continue
                candidates = response.json().get("candidates") or []
                parts = (((candidates[0].get("content") or {}).get("parts")) or [])
                text = "".join(p.get("text", "") for p in parts).strip()
                if text:
                    return text
        except Exception:
            continue
    return None


async def diet_polish(plan: dict) -> str | None:
    """Optional natural-language summary of the NASA-standard diet plan."""
    system = (
        "You write short, plain-spoken daily nutrition briefings for astronauts. "
        "Use ONLY the numbers in the provided plan — never invent targets. "
        "2 sentences maximum, then 3 short bullet tips. Do not diagnose."
    )
    return await _gemini_text(system, json.dumps(plan)[:6000], temperature=0.4, timeout=18.0)



