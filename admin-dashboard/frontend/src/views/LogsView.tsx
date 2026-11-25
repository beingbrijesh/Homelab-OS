import { useEffect, useState } from 'preact/hooks';
import {
  AlertTriangle,
  BellRing,
  Check,
  CheckCheck,
  Clock,
  ScrollText,
  Search,
  XCircle,
} from 'lucide-preact';
import type { LogEntry, LogStats, SystemEvent } from '../types/api';
import { api } from '../api/client';
import { CardHeader, PillButton, StatCard, StatusBadge } from '../components/ui';

const CATEGORIES = [
  { id: 'all', label: 'All' },
  { id: 'system_alerts', label: 'System Alerts' },
  { id: 'containers', label: 'Containers' },
  { id: 'system', label: 'System' },
  { id: 'auth', label: 'Auth' },
  { id: 'storage', label: 'Storage' },
  { id: 'network', label: 'Network' },
  { id: 'music', label: 'Music' },
  { id: 'users', label: 'Users' },
  { id: 'backup', label: 'Backup' },
  { id: 'security', label: 'Security' },
];

export function LogsView({ refreshKey }: { refreshKey: number }) {
  const [stats, setStats] = useState<LogStats | null>(null);
  const [rows, setRows] = useState<LogEntry[]>([]);
  const [alerts, setAlerts] = useState<SystemEvent[]>([]);
  const [category, setCategory] = useState('all');
  const [severity, setSeverity] = useState('');
  const [query, setQuery] = useState('');
  const [unresolvedOnly, setUnresolvedOnly] = useState(true);
  const [autoRefresh, setAutoRefresh] = useState(false);

  const isAlertsMode = category === 'system_alerts';

  const load = async (bg = false) => {
    const stPromise = api<LogStats>('/api/logs/stats', 'GET', null, { bg });
    if (isAlertsMode) {
      const [st, evs] = await Promise.all([
        stPromise,
        api<SystemEvent[]>(
          `/api/system-events?unresolved=${unresolvedOnly ? 1 : 0}&limit=100`,
          'GET',
          null,
          { bg }
        ),
      ]);
      if (!st.error) setStats(st);
      if (Array.isArray(evs)) setAlerts(evs);
    } else {
      const [st, entries] = await Promise.all([
        stPromise,
        api<LogEntry[]>(
          `/api/logs?q=${encodeURIComponent(query)}&category=${encodeURIComponent(
            category
          )}&severity=${encodeURIComponent(severity)}`,
          'GET',
          null,
          { bg }
        ),
      ]);
      if (!st.error) setStats(st);
      if (Array.isArray(entries)) setRows(entries);
    }
  };

  useEffect(() => {
    load(false);
  }, [category, severity, query, unresolvedOnly, refreshKey]);

  useEffect(() => {
    if (!autoRefresh) return;
    const t = setInterval(() => load(true), 15000);
    return () => clearInterval(t);
  }, [autoRefresh, category, severity, query, unresolvedOnly]);

  const resolveOne = async (id: number) => {
    await api(`/api/system-events/${id}/resolve`, 'POST', {});
    load(false);
  };

  const resolveAll = async () => {
    await api('/api/system-events/resolve-all', 'POST', {});
    load(false);
  };

  const filteredAlerts = alerts.filter((a) => {
    if (severity && a.severity !== severity) return false;
    if (query.trim()) {
      const q = query.trim().toLowerCase();
      return (
        (a.message || '').toLowerCase().includes(q) ||
        (a.event_type || '').toLowerCase().includes(q) ||
        (a.source || '').toLowerCase().includes(q)
      );
    }
    return true;
  });

  const unresolvedCount = stats?.unresolved_events || 0;

  return (
    <div class="space-y-4">
      {/* 5 Clickable Metric Counters with Icons */}
      <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3 items-stretch">
        <button
          type="button"
          onClick={() => {
            setCategory('all');
            setSeverity('');
          }}
          class="text-left cursor-pointer hover:scale-[1.01] transition-transform"
        >
          <StatCard
            hero
            label="Total Entries"
            value={(stats?.total || 0).toLocaleString()}
            icon={<ScrollText size={14} />}
          />
        </button>

        <button
          type="button"
          onClick={() => {
            setCategory('all');
            setSeverity('');
          }}
          class="text-left cursor-pointer hover:scale-[1.01] transition-transform"
        >
          <StatCard
            label="Today"
            value={(stats?.today || 0).toLocaleString()}
            icon={<Clock size={14} />}
          />
        </button>

        <button
          type="button"
          onClick={() => {
            setCategory('all');
            setSeverity(severity === 'warning' ? '' : 'warning');
          }}
          class="text-left cursor-pointer hover:scale-[1.01] transition-transform"
        >
          <StatCard
            label="Warnings"
            value={(stats?.warnings || 0).toLocaleString()}
            icon={<AlertTriangle size={14} />}
            tone={(stats?.warnings || 0) > 0 ? 'warn' : 'default'}
          />
        </button>

        <button
          type="button"
          onClick={() => {
            setCategory('all');
            setSeverity(severity === 'error' ? '' : 'error');
          }}
          class="text-left cursor-pointer hover:scale-[1.01] transition-transform"
        >
          <StatCard
            label="Errors"
            value={(stats?.errors || 0).toLocaleString()}
            icon={<XCircle size={14} />}
            tone={(stats?.errors || 0) > 0 ? 'err' : 'default'}
          />
        </button>

        <button
          type="button"
          onClick={() => setCategory('system_alerts')}
          class={`col-span-2 sm:col-span-1 text-left cursor-pointer hover:scale-[1.01] transition-transform rounded-[20px] ${
            isAlertsMode ? 'ring-2 ring-amber-500/70' : ''
          }`}
        >
          <StatCard
            label="System Alerts"
            value={unresolvedCount.toLocaleString()}
            sub="Click to filter & resolve"
            icon={<BellRing size={14} />}
            tone={unresolvedCount > 0 ? 'warn' : 'ok'}
          />
        </button>
      </div>

      {/* Filters & Log / Alerts Table */}
      <div class="bento-card p-4 sm:p-5 space-y-3.5">
        <CardHeader
          title={isAlertsMode ? 'System Alerts' : 'Audit Trail'}
          subtitle={
            isAlertsMode
              ? 'Unresolved & historical threshold alerts from host telemetry'
              : 'Filterable log of admin & automated service events'
          }
          icon={isAlertsMode ? <BellRing size={14} /> : <ScrollText size={14} />}
          action={
            <div class="flex items-center gap-2 flex-wrap justify-end">
              {isAlertsMode && unresolvedCount > 0 && (
                <PillButton size="xs" variant="ok" onClick={resolveAll}>
                  <CheckCheck size={12} /> Resolve All ({unresolvedCount})
                </PillButton>
              )}
              <label class="inline-flex items-center gap-2 text-xs text-zinc-600 dark:text-zinc-400 cursor-pointer bento-sub px-3 py-1.5">
                <input
                  type="checkbox"
                  checked={autoRefresh}
                  onChange={(e) => setAutoRefresh((e.target as HTMLInputElement).checked)}
                  class="accent-zinc-900 dark:accent-white"
                />
                <span>Auto-refresh (15s)</span>
              </label>
            </div>
          }
        />

        {/* Category Filter Pills (now includes System Alerts!) */}
        <div class="flex flex-wrap gap-1.5">
          {CATEGORIES.map((cat) => {
            const active = category === cat.id;
            const isAlertPill = cat.id === 'system_alerts';
            return (
              <button
                key={cat.id}
                type="button"
                onClick={() => setCategory(cat.id)}
                class={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold transition-all cursor-pointer border ${
                  active
                    ? 'bg-zinc-900 text-white border-zinc-900 dark:bg-zinc-100 dark:text-zinc-950 dark:border-zinc-100'
                    : 'bg-zinc-100 text-zinc-600 border-transparent hover:bg-zinc-200 dark:bg-zinc-800/80 dark:text-zinc-400 dark:hover:text-white'
                }`}
              >
                {isAlertPill && <BellRing size={11} />}
                <span>{cat.label}</span>
                {isAlertPill && unresolvedCount > 0 && (
                  <span class="px-1.5 py-0.2 rounded-full text-[10px] font-bold bg-amber-500 text-white">
                    {unresolvedCount}
                  </span>
                )}
              </button>
            );
          })}
        </div>

        {/* Search, Severity & Unresolved Toggle */}
        <div class="flex flex-wrap items-center gap-2.5">
          <div class="relative flex-1 min-w-[200px]">
            <Search size={14} class="absolute left-3.5 top-1/2 -translate-y-1/2 text-zinc-400" />
            <input
              type="text"
              value={query}
              onInput={(e) => setQuery((e.target as HTMLInputElement).value)}
              placeholder={
                isAlertsMode
                  ? 'Search alert message, event type, source...'
                  : 'Search actions, actors, targets, details...'
              }
              class="bento-input w-full pl-9"
            />
          </div>
          {isAlertsMode && (
            <label class="inline-flex items-center gap-2 text-xs text-zinc-600 dark:text-zinc-400 cursor-pointer bento-sub px-3 py-2">
              <input
                type="checkbox"
                checked={unresolvedOnly}
                onChange={(e) => setUnresolvedOnly((e.target as HTMLInputElement).checked)}
                class="accent-zinc-900 dark:accent-white"
              />
              <span>Unresolved only</span>
            </label>
          )}
          <select
            value={severity}
            onChange={(e) => setSeverity((e.target as HTMLSelectElement).value)}
            class="bento-input py-2 px-3 text-xs"
          >
            <option value="">All severities</option>
            <option value="info">Info</option>
            <option value="warning">Warning</option>
            <option value="error">Error</option>
            <option value="critical">Critical</option>
          </select>
        </div>

        {/* Table Body: System Alerts OR Activity Audit Trail */}
        <div class="overflow-x-auto max-h-[520px] overflow-y-auto pr-1">
          {isAlertsMode ? (
            <table class="w-full text-left border-collapse text-xs">
              <thead>
                <tr class="border-b border-zinc-200/80 dark:border-zinc-800 text-[10px] font-semibold uppercase tracking-widest text-zinc-400">
                  <th class="py-2.5 pr-3 whitespace-nowrap">Timestamp</th>
                  <th class="py-2.5 pr-3">Severity</th>
                  <th class="py-2.5 pr-3">Type</th>
                  <th class="py-2.5 pr-3">Alert Message</th>
                  <th class="py-2.5 pr-3">State</th>
                  <th class="py-2.5 text-right">Action</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-zinc-200/60 dark:divide-zinc-800/70">
                {filteredAlerts.length > 0 ? (
                  filteredAlerts.map((a) => {
                    const resolved = !!a.resolved;
                    const sevTone =
                      a.severity === 'critical' || a.severity === 'error'
                        ? 'err'
                        : a.severity === 'warning'
                        ? 'warn'
                        : 'neutral';
                    return (
                      <tr key={a.id} class="hover:bg-zinc-50 dark:hover:bg-zinc-900/40">
                        <td class="py-2.5 pr-3 font-mono text-[11px] text-zinc-400 whitespace-nowrap">
                          {a.timestamp || '—'}
                        </td>
                        <td class="py-2.5 pr-3">
                          <StatusBadge tone={sevTone}>{a.severity || 'info'}</StatusBadge>
                        </td>
                        <td class="py-2.5 pr-3">
                          <StatusBadge tone="neutral">{a.event_type}</StatusBadge>
                        </td>
                        <td class="py-2.5 pr-3 font-semibold text-zinc-800 dark:text-zinc-200">
                          {a.message}
                        </td>
                        <td class="py-2.5 pr-3">
                          <StatusBadge tone={resolved ? 'ok' : 'warn'} dot>
                            {resolved ? 'Resolved' : 'Active'}
                          </StatusBadge>
                        </td>
                        <td class="py-2.5 text-right">
                          {!resolved ? (
                            <PillButton size="xs" variant="ok" onClick={() => resolveOne(a.id)}>
                              <Check size={11} /> Resolve
                            </PillButton>
                          ) : (
                            <span class="text-[11px] text-zinc-400">—</span>
                          )}
                        </td>
                      </tr>
                    );
                  })
                ) : (
                  <tr>
                    <td colSpan={6} class="py-8 text-center text-zinc-400">
                      No active system alerts. Everything is running smoothly.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          ) : (
            <table class="w-full text-left border-collapse text-xs">
              <thead>
                <tr class="border-b border-zinc-200/80 dark:border-zinc-800 text-[10px] font-semibold uppercase tracking-widest text-zinc-400">
                  <th class="py-2.5 pr-3 whitespace-nowrap">Timestamp</th>
                  <th class="py-2.5 pr-3">Severity</th>
                  <th class="py-2.5 pr-3">Category</th>
                  <th class="py-2.5 pr-3">Actor</th>
                  <th class="py-2.5 pr-3">Action &amp; Details</th>
                  <th class="py-2.5 text-right">Status</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-zinc-200/60 dark:divide-zinc-800/70">
                {rows.length > 0 ? (
                  rows.map((r, idx) => {
                    const sevTone =
                      r.severity === 'error' || r.severity === 'critical'
                        ? 'err'
                        : r.severity === 'warning'
                        ? 'warn'
                        : 'neutral';
                    const stTone =
                      r.status === 'ok' ? 'ok' : r.status === 'warning' ? 'warn' : 'err';
                    return (
                      <tr key={r.id ?? idx} class="hover:bg-zinc-50 dark:hover:bg-zinc-900/40">
                        <td class="py-2.5 pr-3 font-mono text-[11px] text-zinc-400 whitespace-nowrap">
                          {r.timestamp || '—'}
                        </td>
                        <td class="py-2.5 pr-3">
                          <StatusBadge tone={sevTone}>{r.severity || 'info'}</StatusBadge>
                        </td>
                        <td class="py-2.5 pr-3">
                          <StatusBadge tone="neutral">{r.category || 'general'}</StatusBadge>
                        </td>
                        <td class="py-2.5 pr-3 font-semibold text-zinc-900 dark:text-white">
                          {r.actor}
                        </td>
                        <td class="py-2.5 pr-3">
                          <div class="font-semibold text-zinc-800 dark:text-zinc-200">{r.action}</div>
                          {r.target && <div class="text-[11px] text-zinc-500">→ {r.target}</div>}
                          {r.detail && <div class="text-[11px] text-zinc-400 mt-0.5">{r.detail}</div>}
                          {r.duration_ms ? (
                            <div class="text-[10px] font-mono text-zinc-400 mt-0.5">
                              {r.duration_ms}ms
                            </div>
                          ) : null}
                        </td>
                        <td class="py-2.5 text-right">
                          <StatusBadge tone={stTone}>
                            {r.status === 'ok' ? 'OK' : r.status === 'warning' ? 'Warn' : 'Error'}
                          </StatusBadge>
                        </td>
                      </tr>
                    );
                  })
                ) : (
                  <tr>
                    <td colSpan={6} class="py-6 text-center text-zinc-400">
                      No matching activity entries found.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}
