import { useState } from 'preact/hooks';
import { ArrowRight, Moon, Server, Sun } from 'lucide-preact';
import type { ThemeMode } from '../hooks/useTheme';

export function LoginView({
  theme,
  onToggleTheme,
  onSuccess,
  onGoRegister,
}: {
  theme: ThemeMode;
  onToggleTheme: () => void;
  onSuccess: (username: string) => void;
  onGoRegister: () => void;
}) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: Event) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const res = await fetch('/login', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'application/json',
        },
        credentials: 'same-origin',
        body: JSON.stringify({ username: username.trim(), password }),
      });
      const ct = res.headers.get('content-type') || '';
      if (ct.includes('application/json')) {
        const data = await res.json();
        if (res.ok && data.ok) {
          onSuccess(data.username || username.trim());
          return;
        }
        setError(data.error || 'Invalid credentials.');
      } else if (res.ok || res.redirected) {
        onSuccess(username.trim() || 'admin');
      } else {
        setError('Login failed. Check your credentials.');
      }
    } catch {
      setError('Cannot reach Homelab server.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div class="min-h-screen w-full flex flex-col items-center justify-center p-4 relative">
      <button
        type="button"
        onClick={onToggleTheme}
        title="Toggle theme"
        class="fixed top-5 right-5 w-10 h-10 rounded-full bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 flex items-center justify-center text-zinc-700 dark:text-zinc-300 shadow-sm cursor-pointer hover:bg-zinc-100 dark:hover:bg-zinc-800"
      >
        {theme === 'light' ? <Moon size={16} /> : <Sun size={16} />}
      </button>

      <div class="w-full max-w-sm">
        <div class="text-center mb-7">
          <div class="inline-flex items-center justify-center w-14 h-14 rounded-3xl bg-zinc-900 dark:bg-white text-white dark:text-zinc-950 shadow-md mb-4">
            <Server size={24} strokeWidth={2.2} />
          </div>
          <h1 class="text-2xl font-bold tracking-tight text-zinc-900 dark:text-white">
            Homelab OS
          </h1>
          <p class="text-xs text-zinc-500 dark:text-zinc-400 mt-1">
            Sign in to your server control plane
          </p>
        </div>

        <div class="bento-card p-6 sm:p-7">
          {error && (
            <div class="mb-4 px-3.5 py-2.5 rounded-2xl bg-rose-500/10 border border-rose-500/25 text-rose-600 dark:text-rose-400 text-xs font-medium">
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} class="space-y-4">
            <div>
              <label class="block text-[11px] font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400 mb-1.5">
                Username
              </label>
              <input
                type="text"
                required
                autoFocus
                value={username}
                onInput={(e) => setUsername((e.target as HTMLInputElement).value)}
                placeholder="admin"
                class="bento-input w-full"
              />
            </div>

            <div>
              <label class="block text-[11px] font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400 mb-1.5">
                Password
              </label>
              <input
                type="password"
                required
                value={password}
                onInput={(e) => setPassword((e.target as HTMLInputElement).value)}
                placeholder="••••••••"
                class="bento-input w-full"
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              class="w-full mt-2 py-2.5 px-4 rounded-full bg-zinc-900 hover:bg-zinc-800 dark:bg-white dark:hover:bg-zinc-200 text-white dark:text-zinc-950 text-xs font-semibold flex items-center justify-center gap-2 transition-all cursor-pointer disabled:opacity-50 shadow-sm"
            >
              {loading ? 'Signing in...' : 'Sign in'}
              {!loading && <ArrowRight size={14} />}
            </button>
          </form>

          <div class="mt-5 pt-4 border-t border-zinc-200/70 dark:border-zinc-800 text-center">
            <button
              type="button"
              onClick={onGoRegister}
              class="text-xs font-medium text-zinc-500 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-white transition-colors cursor-pointer"
            >
              Request an account →
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
