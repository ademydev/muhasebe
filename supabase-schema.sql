-- Hesap · Supabase cloud state (safe to run more than once)
-- Run this script in Supabase Dashboard → SQL Editor after checking whether
-- public.hesap_user_states already exists. This script never drops rows/tables.
create table if not exists public.hesap_user_states (
  user_id uuid primary key references auth.users(id) on delete cascade,
  state jsonb not null default '{"version":1,"accounts":[],"transactions":[],"debts":[],"debt_payments":[],"receivables":[],"collections":[],"categories":[],"applied_imports":[]}'::jsonb,
  revision integer not null default 1 check (revision > 0),
  updated_at timestamptz not null default now(),
  constraint hesap_state_shape check (
    jsonb_typeof(state) = 'object'
    and state->>'version' = '1'
    and jsonb_typeof(state->'accounts') = 'array'
    and jsonb_typeof(state->'transactions') = 'array'
    and jsonb_typeof(state->'debts') = 'array'
    and jsonb_typeof(state->'debt_payments') = 'array'
    and jsonb_typeof(state->'receivables') = 'array'
    and jsonb_typeof(state->'collections') = 'array'
    and jsonb_typeof(state->'categories') = 'array'
    and jsonb_typeof(state->'applied_imports') = 'array'
  )
);

alter table public.hesap_user_states enable row level security;
grant select, insert, update on public.hesap_user_states to authenticated;

-- Install each policy only if it is not already present; never remove existing policies.
do $$ begin
  if not exists (select 1 from pg_policies where schemaname='public' and tablename='hesap_user_states' and policyname='hesap_state_select_own') then
    create policy hesap_state_select_own on public.hesap_user_states for select to authenticated using (auth.uid() = user_id);
  end if;
  if not exists (select 1 from pg_policies where schemaname='public' and tablename='hesap_user_states' and policyname='hesap_state_insert_own') then
    create policy hesap_state_insert_own on public.hesap_user_states for insert to authenticated with check (auth.uid() = user_id);
  end if;
  if not exists (select 1 from pg_policies where schemaname='public' and tablename='hesap_user_states' and policyname='hesap_state_update_own') then
    create policy hesap_state_update_own on public.hesap_user_states for update to authenticated using (auth.uid() = user_id) with check (auth.uid() = user_id);
  end if;
end $$;

-- Realtime is used only to notify other signed-in devices about newer revisions.
do $$ begin
  if exists (select 1 from pg_publication where pubname='supabase_realtime')
     and not exists (select 1 from pg_publication_tables where pubname='supabase_realtime' and schemaname='public' and tablename='hesap_user_states') then
    alter publication supabase_realtime add table public.hesap_user_states;
  end if;
end $$;
