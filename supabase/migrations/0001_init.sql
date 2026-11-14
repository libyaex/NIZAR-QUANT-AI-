-- NIZAR QUANT AI — initial schema (creates new tables only, no destructive changes)
-- Requires approval: run in Supabase SQL editor before first deploy.

create extension if not exists "uuid-ossp";

-- Application state per user (engine/trading flags, persisted across restarts)
create table if not exists public.app_state (
    id uuid primary key default uuid_generate_v4(),
    user_id uuid not null references auth.users(id) on delete cascade,
    trading_active boolean not null default false,
    state text not null default 'trading_stopped',
    updated_at timestamptz not null default now(),
    unique (user_id)
);

-- Exchange API configs (secrets encrypted server-side; never returned to clients)
create table if not exists public.exchange_configs (
    id uuid primary key default uuid_generate_v4(),
    user_id uuid not null references auth.users(id) on delete cascade,
    exchange text not null check (exchange in ('binance','mexc','bybit','okx','bitget')),
    label text not null default 'default',
    product text not null default 'futures' check (product in ('spot','futures')),
    testnet boolean not null default false,
    api_key_enc text not null,
    secret_enc text not null,
    password_enc text,
    connected boolean not null default false,
    last_error text,
    created_at timestamptz not null default now()
);

-- User settings (risk + scanner configuration as JSON)
create table if not exists public.user_settings (
    id uuid primary key default uuid_generate_v4(),
    user_id uuid not null references auth.users(id) on delete cascade,
    risk_settings jsonb not null default '{}'::jsonb,
    scanner_settings jsonb not null default '{}'::jsonb,
    updated_at timestamptz not null default now(),
    unique (user_id)
);

-- Profit missions
create table if not exists public.profit_missions (
    id uuid primary key default uuid_generate_v4(),
    user_id uuid not null references auth.users(id) on delete cascade,
    starting_capital numeric not null check (starting_capital > 0),
    target_capital numeric not null check (target_capital > starting_capital),
    realized_profit numeric not null default 0,
    unrealized_profit numeric not null default 0,
    status text not null default 'active' check (status in ('active','paused','completed')),
    compounding boolean not null default true,
    started_at timestamptz not null default now(),
    completed_at timestamptz,
    created_at timestamptz not null default now()
);

-- Trade history (closed trades with realized results)
create table if not exists public.trades (
    id uuid primary key default uuid_generate_v4(),
    user_id uuid not null references auth.users(id) on delete cascade,
    exchange text not null,
    symbol text not null,
    product text not null default 'futures',
    side text not null check (side in ('long','short')),
    qty numeric not null,
    entry_price numeric not null,
    exit_price numeric,
    realized_pnl numeric not null default 0,
    fees numeric not null default 0,
    status text not null default 'open' check (status in ('open','closed','rejected')),
    notes text,
    created_at timestamptz not null default now(),
    closed_at timestamptz
);

-- Audit log
create table if not exists public.audit_log (
    id uuid primary key default uuid_generate_v4(),
    user_id uuid references auth.users(id) on delete cascade,
    event text not null,
    detail jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- Row Level Security
-- ---------------------------------------------------------------------------

alter table public.app_state enable row level security;
alter table public.exchange_configs enable row level security;
alter table public.user_settings enable row level security;
alter table public.profit_missions enable row level security;
alter table public.trades enable row level security;
alter table public.audit_log enable row level security;

-- Users can only read/modify their own rows.
-- Backend uses the service-role key which bypasses RLS.
create policy "own app_state" on public.app_state
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "own exchange_configs" on public.exchange_configs
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "own user_settings" on public.user_settings
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "own profit_missions" on public.profit_missions
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "own trades" on public.trades
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "own audit_log" on public.audit_log
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- Note: exchange_configs stores only ENCRYPTED secrets (Fernet, server-side
-- key). RLS ensures clients can never read even the ciphertext of other users.
