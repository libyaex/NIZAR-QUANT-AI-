# Deployment Guide

## 1. Environment variables

### Railway (backend)

| Variable | Purpose |
|---|---|
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | Server-side DB access (never expose) |
| `CREDENTIAL_ENCRYPTION_KEY` | Fernet key used to encrypt exchange secrets at rest |
| `API_KEY_SECRET` | Secret for the backend API session token (any strong random string) |
| `CORS_ORIGINS` | Comma-separated list of allowed frontend origins (Vercel domain) |
| `PUBLIC_API_URL` | Optional, override public backend URL used in docs |

### Frontend (Vercel)

| Variable | Purpose |
|---|---|
| `VITE_API_URL` | Backend base URL (Railway public URL, e.g. `https://<app>.up.railway.app`) |

Supabase client keys (`VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`) are provided automatically by the Vercel–Supabase integration; they are only used for user login.

## 2. Supabase

Apply `supabase/migrations/0001_init.sql` in the Supabase SQL editor (create tables + RLS policies).
This migration only **creates new tables** — it does not modify or delete any existing data.
Rollback: `supabase/migrations/0001_rollback.sql`.

## 3. Railway

- Root directory: `backend`
- Start command: handled by `Procfile` (`uvicorn app.main:app`)
- Add all backend environment variables above.

## 4. Vercel

- Root directory: `frontend`
- Framework preset: Vite
- Build command: `npm run build`
- Add `VITE_API_URL`.

## 5. Exchange API configuration

In the app: **Exchange Management** screen → connect API keys.

Create keys on each exchange with **trade permission enabled and withdrawal
permission disabled**. Only the exchange-facing API is used; secrets are
encrypted with `CREDENTIAL_ENCRYPTION_KEY` before storage and are never
returned to the frontend.

## 6. Activating automated trading

1. Open the app, log in.
2. Connect an exchange API key (Exchange Management).
3. Configure risk settings and create a Profit Mission (optional).
4. Press **START TRADING** on the dashboard.

The background engine runs continuously on Railway; pressing START TRADING
activates automated execution of real orders. Press **STOP TRADING** to stop
opening new positions while continuing to manage existing ones.
**CLOSE ALL POSITIONS** closes every open position immediately.
