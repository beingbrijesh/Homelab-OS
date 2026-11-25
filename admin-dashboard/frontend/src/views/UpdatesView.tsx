import { useEffect, useState } from 'preact/hooks';
import { ArrowUpCircle, Clock, Cloud, History, LayoutGrid, RefreshCw, X } from 'lucide-preact';
import type { UpdateJob, UpdatesStatus } from '../types/api';
import { api } from '../api/client';
import { CardHeader, PillButton, ProgressBar, ServiceIcon, StatusBadge } from '../components/ui';

export function UpdatesView({
  refreshKey,
  onBadgeChange,
  onNotify,
}: {
  refreshKey: number;
  onBadgeChange: (count: number) => void;
  onNotify: (msg: string, ok?: boolean) => void;
}) {
  const [status, setStatus] = useState<UpdatesStatus | null>(null);
  const [jobs, setJobs] = useState<UpdateJob[]>([]);
  const [checking, setChecking] = useState(false);

  // Schedule form state
  const [autoEnabled, setAutoEnabled] = useState(false);
  const [freq, setFreq] = useState('weekly');
  const [day, setDay] = useState('sun');
  const [time, setTime] = useState('03:00');
  const [backupBefore, setBackupBefore] = useState(true);
  const [ncApps, setNcApps] = useState(true);
  const [hydrated, setHydrated] = useState(false);

  const hydrateFromPayload = (d: UpdatesStatus) => {
    setStatus(d);
    onBadgeChange(d.updates_available_count || 0);
    if (!hydrated && d.settings) {
      setAutoEnabled(!!d.settings.auto_update_enabled);
      setFreq(d.settings.schedule_freq || 'weekly');
      setDay(d.settings.schedule_day || 'sun');
      setTime(d.settings.schedule_time || '03:00');
      setBackupBefore(d.settings.backup_before !== false);
      setNcApps(d.settings.update_nextcloud_apps !== false);
      setHydrated(true);
    }
  };

  const loadAll = async (bg = false) => {
    const [d, j] = await Promise.all([
      api<UpdatesStatus>('/api/updates/status', 'GET', null, { bg }),
      api<UpdateJob[]>('/api/updates/jobs', 'GET', null, { bg }),
    ]);
    if (!d.error) hydrateFromPayload(d);
    if (Array.isArray(j)) setJobs(j);
  };

  useEffect(() => {
    loadAll(false);
    const t = setInterval(() => loadAll(true), 8000);
    return () => clearInterval(t);
  }, [refreshKey]);

  const handleCheck = async () => {
    setChecking(true);
    const d = await api<UpdatesStatus>('/api/updates/check', 'POST', {});
    setChecking(false);
    if (!d.error) {
      hydrateFromPayload(d);
      onNotify('Update check completed.');
    } else {
      onNotify(d.error, false);
    }
    loadAll(false);
  };

  const handleSaveSettings = async () => {
    const res = await api('/api/updates/settings', 'POST', {
      auto_update_enabled: autoEnabled,
      schedule_freq: freq,
      schedule_day: day,
      schedule_time: time,
      backup_before: backupBefore,
      update_nextcloud_apps: ncApps,
    });
    if (res.error) onNotify(res.error, false);
    else onNotify('Auto-update schedule saved.');
  };

  const handleApply = async (target: string) => {
    if (!confirm(`Start update for "${target}"?`)) return;
    const res = await api('/api/updates/apply', 'POST', { target });
    if (res.error) onNotify(res.error, false);
    else onNotify(`Update started for ${target}.`);
    loadAll(false);
  };

  const handleCancelActive = async () => {
    const jobId = status?.active_job?.id;
    if (!jobId) return;
    await api(`/api/updates/${jobId}/cancel`, 'POST', {});
    onNotify('Cancellation requested.');
    loadAll(false);
  };

  const nc = status?.nextcloud_info;
  const activeJob = status?.active_job;
  const services = status?.services || [];

  return (
    <div class="space-y-5">
      {/* Top action banner */}
      <div class="bento-hero p-4 sm:p-5 flex flex-wrap items-center justify-between gap-4">
        <div class="flex items-center gap-3 min-w-0">
          <span class="w-9 h-9 rounded-2xl bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-950 flex items-center justify-center shrink-0">
            <ArrowUpCircle size={18} />
          </span>
          <div class="min-w-0">
            <div class="flex items-center gap-2 flex-wrap">
              <h2 class="text-sm sm:text-base font-bold text-zinc-900 dark:text-white">
                App-Store Update Engine
              </h2>
              <StatusBadge tone={(status?.updates_available_count || 0) > 0 ? 'ok' : 'neutral'} dot>
                {status?.updates_available_count || 0} available
              </StatusBadge>
            </div>
            <p class="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
              Last checked:{' '}
              {status?.last_checked ? status.last_checked.slice(0, 19).replace('T', ' ') : 'Never'}
            </p>
          </div>
        </div>
        <div class="flex items-center gap-2">
          <PillButton variant="secondary" size="sm" disabled={checking} onClick={handleCheck}>
            <RefreshCw size={13} class={checking ? 'animate-spin' : ''} />
            {checking ? 'Checking...' : 'Check Updates'}
          </PillButton>
          <PillButton variant="primary" size="sm" onClick={() => handleApply('all')}>
            <ArrowUpCircle size={14} /> Update All
          </PillButton>
        </div>
      </div>

      {/* Active Job Progress Card */}
      {activeJob && (
        <div class="bento-card p-5 sm:p-6 border-zinc-900 dark:border-white/30">
          <div class="flex flex-wrap items-center justify-between gap-3 mb-3">
            <div class="flex items-center gap-2">
              <StatusBadge tone="warn" dot pulse>
                {activeJob.cancel_requested ? 'cancelling' : activeJob.status}
              </StatusBadge>
              <span class="text-sm font-bold text-zinc-900 dark:text-white">
                Job #{activeJob.id}: {activeJob.target}
              </span>
            </div>
            <PillButton size="xs" variant="danger" onClick={handleCancelActive}>
              <X size={12} /> Cancel Update
            </PillButton>
          </div>
          <div class="flex items-center justify-between text-xs text-zinc-500 mb-1.5">
            <span>{activeJob.current_step || 'Running...'}</span>
            <span class="font-semibold text-zinc-900 dark:text-white">{activeJob.progress_pct || 0}%</span>
          </div>
          <ProgressBar percent={activeJob.progress_pct || 0} tone="mono" height="h-2" />
          {activeJob.log && (
            <pre class="mt-3 bento-sub p-3 font-mono text-[11px] text-zinc-600 dark:text-zinc-300 max-h-36 overflow-y-auto whitespace-pre-wrap">
              {activeJob.log}
            </pre>
          )}
        </div>
      )}

      {/* Scheduler + Nextcloud Automation — equal flush height */}
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-3.5 items-stretch">
        <div class="bento-card p-4 sm:p-5 h-full flex flex-col justify-between gap-3">
          <div class="space-y-3">
            <CardHeader title="Auto-Update Scheduler" icon={<Clock size={14} />} />

          <label class="flex items-center gap-2.5 text-xs font-semibold text-zinc-900 dark:text-white cursor-pointer">
            <input
              type="checkbox"
              checked={autoEnabled}
              onChange={(e) => setAutoEnabled((e.target as HTMLInputElement).checked)}
              class="accent-zinc-900 dark:accent-white w-4 h-4"
            />
            <span>Enable Automatic Scheduled Updates</span>
          </label>

          <div class="flex flex-wrap items-center gap-2">
            <select
              value={freq}
              onChange={(e) => setFreq((e.target as HTMLSelectElement).value)}
              class="bento-input py-1.5 px-3 text-xs"
            >
              <option value="weekly">Weekly</option>
              <option value="daily">Daily</option>
            </select>
            <select
              value={day}
              onChange={(e) => setDay((e.target as HTMLSelectElement).value)}
              class="bento-input py-1.5 px-3 text-xs"
            >
              <option value="sun">Sunday</option>
              <option value="mon">Monday</option>
              <option value="tue">Tuesday</option>
              <option value="wed">Wednesday</option>
              <option value="thu">Thursday</option>
              <option value="fri">Friday</option>
              <option value="sat">Saturday</option>
            </select>
            <input
              type="text"
              value={time}
              onInput={(e) => setTime((e.target as HTMLInputElement).value)}
              class="bento-input py-1.5 px-3 text-xs w-20 text-center font-mono"
            />
          </div>

          <label class="flex items-center gap-2.5 text-xs text-zinc-600 dark:text-zinc-400 cursor-pointer">
            <input
              type="checkbox"
              checked={backupBefore}
              onChange={(e) => setBackupBefore((e.target as HTMLInputElement).checked)}
              class="accent-zinc-900 dark:accent-white"
            />
            <span>Run pre-update backup snapshot before upgrading</span>
          </label>

          <label class="flex items-center gap-2.5 text-xs text-zinc-600 dark:text-zinc-400 cursor-pointer">
            <input
              type="checkbox"
              checked={ncApps}
              onChange={(e) => setNcApps((e.target as HTMLInputElement).checked)}
              class="accent-zinc-900 dark:accent-white"
            />
            <span>Auto-update Nextcloud apps &amp; DB indices hands-free</span>
          </label>
          </div>

          <div class="pt-2 border-t border-zinc-200/70 dark:border-zinc-800">
            <PillButton size="sm" variant="primary" onClick={handleSaveSettings}>
              Save Schedule
            </PillButton>
          </div>
        </div>

        <div class="bento-card p-4 sm:p-5 h-full flex flex-col justify-between gap-3">
          <div>
            <CardHeader
              title="Hands-Free Nextcloud Updater"
              icon={<Cloud size={14} />}
              action={
                nc?.running ? (
                  <StatusBadge tone={nc.maintenance ? 'warn' : 'ok'} dot>
                    {nc.maintenance ? 'Maintenance ON' : 'Healthy'}
                  </StatusBadge>
                ) : (
                  <StatusBadge tone="neutral">Offline</StatusBadge>
                )
              }
            />

            {nc?.running ? (
              <div class="bento-sub p-3.5 text-xs space-y-1.5 mb-3">
                <div>
                  Installed:{' '}
                  <strong class="text-zinc-900 dark:text-white">{nc.version || 'Unknown'}</strong>
                </div>
                <div>
                  Core update:{' '}
                  <strong
                    class={
                      nc.core_update_available
                        ? 'text-emerald-600 dark:text-emerald-400'
                        : 'text-zinc-500'
                    }
                  >
                    {nc.core_update_available ? nc.available_version : 'Up to date'}
                  </strong>{' '}
                  · App updates: <strong>{nc.app_updates?.length || 0}</strong>
                </div>
                {nc.app_updates && nc.app_updates.length > 0 && (
                  <div class="text-[11px] text-zinc-500">
                    {nc.app_updates
                      .map((a) => `${a.id} (${a.current_version} → ${a.available_version})`)
                      .join(', ')}
                  </div>
                )}
              </div>
            ) : (
              <p class="text-xs text-zinc-500 mb-3">
                Click Check Updates to inspect Nextcloud core &amp; installed apps.
              </p>
            )}

            <p class="text-[11px] text-zinc-500 dark:text-zinc-400 leading-relaxed">
              Automates: Backup → <code class="font-mono">maintenance:mode --on</code> →{' '}
              <code class="font-mono">occ upgrade</code> → <code class="font-mono">app:update --all</code>{' '}
              → <code class="font-mono">db:add-missing-indices</code> →{' '}
              <code class="font-mono">maintenance:mode --off</code>.
            </p>
          </div>

          <div>
            <PillButton size="sm" variant="primary" onClick={() => handleApply('nextcloud')}>
              <ArrowUpCircle size={13} /> Run Hands-Free Nextcloud Update
            </PillButton>
          </div>
        </div>
      </div>

      {/* Service Update Cards */}
      <div class="bento-card p-5 sm:p-6">
        <CardHeader title="Service Image Digests" icon={<LayoutGrid size={16} />} />
        <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3.5">
          {services.map((svc) => {
            const hasUpd = !!svc.update_available;
            return (
              <div key={svc.name} class="bento-sub p-4 flex flex-col justify-between gap-3">
                <div>
                  <div class="flex items-center justify-between gap-2 mb-1.5">
                    <div class="flex items-center gap-2 font-bold text-xs text-zinc-900 dark:text-white">
                      <ServiceIcon name={svc.name} size={14} />
                      {svc.name}
                    </div>
                    <StatusBadge tone={hasUpd ? 'ok' : 'neutral'} dot={hasUpd}>
                      {hasUpd ? 'Update Ready' : 'Current'}
                    </StatusBadge>
                  </div>
                  <div class="text-[11px] font-mono text-zinc-400 truncate">
                    {svc.image || svc.source || 'local'}
                  </div>
                  <div class="text-[11px] text-zinc-600 dark:text-zinc-300 mt-1.5">
                    Now: <code class="font-mono">{svc.current_version || '—'}</code> → Latest:{' '}
                    <code class="font-mono">{svc.latest_version || '—'}</code>
                  </div>
                </div>
                <div class="flex items-center justify-between gap-2 pt-2 border-t border-zinc-200/60 dark:border-zinc-800/70">
                  <span class="text-[10px] text-zinc-400 truncate">{svc.note || ''}</span>
                  <PillButton
                    size="xs"
                    variant={hasUpd ? 'primary' : 'secondary'}
                    onClick={() => handleApply(svc.name)}
                  >
                    {svc.name === 'admin-dashboard' ? 'Update yt-dlp' : 'Update'}
                  </PillButton>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Recent Update Jobs */}
      <div class="bento-card p-5 sm:p-6">
        <CardHeader title="Recent Update Jobs" icon={<History size={16} />} />
        {jobs.length > 0 ? (
          <div class="overflow-x-auto">
            <table class="w-full text-left border-collapse text-xs">
              <thead>
                <tr class="border-b border-zinc-200/80 dark:border-zinc-800 text-[10px] font-semibold uppercase tracking-widest text-zinc-400">
                  <th class="py-2 pr-3">ID</th>
                  <th class="py-2 pr-3">Target</th>
                  <th class="py-2 pr-3">Status</th>
                  <th class="py-2 pr-3">Step / Detail</th>
                  <th class="py-2 text-right">Time</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-zinc-200/60 dark:divide-zinc-800/70">
                {jobs.slice(0, 12).map((j) => (
                  <tr key={j.id}>
                    <td class="py-2.5 pr-3 font-mono text-zinc-400">#{j.id}</td>
                    <td class="py-2.5 pr-3 font-semibold text-zinc-900 dark:text-white">{j.target}</td>
                    <td class="py-2.5 pr-3">
                      <StatusBadge
                        tone={
                          j.status === 'completed'
                            ? 'ok'
                            : j.status === 'failed'
                            ? 'err'
                            : j.status === 'cancelled'
                            ? 'warn'
                            : 'dark'
                        }
                      >
                        {j.status}
                      </StatusBadge>
                    </td>
                    <td class="py-2.5 pr-3 text-zinc-500 dark:text-zinc-400">
                      {j.error || j.current_step || '—'}
                    </td>
                    <td class="py-2.5 text-right font-mono text-[11px] text-zinc-400">
                      {(j.created_at || '').slice(0, 16)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p class="text-xs text-zinc-400">No update jobs executed yet.</p>
        )}
      </div>
    </div>
  );
}
