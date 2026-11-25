import { useEffect, useState } from 'preact/hooks';
import { Ban, CheckCircle2, Lock, Shield, ShieldAlert, ShieldCheck } from 'lucide-preact';
import type { IpBan, LoginAttempt, ZeroTrustSettings } from '../types/api';
import { api } from '../api/client';
import { CardHeader, PillButton, StatusBadge } from '../components/ui';

export function SecurityView({
  refreshKey,
  onNotify,
}: {
  refreshKey: number;
  onNotify: (msg: string, ok?: boolean) => void;
}) {
  const [bans, setBans] = useState<IpBan[]>([]);
  const [attempts, setAttempts] = useState<LoginAttempt[]>([]);

  // Zero Trust form
  const [ztEnabled, setZtEnabled] = useState(false);
  const [ztEmails, setZtEmails] = useState('');
  const [ztSaving, setZtSaving] = useState(false);

  // Quick Ban form
  const [banIp, setBanIp] = useState('');
  const [banDuration, setBanDuration] = useState('24');
  const [banReason, setBanReason] = useState('Manual Admin Ban');
  const [banning, setBanning] = useState(false);

  const loadAll = async () => {
    const [b, a, zt] = await Promise.all([
      api<IpBan[]>('/api/bans'),
      api<LoginAttempt[]>('/api/login-attempts'),
      api<ZeroTrustSettings>('/api/settings/zero-trust'),
    ]);
    if (Array.isArray(b)) setBans(b);
    if (Array.isArray(a)) setAttempts(a);
    if (zt && !zt.error) {
      setZtEnabled(!!zt.enabled);
      setZtEmails((zt.allowed_emails || []).join(', '));
    }
  };

  useEffect(() => {
    loadAll();
  }, [refreshKey]);

  const saveZeroTrust = async () => {
    setZtSaving(true);
    const res = await api<{ ok?: boolean; allowed_emails?: string[] }>(
      '/api/settings/zero-trust',
      'POST',
      {
        enabled: ztEnabled,
        allowed_emails: ztEmails,
        bypass_local: true,
      }
    );
    setZtSaving(false);
    if (res.ok) {
      if (res.allowed_emails) setZtEmails(res.allowed_emails.join(', '));
      onNotify('Cloudflare Zero Trust policy updated.');
    } else {
      onNotify(res.error || 'Failed to save Zero Trust policy.', false);
    }
  };

  const submitQuickBan = async (e: Event) => {
    e.preventDefault();
    if (!banIp.trim()) return;
    setBanning(true);
    const res = await api<{ ok?: boolean }>('/api/bans/add', 'POST', {
      ip: banIp.trim(),
      duration_hours: parseInt(banDuration, 10),
      reason: banReason.trim() || 'Manual Admin Ban',
    });
    setBanning(false);
    if (res.ok) {
      onNotify(`Banned ${banIp.trim()} successfully.`);
      setBanIp('');
      setBanReason('Manual Admin Ban');
      setBanDuration('24');
      loadAll();
    } else {
      onNotify(res.error || 'Failed to ban IP.', false);
    }
  };

  const quickBanRow = async (ip: string) => {
    if (!confirm(`Ban IP ${ip} for 24 hours?\nReason: Failed login attempt`)) return;
    const res = await api<{ ok?: boolean }>('/api/bans/add', 'POST', {
      ip,
      duration_hours: 24,
      reason: 'Failed login attempt',
    });
    if (res.ok) {
      onNotify(`Banned ${ip} for 24h.`);
      loadAll();
    } else {
      onNotify(res.error || 'Failed to ban IP.', false);
    }
  };

  const unban = async (id: number) => {
    await api(`/api/bans/${id}/unban`, 'POST');
    onNotify('IP unbanned.');
    loadAll();
  };

  const bannedIps = new Set(bans.map((b) => b.ip));

  return (
    <div class="space-y-4">
      {/* Cloudflare Zero Trust + Quick Block — flush equal height */}
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-3.5 items-stretch">
        <div class="bento-card p-4 sm:p-5 h-full flex flex-col justify-between gap-3.5">
          <CardHeader
            title="Cloudflare Zero Trust Defense"
            subtitle="LAN & Tailscale bypasses automatically; tunnel traffic requires verified email"
            icon={<ShieldCheck size={16} />}
            action={
              <StatusBadge tone={ztEnabled ? 'ok' : 'neutral'} dot>
                {ztEnabled ? 'Enforced' : 'Disabled'}
              </StatusBadge>
            }
          />

          <label class="flex items-center gap-2.5 text-xs font-semibold text-zinc-900 dark:text-white cursor-pointer">
            <input
              type="checkbox"
              checked={ztEnabled}
              onChange={(e) => setZtEnabled((e.target as HTMLInputElement).checked)}
              class="accent-zinc-900 dark:accent-white w-4 h-4"
            />
            <span>Enforce Cloudflare Zero Trust Email Authorization</span>
          </label>

          <div>
            <label class="block text-[10px] font-semibold uppercase tracking-widest text-zinc-400 mb-1.5">
              Authorized User Emails
            </label>
            <textarea
              rows={3}
              value={ztEmails}
              onInput={(e) => setZtEmails((e.target as HTMLTextAreaElement).value)}
              placeholder="user1@example.com, user2@example.com"
              class="bento-input w-full font-mono text-xs"
            />
          </div>

          <PillButton size="sm" variant="primary" disabled={ztSaving} onClick={saveZeroTrust}>
            <Lock size={12} /> {ztSaving ? 'Saving...' : 'Save Zero Trust Policy'}
          </PillButton>
        </div>

        <div class="bento-card p-5 sm:p-6 flex flex-col justify-between">
          <div>
            <CardHeader
              title="Quick Block IP"
              subtitle="Immediately drop access from a hostile address"
              icon={<ShieldAlert size={16} />}
            />

            <form onSubmit={submitQuickBan} class="space-y-3">
              <div>
                <label class="block text-[10px] font-semibold uppercase tracking-widest text-zinc-400 mb-1">
                  IP Address
                </label>
                <input
                  type="text"
                  required
                  value={banIp}
                  onInput={(e) => setBanIp((e.target as HTMLInputElement).value)}
                  placeholder="e.g. 203.0.113.195"
                  class="bento-input w-full font-mono"
                />
              </div>

              <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label class="block text-[10px] font-semibold uppercase tracking-widest text-zinc-400 mb-1">
                    Duration
                  </label>
                  <select
                    value={banDuration}
                    onChange={(e) => setBanDuration((e.target as HTMLSelectElement).value)}
                    class="bento-input w-full"
                  >
                    <option value="1">1 Hour</option>
                    <option value="24">24 Hours</option>
                    <option value="168">7 Days</option>
                    <option value="0">Permanent</option>
                  </select>
                </div>
                <div>
                  <label class="block text-[10px] font-semibold uppercase tracking-widest text-zinc-400 mb-1">
                    Reason
                  </label>
                  <input
                    type="text"
                    value={banReason}
                    onInput={(e) => setBanReason((e.target as HTMLInputElement).value)}
                    class="bento-input w-full"
                  />
                </div>
              </div>

              <div class="pt-1">
                <PillButton type="submit" size="sm" variant="danger" disabled={banning}>
                  <Ban size={13} /> {banning ? 'Blocking...' : 'Block IP Address'}
                </PillButton>
              </div>
            </form>
          </div>
        </div>
      </div>

      {/* Active IP Bans */}
      <div class="bento-card p-5 sm:p-6">
        <CardHeader
          title="Active IP Bans"
          icon={<Shield size={16} />}
          action={
            <StatusBadge tone={bans.length > 0 ? 'err' : 'ok'} dot>
              {bans.length} active
            </StatusBadge>
          }
        />

        {bans.length > 0 ? (
          <div class="overflow-x-auto">
            <table class="w-full text-left border-collapse text-xs">
              <thead>
                <tr class="border-b border-zinc-200/80 dark:border-zinc-800 text-[10px] font-semibold uppercase tracking-widest text-zinc-400">
                  <th class="py-2 pr-3">IP Address</th>
                  <th class="py-2 pr-3">Reason</th>
                  <th class="py-2 pr-3">Banned At</th>
                  <th class="py-2 pr-3">Expires</th>
                  <th class="py-2 text-right">Action</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-zinc-200/60 dark:divide-zinc-800/70">
                {bans.map((b) => (
                  <tr key={b.id}>
                    <td class="py-2.5 pr-3">
                      <code class="px-2 py-0.5 rounded-lg bg-rose-500/10 text-rose-600 dark:text-rose-400 font-mono text-[11px]">
                        {b.ip}
                      </code>
                    </td>
                    <td class="py-2.5 pr-3 text-zinc-600 dark:text-zinc-300">{b.reason || '—'}</td>
                    <td class="py-2.5 pr-3 font-mono text-[11px] text-zinc-400">
                      {(b.banned_at || '').slice(0, 16)}
                    </td>
                    <td class="py-2.5 pr-3 font-mono text-[11px] text-zinc-400">
                      {b.expires_at ? b.expires_at.slice(0, 16) : 'Permanent'}
                    </td>
                    <td class="py-2.5 text-right">
                      <PillButton size="xs" variant="ok" onClick={() => unban(b.id)}>
                        Unban
                      </PillButton>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div class="bento-sub p-4 flex items-center gap-2 text-xs text-zinc-500">
            <CheckCircle2 size={15} class="text-emerald-500" />
            No active IP bans. All clear.
          </div>
        )}
      </div>

      {/* Recent Login Attempts */}
      <div class="bento-card p-5 sm:p-6">
        <CardHeader title="Recent Login Attempts" icon={<ShieldAlert size={16} />} />
        <div class="overflow-x-auto">
          <table class="w-full text-left border-collapse text-xs">
            <thead>
              <tr class="border-b border-zinc-200/80 dark:border-zinc-800 text-[10px] font-semibold uppercase tracking-widest text-zinc-400">
                <th class="py-2 pr-3">Time</th>
                <th class="py-2 pr-3">IP Address</th>
                <th class="py-2 pr-3">Username</th>
                <th class="py-2 pr-3">Result</th>
                <th class="py-2 pr-3">User Agent</th>
                <th class="py-2 text-right">Action</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-zinc-200/60 dark:divide-zinc-800/70">
              {attempts.length > 0 ? (
                attempts.map((row, idx) => {
                  const ok = !!row.success;
                  const isBanned = bannedIps.has(row.ip);
                  return (
                    <tr key={row.id ?? idx}>
                      <td class="py-2.5 pr-3 font-mono text-[11px] text-zinc-400 whitespace-nowrap">
                        {(row.attempted_at || '').slice(0, 16)}
                      </td>
                      <td class="py-2.5 pr-3 font-mono text-[11px] text-zinc-800 dark:text-zinc-200">
                        {row.ip}
                      </td>
                      <td class="py-2.5 pr-3 text-zinc-600 dark:text-zinc-300">
                        {row.username || '—'}
                      </td>
                      <td class="py-2.5 pr-3">
                        <StatusBadge tone={ok ? 'ok' : 'err'}>
                          {ok ? 'Success' : 'Failed'}
                        </StatusBadge>
                      </td>
                      <td class="py-2.5 pr-3 text-zinc-400 max-w-[200px] truncate">
                        {row.user_agent || '—'}
                      </td>
                      <td class="py-2.5 text-right">
                        {isBanned ? (
                          <StatusBadge tone="err">Banned</StatusBadge>
                        ) : (
                          <PillButton size="xs" variant="danger" onClick={() => quickBanRow(row.ip)}>
                            <Ban size={11} /> Ban
                          </PillButton>
                        )}
                      </td>
                    </tr>
                  );
                })
              ) : (
                <tr>
                  <td colSpan={6} class="py-5 text-center text-zinc-400">
                    No login attempts recorded yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
