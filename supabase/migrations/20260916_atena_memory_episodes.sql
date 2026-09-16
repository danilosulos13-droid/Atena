create table if not exists public.atena_memory_episodes (
  memory_id text primary key,
  sequence bigint,
  record_type text not null,
  task_id text not null,
  domain text not null,
  created_at timestamptz not null,
  content_hash text not null,
  status text not null,
  confidence double precision not null,
  record jsonb not null,
  source_type text,
  source_id text,
  source_url text,
  model text,
  model_digest text,
  system_version text,
  workflow_run_id text,
  verification_method text,
  synced_at timestamptz not null default now()
);

create unique index if not exists atena_memory_episodes_content_hash_idx
  on public.atena_memory_episodes (content_hash);

create index if not exists atena_memory_episodes_source_url_idx
  on public.atena_memory_episodes (source_url);

alter table public.atena_memory_episodes enable row level security;

comment on table public.atena_memory_episodes is 'ATENA episodic memory synchronized from the validated SQLite chain.';
