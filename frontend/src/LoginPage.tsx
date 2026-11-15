import React, { useState } from 'react';

type Props = { api: string; setupRequired: boolean; onAuthed: (operator: string) => void };

export default function LoginPage({ api, setupRequired, onAuthed }: Props) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError('');
    setBusy(true);
    try {
      const path = setupRequired ? '/api/auth/setup' : '/api/auth/login';
      const response = await fetch(`${api}${path}`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || 'Unable to sign in.');
      onAuthed(data.operator || email);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Unable to sign in.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-page">
      <div className="login-card">
        <aside className="login-aside">
          <div className="login-brand">
            <span className="logo-mark">✦</span>
            <div><b>AEGIS<span>·</span>HRP</b><small>Crew health OS</small></div>
          </div>
          <h1>Your body.<br />Your orbit.<br /><em>Your baseline.</em></h1>
          <p>Personal vitals, NASA-derived standards and a private wellbeing check-in — built for the crew.</p>
          <div className="login-badges">
            <span className="login-badge"><i /> NASA-STD-3001</span>
            <span className="login-badge"><i /> Secure local access</span>
          </div>
        </aside>
        <section className="login-main">
          <div className="login-form-head">
            <div>
              <h2>{setupRequired ? 'Create your operator account' : 'Welcome back'}</h2>
              <p>{setupRequired ? 'Set up the first account to access the console.' : 'Sign in to your private crew health console.'}</p>
            </div>
            <span className="login-status"><i /> Local auth</span>
          </div>
          <form onSubmit={submit} className="login-fields">
            <label className="login-field"><span>Email</span><input type="email" required autoComplete="username" value={email} onChange={e => setEmail(e.target.value)} placeholder="operator@mission.example" /></label>
            <label className="login-field"><span>Password</span><input type="password" required minLength={8} autoComplete={setupRequired ? 'new-password' : 'current-password'} value={password} onChange={e => setPassword(e.target.value)} placeholder="Minimum 8 characters" /></label>
            {error && <p className="login-error" role="alert">{error}</p>}
            <button className="login-submit" type="submit" disabled={busy}>{busy ? 'Signing in…' : setupRequired ? 'Create account' : 'Sign in'} <span>→</span></button>
          </form>
          <div className="login-foot"><p><b>Prototype access</b> · Your account is stored locally in the app database.</p><p className="muted">Sessions expire after 12 hours.</p></div>
        </section>
      </div>
    </div>
  );
}
