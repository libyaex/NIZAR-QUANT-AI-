# NIZAR QUANT AI — Deployment (v2)

## 1. Supabase
Run `supabase/migrations/0001_init.sql` once in the SQL editor (creates tables + RLS; additive only).
Rollback: `0001_rollback.sql`. v2 needs **no new SQL**.
Auth → Providers → Email: enabled. (Disable "Confirm email" if you want instant sign-in.)

## 2. Railway (backend)
Root directory: `backend`. Start command comes from `railway.json` (health check `/api/health`).

| Variable | Value |
|---|---|
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | service-role key (server only) |
| `CREDENTIAL_ENCRYPTION_KEY` | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` — keep it forever, losing it makes saved API keys unreadable |
| `API_KEY_SECRET` | any long random string |
| `CORS_ORIGINS` | your Vercel URL, e.g. `https://nizar.vercel.app` (`*.vercel.app` is also allowed) |
| `PUBLIC_EXCHANGES` | optional, default `okx,bitget,mexc,bybit,binance` |

**Region matters.** Binance and Bybit block US servers. In Railway → Service → Settings → Region choose **EU West (Amsterdam)**. The Exchange Management screen shows exactly which exchange is blocked.
Keep the service at **1 replica** (the engine holds trading state in memory).

## 3. Vercel (frontend)
Root directory: `frontend`, framework Vite. Variables:
`VITE_API_URL` (Railway public URL), `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`
(the Vercel×Supabase integration names `NEXT_PUBLIC_SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_ANON_KEY` are also read). Redeploy after changing variables.

## 4. First run
1. Open the app: market data appears without logging in (Scanner, Analysis, charts).
2. Sign up / sign in. 3. Risk & Settings: review defaults.
4. Press START TRADING in **Paper** mode and watch it for a few days.
5. Live: Exchange Management → connect keys (Read + Trade, **no withdrawals**, IP-restrict to Railway) → Trade screen → switch to Live → START.

## 5. Tests
`cd backend && python -m pytest tests -q` (engine flow runs against a fake exchange, no network).
