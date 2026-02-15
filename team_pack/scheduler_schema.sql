-- Scheduler schema (Supabase/PostgreSQL)

create table if not exists public.sched_lines (
  line_id text primary key,
  created_at timestamptz not null default now()
);

create table if not exists public.sched_orders (
  order_id text primary key,
  code text not null,
  qty bigint not null check (qty >= 0),
  due_date date,
  due_serial bigint,
  created_at timestamptz not null default now()
);

create table if not exists public.sched_eligible_lines (
  order_id text not null references public.sched_orders(order_id) on delete cascade,
  line_id text not null references public.sched_lines(line_id) on delete cascade,
  primary key (order_id, line_id)
);

create table if not exists public.sched_cycle_times (
  code text not null,
  line_id text not null references public.sched_lines(line_id) on delete cascade,
  cycle_min_per_piece numeric(12, 3) not null check (cycle_min_per_piece > 0),
  primary key (code, line_id)
);

create table if not exists public.sched_current_config (
  line_id text primary key references public.sched_lines(line_id) on delete cascade,
  current_code text,
  loaded_qty bigint not null default 0 check (loaded_qty >= 0),
  updated_at timestamptz not null default now()
);

create table if not exists public.sched_setup_from_current (
  line_id text not null references public.sched_lines(line_id) on delete cascade,
  to_code text not null,
  setup_min numeric(12, 2) not null check (setup_min >= 0),
  primary key (line_id, to_code)
);

create table if not exists public.sched_setup_between_codes (
  from_code text not null,
  to_code text not null,
  setup_min numeric(12, 2) not null check (setup_min >= 0),
  primary key (from_code, to_code)
);

create table if not exists public.sched_runs (
  run_id bigserial primary key,
  strategy text not null check (strategy in ('due_date', 'min_setup', 'balanced', 'manual')),
  created_at timestamptz not null default now(),
  total_orders bigint not null default 0 check (total_orders >= 0),
  scheduled_orders bigint not null default 0 check (scheduled_orders >= 0),
  unscheduled_orders bigint not null default 0 check (unscheduled_orders >= 0),
  total_tardy_min numeric(12, 2) not null default 0 check (total_tardy_min >= 0),
  total_setup_min numeric(12, 2) not null default 0 check (total_setup_min >= 0),
  makespan_min numeric(12, 2) not null default 0 check (makespan_min >= 0),
  avg_completion_min numeric(12, 2) not null default 0 check (avg_completion_min >= 0)
);

create table if not exists public.sched_tasks (
  task_id bigserial primary key,
  run_id bigint not null references public.sched_runs(run_id) on delete cascade,
  order_id text not null references public.sched_orders(order_id) on delete cascade,
  code text not null,
  line_id text not null references public.sched_lines(line_id) on delete cascade,
  qty bigint not null check (qty >= 0),
  setup_min numeric(12, 2) not null check (setup_min >= 0),
  start_min numeric(12, 2) not null check (start_min >= 0),
  end_min numeric(12, 2) not null check (end_min >= start_min),
  tardy_min numeric(12, 2) not null check (tardy_min >= 0),
  due_date date
);

create table if not exists public.sched_unscheduled (
  unscheduled_id bigserial primary key,
  run_id bigint not null references public.sched_runs(run_id) on delete cascade,
  order_id text not null references public.sched_orders(order_id) on delete cascade,
  code text not null,
  qty bigint not null check (qty >= 0),
  reason text not null
);

create index if not exists idx_sched_tasks_run_id on public.sched_tasks(run_id);
create index if not exists idx_sched_tasks_line_id on public.sched_tasks(line_id);
create index if not exists idx_sched_tasks_order_id on public.sched_tasks(order_id);
create index if not exists idx_sched_unscheduled_run_id on public.sched_unscheduled(run_id);
