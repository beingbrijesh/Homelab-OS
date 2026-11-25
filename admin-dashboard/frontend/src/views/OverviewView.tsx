import {
  Activity,
  ArrowUpRight,
  BatteryCharging,
  Clock,
  Container,
  Cpu,
  HardDrive,
  MemoryStick,
  Plug,
  Server,
  Thermometer,
  Zap,
} from 'lucide-preact';
import type { ContainerInfo, NavSection, SystemTelemetry } from '../types/api';
import { friendlyTempName } from '../utils/format';
import { CardHeader, PillButton, ProgressBar, ServiceIcon, StatusBadge } from '../components/ui';
import { ConcentricRingGauge, SmoothLineChart } from '../components/Charts';

export interface TelemetryHistory {
  labels: string[];
  cpu: number[];
  ram: number[];
  disk: number[];
}

export function OverviewView({
  sys,
  containers,
  history,
  isDark,
  onNavigate,
}: {
  sys: SystemTelemetry | null;
  containers: ContainerInfo[];
  history: TelemetryHistory;
  isDark: boolean;
  onNavigate: (s: NavSection) => void;
}) {
  const temps = sys?.temperatures || {};
  const tempEntries = Object.entries(temps);
  const maxTemp = tempEntries.length ? Math.max(...tempEntries.map(([, v]) => v)) : null;
  const hottestKey = maxTemp !== null ? tempEntries.find(([, v]) => v === maxTemp)?.[0] : null;

  const managed = containers.filter((c) => c.managed);
  const runningCount = managed.filter((c) => c.status === 'running').length;
  const stoppedCount = managed.length - runningCount;

  const ssdPct = sys ? Math.round(sys.disk_percent || 0) : 0;
  const hddPct =
    sys?.backup_mounted && sys.disk_backup && sys.disk_backup.total_gb > 0
      ? Math.round((sys.disk_backup.used_gb / sys.disk_backup.total_gb) * 100)
      : 0;
  const ramPct = sys ? Math.round(sys.ram_percent || 0) : 0;
  const cpuPct = sys ? Math.round(sys.cpu_percent || 0) : 0;

  const powerTone = !sys?.battery
    ? 'ok'
    : sys.battery.charging
    ? 'ok'
    : sys.battery.percent < 20
    ? 'err'
    : 'warn';

  const flowStroke =
    powerTone === 'err' ? '#ef4444' : powerTone === 'warn' ? '#f59e0b' : '#10b981';

  // Symmetrical grid columns so sensor cards never leave a lonely orphan row (e.g. 4 -> 2x2)
  const thermalGridClass =
    tempEntries.length <= 1
      ? 'grid-cols-1'
      : tempEntries.length === 2 || tempEntries.length === 4
      ? 'grid-cols-1 sm:grid-cols-2'
      : tempEntries.length === 3 || tempEntries.length === 5 || tempEntries.length === 6
      ? 'grid-cols-1 sm:grid-cols-2 xl:grid-cols-3'
      : 'grid-cols-1 sm:grid-cols-2 xl:grid-cols-4';

  return (
    <div class="space-y-4">
      {/* Row 1: Flush top & bottom alignment across System Overview, Resource Usage & Capacity */}
      <div class="grid grid-cols-1 lg:grid-cols-12 gap-3.5 items-stretch">
        {/* Featured System Overview Card */}
        <div class="bento-hero p-4 sm:p-5 lg:col-span-5 h-full flex flex-col justify-between">
          <div>
            <div class="flex items-center justify-between gap-2 mb-3.5">
              <div class="flex items-center gap-2">
                <span class="w-7 h-7 rounded-xl bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-950 flex items-center justify-center shrink-0">
                  <Cpu size={14} />
                </span>
                <span class="text-[13px] font-bold text-zinc-900 dark:text-white tracking-tight">
                  System Overview
                </span>
              </div>
              <span class="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-zinc-200/70 dark:bg-zinc-800 text-[10.5px] font-semibold text-zinc-700 dark:text-zinc-300">
                <Clock size={11} />
                {sys?.uptime || 'Loading...'}
              </span>
            </div>

            <div class="grid grid-cols-2 gap-3 mb-4 pb-3.5 border-b border-zinc-200/80 dark:border-zinc-800">
              <div class="flex items-baseline gap-2">
                <span class="text-2xl sm:text-3xl font-bold tracking-tight text-zinc-900 dark:text-white tabular-nums">
                  {runningCount}
                </span>
                <span class="text-[11px] text-zinc-500 dark:text-zinc-400 leading-tight">
                  services<br />running
                </span>
              </div>
              <div class="border-l border-zinc-200/80 dark:border-zinc-800 pl-3 flex items-baseline gap-2">
                <span class="text-2xl sm:text-3xl font-bold tracking-tight text-zinc-900 dark:text-white tabular-nums">
                  {maxTemp !== null ? `${Math.round(maxTemp)}°C` : stoppedCount}
                </span>
                <span class="text-[11px] text-zinc-500 dark:text-zinc-400 leading-tight">
                  {maxTemp !== null ? (
                    <>
                      peak temp<br />
                      {maxTemp > 80 ? 'critical' : maxTemp > 65 ? 'warm' : 'normal'}
                    </>
                  ) : (
                    <>
                      services<br />stopped
                    </>
                  )}
                </span>
              </div>
            </div>
          </div>

          {/* 3 theme-consistent nested sub-cards */}
          <div class="grid grid-cols-3 gap-2">
            <div class="bento-sub p-2.5 sm:p-3 text-center">
              <div class="w-6 h-6 rounded-lg bg-indigo-500/10 text-indigo-600 dark:text-indigo-400 flex items-center justify-center mx-auto mb-1">
                <Cpu size={13} />
              </div>
              <div class="text-lg sm:text-xl font-bold tracking-tight text-zinc-900 dark:text-white tabular-nums">
                {sys ? `${cpuPct}%` : '—'}
              </div>
              <div class="text-[10px] font-medium text-zinc-500 dark:text-zinc-400 truncate">
                {sys?.cpu_count ? `${sys.cpu_count}c · ${sys.cpu_freq_ghz || '?'}GHz` : 'CPU'}
              </div>
            </div>

            <div class="bento-sub p-2.5 sm:p-3 text-center">
              <div class="w-6 h-6 rounded-lg bg-sky-500/10 text-sky-600 dark:text-sky-400 flex items-center justify-center mx-auto mb-1">
                <MemoryStick size={13} />
              </div>
              <div class="text-lg sm:text-xl font-bold tracking-tight text-zinc-900 dark:text-white tabular-nums">
                {sys ? `${sys.ram_used_gb.toFixed(1)}G` : '—'}
              </div>
              <div class="text-[10px] font-medium text-zinc-500 dark:text-zinc-400 truncate">
                {sys ? `${ramPct}% of ${sys.ram_total_gb.toFixed(0)}G` : 'RAM'}
              </div>
            </div>

            <div class="bento-sub p-2.5 sm:p-3 text-center">
              <div class="w-6 h-6 rounded-lg bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 flex items-center justify-center mx-auto mb-1">
                <HardDrive size={13} />
              </div>
              <div class="text-lg sm:text-xl font-bold tracking-tight text-zinc-900 dark:text-white tabular-nums">
                {sys ? `${ssdPct}%` : '—'}
              </div>
              <div class="text-[10px] font-medium text-zinc-500 dark:text-zinc-400 truncate">
                {sys ? `${(sys.disk_total_gb - sys.disk_used_gb).toFixed(0)}G free` : 'SSD'}
              </div>
            </div>
          </div>
        </div>

        {/* Live Resource Usage Graph — aligned flush with sibling cards */}
        <div class="bento-card p-4 sm:p-5 lg:col-span-4 h-full flex flex-col justify-between">
          <CardHeader
            title="Resource Usage"
            subtitle="Live CPU, RAM & Disk (8s interval)"
            icon={<Activity size={14} />}
          />
          <div class="flex-1 flex flex-col justify-end">
            <SmoothLineChart
              labels={history.labels}
              height={152}
              maxY={100}
              isDark={isDark}
              series={[
                { label: 'CPU', data: history.cpu, stroke: '#4f46e5', darkStroke: '#818cf8', fill: true },
                { label: 'RAM', data: history.ram, stroke: '#0284c7', darkStroke: '#38bdf8', fill: true },
                { label: 'Disk', data: history.disk, stroke: '#059669', darkStroke: '#34d399', dashed: true },
              ]}
            />
          </div>
        </div>

        {/* Capacity Concentric Ring Card — aligned flush with sibling cards */}
        <div class="bento-card p-4 sm:p-5 lg:col-span-3 h-full flex flex-col justify-between">
          <CardHeader
            title="Capacity"
            subtitle={sys?.backup_mounted ? 'HDD mounted' : 'HDD offline'}
            icon={<HardDrive size={14} />}
          />

          <div class="flex-1 flex items-center justify-between gap-2 my-1">
            <div class="space-y-2 text-xs min-w-0">
              <div class="flex items-center gap-2">
                <span class="w-2 h-2 rounded-full bg-indigo-500 shrink-0" />
                <div class="min-w-0">
                  <div class="text-[11px] font-bold text-zinc-900 dark:text-white leading-none">SSD</div>
                  <div class="text-[10px] text-zinc-500 dark:text-zinc-400 mt-0.5 tabular-nums">
                    {sys ? `${sys.disk_used_gb.toFixed(0)}/${sys.disk_total_gb.toFixed(0)}G` : '—'}
                  </div>
                </div>
              </div>
              <div class="flex items-center gap-2">
                <span class="w-2 h-2 rounded-full bg-sky-500 shrink-0" />
                <div class="min-w-0">
                  <div class="text-[11px] font-bold text-zinc-900 dark:text-white leading-none">RAM</div>
                  <div class="text-[10px] text-zinc-500 dark:text-zinc-400 mt-0.5 tabular-nums">
                    {sys ? `${ramPct}% used` : '—'}
                  </div>
                </div>
              </div>
              <div class="flex items-center gap-2">
                <span
                  class={`w-2 h-2 rounded-full shrink-0 ${
                    sys?.backup_mounted ? 'bg-emerald-500' : 'bg-rose-500'
                  }`}
                />
                <div class="min-w-0">
                  <div class="text-[11px] font-bold text-zinc-900 dark:text-white leading-none">HDD</div>
                  <div class="text-[10px] text-zinc-500 dark:text-zinc-400 mt-0.5 tabular-nums">
                    {sys?.backup_mounted && sys.disk_backup
                      ? `${sys.disk_backup.used_gb.toFixed(0)}/${sys.disk_backup.total_gb.toFixed(0)}G`
                      : 'Offline'}
                  </div>
                </div>
              </div>
            </div>

            <ConcentricRingGauge
              size={116}
              centerValue={`${ssdPct}%`}
              centerLabel="SSD"
              rings={[
                { label: 'SSD', percent: ssdPct },
                { label: 'RAM', percent: ramPct },
                { label: 'HDD', percent: hddPct },
              ]}
            />
          </div>

          <div class="mt-3 pt-2.5 border-t border-zinc-200/70 dark:border-zinc-800 flex items-center justify-between gap-2">
            <StatusBadge tone={sys?.backup_mounted ? 'ok' : 'err'} dot>
              {sys?.backup_mounted ? 'Online' : 'Offline'}
            </StatusBadge>
            <PillButton size="xs" variant="secondary" onClick={() => onNavigate('backup')}>
              Backups <ArrowUpRight size={11} />
            </PillButton>
          </div>
        </div>
      </div>

      {/* Row 2: Flush top & bottom alignment across Power & Supply + Balanced 2x2 Hardware Thermals */}
      <div class="grid grid-cols-1 lg:grid-cols-12 gap-3.5 items-stretch">
        <div class="bento-card p-4 sm:p-5 lg:col-span-4 h-full flex flex-col justify-between gap-3">
          <CardHeader
            title="Power & Supply"
            subtitle={
              sys?.battery
                ? sys.battery.charging
                  ? 'Charging via AC adapter'
                  : 'Running on battery backup'
                : 'Continuous AC mains rail'
            }
            icon={sys?.battery ? <BatteryCharging size={14} /> : <Plug size={14} />}
            action={
              <StatusBadge tone={powerTone} dot pulse>
                {!sys?.battery ? 'AC Mains' : sys.battery.charging ? 'Charging' : 'Battery'}
              </StatusBadge>
            }
          />

          {/* Live Animated Energy Flow Infographic */}
          <div class="bento-sub p-3.5 flex-1 flex flex-col justify-center">
            <div class="flex items-center justify-between gap-2">
              {/* Source Node */}
              <div class="flex flex-col items-center gap-1 min-w-[60px]">
                <div
                  class={`w-9 h-9 rounded-2xl flex items-center justify-center border animate-subtle-float ${
                    powerTone === 'err'
                      ? 'bg-rose-500/10 text-rose-500 border-rose-500/25'
                      : powerTone === 'warn'
                      ? 'bg-amber-500/10 text-amber-500 border-amber-500/25'
                      : 'bg-emerald-500/10 text-emerald-500 border-emerald-500/25'
                  }`}
                >
                  {sys?.battery ? <BatteryCharging size={17} /> : <Plug size={17} />}
                </div>
                <span class="text-[10px] font-bold text-zinc-700 dark:text-zinc-300">
                  {sys?.battery ? `${sys.battery.percent}%` : 'AC Grid'}
                </span>
              </div>

              {/* Animated Flow Line 1 */}
              <svg class="flex-1 h-6 min-w-[28px]" viewBox="0 0 64 24" preserveAspectRatio="none">
                <line
                  x1="2"
                  y1="12"
                  x2="62"
                  y2="12"
                  stroke={isDark ? 'rgba(255,255,255,0.1)' : 'rgba(15,23,42,0.1)'}
                  stroke-width="2"
                  stroke-linecap="round"
                />
                <line
                  x1="2"
                  y1="12"
                  x2="62"
                  y2="12"
                  stroke={flowStroke}
                  stroke-width="2.5"
                  stroke-linecap="round"
                  class="animate-energy-flow"
                />
              </svg>

              {/* Host Rail Center Node */}
              <div class="flex flex-col items-center gap-1 min-w-[60px]">
                <div class="w-9 h-9 rounded-2xl bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-950 flex items-center justify-center shadow-sm">
                  <Server size={16} />
                </div>
                <span class="text-[10px] font-bold text-zinc-700 dark:text-zinc-300 tabular-nums">
                  {cpuPct}% Load
                </span>
              </div>

              {/* Animated Flow Line 2 */}
              <svg class="flex-1 h-6 min-w-[28px]" viewBox="0 0 64 24" preserveAspectRatio="none">
                <line
                  x1="2"
                  y1="12"
                  x2="62"
                  y2="12"
                  stroke={isDark ? 'rgba(255,255,255,0.1)' : 'rgba(15,23,42,0.1)'}
                  stroke-width="2"
                  stroke-linecap="round"
                />
                <line
                  x1="2"
                  y1="12"
                  x2="62"
                  y2="12"
                  stroke="#38bdf8"
                  stroke-width="2.5"
                  stroke-linecap="round"
                  class="animate-energy-flow"
                />
              </svg>

              {/* Workloads Node */}
              <div class="flex flex-col items-center gap-1 min-w-[60px]">
                <div class="w-9 h-9 rounded-2xl bg-sky-500/10 text-sky-600 dark:text-sky-400 border border-sky-500/25 flex items-center justify-center">
                  <Container size={16} />
                </div>
                <span class="text-[10px] font-bold text-zinc-700 dark:text-zinc-300 tabular-nums">
                  {runningCount}/{managed.length} Live
                </span>
              </div>
            </div>

            {sys?.battery && (
              <div class="mt-3 pt-2.5 border-t border-zinc-200/70 dark:border-zinc-800/80 space-y-1.5">
                <div class="flex items-center justify-between text-[11px]">
                  <span class="font-semibold text-zinc-700 dark:text-zinc-300">
                    Battery Charge
                  </span>
                  <span class="text-zinc-500 dark:text-zinc-400 tabular-nums">
                    {sys.battery.charging
                      ? 'Plugged in · Charging'
                      : sys.battery.time_left
                      ? `${Math.floor(sys.battery.time_left / 60)}h ${sys.battery.time_left % 60}m remaining`
                      : 'Discharging'}
                  </span>
                </div>
                <ProgressBar percent={sys.battery.percent} tone={powerTone} height="h-2" />
              </div>
            )}
          </div>

          {/* Compact telemetry metrics + Eco-Sleep CTA */}
          <div class="flex items-center justify-between gap-2 pt-2 border-t border-zinc-200/70 dark:border-zinc-800">
            <div class="flex items-center gap-2.5 text-[11px] text-zinc-500 dark:text-zinc-400">
              <span>
                Thermal:{' '}
                <strong class="text-zinc-900 dark:text-white tabular-nums">
                  {maxTemp !== null ? `${Math.round(maxTemp)}°C` : 'OK'}
                </strong>
              </span>
              <span>·</span>
              <span>
                RAM:{' '}
                <strong class="text-zinc-900 dark:text-white tabular-nums">{ramPct}%</strong>
              </span>
            </div>
            <PillButton size="xs" variant="secondary" onClick={() => onNavigate('power')}>
              <Zap size={11} /> Eco-Sleep
            </PillButton>
          </div>
        </div>

        {/* Hardware Thermals — balanced symmetrical grid (e.g. 4 sensors = 2x2) */}
        <div class="bento-card p-4 sm:p-5 lg:col-span-8 h-full flex flex-col">
          <CardHeader
            title="Hardware Thermals"
            subtitle={hottestKey ? `Peak: ${friendlyTempName(hottestKey)}` : 'Host thermal probes'}
            icon={<Thermometer size={14} />}
          />
          {tempEntries.length > 0 ? (
            <div class={`grid ${thermalGridClass} gap-2.5 flex-1`}>
              {tempEntries.map(([key, val]) => {
                const tone = val > 80 ? 'err' : val > 65 ? 'warn' : 'ok';
                const statusText = val > 80 ? 'Critical' : val > 65 ? 'Hot' : val > 50 ? 'Warm' : 'Normal';
                return (
                  <div key={key} class="bento-sub p-3.5 flex flex-col justify-between">
                    <div class="flex items-start justify-between gap-2 mb-2.5">
                      <div class="min-w-0">
                        <div class="text-xs font-semibold text-zinc-900 dark:text-white truncate">
                          {friendlyTempName(key)}
                        </div>
                        <div class="text-[10px] font-mono text-zinc-400 truncate">{key}</div>
                      </div>
                      <div class="text-right shrink-0">
                        <div class="text-base font-bold tracking-tight text-zinc-900 dark:text-white leading-none tabular-nums">
                          {Math.round(val)}°C
                        </div>
                        <StatusBadge tone={tone} className="mt-1">
                          {statusText}
                        </StatusBadge>
                      </div>
                    </div>
                    <ProgressBar percent={val} tone={tone} />
                  </div>
                );
              })}
            </div>
          ) : (
            <div class="bento-sub p-3.5 text-xs text-zinc-500 dark:text-zinc-400">
              No hardware temperature sensors detected on this host.
            </div>
          )}
        </div>
      </div>

      {/* Row 3: Symmetrical 3x3 Managed Services Grid */}
      <div>
        <div class="flex items-center justify-between mb-2.5 px-0.5">
          <h2 class="text-xs font-bold uppercase tracking-wider text-zinc-500 dark:text-zinc-400 flex items-center gap-1.5">
            <Container size={14} />
            Managed Services ({runningCount}/{managed.length})
          </h2>
          <PillButton size="xs" variant="ghost" onClick={() => onNavigate('containers')}>
            All containers <ArrowUpRight size={12} />
          </PillButton>
        </div>

        <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {managed.map((c) => {
            const on = c.status === 'running';
            return (
              <button
                key={c.name}
                type="button"
                onClick={() => onNavigate('containers')}
                class="bento-card p-3.5 text-left hover:scale-[1.01] transition-transform cursor-pointer flex items-center justify-between gap-2.5"
              >
                <div class="flex items-center gap-2.5 min-w-0">
                  <div
                    class={`w-8 h-8 rounded-xl flex items-center justify-center shrink-0 ${
                      on
                        ? 'bg-zinc-900 text-white dark:bg-zinc-800 dark:text-zinc-100 border border-transparent dark:border-zinc-700'
                        : 'bg-zinc-100 text-zinc-400 dark:bg-zinc-900 dark:text-zinc-600 border border-transparent dark:border-zinc-800'
                    }`}
                  >
                    <ServiceIcon name={c.name} size={15} />
                  </div>
                  <div class="min-w-0">
                    <div class="text-xs font-bold text-zinc-900 dark:text-white truncate">
                      {c.name}
                    </div>
                    <div class="text-[10.5px] text-zinc-500 dark:text-zinc-400 tabular-nums truncate">
                      {on ? `${c.cpu_percent}% CPU · ${c.mem_mb} MB` : 'Stopped'}
                    </div>
                  </div>
                </div>
                <StatusBadge tone={on ? 'ok' : 'err'} dot>
                  {on ? 'On' : 'Off'}
                </StatusBadge>
              </button>
            );
          })}
          {managed.length === 0 && (
            <div class="bento-card p-4 col-span-full text-center text-xs text-zinc-500">
              Loading container inventory...
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
