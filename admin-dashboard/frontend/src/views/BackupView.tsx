import { useEffect, useState } from 'preact/hooks';
import { DownloadCloud, FileText, HardDrive } from 'lucide-preact';
import type { BackupStatus, SystemTelemetry } from '../types/api';
import { api } from '../api/client';
import { CardHeader, PillButton, StatusBadge } from '../components/ui';
import { ConcentricRingGauge } from '../components/Charts';

export function BackupView({
  sys,
  refreshKey,
  onReloadSys,
}: {
  sys: SystemTelemetry | null;
  refreshKey: number;
  onReloadSys: () => void;
}) {
  const [status, setStatus] = useState<BackupStatus | null>(null);
  const [running, setRunning] = useState(false);
  const [banner, setBanner] = useState<{ text: string; ok: boolean } | null>(null);

  const loadBackup = async () => {
    const res = await api<BackupStatus>('/api/backup/status');
    if (!res.error) setStatus(res);
  };

  useEffect(() => {
    loadBackup();
  }, [refreshKey]);

  const triggerBackup = async () => {
    setRunning(true);
    setBanner(null);
    const res = await api<{ ok?: boolean; message?: string; pid?: number }>('/api/backup/run', 'POST');
    setRunning(false);
    if (res.ok) {
      setBanner({ text: `${res.message || 'Backup started'} — PID ${res.pid}`, ok: true });
      setTimeout(() => {
        loadBackup();
        onReloadSys();
      }, 2500);
    } else {
      setBanner({ text: res.error || 'Backup failed to start.', ok: false });
    }
  };

  const ssdPct = sys ? Math.round((sys.disk_used_gb / Math.max(1, sys.disk_total_gb)) * 100) : 0;
  const hdd = sys?.backup_mounted ? sys.disk_backup : null;
  const hddPct = hdd && hdd.total_gb > 0 ? Math.round((hdd.used_gb / hdd.total_gb) * 100) : 0;

  return (
    <div class="space-y-5">
      {/* Action Hero Banner */}
      <div class="bento-hero p-4 sm:p-5 flex flex-wrap items-center justify-between gap-4">
        <div class="flex items-center gap-3 min-w-0">
          <span class="w-9 h-9 rounded-2xl bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-950 flex items-center justify-center shrink-0">
            <HardDrive size={18} />
          </span>
          <div class="min-w-0">
            <h2 class="text-sm sm:text-base font-bold text-zinc-900 dark:text-white">
              Automated Snapshot Engine
            </h2>
            <p class="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
              Snapshots MariaDB, Nextcloud config, Navidrome &amp; Maloja databases to /mnt/backup
            </p>
          </div>
        </div>
        <PillButton variant="primary" size="md" disabled={running} onClick={triggerBackup}>
          <DownloadCloud size={15} />
          {running ? 'Starting Snapshot...' : 'Run Backup Now'}
        </PillButton>
      </div>

      {banner && (
        <div
          class={`bento-card p-4 text-xs font-medium border ${
            banner.ok
              ? 'border-emerald-500/30 text-emerald-700 dark:text-emerald-400'
              : 'border-rose-500/30 text-rose-700 dark:text-rose-400'
          }`}
        >
          {banner.text}
        </div>
      )}

      {/* Storage Ring Cards */}
      <div class="grid grid-cols-1 md:grid-cols-2 gap-3.5 items-stretch">
        <div class="bento-card p-4 sm:p-5 h-full flex flex-col justify-between">
          <CardHeader
            title="System SSD (root /)"
            subtitle="Primary host filesystem"
            icon={<HardDrive size={16} />}
            action={<StatusBadge tone={ssdPct > 85 ? 'err' : ssdPct > 70 ? 'warn' : 'ok'} dot>{ssdPct}% used</StatusBadge>}
          />
          <div class="flex items-center justify-between gap-4">
            <div class="grid grid-cols-3 gap-2.5 flex-1">
              <div class="bento-sub p-3 text-center">
                <div class="text-[10px] text-zinc-400 uppercase font-semibold">Used</div>
                <div class="text-sm font-bold text-zinc-900 dark:text-white mt-0.5">
                  {sys ? `${sys.disk_used_gb.toFixed(1)}G` : '—'}
                </div>
              </div>
              <div class="bento-sub p-3 text-center">
                <div class="text-[10px] text-zinc-400 uppercase font-semibold">Free</div>
                <div class="text-sm font-bold text-emerald-600 dark:text-emerald-400 mt-0.5">
                  {sys ? `${(sys.disk_total_gb - sys.disk_used_gb).toFixed(1)}G` : '—'}
                </div>
              </div>
              <div class="bento-sub p-3 text-center">
                <div class="text-[10px] text-zinc-400 uppercase font-semibold">Total</div>
                <div class="text-sm font-bold text-zinc-900 dark:text-white mt-0.5">
                  {sys ? `${sys.disk_total_gb.toFixed(1)}G` : '—'}
                </div>
              </div>
            </div>
            <ConcentricRingGauge
              size={104}
              centerValue={`${ssdPct}%`}
              rings={[{ label: 'SSD', percent: ssdPct }]}
            />
          </div>
        </div>

        <div class="bento-card p-5 sm:p-6">
          <CardHeader
            title="Backup HDD (/mnt/backup)"
            subtitle={hdd ? 'External storage mounted' : 'Drive disconnected'}
            icon={<HardDrive size={16} />}
            action={
              <StatusBadge tone={hdd ? 'ok' : 'err'} dot>
                {hdd ? 'Online' : 'Offline'}
              </StatusBadge>
            }
          />
          {hdd ? (
            <div class="flex items-center justify-between gap-4">
              <div class="grid grid-cols-3 gap-2.5 flex-1">
                <div class="bento-sub p-3 text-center">
                  <div class="text-[10px] text-zinc-400 uppercase font-semibold">Used</div>
                  <div class="text-sm font-bold text-zinc-900 dark:text-white mt-0.5">
                    {hdd.used_gb.toFixed(1)}G
                  </div>
                </div>
                <div class="bento-sub p-3 text-center">
                  <div class="text-[10px] text-zinc-400 uppercase font-semibold">Free</div>
                  <div class="text-sm font-bold text-emerald-600 dark:text-emerald-400 mt-0.5">
                    {(hdd.total_gb - hdd.used_gb).toFixed(1)}G
                  </div>
                </div>
                <div class="bento-sub p-3 text-center">
                  <div class="text-[10px] text-zinc-400 uppercase font-semibold">Total</div>
                  <div class="text-sm font-bold text-zinc-900 dark:text-white mt-0.5">
                    {hdd.total_gb.toFixed(1)}G
                  </div>
                </div>
              </div>
              <ConcentricRingGauge
                size={104}
                centerValue={`${hddPct}%`}
                rings={[{ label: 'HDD', percent: hddPct }]}
              />
            </div>
          ) : (
            <div class="bento-sub p-5 text-xs text-zinc-500 dark:text-zinc-400">
              Backup HDD is not mounted. Connect the external drive to <code class="font-mono">/mnt/backup</code>.
            </div>
          )}
        </div>
      </div>

      {/* Backup Logs */}
      <div class="bento-card p-5 sm:p-6">
        <CardHeader
          title="Recent Backup Log Entries"
          icon={<FileText size={16} />}
          action={
            <PillButton size="xs" variant="secondary" onClick={loadBackup}>
              Refresh Logs
            </PillButton>
          }
        />
        {status?.last_logs && status.last_logs.length > 0 ? (
          <div class="bento-sub p-4 font-mono text-[11px] space-y-1.5 max-h-72 overflow-y-auto">
            {status.last_logs.map((line, i) => {
              const lower = line.toLowerCase();
              const isErr = lower.includes('error') || lower.includes('fail');
              const isOk = lower.includes('complete') || lower.includes('success') || line.includes('✓');
              return (
                <div
                  key={i}
                  class={`py-0.5 border-b border-zinc-200/50 dark:border-zinc-800/50 last:border-0 ${
                    isErr
                      ? 'text-rose-600 dark:text-rose-400'
                      : isOk
                      ? 'text-emerald-600 dark:text-emerald-400'
                      : 'text-zinc-600 dark:text-zinc-400'
                  }`}
                >
                  {line}
                </div>
              );
            })}
          </div>
        ) : (
          <p class="text-xs text-zinc-500">No backup log entries recorded yet.</p>
        )}
      </div>
    </div>
  );
}
