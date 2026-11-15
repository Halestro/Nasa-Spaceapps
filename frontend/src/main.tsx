import React, { useCallback, useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import '@fontsource-variable/plus-jakarta-sans';
import '@fontsource-variable/inter';
import './style.css';

/* ------------------------------------------------------------------ types */
type Level = 'NOMINAL' | 'CAUTION' | 'CRITICAL' | 'ADVISORY';
type NavKey = 'dashboard' | 'vitals' | 'wellbeing' | 'standards' | 'logs';
type Report = {
  risk_level: Level;
  physiological_mechanism: string;
  nasa_reference_citation: string;
  countermeasures: string[];
  eva_status: 'GO' | 'RESTRICTED' | 'NO-GO';
};
type Snapshot = {
  standby?: boolean;
  active?: boolean;
  operator?: string;
  timestamp?: string;
  mission_elapsed_s: number;
  phase: string;
  phase_label: string;
  anomaly: string;
  telemetry: Record<string, number>;
  status: Record<string, Level>;
  history?: { telemetry: Record<string, number> }[];
};
type Alert = {
  id: string;
  level: Level;
  title: string;
  message: string;
  action?: string;
  source?: string;
};
type ChatMsg = { role: 'user' | 'assistant'; content: string; provider?: string };

/* ------------------------------------------------------------------ consts */
const API = import.meta.env.VITE_API_URL || 'http://localhost:8000';
const TODAY = new Date().toISOString().slice(0, 10);
const MOODS: { value: string; label: string; color: string }[] = [
  { value: 'great', label: 'Great', color: '#84cc16' },
  { value: 'good', label: 'Good', color: '#a3e635' },
  { value: 'neutral', label: 'Neutral', color: '#fbbf24' },
  { value: 'poor', label: 'Low', color: '#fb923c' },
  { value: 'critical', label: 'Critical', color: '#ef4444' },
];
const MOOD_COLOR: Record<string, string> = Object.fromEntries(MOODS.map(m => [m.value, m.color]));
const PHASES: [string, string][] = [
  ['LAUNCH_ACUTE_0_72H', 'Launch / acute · 0–72 h'],
  ['ORBITAL_ADAPTATION_W2_W12', 'Orbital adaptation · W2–W12'],
  ['LONG_DURATION_M6_PLUS', 'Long duration · M6+'],
  ['EVA_SPACEWALK', 'EVA / spacewalk'],
];
const ANOMALIES: [string, string][] = [
  ['NONE', 'Nominal'],
  ['CO2_SCRUBBER_DEGRADATION', 'CO₂ fault'],
  ['SANS_FLUID_SURGE', 'Fluid surge'],
  ['EVA_SUBLIMATOR_FAULT', 'Cooling leak'],
  ['SOLAR_PARTICLE_EVENT', 'Solar event'],
];

type VitalMeta = {
  field: string;
  telemetry: string;
  label: string;
  unit: string;
  decimals: number;
  min: number;
  max: number;
  tone: 'lav' | 'lime';
  icon: string;
};
const VITAL_META: VitalMeta[] = [
  { field: 'heart_rate', telemetry: 'heart_rate_bpm', label: 'Heart rate', unit: 'BPM', decimals: 0, min: 40, max: 180, tone: 'lav', icon: 'heart' },
  { field: 'oxygen_saturation', telemetry: 'spo2_pct', label: 'Oxygen saturation', unit: '%', decimals: 1, min: 80, max: 100, tone: 'lime', icon: 'wind' },
  { field: 'body_temperature', telemetry: 'core_temp_c', label: 'Body temperature', unit: '°C', decimals: 1, min: 34, max: 42, tone: 'lav', icon: 'thermo' },
  { field: 'radiation_exposure', telemetry: 'cumulative_radiation_msv', label: 'Radiation dose', unit: 'mSv', decimals: 1, min: 0, max: 600, tone: 'lime', icon: 'radiation' },
];
const TELEMETRY_IDS = new Set([
  'heart_rate_bpm', 'spo2_pct', 'core_temp_c', 'cabin_ppco2_mmhg', 'cephalad_fluid_shift_idx',
  'intraocular_pressure_mmhg', 'cumulative_radiation_msv', 'circadian_alignment_pct', 'anomaly',
]);

/* ------------------------------------------------------------------ helpers */
const msg = (e: unknown, fallback: string): string =>
  e instanceof Error && e.message ? e.message : fallback;

const post = async (path: string, body?: unknown) => {
  const r = await fetch(`${API}${path}`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
  if (r.status === 401) throw new Error('Session expired — sign in again.');
  if (!r.ok) {
    const detail = (await r.json().catch(() => ({}))) as { detail?: string };
    throw new Error(detail.detail || `Request failed (${r.status})`);
  }
  return r.json();
};

const clamp = (n: number, lo = 0, hi = 100) => Math.max(lo, Math.min(hi, n));

const fmtTime = (iso?: string) => {
  const d = new Date(iso || '');
  return isNaN(d.getTime())
    ? ''
    : d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
};

const fmtDuration = (hours: number | null) => {
  if (hours == null || Number.isNaN(hours)) return '0h 00m';
  const h = Math.floor(hours);
  const m = Math.round((hours - h) * 60);
  return `${h}h ${String(m).padStart(2, '0')}m`;
};

const initials = (name: string, email: string) => {
  const base = name || email.split('@')[0] || 'A';
  const parts = base.split(/[\s._-]+/).filter(Boolean);
  return ((parts[0]?.[0] || 'A') + (parts[1]?.[0] || '')).toUpperCase().slice(0, 2);
};

/** Newest value for a field across logged records. */
function latest(entries: any[], field: string): { value: number; at: string } | null {
  for (const row of entries) {
    const raw = row?.[field];
    if (raw !== null && raw !== undefined && raw !== '') {
      return { value: Number(raw), at: String(row.recorded_at || '') };
    }
  }
  return null;
}

/** Last N values in chronological order (oldest → newest). */
function series(entries: any[], field: string, count = 7): number[] {
  return entries
    .filter(row => row?.[field] !== null && row?.[field] !== undefined && row?.[field] !== '')
    .slice(0, count)
    .map(row => Number(row[field]))
    .reverse();
}

/* ------------------------------------------------------------------ icons */
const ICONS: Record<string, React.ReactNode> = {
  grid: <><rect x="3" y="3" width="7" height="7" rx="2" /><rect x="14" y="3" width="7" height="7" rx="2" /><rect x="3" y="14" width="7" height="7" rx="2" /><rect x="14" y="14" width="7" height="7" rx="2" /></>,
  activity: <path d="M3 12h4l2.2-6 4.2 12 2.2-6H21" />,
  sparkles: <><path d="M12 3l1.7 4.3L18 9l-4.3 1.7L12 15l-1.7-4.3L6 9l4.3-1.7L12 3Z" /><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8L19 15Z" /></>,
  book: <><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v16H6.5A2.5 2.5 0 0 0 4 21.5V5.5Z" /><path d="M4 18.5A2.5 2.5 0 0 1 6.5 16H20" /></>,
  list: <><path d="M8 6h13M8 12h13M8 18h13" /><circle cx="3.5" cy="6" r="1" /><circle cx="3.5" cy="12" r="1" /><circle cx="3.5" cy="18" r="1" /></>,
  search: <><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></>,
  chevron: <path d="m6 9 6 6 6-6" />,
  plus: <path d="M12 5v14M5 12h14" />,
  send: <path d="M4 12 20 4l-6 16-3-7-7-1Z" />,
  play: <path d="M8 5v14l11-7-11-7Z" />,
  pause: <><rect x="7" y="5" width="4" height="14" rx="1.2" /><rect x="14" y="5" width="4" height="14" rx="1.2" /></>,
  logout: <><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" /><path d="m16 17 5-5-5-5M21 12H9" /></>,
  heart: <path d="M20.8 5.6a5.5 5.5 0 0 0-7.8 0L12 6.6l-1-1a5.5 5.5 0 0 0-7.8 7.8l1 1L12 22l7.8-7.6 1-1a5.5 5.5 0 0 0 0-7.8Z" />,
  wind: <><path d="M3 8h11a3 3 0 1 0-3-3" /><path d="M3 12h15a3 3 0 1 1-3 3" /><path d="M3 16h7a2 2 0 1 1-2 2" /></>,
  thermo: <><path d="M14 14.8V5a2 2 0 1 0-4 0v9.8a4 4 0 1 0 4 0Z" /><path d="M12 9v6" /></>,
  radiation: <><circle cx="12" cy="12" r="2" /><path d="M12 2v6M4 20l5-3M20 20l-5-3" /></>,
  arrow: <path d="M5 12h14m-6-6 6 6-6 6" />,
  check: <path d="m4 12 5 5L20 6" />,
  alert: <><path d="M12 3 2.5 20h19L12 3Z" /><path d="M12 9v5M12 17.5v.5" /></>,
  brain: <><path d="M9 3a3 3 0 0 0-3 3v1a3 3 0 0 0-1 5.8V15a3 3 0 0 0 4 2.8V21" /><path d="M15 3a3 3 0 0 1 3 3v1a3 3 0 0 1 1 5.8V15a3 3 0 0 1-4 2.8V21" /><path d="M12 6v12" /></>,
};

function Icon({ name, size = 18 }: { name: string; size?: number }) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} fill="none" stroke="currentColor"
      strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {ICONS[name] || ICONS.grid}
    </svg>
  );
}

/* ------------------------------------------------------------------ atoms */
function Ring({ pct, tone, children }: { pct: number; tone: 'lav' | 'lime'; children: React.ReactNode }) {
  return (
    <div className={`ring tone-${tone}`} style={{ '--p': `${clamp(pct)}%` } as React.CSSProperties}>
      <div className="ring-inner">{children}</div>
    </div>
  );
}

function Spark({ values, tone }: { values: number[]; tone: 'lav' | 'lime' }) {
  const last = values.slice(-7);
  const slots: (number | null)[] = [
    ...Array(Math.max(0, 7 - last.length)).fill(null),
    ...last,
  ];
  const max = last.length ? Math.max(...last) : 0;
  const min = last.length ? Math.min(...last) : 0;
  const span = max - min;
  const heightFor = (v: number | null) => {
    if (v == null) return 10;
    if (!span) return 58;
    return 22 + ((v - min) / span) * 78;
  };
  return (
    <div className={`spark tone-${tone}`} aria-hidden="true">
      {slots.map((v, i) => (
        <i key={i} className={v == null ? 'empty' : ''} style={{ height: `${heightFor(v)}%` }} />
      ))}
    </div>
  );
}

function StatusPill({ level }: { level: Level | null }) {
  if (!level) return <span className="pill">No session</span>;
  const cls = level.toLowerCase();
  return <span className={`pill status ${cls}`}><i className="dot" />{level === 'NOMINAL' ? 'Nominal' : level[0] + level.slice(1).toLowerCase()}</span>;
}

function CardHead({ title, sub, right }: { title: string; sub?: string; right?: React.ReactNode }) {
  return (
    <div className="card-head">
      <div>
        <h2>{title}</h2>
        {sub && <p>{sub}</p>}
      </div>
      {right}
    </div>
  );
}

/* ================================================================== APP */
function App() {
  return <Dashboard operator="Operator" />;
}

/* ============================================================== DASHBOARD */
function Dashboard({ operator }: { operator: string }) {
  /* ---- personal data ---- */
  const [profile, setProfile] = useState<any>(null);
  const [showProfile, setShowProfile] = useState(false);
  const [vitals, setVitals] = useState<any[]>([]);
  const [moods, setMoods] = useState<any[]>([]);

  /* ---- monitoring: strictly off until the operator starts it ---- */
  const [monitoring, setMonitoring] = useState(false);
  const [session, setSession] = useState<Snapshot | null>(null);

  /* ---- NASA data ---- */
  const [apod, setApod] = useState<any>(null);
  const [standards, setStandards] = useState<any>(null);
  const [plan, setPlan] = useState<any>(null);
  const [planBusy, setPlanBusy] = useState(false);

  /* ---- wellbeing ---- */
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [chats, setChats] = useState<ChatMsg[]>([]);
  const [chatInput, setChatInput] = useState('');
  const [chatBusy, setChatBusy] = useState(false);
  const chatEnd = useRef<HTMLDivElement>(null);

  /* ---- check-in ---- */
  const [mood, setMood] = useState('good');
  const [sleep, setSleep] = useState('');
  const [stress, setStress] = useState('0');
  const [anxiety, setAnxiety] = useState('0');

  /* ---- vitals form ---- */
  const [logField, setLogField] = useState('heart_rate');
  const [logValue, setLogValue] = useState('');
  const [showVitalForm, setShowVitalForm] = useState(false);

  /* ---- UI ---- */
  const [activeNav, setActiveNav] = useState<NavKey>('dashboard');
  const [query, setQuery] = useState('');
  const [toast, setToast] = useState('');
  const [auditBusy, setAuditBusy] = useState(false);
  const [report, setReport] = useState<Report | null>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  const astroId = operator;
  const notify = (message: string) => setToast(message);

  useEffect(() => {
    if (!toast) return;
    const t = window.setTimeout(() => setToast(''), 3800);
    return () => window.clearTimeout(t);
  }, [toast]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        searchRef.current?.focus();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  /* ---------- initial load: real profile / standards / imagery only ---------- */
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const p = await fetch(`${API}/api/profile`, { credentials: 'include' }).then(r => (r.ok ? r.json() : null));
        if (!cancelled) setProfile(p);
      } catch { /* profile optional */ }
      fetch(`${API}/api/apod?date=${TODAY}`)
        .then(r => r.json())
        .then(d => { if (!cancelled) setApod(d); })
        .catch(() => {});
      fetch(`${API}/api/standards`)
        .then(r => r.json())
        .then(d => { if (!cancelled) setStandards(d); })
        .catch(() => {});
    })();
    return () => { cancelled = true; };
  }, []);

  const loadRecords = useCallback(async () => {
    try {
      const [vr, mr] = await Promise.all([
        fetch(`${API}/api/health/vitals?astronaut_id=${encodeURIComponent(astroId)}&limit=60`),
        fetch(`${API}/api/health/mood?astronaut_id=${encodeURIComponent(astroId)}&limit=60`),
      ]);
      if (vr.ok) setVitals(await vr.json());
      if (mr.ok) setMoods(await mr.json());
    } catch { /* cards stay at zero state */ }
  }, [astroId]);
  useEffect(() => { void loadRecords(); }, [loadRecords]);

  const loadAlerts = useCallback(async () => {
    try {
      const r = await fetch(`${API}/api/agent/alerts?astronaut_id=${encodeURIComponent(astroId)}`);
      if (r.ok) {
        const data = await r.json();
        setAlerts((data.alerts || []) as Alert[]);
      }
    } catch { /* advisory only */ }
  }, [astroId]);
  useEffect(() => {
    void loadAlerts();
    const t = window.setInterval(() => void loadAlerts(), 30000);
    return () => window.clearInterval(t);
  }, [loadAlerts]);

  /* ---------- stream only exists while monitoring is explicitly on ---------- */
  useEffect(() => {
    if (!monitoring) {
      setSession(null);
      return;
    }
    const es = new EventSource(`${API}/api/stream`);
    es.onmessage = e => {
      const s: Snapshot = JSON.parse(e.data);
      if (s.standby) {
        setMonitoring(false);
        return;
      }
      setSession(s);
    };
    es.onerror = () => setSession(null);
    return () => es.close();
  }, [monitoring]);

  const toggleMonitoring = async () => {
    try {
      if (monitoring) {
        await post('/api/session/stop');
        setMonitoring(false);
        setSession(null);
        setReport(null);
        notify('Telemetry session paused');
      } else {
        await post('/api/session/start');
        setMonitoring(true);
        notify('Telemetry session started');
      }
    } catch (e) {
      notify(msg(e, 'Session switch failed'));
    }
  };

  /* ---------- logging ---------- */
  const submitVital = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!logValue) return;
    const field = VITAL_META.find(f => f.field === logField);
    if (!field) return;
    const body: any = { astronaut_id: astroId, notes: '' };
    body[field.field] = Number(logValue);
    try {
      const saved = await post('/api/health/vitals', body);
      setVitals([saved, ...vitals]);
      setLogValue('');
      setShowVitalForm(false);
      notify(`${field.label} saved`);
      void loadAlerts();
    } catch (err) { notify(msg(err, 'Could not save reading')); }
  };

  const submitMood = async () => {
    const body: any = {
      astronaut_id: astroId,
      mood,
      sleep_hours: sleep ? Number(sleep) : null,
      stress_level: Number(stress),
      anxiety_level: Number(anxiety),
    };
    try {
      const saved = await post('/api/health/mood', body);
      setMoods([saved, ...moods]);
      setSleep('');
      notify('Wellbeing check-in saved');
      void loadAlerts();
    } catch (err) { notify(msg(err, 'Could not save check-in')); }
  };

  const saveProfile = async (e: React.FormEvent) => {
    e.preventDefault();
    const f = new FormData(e.target as HTMLFormElement);
    try {
      const saved = await post('/api/profile', {
        name: String(f.get('name') || ''),
        age: Number(f.get('age')) || null,
        sex: String(f.get('sex') || 'm'),
        height_cm: Number(f.get('height_cm')) || null,
        weight_kg: Number(f.get('weight_kg')) || null,
      });
      setProfile(saved);
      setShowProfile(false);
      notify('Profile updated');
      if (monitoring) void post('/api/session/start').catch(() => {});
    } catch (err) { notify(msg(err, 'Could not save profile')); }
  };

  const generatePlan = async () => {
    setPlanBusy(true);
    try {
      setPlan(await post('/api/diet/plan'));
      notify('NASA-derived plan built');
    } catch (err) { notify(msg(err, 'Could not build plan')); }
    finally { setPlanBusy(false); }
  };

  /* ---------- Gemini wellbeing assistant ---------- */
  const sendChat = async (e: React.FormEvent) => {
    e.preventDefault();
    const text = chatInput.trim();
    if (!text) return;
    setChats(c => [...c, { role: 'user', content: text }]);
    setChatInput('');
    setChatBusy(true);
    try {
      const out = await post('/api/chat', { astronaut_id: astroId, message: text });
      setChats(c => [...c, { role: 'assistant', content: out.reply, provider: out.provider }]);
    } catch (err) {
      setChats(c => [...c, { role: 'assistant', content: 'Comms dropped — try that again shortly.' }]);
      notify(msg(err, 'Assistant unavailable'));
    } finally { setChatBusy(false); }
  };
  useEffect(() => { chatEnd.current?.scrollIntoView({ behavior: 'smooth' }); }, [chats]);

  const runAudit = async () => {
    setAuditBusy(true);
    try {
      setReport(await post('/api/flight-surgeon/analyze'));
      notify('Flight-surgeon audit complete');
    } catch (err) { notify(msg(err, 'Audit failed')); }
    finally { setAuditBusy(false); }
  };

  /* ---------- derived ---------- */
  const name = profile?.name || operator.split('@')[0] || 'Operator';
  const hour = new Date().getHours();
  const greeting = hour < 5 ? 'Good night' : hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening';
  const missionDay = session ? Math.floor(session.mission_elapsed_s / 86400) : 0;
  const met = session
    ? `${String(Math.floor(session.mission_elapsed_s / 3600)).padStart(2, '0')}:${String(Math.floor((session.mission_elapsed_s % 3600) / 60)).padStart(2, '0')}`
    : '00:00';
  const today = new Date().toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long' });
  const initialsText = initials(name, operator);

  const telemetryValue = (key: string): number | null => {
    if (!monitoring || !session) return null;
    const v = session.telemetry?.[key];
    return typeof v === 'number' ? v : null;
  };

  const latestMood = moods[0];
  const sleepLatest = latest(moods, 'sleep_hours');
  const sleepHours = sleepLatest?.value ?? null;
  const sleepSeries = series(moods, 'sleep_hours');
  const sleepSlots: (number | null)[] = [
    ...Array(Math.max(0, 7 - sleepSeries.length)).fill(null),
    ...sleepSeries.slice(-7),
  ];
  const sleepEfficiency = sleepHours != null ? Math.round(clamp((sleepHours / 8) * 100)) : null;
  const circadian = telemetryValue('circadian_alignment_pct');
  const t = monitoring && session ? session.telemetry : null;

  const hrp = [
    {
      label: 'Orbital adaptation',
      value: monitoring && session ? (session.phase_label.split('·').pop() || '').trim() || 'Active' : '--',
      unit: '',
      note: monitoring ? 'Active phase' : 'Awaiting session',
      status: monitoring ? ('NOMINAL' as Level) : null,
    },
    {
      label: 'Muscle mass',
      value: '--',
      unit: 'kg',
      note: 'No scan on file',
      status: null,
    },
    {
      label: 'Fluid shift',
      value: t?.cephalad_fluid_shift_idx != null ? t.cephalad_fluid_shift_idx.toFixed(2) : '--',
      unit: 'idx',
      note: monitoring ? 'Cephalad shift' : 'Awaiting session',
      status: monitoring ? session?.status?.cephalad_fluid_shift_idx ?? 'NOMINAL' : null,
    },
    {
      label: 'Cognitive score',
      value: t?.circadian_alignment_pct != null ? t.circadian_alignment_pct.toFixed(0) : '--',
      unit: '%',
      note: monitoring ? 'Circadian alignment' : 'Awaiting session',
      status: monitoring ? session?.status?.circadian_alignment_pct ?? 'NOMINAL' : null,
    },
  ];

  const logEntries = [
    ...vitals.map(v => {
      const bits: string[] = [];
      if (v.heart_rate != null) bits.push(`HR ${v.heart_rate} BPM`);
      if (v.oxygen_saturation != null) bits.push(`SpO₂ ${v.oxygen_saturation}%`);
      if (v.body_temperature != null) bits.push(`Temp ${v.body_temperature}°C`);
      if (v.radiation_exposure != null) bits.push(`Radiation ${v.radiation_exposure} mSv`);
      return {
        id: `v-${v.id}`, kind: 'vital' as const, title: 'Vitals logged',
        detail: bits.join(' · ') || 'Reading saved', at: String(v.recorded_at || ''),
      };
    }),
    ...moods.map(m => {
      const bits = [`Mood ${m.mood}`];
      if (m.sleep_hours != null) bits.push(`Sleep ${m.sleep_hours} h`);
      if (m.stress_level != null) bits.push(`Stress ${m.stress_level}/10`);
      if (m.anxiety_level != null) bits.push(`Anxiety ${m.anxiety_level}/10`);
      return {
        id: `m-${m.id}`, kind: 'mood' as const, title: 'Wellbeing check-in',
        detail: bits.join(' · '), at: String(m.recorded_at || ''),
      };
    }),
  ].sort((a, b) => new Date(b.at).getTime() - new Date(a.at).getTime());

  const q = query.trim().toLowerCase();
  const visibleLogs = (q
    ? logEntries.filter(e => `${e.title} ${e.detail}`.toLowerCase().includes(q))
    : logEntries
  ).slice(0, 6);

  const visibleAlerts = alerts
    .filter(a => monitoring || a.source !== 'simulated mission telemetry')
    .filter(a => !q || `${a.title} ${a.message} ${a.action || ''}`.toLowerCase().includes(q))
    .slice(0, 3);

  const filteredGroups = (standards?.groups || [])
    .map((g: any) => ({
      ...g,
      items: (g.items || []).filter((it: any) =>
        !q || `${it.label} ${it.target} ${it.source || ''}`.toLowerCase().includes(q),
      ),
    }))
    .filter((g: any) => g.items.length > 0);

  const go = (key: NavKey) => {
    setActiveNav(key);
    document.getElementById(key)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  const navItems: { key: NavKey; label: string; icon: string; badge: number }[] = [
    { key: 'dashboard', label: 'Dashboard', icon: 'grid', badge: visibleAlerts.length },
    { key: 'vitals', label: 'Vitals & Labs', icon: 'activity', badge: vitals.length },
    { key: 'wellbeing', label: 'AI Wellbeing', icon: 'sparkles', badge: chats.length },
    { key: 'standards', label: 'NASA Standards', icon: 'book', badge: standards?.rows?.length ?? 0 },
    { key: 'logs', label: 'Mission Logs', icon: 'list', badge: logEntries.length },
  ];

  return (
    <div className="app-frame">
      {/* ===================================================== sidebar */}
      <aside className="sidebar">
        <div className="logo">
          <span className="logo-mark"><Icon name="activity" size={20} /></span>
          <div>
            <b>AEGIS<span>·</span>HRP</b>
            <small>Crew health OS</small>
          </div>
        </div>

        <nav className="nav" aria-label="Primary">
          {navItems.map(item => (
            <button
              key={item.key}
              className={`nav-link ${activeNav === item.key ? 'active' : ''}`}
              onClick={() => go(item.key)}
            >
              <Icon name={item.icon} />
              <span>{item.label}</span>
              <em className="nav-badge">{item.badge}</em>
            </button>
          ))}
        </nav>

        <div className="sidebar-foot">
          <div className="ready-card">
            <span className="ready-kicker">Mission readiness</span>
            <h3>Pro telemetry</h3>
            <p className="ready-meta">
              {monitoring ? `Streaming · T+${met}` : 'Standby · zero-state'}
            </p>
            <button className="ready-cta" onClick={() => void toggleMonitoring()}>
              <span>{monitoring ? 'Pause session' : 'Start session'}</span>
              <Icon name={monitoring ? 'pause' : 'play'} size={15} />
            </button>
          </div>
          <p className="sidebar-note">NASA Space Apps · HRP evidence base</p>
        </div>
      </aside>

      {/* ===================================================== canvas */}
      <main className="canvas">
        <header className="topbar">
          <button className="profile-pill" onClick={() => setShowProfile(v => !v)} aria-expanded={showProfile}>
            <span className="avatar">{initialsText}</span>
            <span className="profile-meta">
              <strong>{name}</strong>
              <small>Crew operator</small>
            </span>
            <span className="chev"><Icon name="chevron" size={16} /></span>
          </button>

          <label className="search-pill">
            <Icon name="search" size={17} />
            <input
              ref={searchRef}
              value={query}
              onChange={e => setQuery(e.target.value)}
              placeholder="Search metrics, logs, standards"
              aria-label="Search"
            />
            <kbd>⌘K</kbd>
          </label>
        </header>

        {showProfile && (
          <section className="profile-panel">
            <form onSubmit={saveProfile}>
              <div className="profile-panel-head">
                <div>
                  <h2>Your profile</h2>
                  <p>Personalises every target, plan and greeting. NASA standards scale to your body.</p>
                </div>
              </div>
              <div className="profile-grid">
                <label className="field"><span>Name</span><input name="name" defaultValue={profile?.name || ''} maxLength={60} /></label>
                <label className="field"><span>Age</span><input name="age" type="number" min="18" max="70" defaultValue={profile?.age ?? ''} /></label>
                <label className="field">
                  <span>Sex</span>
                  <select name="sex" defaultValue={profile?.sex || 'm'}>
                    <option value="m">Male</option>
                    <option value="f">Female</option>
                  </select>
                </label>
                <label className="field"><span>Height (cm)</span><input name="height_cm" type="number" step="0.5" defaultValue={profile?.height_cm ?? ''} /></label>
                <label className="field"><span>Weight (kg)</span><input name="weight_kg" type="number" step="0.5" defaultValue={profile?.weight_kg ?? ''} /></label>
              </div>
              <div className="profile-submit">
                <button className="btn" type="submit">Save profile</button>
                <span className="muted-copy">Used for BMR, meal split and countermeasure targets.</span>
              </div>
            </form>
          </section>
        )}

        {/* ================================================= greeting */}
        <section className="greeting" id="dashboard">
          <div className="greeting-row">
            <div>
              <span className="eyebrow">Crew health overview</span>
              <h1>{greeting}, {name}.</h1>
              <p>{today} <span className="dot-sep">·</span> Mission day {missionDay}</p>
            </div>
            <div className="greeting-status">
              <span className={`pill ${monitoring ? 'live' : ''}`}>
                <i className="dot" />
                {monitoring ? 'Monitoring live' : 'Monitoring off'}
              </span>
              <span className="pill">NASA HRP</span>
            </div>
          </div>
        </section>

        {/* ================================================= bento */}
        <div className="bento">
          {/* ---------------------------------------- vitals */}
          <section className="card span-8" id="vitals">
            <CardHead
              title="Live vitals"
              sub="Logged readings stay yours. Live telemetry only appears after you start a session."
              right={
                <div className="head-actions">
                  <span className={`pill ${monitoring ? 'live' : ''}`}>
                    <i className="dot" />{monitoring ? 'Live' : 'Zero-state'}
                  </span>
                  <button className="btn ghost small" onClick={() => setShowVitalForm(v => !v)}>
                    <Icon name="plus" size={14} /> Log reading
                  </button>
                </div>
              }
            />

            <div className="vital-grid">
              {VITAL_META.map(meta => {
                const logged = latest(vitals, meta.field);
                const live = telemetryValue(meta.telemetry);
                const value = logged ? logged.value : live;
                const fromLive = !logged && live !== null;
                const loggedSeries = series(vitals, meta.field);
                const liveSeries = fromLive && session?.history
                  ? session.history
                      .map(h => h.telemetry?.[meta.telemetry])
                      .filter((v): v is number => typeof v === 'number')
                      .slice(-7)
                  : [];
                const values = loggedSeries.length ? loggedSeries : liveSeries;
                const display = value == null ? '--' : value.toFixed(meta.decimals);
                const pct = value == null ? 0 : ((value - meta.min) / (meta.max - meta.min)) * 100;
                return (
                  <article className="vital-tile" key={meta.field}>
                    <div className="vital-top">
                      <span className="vital-label"><Icon name={meta.icon} size={14} />{meta.label}</span>
                      <span className={`mini-pill ${fromLive ? 'live' : ''}`}>
                        {fromLive ? 'Live' : logged ? 'Logged' : 'No data'}
                      </span>
                    </div>
                    <div className="vital-main">
                      <Ring pct={pct} tone={meta.tone}>
                        <b>{display}</b>
                        <small>{meta.unit}</small>
                      </Ring>
                      <Spark values={values} tone={meta.tone} />
                    </div>
                    <div className="vital-foot">
                      {fromLive
                        ? 'Live session · simulated telemetry'
                        : logged
                          ? `Last logged ${fmtTime(logged.at)}`
                          : 'Log your first reading'}
                    </div>
                  </article>
                );
              })}
            </div>

            {showVitalForm && (
              <form className="inline-form" onSubmit={submitVital}>
                <select value={logField} onChange={e => setLogField(e.target.value)} aria-label="Vital type">
                  {VITAL_META.map(f => <option key={f.field} value={f.field}>{f.label} ({f.unit})</option>)}
                </select>
                <input type="number" step="any" placeholder="Value" value={logValue} onChange={e => setLogValue(e.target.value)} aria-label="Vital value" />
                <button className="btn lime small" type="submit">Save reading</button>
              </form>
            )}
          </section>

          {/* ---------------------------------------- sleep (dark) */}
          <section className="card dark span-4">
            <CardHead
              title="Sleep & circadian"
              sub="NASA 8-hour sleep opportunity"
              right={<span className="pill">{sleepLatest ? 'Logged' : 'No data'}</span>}
            />
            <div className="sleep-big">
              {fmtDuration(sleepHours)}
              <small>last night</small>
            </div>
            <div className="sleep-meta">
              <div>
                <span>Sleep efficiency</span>
                <b>{sleepEfficiency != null ? `${sleepEfficiency}%` : '--%'}</b>
              </div>
              <div>
                <span>Circadian alignment</span>
                <b>{circadian != null ? `${circadian.toFixed(0)}%` : '--%'}</b>
              </div>
            </div>
            <div className="sleep-bars" aria-hidden="true">
              {sleepSlots.map((v, i) => (
                <i
                  key={i}
                  className={v == null ? 'empty' : ''}
                  style={{ height: `${v == null ? 10 : Math.max(10, Math.min(100, (v / 12) * 100))}%` }}
                />
              ))}
            </div>
            <div className="sleep-foot">
              {sleepLatest ? `Last check-in ${fmtTime(sleepLatest.at)}` : 'Log sleep in your wellbeing check-in'}
            </div>
          </section>

          {/* ---------------------------------------- NASA standards */}
          <section className="card span-5">
            <CardHead
              title="NASA standards"
              sub="Orbital adaptation & HRP targets"
              right={<span className="pill">NASA HRP</span>}
            />
            <div className="hrp-grid">
              {hrp.map(item => (
                <div className="hrp-tile" key={item.label}>
                  <span>{item.label}</span>
                  <b>{item.value}<em>{item.unit}</em></b>
                  <StatusPill level={item.status} />
                  <small>{item.note}</small>
                </div>
              ))}
            </div>

            {plan ? (
              <>
                <div className="target-strip">
                  <div className="target-chip"><b>{plan.targets.energy_kcal}</b><span>kcal</span></div>
                  <div className="target-chip"><b>{plan.targets.protein_g}</b><span>g protein</span></div>
                  <div className="target-chip"><b>{plan.targets.water_l}</b><span>L water</span></div>
                  <div className="target-chip"><b>{plan.targets.sleep_h}</b><span>h sleep</span></div>
                </div>
                <div className="card-actions">
                  <button className="btn ghost small" onClick={() => void generatePlan()} disabled={planBusy}>
                    {planBusy ? 'Building…' : 'Rebuild plan'}
                  </button>
                  <button className="link-btn" onClick={() => go('standards')}>Full standards <Icon name="arrow" size={14} /></button>
                </div>
              </>
            ) : (
              <div className="plan-cta">
                <p>Personalised nutrition and countermeasure targets from NASA-STD-3001 and HRP evidence.</p>
                <button className="btn lime" onClick={() => void generatePlan()} disabled={planBusy}>
                  {planBusy ? 'Building…' : 'Build my plan'}
                  <Icon name="arrow" size={15} />
                </button>
              </div>
            )}
            <p className="card-source">
              NASA-STD-3001 Vol. 2 · Human Research Program nutrition, bone and behavioral health evidence.
            </p>
          </section>

          {/* ---------------------------------------- AI wellbeing */}
          <section className="card span-7" id="wellbeing">
            <CardHead
              title="Mind & wellbeing"
              sub="Private AI check-in and mood tracking"
              right={<span className="pill dark"><Icon name="sparkles" size={13} /> Gemini</span>}
            />

            <div className="mood-row" role="group" aria-label="Mood">
              {MOODS.map(m => (
                <button
                  key={m.value}
                  className={`mood-pill ${mood === m.value ? 'on' : ''}`}
                  onClick={() => setMood(m.value)}
                  type="button"
                >
                  <i className="dot" style={{ background: m.color }} />
                  {m.label}
                </button>
              ))}
            </div>

            <div className="slider-grid">
              <div className="slider">
                <label>Stress <b>{stress}/10</b></label>
                <input
                  type="range" min="0" max="10" step="1" value={stress}
                  onChange={e => setStress(e.target.value)}
                  style={{ '--fill': `${Number(stress) * 10}%` } as React.CSSProperties}
                />
              </div>
              <div className="slider">
                <label>Anxiety <b>{anxiety}/10</b></label>
                <input
                  type="range" min="0" max="10" step="1" value={anxiety}
                  onChange={e => setAnxiety(e.target.value)}
                  style={{ '--fill': `${Number(anxiety) * 10}%` } as React.CSSProperties}
                />
              </div>
            </div>

            <div className="checkin-row">
              <label className="sleep-field">
                <span>Sleep last night</span>
                <div className="sleep-input">
                  <input type="number" step="0.5" min="0" max="24" placeholder="0" value={sleep} onChange={e => setSleep(e.target.value)} />
                  <em>h</em>
                </div>
              </label>
              <button className="btn" onClick={() => void submitMood()}>
                <Icon name="check" size={15} /> Save check-in
              </button>
              <span className="muted-copy">Today&apos;s latest: {latestMood ? latestMood.mood : '--'}</span>
            </div>

            <div className="chat-box">
              <div className="chat-scroll">
                {chats.length === 0 && (
                  <p className="chat-empty">
                    Talk about how the mission feels — sleep, isolation, stress, anything. OrbitWatch listens,
                    never diagnoses, and points you to the flight surgeon for anything urgent.
                  </p>
                )}
                {chats.map((m, i) => (
                  <div className={`bubble ${m.role === 'user' ? 'user' : 'ai'}`} key={i}>
                    <span className="who">
                      {m.role === 'user' ? name : `OrbitWatch${m.provider === 'gemini' ? ' · Gemini' : ''}`}
                    </span>
                    {m.content}
                  </div>
                ))}
                {chatBusy && <div className="bubble ai"><span className="who">OrbitWatch</span>Thinking…</div>}
                <div ref={chatEnd} />
              </div>
              <form className="chat-form" onSubmit={sendChat}>
                <input
                  value={chatInput}
                  onChange={e => setChatInput(e.target.value)}
                  placeholder="What's on your mind?"
                  disabled={chatBusy}
                  maxLength={2000}
                  aria-label="Message the wellbeing assistant"
                />
                <button type="submit" disabled={chatBusy || !chatInput.trim()} aria-label="Send message">
                  <Icon name="send" size={16} />
                </button>
              </form>
              <p className="safety-note">
                If you feel unsafe or have urgent symptoms, contact mission control and the flight surgeon now.
              </p>
            </div>
          </section>

          {/* ---------------------------------------- plan */}
          <section className="card span-7 plan-card">
            <CardHead
              title="Personal plan"
              sub="NASA-derived nutrition & countermeasures"
              right={<span className="pill">{plan ? 'Ready' : 'Not built'}</span>}
            />
            {plan ? (
              <>
                <div className="plan-stats">
                  <div className="plan-stat"><b>{plan.targets.energy_kcal}</b><span>kcal / day</span></div>
                  <div className="plan-stat"><b>{plan.targets.protein_g}</b><span>g protein</span></div>
                  <div className="plan-stat"><b>{plan.targets.carbohydrate_g}</b><span>g carbs</span></div>
                  <div className="plan-stat"><b>{plan.targets.water_l}</b><span>L water</span></div>
                </div>
                <div className="meal-preview">
                  {plan.meals.slice(0, 3).map((m: any) => (
                    <div className="meal-row" key={m.meal}>
                      <b>{m.meal}</b>
                      <span>{m.kcal} kcal</span>
                      <em>{m.focus}</em>
                    </div>
                  ))}
                </div>
                {plan.gemini_note && <p className="plan-note">{plan.gemini_note}</p>}
                <div className="card-actions">
                  <button className="btn ghost small" onClick={() => void generatePlan()} disabled={planBusy}>
                    {planBusy ? 'Building…' : 'Regenerate'}
                  </button>
                  <button className="link-btn" onClick={() => go('standards')}>Meals & exercise week <Icon name="arrow" size={14} /></button>
                </div>
              </>
            ) : (
              <div className="plan-empty">
                <div>
                  <h3>Your daily targets, not a template.</h3>
                  <p>
                    Built from your profile with Mifflin-St Jeor BMR and published NASA standards. Gemini may
                    polish the wording but never invents the numbers.
                  </p>
                </div>
                <button className="btn" onClick={() => void generatePlan()} disabled={planBusy}>
                  {planBusy ? 'Building…' : 'Build my plan'}
                  <Icon name="arrow" size={15} />
                </button>
              </div>
            )}
          </section>

          {/* ---------------------------------------- logs */}
          <section className="card span-5" id="logs">
            <CardHead
              title="Mission logs"
              sub="Your latest check-ins and alerts"
              right={<span className="pill">{logEntries.length}</span>}
            />
            {visibleAlerts.length > 0 && (
              <div className="alert-list">
                {visibleAlerts.map(a => (
                  <div className={`alert-row ${a.level.toLowerCase()}`} key={a.id}>
                    <Icon name="alert" size={15} />
                    <div>
                      <b>{a.title}</b>
                      <span>{a.message}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
            <div className="log-list">
              {visibleLogs.length === 0 && (
                <p className="empty-note">No entries yet. Log a reading or save a wellbeing check-in to start your log.</p>
              )}
              {visibleLogs.map(entry => (
                <div className="log-item" key={entry.id}>
                  <span className={`log-dot ${entry.kind}`} />
                  <div className="log-copy">
                    <b>{entry.title}</b>
                    <span>{entry.detail}</span>
                  </div>
                  <time>{fmtTime(entry.at)}</time>
                </div>
              ))}
            </div>

            <div className="audit">
              <button className="btn ghost small" onClick={() => void runAudit()} disabled={auditBusy || !monitoring}>
                <Icon name="activity" size={15} />
                {auditBusy ? 'Analyzing…' : 'Flight-surgeon audit'}
              </button>
              {!monitoring && <span className="muted-copy">Start a session to run the audit.</span>}
            </div>

            {report && (
              <div className="report">
                <div className="report-top">
                  <StatusPill level={report.risk_level} />
                  <span className="pill">EVA {report.eva_status}</span>
                </div>
                <p>{report.physiological_mechanism}</p>
                <ul>{report.countermeasures.map(c => <li key={c}>{c}</li>)}</ul>
                <small>{report.nasa_reference_citation}</small>
              </div>
            )}
          </section>

          {/* ---------------------------------------- live session controls */}
          {monitoring && (
            <section className="card span-12 session-card">
              <CardHead
                title="Active telemetry session"
                sub={`T+${met} · ${session?.phase_label || 'Connecting…'} · simulated demo stream`}
                right={<span className="pill live"><i className="dot" />Streaming</span>}
              />
              <div className="session-tools">
                <select
                  value={session?.phase || 'ORBITAL_ADAPTATION_W2_W12'}
                  onChange={e => void post(`/api/phase/${e.target.value}`)}
                  aria-label="Mission phase"
                >
                  {PHASES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                </select>
                {ANOMALIES.map(([v, l]) => (
                  <button
                    key={v}
                    className={`chip-btn ${session?.anomaly === v ? 'on' : ''}`}
                    onClick={() => void post(`/api/anomaly/${v}`)}
                  >
                    {l}
                  </button>
                ))}
              </div>
              <div className="live-grid">
                {Object.entries(session?.telemetry || {}).map(([key, value]) => {
                  const status = session?.status?.[key] || 'NOMINAL';
                  const label = key.replace(/_/g, ' ').replace(/^./, c => c.toUpperCase());
                  return (
                    <div className="live-item" key={key}>
                      <span>{label}</span>
                      <b>{value.toFixed(1)}</b>
                      <StatusPill level={status} />
                    </div>
                  );
                })}
              </div>
            </section>
          )}
        </div>

        {/* ================================================= standards library */}
        <section className="section" id="standards">
          <div className="section-head">
            <div>
              <span className="eyebrow">NASA-STD-3001 · HRP evidence base</span>
              <h2>Standards library</h2>
            </div>
            <span className="pill">{standards?.rows?.length ?? 0} cited targets</span>
          </div>

          {q && (
            <p className="filter-note">
              Filtering by <b>“{query}”</b> — {filteredGroups.length} matching group(s).
            </p>
          )}

          <div className="std-groups">
            {filteredGroups.map((group: any) => (
              <article className="std-group" key={group.group}>
                <h3>{group.group}</h3>
                {group.items.map((it: any) => (
                  <div className="std-item" key={it.label}>
                    <div className="std-row">
                      <span>{it.label}</span>
                      <b>{it.target}</b>
                    </div>
                    <small>{it.source}</small>
                  </div>
                ))}
              </article>
            ))}
            {standards && filteredGroups.length === 0 && (
              <p className="empty-note">No standards match “{query}”.</p>
            )}
          </div>

          {plan && (
            <div className="full-plan">
              <div className="section-head tight">
                <div>
                  <span className="eyebrow">Personal output</span>
                  <h2>Daily meals & exercise week</h2>
                </div>
                <span className="pill">BMR {plan.bmr_kcal} kcal</span>
              </div>
              <div className="full-plan-grid">
                <div className="full-plan-col">
                  <h3>Meals</h3>
                  {plan.meals.map((m: any) => (
                    <div className="meal-row" key={m.meal}>
                      <b>{m.meal}</b><span>{m.kcal} kcal</span><em>{m.focus}</em>
                    </div>
                  ))}
                </div>
                <div className="full-plan-col">
                  <h3>Exercise week</h3>
                  {plan.exercise_week.map((x: any) => (
                    <div className="meal-row" key={x.day}>
                      <b>{x.day}</b><em>{x.plan}</em>
                    </div>
                  ))}
                  <h3 className="mt">Countermeasure targets</h3>
                  <div className="target-strip">
                    <div className="target-chip"><b>{plan.targets.calcium_mg}</b><span>mg calcium</span></div>
                    <div className="target-chip"><b>{plan.targets.vitamin_d_iu}</b><span>IU vit D</span></div>
                    <div className="target-chip"><b>{plan.targets.sodium_mg_max}</b><span>mg sodium max</span></div>
                    <div className="target-chip"><b>{plan.targets.exercise_min}</b><span>min exercise</span></div>
                  </div>
                </div>
              </div>
              {plan.space_weather_note && <p className="plan-warn">{plan.space_weather_note}</p>}
              <p className="plan-source">Grounded in {plan.nasa_sources.join(' · ')}. {plan.disclaimer}</p>
            </div>
          )}

          {apod?.url && apod.media_type === 'image' && (
            <figure className="apod-card">
              <img src={apod.hdurl || apod.url} alt={apod.title} loading="lazy" />
              <figcaption>
                <span>NASA imagery</span>
                <b>{apod.title}</b>
                <em>Astronomy Picture of the Day · {apod.date}</em>
              </figcaption>
            </figure>
          )}
        </section>

        <footer className="foot">
          <span>AEGIS-HRP · NASA Space Apps</span>
          <span>NASA-STD-3001 · HRP evidence base</span>
          <span>Zero-state by default · telemetry is opt-in and simulated</span>
        </footer>
      </main>

      {toast && <div className="toast" role="status">{toast}</div>}
    </div>
  );
}

createRoot(document.getElementById('root')!).render(<App />);
