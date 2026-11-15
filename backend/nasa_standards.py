"""NASA-derived crew health standards and personalized planning.

Targets are drawn from published NASA references — NASA-STD-3001 (Volume 2),
the NASA Human Research Program nutrition/exercise evidence base, and the
NASA Spaceflight Nutrition report. They are used to personalize diet and
activity guidance for the signed-in operator.

This module is deliberately deterministic: the same profile always yields the
same plan. Gemini may polish the wording, but never invents the numbers.
"""
from math import inf

# ---------------------------------------------------------------------------
# Reference standards. Every item carries its NASA source so the UI can cite it.
# ---------------------------------------------------------------------------
STANDARDS: list[dict] = [
    {
        "group": "REST & CIRCADIAN",
        "items": [
            {"label": "Sleep opportunity", "target": "8 h per 24 h", "key": "sleep_h",
             "range": (7, 9), "source": "NASA-STD-3001, Vol. 2 — habitability and human factors: 8-hour sleep opportunity per 24 h"},
            {"label": "Circadian alignment", "target": "≥ 80% aligned", "key": "circadian_pct",
             "range": (80, 100), "source": "NASA HRP — Risk of Adverse Cognitive Outcomes; lighting discipline countermeasures"},
        ],
    },
    {
        "group": "EXERCISE COUNTERMEASURES",
        "items": [
            {"label": "Daily exercise", "target": "≈ 2 h/day, 6 days/wk", "key": "exercise_min",
             "range": (105, 135), "source": "NASA HRP — ISS exercise countermeasure operations (treadmill + cycle + ARED)"},
            {"label": "Resistive loading", "target": "≥ 3 sessions/wk", "key": "resistive_wk",
             "range": (3, 6), "source": "NASA HRP — Bone loss (~1–2%/mo at hip without countermeasure); ARED countermeasure standard"},
        ],
    },
    {
        "group": "NUTRITION (NASA SPACEFLIGHT NUTRITION REPORT)",
        "items": [
            {"label": "Protein", "target": "1.2–1.7 g/kg/day", "key": "protein_g_kg",
             "range": (1.2, 1.7), "source": "NASA Spaceflight Nutrition / HRP — protein standard for flight"},
            {"label": "Fat", "target": "25–35% of energy", "key": "fat_pct",
             "range": (25, 35), "source": "NASA Spaceflight Nutrition — macronutrient distribution"},
            {"label": "Carbohydrate", "target": "45–55% of energy", "key": "carb_pct",
             "range": (45, 55), "source": "NASA Spaceflight Nutrition — macronutrient distribution"},
            {"label": "Calcium", "target": "1000–1200 mg/day", "key": "calcium_mg",
             "range": (1000, 1200), "source": "NASA Spaceflight Nutrition — bone-support standard"},
            {"label": "Vitamin D", "target": "600–800 IU/day", "key": "vitd_iu",
             "range": (600, 800), "source": "NASA Spaceflight Nutrition — ISS vitamin D standard"},
            {"label": "Sodium", "target": "≤ 2300 mg/day", "key": "sodium_mg",
             "range": (1000, 2300), "source": "NASA Spaceflight Nutrition — sodium tied to bone calcium excretion"},
            {"label": "Omega-3 (n-3)", "target": "≈ 1.1–1.6 g/day", "key": "omega3_g",
             "range": (1.1, 1.6), "source": "NASA Spaceflight Nutrition — fish twice weekly aboard ISS"},
        ],
    },
    {
        "group": "RADIATION & ENVIRONMENT",
        "items": [
            {"label": "Career effective dose", "target": "≤ 600 mSv", "key": "career_msv",
             "range": (0, 600), "source": "NASA-STD-3001, Vol. 2 — permissible exposure limits for spaceflight"},
            {"label": "Cabin CO₂", "target": "≤ 2.6 mmHg avg", "key": "pco2_mmhg",
             "range": (0, 2.6), "source": "NASA-STD-3001, Vol. 2 — atmospheric CO₂ limit (7-day average)"},
        ],
    },
    {
        "group": "MENTAL HEALTH",
        "items": [
            {"label": "Private check-ins", "target": "≥ 1 per week", "key": "checkin_wk",
             "range": (1, 7), "source": "NASA HRP — Behavioral health & performance: behavioral health check requirements"},
            {"label": "Team communication", "target": "daily", "key": "comm",
             "range": (1, 3), "source": "NASA HRP — Risk of Adverse Behavioral Conditions: team-support countermeasures"},
        ],
    },
]

_SOURCES = [
    "NASA-STD-3001, Volume 2 (NASA Technical Standards)",
    "NASA Human Research Program — Spaceflight Nutrition (HRP evidence base)",
    "NASA HRP Evidence Reports: Bone, Behavioral Health, Cognitive Performance",
]

def defaults() -> dict:
    """Fallback profile when the operator has not completed theirs."""
    return {"name": "", "age": 35, "sex": "m", "height_cm": 175.0, "weight_kg": 70.0}


def _bmr(sex: str, weight_kg: float, height_cm: float, age: int) -> float:
    """Mifflin-St Jeor BMR."""
    base = 10 * weight_kg + 6.25 * height_cm - 5 * age
    return base + (5 if sex == "m" else -161)


def personalize(profile: dict) -> dict:
    """Turn an operator profile into personalized targets grounded in the standards."""
    d = {**defaults(), **{k: v for k, v in (profile or {}).items() if v}}
    weight = max(40.0, min(150.0, float(d["weight_kg"])))
    height = max(120.0, min(220.0, float(d["height_cm"])))
    age = max(18, min(70, int(d["age"])))
    sex = "m" if str(d["sex"]).lower().startswith("m") else "f"

    # Flight ops are "heavy" activity: ~2 h/day of scheduled exercise (NASA ISS).
    bmr = _bmr(sex, weight, height, age)
    kcal = round(bmr * 1.7 / 10) * 10
    protein_g = round(weight * 1.45)          # midpoint of NASA 1.2–1.7 g/kg
    fat_g = round(kcal * 0.30 / 9)            # midpoint of 25–35% energy
    carb_g = round(kcal * 0.50 / 4)           # midpoint of 45–55% energy
    water_l = round(kcal * 1.0 / 1000 * 10) / 10   # ≈1 mL per kcal + sweat losses

    # Meal split follows ISS practice: 3 meals + 2 snacks.
    split = [("Breakfast", 0.25), ("Lunch mid", 0.10), ("Lunch", 0.30), ("Dinner", 0.27), ("Evening snack", 0.08)]
    meals = [{"meal": name, "kcal": round(kcal * share / 10) * 10, "focus": focus}
             for (name, share), focus in zip(split, [
                 "Oat/grain + fruit + egg — slow carbs, choline",
                 "Protein snack + vitamin D-fortified item",
                 "Lean protein + vegetable + complex carb — calcium focus",
                 "Fish or legume twice weekly — omega-3, iron",
                 "Dairy/soy + tart cherry — supports sleep onset"])]
    # Repair rounding drift into the largest meal.
    drift = kcal - sum(m["kcal"] for m in meals)
    meals[2]["kcal"] += drift

    return {
        "profile": {"name": d.get("name") or "", "age": age, "sex": sex, "height_cm": height, "weight_kg": weight},
        "bmr_kcal": round(bmr),
        "targets": {
            "energy_kcal": kcal,
            "protein_g": protein_g,
            "fat_g": fat_g,
            "carbohydrate_g": carb_g,
            "water_l": water_l,
            "calcium_mg": 1100,
            "vitamin_d_iu": 800,
            "sodium_mg_max": 2300,
            "sleep_h": 8,
            "exercise_min": 120,
            "resistive_sessions_wk": 4,
        },
        "meals": meals,
        "exercise_week": [
            {"day": "Mon–Fri", "plan": "45 min treadmill @ 75% HRR · 30 min cycle · 45 min ARED (alternating muscle groups)"},
            {"day": "Sat", "plan": "60 min interval treadmill · 30 min ARED core"},
            {"day": "Sun", "plan": "Rest + mobility, 20 min easy cycle optional"},
        ],
        "nasa_sources": _SOURCES,
    }


def summary_targets() -> list[dict]:
    """Flat list for a compact standards table."""
    rows = []
    for group in STANDARDS:
        for item in group["items"]:
            lo, hi = item["range"]
            rows.append({"group": group["group"], "label": item["label"],
                         "target": item["target"], "source": item["source"],
                         "lo": lo if lo != -inf else None, "hi": hi if hi != inf else None})
    return rows
