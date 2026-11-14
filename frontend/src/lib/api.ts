import { createClient, SupabaseClient } from '@supabase/supabase-js';

const supabaseUrl = (import.meta.env.VITE_SUPABASE_URL || '') as string;
const supabaseAnonKey = (import.meta.env.VITE_SUPABASE_ANON_KEY || '') as string;
const apiBase = (import.meta.env.VITE_API_URL || '').replace(/\/$/, '');

export function missingEnvVars(): string[] {
  const missing: string[] = [];
  if (!supabaseUrl) missing.push('VITE_SUPABASE_URL');
  if (!supabaseAnonKey) missing.push('VITE_SUPABASE_ANON_KEY');
  return missing;
}

let _client: SupabaseClient | null = null;

export function getSupabase(): SupabaseClient | null {
  const missing = missingEnvVars();
  if (missing.length > 0) {
    console.error('[NIZAR] Missing frontend environment variables: ' + missing.join(', '));
    return null;
  }
  if (_client === null) {
    _client = createClient(supabaseUrl, supabaseAnonKey);
  }
  return _client;
}

export const supabase: SupabaseClient = new Proxy({} as SupabaseClient, {
  get(_target, prop) {
    const client = getSupabase();
    if (client) return Reflect.get(client, prop);
    throw new Error('Supabase is not configured: set ' + missingEnvVars().join(', '));
  },
}) as SupabaseClient;

export function apiBasePath(): string {
  return apiBase;
}

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  if (!apiBase) {
    throw new Error('Backend URL is not configured: set VITE_API_URL in Vercel environment variables');
  }
  const client = getSupabase();
  const token = (await client?.auth.getSession())?.data.session?.access_token ?? '';
  const resp = await fetch(`${apiBase}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
      ...(init.headers || {}),
    },
  });
  if (!resp.ok) {
    const detail = await resp.json().catch(() => ({}));
    throw new Error((detail as Record<string, unknown>).detail || `API error ${resp.status}`);
  }
  return resp.json() as Promise<T>;
}
