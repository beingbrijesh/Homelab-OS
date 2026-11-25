import { useEffect, useMemo, useState } from 'preact/hooks';
import {
  Activity,
  ArrowDownToLine,
  ArrowUpFromLine,
  BarChart3,
  Calendar,
  Container,
  Globe,
  Network,
} from 'lucide-preact';
import type {
  NetworkHistoryRow,
  NetworkLive,
  NetworkSummary,
  NetworkSummaryRow,
  NetworkTotalPair,
} from '../types/api';
import { api } from '../api/client';
import { fmtBytes, fmtBytesPerSec } from '../utils/format';
import { CardHeader, ProgressBar, ServiceIcon, StatCard, StatusBadge } from '../components/ui';
import { SmoothLineChart } from '../components/Charts';

function sumRows(arr?: NetworkSummaryRow[]): NetworkTotalPair {
  return (arr || []).reduce(
    (acc, r) => ({
      in: (acc.in || 0) + (r.bytes_in ?? r.tin ?? 0),
      out: (acc.out || 0) + (r.bytes_out ?? r.tout ?? 0),
    }),
    { in: 0, out: 0 }
  );
}

function pairBytes(t?: NetworkTotalPair) {
  const bin = t?.bytes_in ?? t?.in ?? 0;
  const bout = t?.bytes_out ?? t?.out ?? 0;
  return { bin, bout, total: bin + bout };
}

function isVirtualIface(name: string): boolean {
  return (
    name === 'lo' ||
    name.startsWith('docker') ||
    name.startsWith('veth') ||
    name.startsWith('br-')
  );
}

function formatHistoryLabel(r: NetworkHistoryRow, period: string): string {
  if (period === '1h' || period === '24h') {
    if (r.ts && r.ts.length >= 16) return r.ts.slice(11, 16);
  }
  if (period === '7d') {
    if (r.ts && r.ts.length >= 13) return `${r.ts.slice(5, 10)} ${r.ts.slice(11, 13)}h`;
  }
  if (r.day) return r.day.slice(5);
  if (r.ts && r.ts.length >= 10) return r.ts.slice(5, 10);
  return '';
}

export function NetworkView({
  refreshKey,
  isDark,
}: {
  refreshKey: number;
  isDark: boolean;
}) {
  const [period, setPeriod] = useState('24h');
  const [scaleMode, setScaleMode] = useState<'log' | 'linear'>('log');
  const [selectedIface, setSelectedIface] = useState<string>('');
  const [live, setLive] = useState<NetworkLive | null>(null);
  const [summary, setSummary] = useState<NetworkSummary | null>(null);
  const [historyRows, setHistoryRows] = useState<NetworkHistoryRow[]>([]);

  const loadLive = async (bg = false) => {
    const res = await api<NetworkLive>('/api/network/live', 'GET', null, { bg });
    if (!res.error) {
      setLive(res);
      // Append live point smoothly to 1h/24h history so chart stays alive
      if ((period === '1h' || period === '24h') && res.interfaces?.length) {
        const nowIso = new Date().toISOString();
        const appended: NetworkHistoryRow[] = res.interfaces.map((i) => ({
          iface: i.iface,
          in_rate: i.bytes_in_rate || 0,
          out_rate: i.bytes_out_rate || 0,
          ts: nowIso,
        }));
        setHistoryRows((prev) => [...prev, ...appended]);
      }
    }
  };

  const loadAll = async () => {
    const [l, s, h] = await Promise.all([
      api<NetworkLive>('/api/network/live'),
      api<NetworkSummary>('/api/network/summary'),
      api<{ rows?: NetworkHistoryRow[] }>(
        `/api/network/history?period=${encodeURIComponent(period)}`
      ),
    ]);
    if (!l.error) setLive(l);
    if (!s.error) setSummary(s);
    if (!h.error && Array.isArray(h.rows)) setHistoryRows(h.rows);
  };

  useEffect(() => {
    loadAll();
    const timer = setInterval(() => loadLive(true), 10000);
    return () => clearInterval(timer);
  }, [period, refreshKey]);

  // Group history rows by interface and compute total traffic to pick the truly active interface
  const { grouped, availableIfaces, bestIface } = useMemo(() => {
    const map: Record<
      string,
      { inData: number[]; outData: number[]; labels: string[]; volume: number }
    > = {};

    for (const r of historyRows) {
      if (!r.iface) continue;
      if (!map[r.iface]) {
        map[r.iface] = { inData: [], outData: [], labels: [], volume: 0 };
      }
      const inVal = Math.max(0, Number(r.in_rate) || 0);
      const outVal = Math.max(0, Number(r.out_rate) || 0);
      map[r.iface].inData.push(inVal);
      map[r.iface].outData.push(outVal);
      map[r.iface].labels.push(formatHistoryLabel(r, period));
      map[r.iface].volume += inVal + outVal;
    }

    // Ensure live interfaces are also selectable
    for (const li of live?.interfaces || []) {
      if (!map[li.iface]) {
        map[li.iface] = {
          inData: [li.bytes_in_rate || 0],
          outData: [li.bytes_out_rate || 0],
          labels: [new Date().toTimeString().slice(0, 5)],
          volume: (li.bytes_in_rate || 0) + (li.bytes_out_rate || 0),
        };
      }
    }

    const names = Object.keys(map);
    const physical = names.filter((k) => !isVirtualIface(k) && !k.startsWith('tailscale'));
    const nonVirtual = names.filter((k) => !isVirtualIface(k));
    const candidates = physical.length ? physical : nonVirtual.length ? nonVirtual : names;

    // Pick highest-volume interface (e.g. wlp2s0 over idle enp4s0)
    let best = candidates[0] || '';
    let bestVol = -1;
    for (const c of candidates) {
      const vol = map[c]?.volume ?? 0;
      if (vol > bestVol) {
        bestVol = vol;
        best = c;
      }
    }

    return { grouped: map, availableIfaces: nonVirtual.length ? nonVirtual : names, bestIface: best };
  }, [historyRows, live, period]);

  const activeIface = selectedIface && grouped[selectedIface] ? selectedIface : bestIface;
  const chartData = activeIface
    ? grouped[activeIface]
    : { inData: [], outData: [], labels: [], volume: 0 };

  const liveIfaces = live?.interfaces || [];
  const mainLive =
    liveIfaces.find((i) => i.iface === activeIface) ||
    liveIfaces.find((i) => !isVirtualIface(i.iface)) ||
    liveIfaces[0];

  const today = pairBytes(summary?.totals?.today || sumRows(summary?.today));
  const week = pairBytes(summary?.totals?.this_week || sumRows(summary?.this_week || summary?.week));
  const month = pairBytes(summary?.totals?.this_month || sumRows(summary?.this_month || summary?.month));
  const year = pairBytes(summary?.totals?.this_year || sumRows(summary?.this_year || summary?.year));
  const allTime = pairBytes(summary?.totals?.all_time || sumRows(summary?.all_time));

  const containers = live?.containers || [];
  const maxCtrBytes = Math.max(1, ...containers.map((c) => (c.delta_in || 0) + (c.delta_out || 0)));

  return (
    <div class="space-y-4">
      {/* Top 4 compact speed & transfer cards with crisp icons */}
      <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3.5">
        <StatCard
          hero
          label={`Download (${mainLive?.iface || 'host'})`}
          value={`↓ ${mainLive?.rate_in_human || fmtBytesPerSec(mainLive?.bytes_in_rate || 0)}`}
          sub="Live inbound rate"
          icon={<ArrowDownToLine size={15} class="text-emerald-400" />}
        />
        <StatCard
          label={`Upload (${mainLive?.iface || 'host'})`}
          value={`↑ ${mainLive?.rate_out_human || fmtBytesPerSec(mainLive?.bytes_out_rate || 0)}`}
          sub="Live outbound rate"
          icon={<ArrowUpFromLine size={15} />}
          action={<StatusBadge tone="ok" dot pulse>10s</StatusBadge>}
        />
        <StatCard
          label="Today Total"
          value={fmtBytes(today.total)}
          sub={`↓ ${fmtBytes(today.bin)} · ↑ ${fmtBytes(today.bout)}`}
          icon={<Calendar size={15} />}
        />
        <StatCard
          label="All-Time Transfer"
          value={fmtBytes(allTime.total)}
          sub={`30d: ${fmtBytes(month.total)} · 1y: ${fmtBytes(year.total)}`}
          icon={<Globe size={15} />}
        />
      </div>

      {/* Bandwidth History Chart — full responsive width + interface picker + Log/Linear toggle */}
      <div class="bento-card p-4 sm:p-5">
        <CardHeader
          title="Bandwidth History"
          subtitle={
            activeIface
              ? `Interface: ${activeIface} · ${scaleMode === 'log' ? 'Perceptual log scale' : 'Linear scale'}`
              : 'Throughput over time'
          }
          icon={<Activity size={14} />}
          action={
            <div class="flex items-center gap-1.5 flex-wrap justify-end">
              <button
                type="button"
                onClick={() => setScaleMode((m) => (m === 'log' ? 'linear' : 'log'))}
                title="Toggle between perceptual Log scale (shows idle & burst together) and Linear scale"
                class="px-2.5 py-1 rounded-full text-[11px] font-semibold border border-zinc-200 dark:border-zinc-700 bg-zinc-100 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-200 hover:bg-zinc-200 dark:hover:bg-zinc-700 transition-colors cursor-pointer"
              >
                {scaleMode === 'log' ? 'Scale: Log' : 'Scale: Linear'}
              </button>
              {availableIfaces.length > 0 && (
                <select
                  aria-label="Network interface"
                  value={activeIface}
                  onChange={(e) => setSelectedIface((e.target as HTMLSelectElement).value)}
                  class="bento-input py-1 px-2.5 text-xs font-mono"
                >
                  {availableIfaces.map((iface) => (
                    <option key={iface} value={iface}>
                      {iface}
                    </option>
                  ))}
                </select>
              )}
              <select
                aria-label="History period"
                value={period}
                onChange={(e) => setPeriod((e.target as HTMLSelectElement).value)}
                class="bento-input py-1 px-2.5 text-xs"
              >
                <option value="1h">Last 1 hour</option>
                <option value="24h">Last 24 hours</option>
                <option value="7d">Last 7 days</option>
                <option value="30d">Last 30 days</option>
                <option value="1y">Last 1 year</option>
                <option value="all">All Time</option>
              </select>
            </div>
          }
        />

        <SmoothLineChart
          labels={chartData.labels}
          height={210}
          scale={scaleMode}
          logBase={512}
          isDark={isDark}
          formatValue={(v) => fmtBytesPerSec(v)}
          emptyText="No network snapshots recorded for this period yet."
          series={[
            { label: 'Download', data: chartData.inData, stroke: '#059669', darkStroke: '#34d399', fill: true },
            { label: 'Upload', data: chartData.outData, stroke: '#2563eb', darkStroke: '#60a5fa', fill: true },
          ]}
        />

        {/* Compact inline rollup strip inside chart card — zero blank card bloat */}
        <div class="grid grid-cols-2 sm:grid-cols-5 gap-2 mt-4 pt-3.5 border-t border-zinc-200/70 dark:border-zinc-800/80">
          {[
            { label: 'Today', data: today },
            { label: '7 Days', data: week },
            { label: '30 Days', data: month },
            { label: 'This Year', data: year },
            { label: 'All-Time', data: allTime },
          ].map((item) => (
            <div key={item.label} class="bento-sub px-3 py-2">
              <div class="text-[9.5px] font-bold uppercase tracking-wider text-zinc-400">
                {item.label}
              </div>
              <div class="text-sm font-bold text-zinc-900 dark:text-white tabular-nums mt-0.5">
                {fmtBytes(item.data.total)}
              </div>
              <div class="text-[10px] text-zinc-500 dark:text-zinc-400 tabular-nums truncate">
                ↓ {fmtBytes(item.data.bin)} · ↑ {fmtBytes(item.data.bout)}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Bottom 2 columns: matched height with smooth internal scroll */}
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-3.5 items-stretch">
        <div class="bento-card p-4 sm:p-5 lg:h-[360px] flex flex-col">
          <CardHeader
            title="Container Traffic (24h)"
            subtitle={`${containers.length} active containers`}
            icon={<Container size={14} />}
          />
          {containers.length > 0 ? (
            <div class="flex-1 min-h-0 overflow-y-auto pr-1.5 space-y-2.5">
              {containers.map((c) => {
                const tot = (c.delta_in || 0) + (c.delta_out || 0);
                const share = Math.round((tot / maxCtrBytes) * 100);
                return (
                  <div key={c.container} class="bento-sub p-3">
                    <div class="flex items-center justify-between gap-2 mb-1.5">
                      <div class="flex items-center gap-2 font-semibold text-xs text-zinc-900 dark:text-white min-w-0">
                        <ServiceIcon name={c.container} size={14} />
                        <span class="truncate">{c.container}</span>
                      </div>
                      <div class="text-[11px] text-zinc-500 dark:text-zinc-400 tabular-nums shrink-0">
                        ↓ {fmtBytes(c.delta_in || 0)} · ↑ {fmtBytes(c.delta_out || 0)}
                      </div>
                    </div>
                    <ProgressBar percent={share} tone="mono" />
                  </div>
                );
              })}
            </div>
          ) : (
            <div class="flex-1 flex items-center justify-center text-xs text-zinc-500">
              No container network data recorded yet.
            </div>
          )}
        </div>

        <div class="bento-card p-4 sm:p-5 lg:h-[360px] flex flex-col">
          <CardHeader
            title="Interface Rollups"
            subtitle="Today, 7d, 30d & all-time per interface"
            icon={<Network size={14} />}
            action={<BarChart3 size={14} class="text-zinc-400" />}
          />
          <div class="flex-1 min-h-0 overflow-y-auto pr-1.5 space-y-3">
            {[
              { label: 'Today', rows: summary?.today },
              { label: '7 Days', rows: summary?.this_week || summary?.week },
              { label: '30 Days', rows: summary?.this_month || summary?.month },
              { label: 'All Time', rows: summary?.all_time },
            ].map((section) => (
              <div key={section.label}>
                <div class="text-[10px] font-bold uppercase tracking-widest text-zinc-400 mb-1">
                  {section.label}
                </div>
                {section.rows && section.rows.length > 0 ? (
                  <div class="divide-y divide-zinc-200/60 dark:divide-zinc-800/70">
                    {section.rows.map((r) => (
                      <div
                        key={`${section.label}-${r.iface}`}
                        class="py-1.5 flex items-center justify-between gap-2 text-xs"
                      >
                        <span class="font-mono text-zinc-700 dark:text-zinc-300">{r.iface}</span>
                        <span class="text-zinc-500 dark:text-zinc-400 tabular-nums">
                          ↓ {r.human_in || fmtBytes(r.bytes_in ?? r.tin ?? 0)} · ↑{' '}
                          {r.human_out || fmtBytes(r.bytes_out ?? r.tout ?? 0)}
                        </span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p class="text-xs text-zinc-400">No data yet.</p>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
