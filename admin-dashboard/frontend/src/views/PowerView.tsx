import { useEffect, useState } from 'preact/hooks';
import {
  Container,
  Cpu,
  Gauge,
  HardDrive,
  MemoryStick,
  Moon,
  Power,
  Sparkles,
  Sun,
  Zap,
} from 'lucide-preact';
import type { ResourcesStatus, SleepStatus } from '../types/api';
import { api } from '../api/client';
import { CardHeader, PillButton, StatCard, StatusBadge } from '../components/ui';

const PROTECTED = new Set(['pihole', 'admin-dashboard']);

export function PowerView({
  refreshKey,
  onNotify,
}: {
  refreshKey: number;
  onNotify: (msg: string, ok?: boolean) => void;
}) {
  const [resData, setResData] = useState<ResourcesStatus | null>(null);
  const [slpData, setSlpData] = useState<SleepStatus | null>(null);
  const [compacting, setCompacting] = useState(false);

  // Resource policy form
  const [reclaimPct, setReclaimPct] = useState('88');
  const [cpuThrPct, setCpuThrPct] = useState('85');
  const [tempThr, setTempThr] = useState('80');
  const [dlRate, setDlRate] = useState('');

  // Sleep policy form
  const [ecoEnabled, setEcoEnabled] = useState(true);
  const [sleepMode, setSleepMode] = useState('stop');
  const [schedEnabled, setSchedEnabled] = useState(false);
  const [sleepStart, setSleepStart] = useState('00:00');
  const [sleepEnd, setSleepEnd] = useState('07:00');
  const [idleEnabled, setIdleEnabled] = useState(false);
  const [idleMin, setIdleMin] = useState('60');
  const [ctrIdleEnabled, setCtrIdleEnabled] = useState(true);
  const [ctrIdleMin, setCtrIdleMin] = useState('15');
  const [srvIdleEnabled, setSrvIdleEnabled] = useState(true);
  const [srvIdleMin, setSrvIdleMin] = useState('30');
  const [wakeAll, setWakeAll] = useState('false');
  const [wakeTimeout, setWakeTimeout] = useState('25');
  const [hostSleep, setHostSleep] = useState(false);
  const [sleepTargets, setSleepTargets] = useState<string[]>([]);
  const [hydrated, setHydrated] = useState(false);

  // Editable container limits keyed by container name
  const [limitsMap, setLimitsMap] = useState<
    Record<string, { mem: string; shares: string; quota: string }>
  >({});

  const loadPower = async (bg = false) => {
    const [d, sLive] = await Promise.all([
      api<ResourcesStatus>('/api/resources/status', 'GET', null, { bg }),
      api<SleepStatus>('/api/sleep/status', 'GET', null, { bg }),
    ]);
    if (!d.error) {
      setResData(d);
      const slp = !sLive.error ? sLive : d.sleep || {};
      setSlpData(slp);

      if (!hydrated) {
        const s = d.settings || {};
        setReclaimPct(String(s.mem_auto_reclaim_pct ?? 88));
        setCpuThrPct(String(s.cpu_throttle_pct ?? 85));
        setTempThr(String(s.cpu_throttle_temp_c ?? 80));
        setDlRate(s.download_rate_limit || '');

        setEcoEnabled(!!slp.eco_sleep_enabled);
        setSleepMode(slp.sleep_mode || 'stop');
        setSchedEnabled(!!slp.schedule_enabled);
        setSleepStart(slp.sleep_start || '00:00');
        setSleepEnd(slp.sleep_end || '07:00');
        setIdleEnabled(!!slp.idle_sleep_enabled);
        setIdleMin(String(slp.idle_minutes ?? 60));
        setCtrIdleEnabled(slp.container_idle_sleep_enabled !== false);
        setCtrIdleMin(String(slp.container_idle_minutes ?? 15));
        setSrvIdleEnabled(slp.server_idle_sleep_enabled !== false);
        setSrvIdleMin(String(slp.server_idle_minutes ?? 30));
        setWakeAll(slp.wake_all_on_server_wake ? 'true' : 'false');
        setWakeTimeout(String(slp.wake_timeout_sec ?? 25));
        setHostSleep(!!slp.host_sleep_enabled);
        setSleepTargets(slp.sleep_targets || []);
        setHydrated(true);
      }

      if (d.containers) {
        setLimitsMap((prev) => {
          const next = { ...prev };
          for (const ct of d.containers!) {
            if (!next[ct.name]) {
              next[ct.name] = {
                mem: String(ct.mem_limit_mb || 0),
                shares: String(ct.cpu_shares || 512),
                quota: String(ct.cpu_quota_pct || 0),
              };
            }
          }
          return next;
        });
      }
    }
  };

  useEffect(() => {
    loadPower(false);
    const t = setInterval(() => loadPower(true), 8000);
    return () => clearInterval(t);
  }, [refreshKey]);

  const compactRam = async () => {
    setCompacting(true);
    const r = await api<{ ok?: boolean; freed_mb?: number; actions?: string[] }>(
      '/api/resources/memory/compact',
      'POST',
      {}
    );
    setCompacting(false);
    if (r.ok) {
      onNotify(`RAM compacted: freed ${r.freed_mb ?? 0} MB (${(r.actions || []).join(', ')})`);
    } else {
      onNotify(r.error || 'RAM compaction failed', false);
    }
    loadPower(false);
  };

  const setProfile = async (profile: 'eco' | 'balanced' | 'performance') => {
    const r = await api('/api/resources/profile', 'POST', { profile });
    if (r.ok) onNotify(`Switched to ${profile} power profile.`);
    else onNotify(r.error || 'Failed to switch profile', false);
    loadPower(false);
  };

  const saveResourceSettings = async () => {
    const r = await api('/api/resources/settings', 'POST', {
      mem_auto_reclaim_pct: parseInt(reclaimPct || '88', 10),
      cpu_throttle_pct: parseInt(cpuThrPct || '85', 10),
      cpu_throttle_temp_c: parseInt(tempThr || '80', 10),
      download_rate_limit: dlRate.trim(),
    });
    if (r.error) onNotify(r.error, false);
    else onNotify('Resource guard policy saved.');
  };

  const saveSleepSettings = async () => {
    const r = await api('/api/sleep/settings', 'POST', {
      eco_sleep_enabled: ecoEnabled,
      sleep_mode: sleepMode,
      sleep_targets: sleepTargets,
      schedule_enabled: schedEnabled,
      sleep_start: sleepStart,
      sleep_end: sleepEnd,
      idle_sleep_enabled: idleEnabled,
      idle_minutes: parseInt(idleMin || '60', 10),
      container_idle_sleep_enabled: ctrIdleEnabled,
      container_idle_minutes: parseInt(ctrIdleMin || '15', 10),
      server_idle_sleep_enabled: srvIdleEnabled,
      server_idle_minutes: parseInt(srvIdleMin || '30', 10),
      wake_all_on_server_wake: wakeAll === 'true',
      wake_timeout_sec: parseInt(wakeTimeout || '25', 10),
      host_sleep_enabled: hostSleep,
    });
    if (r.error) onNotify(r.error, false);
    else {
      onNotify('Auto-Sleep policy saved.');
      loadPower(false);
    }
  };

  const toggleTarget = (name: string) => {
    if (PROTECTED.has(name)) return;
    setSleepTargets((prev) =>
      prev.includes(name) ? prev.filter((x) => x !== name) : [...prev, name]
    );
  };

  const sleepNow = async (targets?: string[]) => {
    const r = await api<{ ok?: boolean; message?: string }>(
      '/api/sleep/now',
      'POST',
      targets ? { targets } : {}
    );
    if (r.ok) onNotify(r.message || 'Sleep triggered.');
    else onNotify(r.error || 'Sleep action failed', false);
    loadPower(false);
  };

  const wakeNow = async (service?: string) => {
    const r = await api<{ ok?: boolean; message?: string }>(
      '/api/sleep/wake',
      'POST',
      service ? { service } : {}
    );
    if (r.ok) onNotify(r.message || `Woke ${service || 'stack'}.`);
    else onNotify(r.error || 'Wake failed', false);
    loadPower(false);
  };

  const sleepHostNow = async () => {
    if (!confirm('Put physical server host to S3 sleep? Ensure Wake-on-LAN or RTC wake is configured.'))
      return;
    const r = await api<{ ok?: boolean; message?: string }>('/api/sleep/host', 'POST', {
      wake_minutes: 0,
    });
    if (r.ok) onNotify(r.message || 'Host suspend initiated.');
    else onNotify(r.error || 'Host suspend unsupported', false);
  };

  const saveContainerLimits = async (name: string) => {
    const vals = limitsMap[name];
    if (!vals) return;
    const r = await api(`/api/resources/container/${encodeURIComponent(name)}/limits`, 'POST', {
      mem_limit_mb: parseInt(vals.mem || '0', 10),
      cpu_shares: parseInt(vals.shares || '512', 10),
      cpu_quota_pct: parseInt(vals.quota || '0', 10),
    });
    if (r.ok) onNotify(`Updated resource limits for ${name}.`);
    else onNotify(r.error || `Failed updating ${name}`, false);
    loadPower(false);
  };

  const m = resData?.memory;
  const c = resData?.cpu;
  const profile = resData?.profile || 'balanced';
  const slp = slpData || {};
  const isSleeping = !!slp.sleeping_now || (slp.sleeping_containers?.length || 0) > 0;
  const candidates =
    resData?.containers && resData.containers.length > 0
      ? resData.containers.map((x) => x.name)
      : ['nextcloud', 'mariadb', 'navidrome', 'maloja', 'samba', 'redis', 'nginx-proxy', 'pihole', 'admin-dashboard'];
  const idleRows = Object.values(slp.containers_idle || {});

  return (
    <div class="space-y-4">
      {/* Top Compact Metrics with Icons */}
      <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3.5">
        <StatCard
          hero
          label="Host RAM"
          value={m ? `${m.percent}%` : '—'}
          sub={m ? `${m.used_mb} / ${m.total_mb} MB (${m.available_mb} MB free)` : 'Loading...'}
          icon={<MemoryStick size={15} />}
          action={
            <PillButton size="xs" variant="primary" disabled={compacting} onClick={compactRam}>
              <Sparkles size={11} /> {compacting ? 'Cleaning...' : 'Compact'}
            </PillButton>
          }
        />

        <StatCard
          label="Cache & Swap"
          value={m ? `${m.cached_mb} MB` : '—'}
          sub={m ? `Swap: ${m.swap_used_mb} / ${m.swap_total_mb} MB (${m.swap_percent}%)` : '—'}
          icon={<HardDrive size={15} />}
        />

        <StatCard
          label="CPU & Load"
          value={c ? `${c.percent}%` : '—'}
          sub={`Load ${(c?.load_avg || [0, 0, 0]).join(' · ')}`}
          icon={<Cpu size={15} />}
        />

        <StatCard
          label="Active Profile"
          value={profile.toUpperCase()}
          sub={
            c?.max_temp_c !== null && c?.max_temp_c !== undefined
              ? `${c.max_temp_c}°C ${c.throttled ? '(Throttled)' : 'OK'}`
              : c?.throttled
              ? 'CPU Throttled'
              : 'Thermal OK'
          }
          icon={<Gauge size={15} />}
          tone={c?.throttled ? 'warn' : 'default'}
        />
      </div>

      {/* Power Profiles + Auto-Sleep (equal height, scrollable policy body) */}
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-3.5 items-stretch">
        <div class="bento-card p-4 sm:p-5 lg:h-[420px] flex flex-col justify-between gap-3.5">
          <div class="space-y-3.5">
            <CardHeader
              title="CPU Power Profile & Guards"
              subtitle="Thermal throttling, RAM auto-reclaim & bandwidth cap"
              icon={<Cpu size={14} />}
              action={<StatusBadge tone="neutral" className="uppercase">{profile}</StatusBadge>}
            />

            <div class="flex flex-wrap gap-2">
              {(['eco', 'balanced', 'performance'] as const).map((p) => (
                <PillButton
                  key={p}
                  size="sm"
                  variant={profile === p ? 'primary' : 'secondary'}
                  onClick={() => setProfile(p)}
                  className="capitalize"
                >
                  <Zap size={12} /> {p}
                </PillButton>
              ))}
            </div>

            <div class="grid grid-cols-2 gap-3 text-xs">
              <div>
                <label class="block text-[10px] font-semibold uppercase tracking-wider text-zinc-400 mb-1">
                  Auto RAM Reclaim (%)
                </label>
                <input
                  type="text"
                  value={reclaimPct}
                  onInput={(e) => setReclaimPct((e.target as HTMLInputElement).value)}
                  class="bento-input w-full"
                />
              </div>
              <div>
                <label class="block text-[10px] font-semibold uppercase tracking-wider text-zinc-400 mb-1">
                  CPU Throttle Guard (%)
                </label>
                <input
                  type="text"
                  value={cpuThrPct}
                  onInput={(e) => setCpuThrPct((e.target as HTMLInputElement).value)}
                  class="bento-input w-full"
                />
              </div>
              <div>
                <label class="block text-[10px] font-semibold uppercase tracking-wider text-zinc-400 mb-1">
                  Thermal Throttle (°C)
                </label>
                <input
                  type="text"
                  value={tempThr}
                  onInput={(e) => setTempThr((e.target as HTMLInputElement).value)}
                  class="bento-input w-full"
                />
              </div>
              <div>
                <label class="block text-[10px] font-semibold uppercase tracking-wider text-zinc-400 mb-1">
                  Default DL Rate Cap
                </label>
                <input
                  type="text"
                  value={dlRate}
                  placeholder="e.g. 1M"
                  onInput={(e) => setDlRate((e.target as HTMLInputElement).value)}
                  class="bento-input w-full"
                />
              </div>
            </div>

            <div class="bento-sub p-3 grid grid-cols-3 gap-2 text-center text-[11px]">
              <div>
                <div class="text-[9.5px] font-semibold uppercase text-zinc-400">RAM Guard</div>
                <div class="font-bold text-zinc-900 dark:text-white tabular-nums mt-0.5">
                  {m?.percent ?? 0}% / {reclaimPct}%
                </div>
              </div>
              <div class="border-x border-zinc-200/70 dark:border-zinc-800">
                <div class="text-[9.5px] font-semibold uppercase text-zinc-400">CPU Guard</div>
                <div class="font-bold text-zinc-900 dark:text-white tabular-nums mt-0.5">
                  {c?.percent ?? 0}% / {cpuThrPct}%
                </div>
              </div>
              <div>
                <div class="text-[9.5px] font-semibold uppercase text-zinc-400">Temp Guard</div>
                <div class="font-bold text-zinc-900 dark:text-white tabular-nums mt-0.5">
                  {c?.max_temp_c ?? '—'}° / {tempThr}°C
                </div>
              </div>
            </div>
          </div>

          <div class="pt-2 border-t border-zinc-200/70 dark:border-zinc-800">
            <PillButton size="sm" variant="primary" onClick={saveResourceSettings}>
              Save Resource Policy
            </PillButton>
          </div>
        </div>

        {/* Auto-Sleep Mode Card — matched height with smooth internal scroll */}
        <div class="bento-card p-4 sm:p-5 lg:h-[420px] flex flex-col gap-3">
          <div>
            <CardHeader
              title="Auto-Sleep & WakeProxy"
              subtitle="Scrollable idle timers, schedule & target services"
              icon={<Moon size={14} />}
              action={
                <StatusBadge tone={isSleeping ? 'warn' : 'ok'} dot>
                  {slp.sleeping_now ? 'Server Sleeping' : isSleeping ? 'Partial Sleep' : 'Awake'}
                </StatusBadge>
              }
            />

            <div class="flex flex-wrap gap-2">
              <PillButton size="xs" variant="warn" onClick={() => sleepNow()}>
                <Moon size={12} /> Sleep Now
              </PillButton>
              <PillButton size="xs" variant="ok" onClick={() => wakeNow()}>
                <Sun size={12} /> Wake All
              </PillButton>
              {hostSleep && (
                <PillButton size="xs" variant="danger" onClick={sleepHostNow}>
                  <Power size={12} /> Host S3 Suspend
                </PillButton>
              )}
            </div>
          </div>

          <div class="flex-1 min-h-0 overflow-y-auto pr-1.5 space-y-2.5 text-xs">
            <div class="flex flex-wrap items-center gap-3">
              <label class="inline-flex items-center gap-2 cursor-pointer font-medium">
                <input
                  type="checkbox"
                  checked={ecoEnabled}
                  onChange={(e) => setEcoEnabled((e.target as HTMLInputElement).checked)}
                  class="accent-zinc-900 dark:accent-white"
                />
                <span>Container Eco-Sleep</span>
              </label>
              <select
                value={sleepMode}
                onChange={(e) => setSleepMode((e.target as HTMLSelectElement).value)}
                class="bento-input py-1 px-2.5 text-xs"
              >
                <option value="stop">Deep Save (Stop containers)</option>
                <option value="pause">Instant Wake (Freeze CPU)</option>
              </select>
            </div>

            <div class="flex flex-wrap items-center gap-2">
              <label class="inline-flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={schedEnabled}
                  onChange={(e) => setSchedEnabled((e.target as HTMLInputElement).checked)}
                  class="accent-zinc-900 dark:accent-white"
                />
                <span>Night window:</span>
              </label>
              <input
                type="text"
                value={sleepStart}
                onInput={(e) => setSleepStart((e.target as HTMLInputElement).value)}
                class="bento-input py-1 px-2 w-16 text-center text-xs font-mono"
              />
              <span class="text-zinc-400">to</span>
              <input
                type="text"
                value={sleepEnd}
                onInput={(e) => setSleepEnd((e.target as HTMLInputElement).value)}
                class="bento-input py-1 px-2 w-16 text-center text-xs font-mono"
              />
            </div>

            <div class="bento-sub p-3 flex flex-wrap items-center gap-3">
              <label class="inline-flex items-center gap-1.5 cursor-pointer">
                <input
                  type="checkbox"
                  checked={ctrIdleEnabled}
                  onChange={(e) => setCtrIdleEnabled((e.target as HTMLInputElement).checked)}
                  class="accent-zinc-900 dark:accent-white"
                />
                <span>Idle container:</span>
              </label>
              <input
                type="text"
                value={ctrIdleMin}
                onInput={(e) => setCtrIdleMin((e.target as HTMLInputElement).value)}
                class="bento-input py-0.5 px-2 w-12 text-center text-xs"
              />
              <span class="text-zinc-400">min</span>

              <label class="inline-flex items-center gap-1.5 cursor-pointer ml-auto">
                <input
                  type="checkbox"
                  checked={srvIdleEnabled}
                  onChange={(e) => setSrvIdleEnabled((e.target as HTMLInputElement).checked)}
                  class="accent-zinc-900 dark:accent-white"
                />
                <span>Server:</span>
              </label>
              <input
                type="text"
                value={srvIdleMin}
                onInput={(e) => setSrvIdleMin((e.target as HTMLInputElement).value)}
                class="bento-input py-0.5 px-2 w-12 text-center text-xs"
              />
              <span class="text-zinc-400">min</span>
            </div>

            <div class="flex flex-wrap items-center gap-2">
              <label class="inline-flex items-center gap-1.5 cursor-pointer">
                <input
                  type="checkbox"
                  checked={idleEnabled}
                  onChange={(e) => setIdleEnabled((e.target as HTMLInputElement).checked)}
                  class="accent-zinc-900 dark:accent-white"
                />
                <span>Legacy idle:</span>
              </label>
              <input
                type="text"
                value={idleMin}
                onInput={(e) => setIdleMin((e.target as HTMLInputElement).value)}
                class="bento-input py-0.5 px-2 w-12 text-center text-xs"
              />
              <span class="text-zinc-400">min</span>
              <label class="inline-flex items-center gap-1.5 cursor-pointer ml-auto">
                <input
                  type="checkbox"
                  checked={hostSleep}
                  onChange={(e) => setHostSleep((e.target as HTMLInputElement).checked)}
                  class="accent-zinc-900 dark:accent-white"
                />
                <span>Enable Host S3</span>
              </label>
            </div>

            <div class="flex flex-wrap items-center gap-2">
              <select
                value={wakeAll}
                onChange={(e) => setWakeAll((e.target as HTMLSelectElement).value)}
                class="bento-input py-1 px-2.5 text-xs flex-1"
              >
                <option value="false">Wake requested service + DB only (Low RAM)</option>
                <option value="true">Wake entire stack</option>
              </select>
              <span class="text-zinc-400 text-[11px]">Timeout (s):</span>
              <input
                type="text"
                value={wakeTimeout}
                onInput={(e) => setWakeTimeout((e.target as HTMLInputElement).value)}
                class="bento-input py-1 px-2 w-12 text-center text-xs"
              />
            </div>

            {/* Target Checkboxes */}
            <div class="bento-sub p-3 flex flex-wrap gap-3">
              {candidates.map((name) => {
                const prot = PROTECTED.has(name);
                return (
                  <label
                    key={name}
                    class={`inline-flex items-center gap-1.5 text-[11px] ${
                      prot ? 'opacity-45 cursor-not-allowed' : 'cursor-pointer'
                    }`}
                  >
                    <input
                      type="checkbox"
                      disabled={prot}
                      checked={!prot && sleepTargets.includes(name)}
                      onChange={() => toggleTarget(name)}
                      class="accent-zinc-900 dark:accent-white"
                    />
                    <span>
                      {name}
                      {prot ? ' (protected)' : ''}
                    </span>
                  </label>
                );
              })}
            </div>

            {/* Live Per-Service Idle Status */}
            <div class="bento-sub p-3 space-y-2">
              <div class="flex items-center justify-between text-[11px]">
                <span class="text-zinc-500">
                  Server Idle:{' '}
                  <strong class="text-zinc-900 dark:text-white">
                    {slp.idle_elapsed_minutes ?? 0}m / {slp.server_idle_minutes ?? 30}m
                  </strong>
                </span>
                <StatusBadge tone={slp.wake_proxy_active ? 'ok' : 'neutral'}>
                  {slp.wake_proxy_active ? 'Wake-Proxy Active' : 'Wake-Proxy Ready'}
                </StatusBadge>
              </div>
              {idleRows.map((row) => (
                <div
                  key={row.service}
                  class="flex items-center justify-between pt-2 border-t border-zinc-200/60 dark:border-zinc-800/60 text-[11px]"
                >
                  <span class="font-semibold text-zinc-900 dark:text-white">{row.service}</span>
                  <StatusBadge tone={row.sleeping ? 'warn' : 'ok'}>
                    {row.sleeping ? 'Sleeping' : 'Awake'} ({row.idle_minutes || 0}m /{' '}
                    {slp.container_idle_minutes || 15}m)
                  </StatusBadge>
                  {row.sleeping ? (
                    <PillButton size="xs" variant="ok" onClick={() => wakeNow(row.service)}>
                      Wake
                    </PillButton>
                  ) : (
                    <PillButton size="xs" variant="warn" onClick={() => sleepNow([row.service])}>
                      Sleep
                    </PillButton>
                  )}
                </div>
              ))}
            </div>
          </div>

          <div class="pt-2 border-t border-zinc-200/70 dark:border-zinc-800 shrink-0">
            <PillButton size="sm" variant="primary" onClick={saveSleepSettings}>
              Save Sleep Policy
            </PillButton>
          </div>
        </div>
      </div>

      {/* Per-Container Resource Limits Table */}
      <div class="bento-card p-4 sm:p-5">
        <CardHeader title="Per-Container Live CPU & RAM Limits" icon={<Container size={14} />} />
        {resData?.containers && resData.containers.length > 0 ? (
          <div class="overflow-x-auto max-h-[340px] overflow-y-auto pr-1">
            <table class="w-full text-left border-collapse text-xs">
              <thead>
                <tr class="border-b border-zinc-200/80 dark:border-zinc-800 text-[10px] font-semibold uppercase tracking-widest text-zinc-400">
                  <th class="py-2 pr-3">Container</th>
                  <th class="py-2 pr-3">Status</th>
                  <th class="py-2 pr-3">RAM Used / Limit (MB)</th>
                  <th class="py-2 pr-3">CPU Shares</th>
                  <th class="py-2 pr-3">CPU Quota (%)</th>
                  <th class="py-2 text-right">Action</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-zinc-200/60 dark:divide-zinc-800/70">
                {resData.containers.map((ct) => {
                  const vals = limitsMap[ct.name] || {
                    mem: String(ct.mem_limit_mb || 0),
                    shares: String(ct.cpu_shares || 512),
                    quota: String(ct.cpu_quota_pct || 0),
                  };
                  return (
                    <tr key={ct.name}>
                      <td class="py-2.5 pr-3 font-semibold text-zinc-900 dark:text-white">
                        {ct.name}
                      </td>
                      <td class="py-2.5 pr-3">
                        <StatusBadge tone={ct.status === 'running' ? 'ok' : 'warn'}>
                          {ct.status}
                        </StatusBadge>
                      </td>
                      <td class="py-2.5 pr-3 whitespace-nowrap">
                        <span class="text-zinc-500 mr-1.5">{ct.mem_mb || 0} /</span>
                        <input
                          type="text"
                          value={vals.mem}
                          onInput={(e) =>
                            setLimitsMap((p) => ({
                              ...p,
                              [ct.name]: { ...vals, mem: (e.target as HTMLInputElement).value },
                            }))
                          }
                          class="bento-input py-1 px-2 w-16 text-xs"
                        />
                      </td>
                      <td class="py-2.5 pr-3">
                        <input
                          type="text"
                          value={vals.shares}
                          onInput={(e) =>
                            setLimitsMap((p) => ({
                              ...p,
                              [ct.name]: { ...vals, shares: (e.target as HTMLInputElement).value },
                            }))
                          }
                          class="bento-input py-1 px-2 w-16 text-xs"
                        />
                      </td>
                      <td class="py-2.5 pr-3">
                        <input
                          type="text"
                          value={vals.quota}
                          onInput={(e) =>
                            setLimitsMap((p) => ({
                              ...p,
                              [ct.name]: { ...vals, quota: (e.target as HTMLInputElement).value },
                            }))
                          }
                          class="bento-input py-1 px-2 w-14 text-xs"
                        />
                      </td>
                      <td class="py-2.5 text-right">
                        <PillButton size="xs" variant="primary" onClick={() => saveContainerLimits(ct.name)}>
                          Apply
                        </PillButton>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <p class="text-xs text-zinc-400">No Docker containers detected.</p>
        )}
      </div>
    </div>
  );
}
