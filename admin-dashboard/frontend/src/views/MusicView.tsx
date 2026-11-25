import { useEffect, useState } from 'preact/hooks';
import { Disc, ExternalLink, FolderOpen, Monitor, Music, Smartphone, Users } from 'lucide-preact';
import type { MusicStatus } from '../types/api';
import { api } from '../api/client';
import { CardHeader, StatusBadge } from '../components/ui';

export function MusicView({ refreshKey }: { refreshKey: number }) {
  const [data, setData] = useState<MusicStatus | null>(null);

  const load = async () => {
    const res = await api<MusicStatus>('/api/music/status');
    if (!res.error) setData(res);
  };

  useEffect(() => {
    load();
  }, [refreshKey]);

  const running = !!data?.navidrome_running;
  const url = data?.navidrome_url || '#';

  return (
    <div class="space-y-5">
      {/* Library Overview Hero */}
      <div class="bento-hero p-4 sm:p-5">
        <div class="flex flex-wrap items-center justify-between gap-4 mb-4">
          <div class="flex items-center gap-3">
            <div class="w-10 h-10 rounded-2xl bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-950 flex items-center justify-center shrink-0">
              <Music size={19} />
            </div>
            <div>
              <div class="flex items-center gap-2 flex-wrap">
                <h2 class="text-sm sm:text-base font-bold text-zinc-900 dark:text-white">
                  Navidrome Streaming Server
                </h2>
                <StatusBadge tone={running ? 'ok' : 'err'} dot>
                  {running ? 'Running' : 'Stopped'}
                </StatusBadge>
              </div>
              <p class="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
                Last scan: {data?.last_scan || 'Never'}
              </p>
            </div>
          </div>

          <a
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            class="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-zinc-900 text-white hover:bg-zinc-800 dark:bg-zinc-100 dark:text-zinc-950 dark:hover:bg-zinc-200 text-xs font-semibold transition-all shadow-sm"
          >
            Launch Web Player <ExternalLink size={13} />
          </a>
        </div>

        <div class="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
          <div class="bento-sub p-3.5 flex items-center justify-between">
            <div>
              <div class="text-[10px] uppercase tracking-widest font-semibold text-zinc-500 dark:text-zinc-400">
                Artists
              </div>
              <div class="text-2xl font-bold text-zinc-900 dark:text-white mt-0.5 tabular-nums">
                {(data?.artists_count || 0).toLocaleString()}
              </div>
            </div>
            <Users size={18} class="text-zinc-400" />
          </div>

          <div class="bento-sub p-3.5 flex items-center justify-between">
            <div>
              <div class="text-[10px] uppercase tracking-widest font-semibold text-zinc-500 dark:text-zinc-400">
                Albums
              </div>
              <div class="text-2xl font-bold text-zinc-900 dark:text-white mt-0.5 tabular-nums">
                {(data?.albums_count || 0).toLocaleString()}
              </div>
            </div>
            <Disc size={18} class="text-zinc-400" />
          </div>

          <div class="bento-sub p-3.5 flex items-center justify-between">
            <div>
              <div class="text-[10px] uppercase tracking-widest font-semibold text-zinc-500 dark:text-zinc-400">
                Total Songs
              </div>
              <div class="text-2xl font-bold text-zinc-900 dark:text-white mt-0.5 tabular-nums">
                {(data?.music_file_count || 0).toLocaleString()}
              </div>
            </div>
            <Music size={18} class="text-zinc-400" />
          </div>
        </div>
      </div>

      {/* Details + Subsonic Clients */}
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-3.5 items-stretch">
        <div class="bento-card p-4 sm:p-5 h-full space-y-3.5">
          <CardHeader title="Endpoint & Storage" icon={<FolderOpen size={16} />} />

          <div>
            <div class="text-[10px] font-semibold uppercase tracking-widest text-zinc-400 mb-1.5">
              Dynamic Server URL
            </div>
            <div class="bento-sub px-3.5 py-2.5 font-mono text-xs text-zinc-800 dark:text-zinc-200 truncate">
              {data?.navidrome_url || '—'}
            </div>
          </div>

          <div>
            <div class="flex items-center justify-between mb-1.5">
              <span class="text-[10px] font-semibold uppercase tracking-widest text-zinc-400">
                Music Directory
              </span>
              <StatusBadge tone={data?.music_dir_exists ? 'ok' : 'err'} dot>
                {data?.music_dir_exists ? 'Mounted' : 'Missing'}
              </StatusBadge>
            </div>
            <div class="bento-sub px-3.5 py-2.5 font-mono text-xs text-zinc-800 dark:text-zinc-200 truncate">
              {data?.music_dir || '—'}
            </div>
          </div>
        </div>

        <div class="bento-card p-5 sm:p-6">
          <CardHeader title="Subsonic Ecosystem Apps" icon={<Smartphone size={16} />} />
          <div class="space-y-2.5">
            {[
              { name: 'Android Clients', apps: 'Subtracks · Symfonium · DSub', tag: 'Subsonic API', icon: Smartphone },
              { name: 'iOS Clients', apps: 'Amperfy · play:Sub · substreamer', tag: 'Subsonic API', icon: Smartphone },
              { name: 'Desktop Clients', apps: 'Feishin · Sonixd · Navidrome Web', tag: 'Cross-Platform', icon: Monitor },
            ].map((c) => {
              const Icon = c.icon;
              return (
                <div key={c.name} class="bento-sub p-3.5 flex items-center justify-between gap-3">
                  <div class="flex items-center gap-3 min-w-0">
                    <div class="w-8 h-8 rounded-xl bg-white dark:bg-zinc-900 border border-zinc-200/70 dark:border-zinc-800 flex items-center justify-center text-zinc-700 dark:text-zinc-300 shrink-0">
                      <Icon size={15} />
                    </div>
                    <div class="min-w-0">
                      <div class="text-xs font-semibold text-zinc-900 dark:text-white">{c.name}</div>
                      <div class="text-[11px] text-zinc-500 dark:text-zinc-400 truncate">{c.apps}</div>
                    </div>
                  </div>
                  <StatusBadge tone="neutral">{c.tag}</StatusBadge>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
