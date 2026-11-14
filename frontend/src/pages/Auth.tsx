import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { getSupabase, missingEnvVars, apiBasePath } from '../lib/api';

function SetupBanner() {
  const missing = missingEnvVars();
  const noApi = !apiBasePath();
  if (missing.length === 0 && !noApi) return null;
  return (
    <div className="card" style={{ marginBottom: 16, borderColor: 'var(--red)', maxWidth: 420 }}>
      <h3 style={{ color: 'var(--red)' }}>Configuration Required</h3>
      <p style={{ fontSize: 13, lineHeight: 1.6 }}>
        Missing environment variables (set them in Vercel, then redeploy):
      </p>
      <ul style={{ paddingLeft: 20, fontSize: 13, lineHeight: 1.8, color: 'var(--text-dim)' }}>
        {missing.map((v) => <li key={v}><code>{v}</code></li>)}
        {noApi && <li><code>VITE_API_URL</code></li>}
      </ul>
    </div>
  );
}

export default function Auth() {
  const navigate = useNavigate();
  const [mode, setMode] = useState<'signin' | 'signup'>('signin');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const client = getSupabase();

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!client) {
      setError('Cannot sign in: Supabase is not configured. Add the missing environment variables in Vercel and redeploy.');
      return;
    }
    setBusy(true);
    setError('');
    try {
      if (mode === 'signin') {
        const { error } = await client.auth.signInWithPassword({ email, password });
        if (error) throw error;
      } else {
        const { error } = await client.auth.signUp({ email, password });
        if (error) throw error;
      }
      navigate('/');
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight: '100vh', padding: 16 }}>
      <SetupBanner />
      <div className="card" style={{ width: 380, maxWidth: '100%' }}>
        <div style={{ fontSize: 20, fontWeight: 700, marginBottom: 18 }}>
          NIZAR <span style={{ color: 'var(--accent)' }}>QUANT AI</span>
        </div>
        <form onSubmit={submit}>
          <div className="form-row">
            <label>Email</label>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </div>
          <div className="form-row">
            <label>Password</label>
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={6} />
          </div>
          {error && <p style={{ color: 'var(--red)', fontSize: 13, marginBottom: 10 }}>{error}</p>}
          <button className="btn primary" style={{ width: '100%' }} disabled={busy || !client}>
            {mode === 'signin' ? 'Sign In' : 'Create Account'}
          </button>
        </form>
        <button
          className="nav-link"
          style={{ marginTop: 12, textAlign: 'center', justifyContent: 'center' }}
          onClick={() => setMode(mode === 'signin' ? 'signup' : 'signin')}
        >
          {mode === 'signin' ? "Don't have an account? Sign up" : 'Already have an account? Sign in'}
        </button>
      </div>
    </div>
  );
}
