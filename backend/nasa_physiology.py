"""Scenario ranges for a demonstrator; values are operationally inspired, not clinical limits."""
from dataclasses import dataclass

PHASES = {
    "LAUNCH_ACUTE_0_72H": {"label": "LAUNCH / ACUTE · 0–72 H", "fluid": 1.12, "hr": 78, "ioP": 16.0, "radiation": 0.0, "circadian": 88},
    "ORBITAL_ADAPTATION_W2_W12": {"label": "ORBITAL ADAPTATION · W2–W12", "fluid": 1.65, "hr": 72, "ioP": 19.0, "radiation": 12.0, "circadian": 76},
    "LONG_DURATION_M6_PLUS": {"label": "LONG DURATION · M6+", "fluid": 1.65, "hr": 70, "ioP": 20.0, "radiation": 180.0, "circadian": 68},
    "EVA_SPACEWALK": {"label": "EVA / SPACEWALK", "fluid": 1.55, "hr": 108, "ioP": 18.0, "radiation": 0.0, "circadian": 72},
}

@dataclass(frozen=True)
class Channel:
    label: str; unit: str; earth: float; nominal: tuple[float, float]; caution: tuple[float, float]; critical: tuple[float, float]; countermeasure: str

CHANNELS = {
 "heart_rate_bpm": Channel("HEART RATE", "bpm", 70, (55, 100), (45, 54), (0, 44), "Exercise protocol / hydration review"),
 "spo2_pct": Channel("OXYGEN SATURATION", "%", 98, (94, 100), (90, 93), (0, 89), "Verify sensor and cabin O₂ supply"),
 "core_temp_c": Channel("CORE TEMPERATURE", "°C", 37.0, (36.1, 37.8), (37.9, 38.3), (38.4, 50), "Thermal control and crew rest"),
 "cabin_ppco2_mmhg": Channel("CABIN PCO₂", "mmHg", .3, (0, 3.0), (3.0, 4.5), (4.5, 100), "CDRA scrubber boost / inspect beds"),
 "cephalad_fluid_shift_idx": Channel("CEPHALAD FLUID SHIFT", "× Earth", 1.0, (1.0, 1.65), (1.66, 1.8), (1.81, 5), "Lower Body Negative Pressure (LBNP)"),
 "intraocular_pressure_mmhg": Channel("INTRAOCULAR PRESSURE", "mmHg", 15, (10, 21), (21.1, 23), (23.1, 60), "SANS imaging and fluid-shift mitigation"),
 "cumulative_radiation_msv": Channel("CUMULATIVE RADIATION", "mSv", 0, (0, 250), (250, 400), (400, 2000), "Shelter in designated storm area"),
 "circadian_alignment_pct": Channel("CIRCADIAN ALIGNMENT", "%", 100, (70, 100), (55, 69), (0, 54), "480 nm LED phase-shift protocol"),
}

ANOMALIES = ["NONE", "CO2_SCRUBBER_DEGRADATION", "SANS_FLUID_SURGE", "EVA_SUBLIMATOR_FAULT", "SOLAR_PARTICLE_EVENT"]
