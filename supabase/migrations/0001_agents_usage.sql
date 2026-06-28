-- Agents + usage events for multi-tenant SaaS control plane.
-- Server uses service-role connection (bypasses RLS); policies are defense-in-depth
-- for any anon/PostgREST access.

create extension if not exists pgcrypto;

create table agents (
    id uuid primary key default gen_random_uuid(),
    owner_id uuid not null,
    slug text not null,
    config jsonb not null,
    template_id text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (owner_id, slug)
);

create table usage_events (
    id bigint generated always as identity primary key,
    owner_id uuid not null,
    agent_id uuid references agents(id) on delete set null,
    session_id text,
    model text,
    tokens_in int,
    tokens_out int,
    tokens_total int,
    cache_read int,
    tool_hops int,
    duration_ms int,
    status text,
    created_at timestamptz not null default now()
);

create index usage_events_owner_created_idx on usage_events (owner_id, created_at);

alter table agents enable row level security;
alter table usage_events enable row level security;

create policy agents_owner_select on agents for select using (owner_id = auth.uid());
create policy agents_owner_insert on agents for insert with check (owner_id = auth.uid());
create policy agents_owner_update on agents for update using (owner_id = auth.uid());
create policy agents_owner_delete on agents for delete using (owner_id = auth.uid());

create policy usage_events_owner_select on usage_events for select using (owner_id = auth.uid());
create policy usage_events_owner_insert on usage_events for insert with check (owner_id = auth.uid());
create policy usage_events_owner_update on usage_events for update using (owner_id = auth.uid());
create policy usage_events_owner_delete on usage_events for delete using (owner_id = auth.uid());
