-- OrbitWatch — Astronaut Health Monitor schema
-- Apply this in the Supabase SQL Editor.

-- Saved NASA discoveries (APOD)
create table if not exists public.saved_discoveries (
  id bigint generated always as identity primary key,
  date date not null unique,
  title text not null,
  url text,
  explanation text,
  created_at timestamptz not null default now()
);

-- Astronaut physical vitals
create table if not exists public.astronaut_vitals (
  id bigint generated always as identity primary key,
  astronaut_id text not null,
  recorded_at timestamptz not null default now(),
  heart_rate integer,
  blood_pressure_systolic integer,
  blood_pressure_diastolic integer,
  oxygen_saturation numeric,
  body_temperature numeric,
  radiation_exposure numeric,
  notes text
);

-- Mental health / mood check-ins
create table if not exists public.mood_logs (
  id bigint generated always as identity primary key,
  astronaut_id text not null,
  recorded_at timestamptz not null default now(),
  mood text check (mood in ('great','good','neutral','poor','critical')),
  stress_level integer check (stress_level between 0 and 10),
  anxiety_level integer check (anxiety_level between 0 and 10),
  sleep_hours numeric,
  notes text
);

-- AI assistant conversation history
create table if not exists public.chat_messages (
  id bigint generated always as identity primary key,
  astronaut_id text not null,
  role text not null,
  content text not null,
  created_at timestamptz not null default now()
);

-- Indexes for common queries
create index if not exists idx_vitals_astro_time on public.astronaut_vitals(astronaut_id, recorded_at desc);
create index if not exists idx_mood_astro_time on public.mood_logs(astronaut_id, recorded_at desc);
create index if not exists idx_chat_astro_time on public.chat_messages(astronaut_id, created_at asc);

-- Row Level Security
alter table public.saved_discoveries enable row level security;
alter table public.astronaut_vitals enable row level security;
alter table public.mood_logs enable row level security;
alter table public.chat_messages enable row level security;

-- The backend calls Supabase with the service key, which bypasses RLS.
-- Uncomment the permissive policies below only if you call Supabase directly from the browser
-- with the anon key. Never put the service key in the frontend.

-- create policy "Public read" on public.saved_discoveries for select using (true);
-- create policy "Public insert" on public.saved_discoveries for insert with check (true);
-- create policy "Public read" on public.astronaut_vitals for select using (true);
-- create policy "Public insert" on public.astronaut_vitals for insert with check (true);
-- create policy "Public read" on public.mood_logs for select using (true);
-- create policy "Public insert" on public.mood_logs for insert with check (true);
-- create policy "Public read" on public.chat_messages for select using (true);
-- create policy "Public insert" on public.chat_messages for insert with check (true);
