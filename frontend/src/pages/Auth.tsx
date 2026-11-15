import { FormEvent, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { getSupabase } from '../lib/api';
import { Banner, Field } from '../components/ui';

export default function Auth() {
  const nav = useNavigate();
  const sb = getSupabase();
  const [mode, setMode] = useState<'in' | 'up'>('in');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [msg, setMsg] = useState<{ kind: 'err' | 'ok'; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!sb) return;
    setBusy(true); setMsg(null);
    const res = mode === 'in' ? await sb.auth.signInWithPassword({ email, password }) : await sb.auth.signUp({ email, password });
    setBusy(false);
    if (res.error) return setMsg({ kind: 'err', text: res.error.message });
    if (mode === 'up' && !res.data.session) return setMsg({ kind: 'ok', text: 'Account created. Check your email to confirm, then sign in.' });
    nav('/');
  };

  return (
    <div className="auth-wrap">
      <div className="auth-card stack">
        <div className="brand" style={{ justifyContent: 'center', fontSize: 20 }}><i>N</i>NIZAR <span>QUANT AI</span></div>
        <form className="card stack" onSubmit={submit}>
          <h2 style={{ fontSize: 20 }}>{mode === 'in' ? 'Sign in' : 'Create account'}</h2>
          {!sb && <Banner kind="err">Supabase is not configured. Set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY in Vercel and redeploy.</Banner>}
          <Field label="Email"><input className="input" type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
          <Field label="Password"><input className="input" type="password" required minLength={6} autoComplete={mode === 'in' ? 'current-password' : 'new-password'} value={password} onChange={(e) => setPassword(e.target.value)} /></Field>
          {msg && <Banner kind={msg.kind}>{msg.text}</Banner>}
          <button className="btn primary block" disabled={busy || !sb}>{busy ? 'Please wait…' : mode === 'in' ? 'Sign in' : 'Create account'}</button>
          <button type="button" className="btn ghost block" onClick={() => setMode(mode === 'in' ? 'up' : 'in')}>
            {mode === 'in' ? 'New here? Create an account' : 'Have an account? Sign in'}
          </button>
        </form>
        <Link to="/" className="muted small" style={{ textAlign: 'center' }}>Continue to live market view without signing in</Link>
      </div>
    </div>
  );
}
