import { createClient, SupabaseClient, Session } from '@supabase/supabase-js';
import { useCallback, useEffect, useRef, useState } from 'react';

const env = import.meta.env as Record<string, string | undefined>;
const supabaseUrl = env.VITE_SUPABASE_URL || env.NEXT_PUBLIC_SUPABASE_URL || '';
const supabaseKey = env.VITE_SUPABASE_ANON_KEY || env.NEXT_PUBLIC_SUPABASE_ANON_KEY || env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY || '';
export const apiBase = (env.VITE_API_URL || '').replace(/\/$/, '');

let client: SupabaseClient | null = null;
export function getSupabase(): SupabaseClient | null {
  if (!supabaseUrl || !supabaseKey) return null;
  if (!client) client = createClient(supabaseUrl, supabaseKey);
  return client;
}
export const configIssues = (): string[] => [
  ...(!apiBase ? ['VITE_API_URL'] : []),
  ...(!supabaseUrl ? ['VITE_SUPABASE_URL'] : []),
  ...(!supabaseKey ? ['VITE_SUPABASE_ANON_KEY'] : []),
];

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) { super(message); this.status = status; }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  if (!apiBase) throw new ApiError('Backend URL is not configured (VITE_API_URL)', 0);
  const token = (await getSupabase()?.auth.getSession())?.data.session?.access_token;
  let resp: Response;
  try {
    resp = await fetch(`${apiBase}${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(init.headers || {}) },
    });
  } catch {
    throw new ApiError('Cannot reach the backend. Check VITE_API_URL and that the Railway service is running.', 0);
  }
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    const detail = (body as { detail?: unknown }).detail;
    throw new ApiError(typeof detail === 'string' ? detail : `Request failed (${resp.status})`, resp.status);
  }
  return resp.json() as Promise<T>;
}
export const post = <T,>(path: string, body?: unknown) =>
  api<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) });
export const put = <T,>(path: string, body: unknown) => api<T>(path, { method: 'PUT', body: JSON.stringify(body) });
export const del = <T,>(path: string) => api<T>(path, { method: 'DELETE' });

/** Poll an endpoint; keeps the last good data while retrying. */
export function usePoll<T>(path: string | null, intervalMs = 5000) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const alive = useRef(true);
  const load = useCallback(async () => {
    if (!path) return;
    try {
      const d = await api<T>(path);
      if (alive.current) { setData(d); setError(null); }
    } catch (e) {
      if (alive.current) setError(e as ApiError);
    } finally {
      if (alive.current) setLoading(false);
    }
  }, [path]);
  useEffect(() => {
    alive.current = true;
    setLoading(true);
    load();
    const id = path ? setInterval(load, intervalMs) : undefined;
    return () => { alive.current = false; if (id) clearInterval(id); };
  }, [load, path, intervalMs]);
  return { data, error, loading, reload: load };
}

export function useSession() {
  const [session, setSession] = useState<Session | null>(null);
  const [ready, setReady] = useState(false);
  useEffect(() => {
    const sb = getSupabase();
    if (!sb) { setReady(true); return; }
    sb.auth.getSession().then(({ data }) => { setSession(data.session); setReady(true); });
    const { data: sub } = sb.auth.onAuthStateChange((_e, s) => setSession(s));
    return () => sub.subscription.unsubscribe();
  }, []);
  return { session, ready };
}
