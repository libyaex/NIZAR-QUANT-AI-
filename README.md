# NIZAR QUANT AI

Automated multi-exchange cryptocurrency scalping platform.

- **Frontend**: React + TypeScript + Vite (deploy: Vercel)
- **Backend**: Python FastAPI, async trading engine (deploy: Railway)
- **Database**: Supabase (PostgreSQL + RLS)
- **Exchanges**: Binance, MEXC, Bybit, OKX, Bitget (Futures primary, Spot where supported)

## Repository layout

```
backend/    FastAPI app + background trading engine
frontend/   React TypeScript dashboard (PWA)
supabase/   SQL migrations (require approval before applying)
```

## Status

The full application (scanner, TA engine, probability engine, decision engine,
execution engine, risk management, Profit Mission, auth, API key vault) is
implemented on branch `nizar-quant-ai`.

See `DEPLOYMENT.md` for environment variables and deployment steps.
