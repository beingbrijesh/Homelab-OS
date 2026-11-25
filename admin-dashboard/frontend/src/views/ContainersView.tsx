import { useState } from 'preact/hooks';
import {
  Cpu,
  FileText,
  MemoryStick,
  MoreHorizontal,
  Play,
  RefreshCw,
  RotateCw,
  Square,
} from 'lucide-preact';
import type { ContainerInfo } from '../types/api';
import { api } from '../api/client';
import { Modal, PillButton, ServiceIcon, StatusBadge } from '../components/ui';

export function ContainersView({
  containers,
  error,
  onReload,
  onNotify,
}: {
  containers: ContainerInfo[];
  error: string;
  onReload: () => void;
  onNotify: (msg: string, ok?: boolean) => void;
}) {
  const [busyName, setBusyName] = useState<string | null>(null);
  const [openMenu, setOpenMenu] = useState<string | null>(null);
  const [logModal, setLogModal] = useState<{ open: boolean; name: string; content: string; loading: boolean }>({
    open: false,
    name: '',
    content: '',
    loading: false,
  });

  const runningCount = containers.filter((c) => c.status === 'running').length;

  const runAction = async (name: string, action: 'start' | 'stop' | 'restart') => {
    setOpenMenu(null);
    if (!confirm(`${action.charAt(0).toUpperCase() + action.slice(1)} "${name}"?`)) return;
    setBusyName(name);
    const res = await api(`/api/container/${encodeURIComponent(name)}/${action}`, 'POST');
    setBusyName(null);
    if (res.error) {
      onNotify(res.error, false);
    } else {
      onNotify(`Container "${name}" ${action} requested.`);
      setTimeout(onReload, 1500);
    }
  };

  const openLogs = async (name: string) => {
    setOpenMenu(null);
    setLogModal({ open: true, name, content: 'Loading container logs...', loading: true });
    const res = await api<{ logs?: string }>(`/api/container/${encodeURIComponent(name)}/logs?lines=100`);
    setLogModal({
      open: true,
      name,
      content: res.logs || res.error || 'No logs available.',
      loading: false,
    });
  };

  return (
    <div class="space-y-4">
      {/* Summary Header Strip */}
      <div class="bento-card p-4 sm:p-5 flex flex-wrap items-center justify-between gap-3">
        <div class="flex items-center gap-3">
          <StatusBadge tone="ok" dot>
            {runningCount} Running
          </StatusBadge>
          <StatusBadge tone={containers.length - runningCount > 0 ? 'warn' : 'neutral'} dot>
            {containers.length - runningCount} Stopped
          </StatusBadge>
        </div>
        <PillButton size="sm" variant="secondary" onClick={onReload}>
          <RefreshCw size={13} /> Refresh
        </PillButton>
      </div>

      {error && (
        <div class="bento-card p-4 border-rose-500/30 text-xs text-rose-600 dark:text-rose-400">
          {error}
        </div>
      )}

      {/* Bento Container Cards */}
      <div class="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3.5 items-stretch">
        {containers.map((c) => {
          const on = c.status === 'running';
          const isBusy = busyName === c.name;
          return (
            <div
              key={c.name}
              class="bento-card p-4 h-full flex flex-col justify-between gap-3 relative"
            >
              <div class="flex items-start justify-between gap-3">
                <div class="flex items-center gap-3 min-w-0">
                  <div
                    class={`w-10 h-10 rounded-2xl flex items-center justify-center shrink-0 ${
                      on
                        ? 'bg-zinc-900 text-white dark:bg-zinc-800 dark:text-zinc-100 border border-transparent dark:border-zinc-700'
                        : 'bg-zinc-100 text-zinc-400 dark:bg-zinc-900 dark:text-zinc-600 border border-transparent dark:border-zinc-800'
                    }`}
                  >
                    <ServiceIcon name={c.name} size={18} />
                  </div>
                  <div class="min-w-0">
                    <div class="text-sm font-bold text-zinc-900 dark:text-white truncate">
                      {c.name}
                    </div>
                    <div class="text-[11px] font-mono text-zinc-400 truncate" title={c.image}>
                      {c.image}
                    </div>
                  </div>
                </div>

                {/* 3-dot context menu matching iDraft task cards */}
                <div class="relative">
                  <button
                    type="button"
                    onClick={() => setOpenMenu(openMenu === c.name ? null : c.name)}
                    class="w-8 h-8 rounded-full flex items-center justify-center text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900 dark:hover:bg-zinc-800 dark:hover:text-white cursor-pointer"
                    aria-label="Container options"
                  >
                    <MoreHorizontal size={16} />
                  </button>
                  {openMenu === c.name && (
                    <div class="absolute right-0 mt-1 w-36 rounded-2xl bg-zinc-900 dark:bg-zinc-800 text-white shadow-xl border border-white/10 py-1.5 z-20 text-xs">
                      {on ? (
                        <>
                          <button
                            type="button"
                            onClick={() => runAction(c.name, 'restart')}
                            class="w-full px-3.5 py-2 text-left hover:bg-white/10 flex items-center gap-2 cursor-pointer"
                          >
                            <RotateCw size={12} /> Restart
                          </button>
                          <button
                            type="button"
                            onClick={() => runAction(c.name, 'stop')}
                            class="w-full px-3.5 py-2 text-left hover:bg-white/10 text-rose-300 flex items-center gap-2 cursor-pointer"
                          >
                            <Square size={12} /> Stop
                          </button>
                        </>
                      ) : (
                        <button
                          type="button"
                          onClick={() => runAction(c.name, 'start')}
                          class="w-full px-3.5 py-2 text-left hover:bg-white/10 text-emerald-300 flex items-center gap-2 cursor-pointer"
                        >
                          <Play size={12} /> Start
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => openLogs(c.name)}
                        class="w-full px-3.5 py-2 text-left hover:bg-white/10 flex items-center gap-2 cursor-pointer"
                      >
                        <FileText size={12} /> View Logs
                      </button>
                    </div>
                  )}
                </div>
              </div>

              {/* Metrics row */}
              <div class="grid grid-cols-2 gap-2">
                <div class="bento-sub px-3 py-2 flex items-center justify-between gap-2">
                  <div>
                    <div class="text-[9.5px] font-bold uppercase tracking-wider text-zinc-400">
                      CPU
                    </div>
                    <div class="text-sm font-bold text-zinc-900 dark:text-white tabular-nums">
                      {on ? `${c.cpu_percent}%` : '—'}
                    </div>
                  </div>
                  <Cpu size={14} class="text-zinc-400 shrink-0" />
                </div>
                <div class="bento-sub px-3 py-2 flex items-center justify-between gap-2">
                  <div>
                    <div class="text-[9.5px] font-bold uppercase tracking-wider text-zinc-400">
                      Memory
                    </div>
                    <div class="text-sm font-bold text-zinc-900 dark:text-white tabular-nums">
                      {on ? `${c.mem_mb} MB` : '—'}
                    </div>
                  </div>
                  <MemoryStick size={14} class="text-zinc-400 shrink-0" />
                </div>
              </div>

              {/* Footer badges + quick controls */}
              <div class="flex items-center justify-between gap-2 pt-3 border-t border-zinc-200/70 dark:border-zinc-800/80">
                <div class="flex items-center gap-1.5">
                  <StatusBadge tone={on ? 'ok' : 'err'} dot>
                    {on ? 'Online' : c.status}
                  </StatusBadge>
                  <StatusBadge tone="neutral">{c.managed ? 'managed' : 'external'}</StatusBadge>
                </div>

                <div class="flex items-center gap-1.5">
                  {on ? (
                    <>
                      <PillButton
                        size="xs"
                        variant="warn"
                        disabled={isBusy}
                        onClick={() => runAction(c.name, 'restart')}
                      >
                        <RotateCw size={11} />
                      </PillButton>
                      <PillButton
                        size="xs"
                        variant="danger"
                        disabled={isBusy}
                        onClick={() => runAction(c.name, 'stop')}
                      >
                        <Square size={11} />
                      </PillButton>
                    </>
                  ) : (
                    <PillButton
                      size="xs"
                      variant="ok"
                      disabled={isBusy}
                      onClick={() => runAction(c.name, 'start')}
                    >
                      <Play size={11} /> Start
                    </PillButton>
                  )}
                  <PillButton size="xs" variant="secondary" onClick={() => openLogs(c.name)}>
                    Logs
                  </PillButton>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      <Modal
        open={logModal.open}
        title={`${logModal.name} — container logs`}
        onClose={() => setLogModal((p) => ({ ...p, open: false }))}
      >
        <pre class="font-mono text-[11px] leading-relaxed text-zinc-700 dark:text-zinc-300 bg-zinc-50 dark:bg-zinc-950 border border-zinc-200 dark:border-zinc-800 rounded-2xl p-4 whitespace-pre-wrap overflow-x-auto max-h-[64vh]">
          {logModal.content}
        </pre>
      </Modal>
    </div>
  );
}
