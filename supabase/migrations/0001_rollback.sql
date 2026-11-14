-- Rollback for 0001_init.sql — DESTRUCTIVE: removes all app tables and data.
-- Run ONLY with explicit approval after confirming no data needs to be kept.

drop table if exists public.audit_log cascade;
drop table if exists public.trades cascade;
drop table if exists public.profit_missions cascade;
drop table if exists public.user_settings cascade;
drop table if exists public.exchange_configs cascade;
drop table if exists public.app_state cascade;