import asyncio, json, math, random, time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
import aiosqlite
from nasa_physiology import CHANNELS, PHASES, ANOMALIES

DB_PATH = Path(__file__).with_name("aegis_telemetry.db")
class TelemetryEngine:
    def __init__(self):
        self.phase = "ORBITAL_ADAPTATION_W2_W12"; self.anomaly = "NONE"; self.scenario = None; self.scenario_task = None; self.values = self._targets(); self.buffer = deque(maxlen=120); self.events = deque(maxlen=40); self.started = time.monotonic(); self._task = None; self._db = None
        # Vitals only run when the operator turns monitoring on — this is a
        # personal tracker, not a ward monitor.
        self.active = False; self.operator = ""
    def _targets(self):
        p=PHASES[self.phase]
        return {"heart_rate_bpm":p["hr"],"spo2_pct":97.8,"core_temp_c":37.0,"cabin_ppco2_mmhg":2.2,"cephalad_fluid_shift_idx":p["fluid"],"intraocular_pressure_mmhg":p["ioP"],"cumulative_radiation_msv":p["radiation"],"circadian_alignment_pct":p["circadian"]}
    async def start(self):
        self._db=await aiosqlite.connect(DB_PATH); await self._db.execute("CREATE TABLE IF NOT EXISTS anomaly_events (id INTEGER PRIMARY KEY, at TEXT, anomaly TEXT, phase TEXT, details TEXT)"); await self._db.commit(); self._task=asyncio.create_task(self._run())
    async def close(self):
        if self.scenario_task: self.scenario_task.cancel()
        if self._task: self._task.cancel()
        if self._db: await self._db.close()
    async def set_phase(self, phase):
        if phase not in PHASES: raise ValueError(phase)
        self.phase=phase; return {"phase":phase}
    async def set_anomaly(self, anomaly):
        if anomaly not in ANOMALIES: raise ValueError(anomaly)
        self.anomaly=anomaly
        if anomaly != "NONE":
            evt={"at":datetime.now(timezone.utc).isoformat(),"anomaly":anomaly,"phase":self.phase}; self.events.appendleft(evt)
            await self._db.execute("INSERT INTO anomaly_events(at, anomaly, phase, details) VALUES (?, ?, ?, ?)",(evt["at"],anomaly,self.phase,json.dumps(evt))); await self._db.commit()
        return {"anomaly":anomaly}
    async def run_scenario(self, name):
        scenarios = {
            "CO2_SCRUBBER_REHEARSAL": [("ORBITAL_ADAPTATION_W2_W12", "NONE", 8), ("ORBITAL_ADAPTATION_W2_W12", "CO2_SCRUBBER_DEGRADATION", 25)],
            "SANS_MONITORING_REHEARSAL": [("LONG_DURATION_M6_PLUS", "NONE", 8), ("LONG_DURATION_M6_PLUS", "SANS_FLUID_SURGE", 25)],
            "EVA_COOLING_REHEARSAL": [("EVA_SPACEWALK", "NONE", 8), ("EVA_SPACEWALK", "EVA_SUBLIMATOR_FAULT", 25)],
            "SOLAR_STORM_REHEARSAL": [("LONG_DURATION_M6_PLUS", "NONE", 8), ("LONG_DURATION_M6_PLUS", "SOLAR_PARTICLE_EVENT", 25)],
        }
        if name not in scenarios: raise ValueError(name)
        if self.scenario_task and not self.scenario_task.done(): self.scenario_task.cancel()
        self.scenario = name
        self.scenario_task = asyncio.create_task(self._play_scenario(name, scenarios[name]))
        return {"scenario": name, "status": "running", "duration_s": sum(x[2] for x in scenarios[name])}
    async def stop_scenario(self):
        if self.scenario_task and not self.scenario_task.done(): self.scenario_task.cancel()
        self.scenario_task = None; self.scenario = None; self.anomaly = "NONE"
        return {"scenario": None, "status": "stopped"}
    async def _play_scenario(self, name, steps):
        try:
            for phase, anomaly, duration in steps:
                self.phase = phase; self.anomaly = anomaly
                self.events.appendleft({"at":datetime.now(timezone.utc).isoformat(),"scenario":name,"anomaly":anomaly,"phase":phase,"duration_s":duration})
                await asyncio.sleep(duration)
        finally:
            self.anomaly = "NONE"; self.scenario = None; self.scenario_task = None
    def snapshot(self):
        base = {"timestamp":datetime.now(timezone.utc).isoformat(),"active":self.active,"operator":self.operator,"phase":self.phase,"phase_label":PHASES[self.phase]["label"],"anomaly":self.anomaly,"scenario":self.scenario,"telemetry":dict(self.values),"status":{k:self.flag(k,v) for k,v in self.values.items()},"deltas":{k:((v-CHANNELS[k].earth)/CHANNELS[k].earth*100 if CHANNELS[k].earth else None) for k,v in self.values.items()},"history":list(self.buffer)[-60:],"recent_events":list(self.events)}
        if not self.active:
            base["standby"] = True
            base["mission_elapsed_s"] = int(time.monotonic() - self.started)
            return base
        base["mission_elapsed_s"] = int(time.monotonic() - self.started)
        return base
    @staticmethod
    def flag(key,val):
        c=CHANNELS[key]
        if key=="heart_rate_bpm": return "CRITICAL" if val<45 or val>150 else "CAUTION" if val<55 or val>120 else "NOMINAL"
        if key=="spo2_pct":
            return "CRITICAL" if val<c.critical[1] else "CAUTION" if val<c.nominal[0] else "NOMINAL"
        if key=="circadian_alignment_pct":
            return "CRITICAL" if val<c.caution[0] else "CAUTION" if val<c.nominal[0] else "NOMINAL"
        if key=="cephalad_fluid_shift_idx":
            return "CRITICAL" if val>c.caution[1] else "CAUTION" if val>c.nominal[1] else "NOMINAL"
        if key=="core_temp_c": return "CRITICAL" if val>c.critical[0] else "CAUTION" if val>c.caution[0] else "NOMINAL"
        return "CRITICAL" if val>c.critical[0] else "CAUTION" if val>c.caution[0] else "NOMINAL"
    async def _run(self):
        while True:
            if not self.active:
                await asyncio.sleep(1); continue
            p=PHASES[self.phase]; targets=self._targets()
            anomaly_targets={"CO2_SCRUBBER_DEGRADATION":{"cabin_ppco2_mmhg":5.1},"SANS_FLUID_SURGE":{"cephalad_fluid_shift_idx":1.95,"intraocular_pressure_mmhg":25.0},"EVA_SUBLIMATOR_FAULT":{"core_temp_c":38.5,"heart_rate_bpm":132,"spo2_pct":91},"SOLAR_PARTICLE_EVENT":{"cumulative_radiation_msv":450}}
            targets.update(anomaly_targets.get(self.anomaly,{}))
            for k,target in targets.items():
                noise=random.gauss(0, .012 if k not in ("heart_rate_bpm","cumulative_radiation_msv") else .35)
                self.values[k] += (target-self.values[k])*.12 + noise
                self.values[k]=max(0,self.values[k])
            self.buffer.append({"timestamp":datetime.now(timezone.utc).isoformat(),"telemetry":dict(self.values),"status":{k:self.flag(k,v) for k,v in self.values.items()}})
            if self.anomaly!="NONE" and self.anomaly!="SOLAR_PARTICLE_EVENT": self.values["cumulative_radiation_msv"] += .002
            await asyncio.sleep(1)
engine=TelemetryEngine()
