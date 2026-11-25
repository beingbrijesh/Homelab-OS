import { useState } from 'preact/hooks';
import { KeyRound, Moon, Sun } from 'lucide-preact';
import { api } from '../api/client';
import type { ThemeMode } from '../hooks/useTheme';
import { CardHeader, PillButton } from '../components/ui';

export function SettingsView({
  theme,
  onToggleTheme,
}: {
  theme: ThemeMode;
  onToggleTheme: () => void;
}) {
  const [current, setCurrent] = useState('');
  const [nextPw, setNextPw] = useState('');
  const [confirmPw, setConfirmPw] = useState('');
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<{ text: string; ok: boolean } | null>(null);

  const handleSave = async (e: Event) => {
    e.preventDefault();
    setMsg(null);
    if (nextPw !== confirmPw) {
      setMsg({ text: 'Passwords do not match.', ok: false });
      return;
    }
    if (nextPw.length < 8) {
      setMsg({ text: 'Minimum 8 characters required.', ok: false });
      return;
    }
    setSaving(true);
    const res = await api<{ ok?: boolean }>('/api/admin/change-password', 'POST', {
      current,
      new: nextPw,
    });
    setSaving(false);
    if (res.ok) {
      setMsg({ text: 'Password updated successfully.', ok: true });
      setCurrent('');
      setNextPw('');
      setConfirmPw('');
    } else {
      setMsg({ text: res.error || 'Failed to update password.', ok: false });
    }
  };

  return (
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4 items-start max-w-4xl">
      <div class="bento-card p-4 sm:p-5">
        <CardHeader
          title="Change Admin Password"
          subtitle="Uses scrypt cryptographic hashing"
          icon={<KeyRound size={14} />}
        />

        <form onSubmit={handleSave} class="space-y-3.5">
          <div>
            <label class="block text-[10px] font-semibold uppercase tracking-widest text-zinc-400 mb-1">
              Current Password
            </label>
            <input
              type="password"
              required
              value={current}
              onInput={(e) => setCurrent((e.target as HTMLInputElement).value)}
              placeholder="Current password"
              class="bento-input w-full"
            />
          </div>

          <div>
            <label class="block text-[10px] font-semibold uppercase tracking-widest text-zinc-400 mb-1">
              New Password
            </label>
            <input
              type="password"
              required
              value={nextPw}
              onInput={(e) => setNextPw((e.target as HTMLInputElement).value)}
              placeholder="Minimum 8 characters"
              class="bento-input w-full"
            />
          </div>

          <div>
            <label class="block text-[10px] font-semibold uppercase tracking-widest text-zinc-400 mb-1">
              Confirm New Password
            </label>
            <input
              type="password"
              required
              value={confirmPw}
              onInput={(e) => setConfirmPw((e.target as HTMLInputElement).value)}
              placeholder="Repeat new password"
              class="bento-input w-full"
            />
          </div>

          {msg && (
            <div
              class={`px-3.5 py-2 rounded-2xl text-xs font-medium border ${
                msg.ok
                  ? 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-emerald-500/25'
                  : 'bg-rose-500/10 text-rose-700 dark:text-rose-400 border-rose-500/25'
              }`}
            >
              {msg.text}
            </div>
          )}

          <PillButton type="submit" size="sm" variant="primary" disabled={saving}>
            {saving ? 'Saving...' : 'Save Password'}
          </PillButton>
        </form>
      </div>

      <div class="bento-card p-4 sm:p-5 space-y-3.5">
        <CardHeader
          title="Interface Appearance"
          subtitle="Switch between Light and Dark Monochrome Bento themes"
          icon={theme === 'light' ? <Sun size={14} /> : <Moon size={14} />}
        />
        <p class="text-xs text-zinc-500 dark:text-zinc-400 leading-relaxed">
          Your theme preference is stored locally in your browser with instant zero-flash boot.
        </p>
        <div>
          <PillButton size="sm" variant="secondary" onClick={onToggleTheme}>
            {theme === 'light' ? <Moon size={13} /> : <Sun size={13} />}
            Switch to {theme === 'light' ? 'Dark Monochrome' : 'Light Monochrome'}
          </PillButton>
        </div>
      </div>
    </div>
  );
}
