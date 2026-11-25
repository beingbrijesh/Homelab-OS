import { useEffect, useState } from 'preact/hooks';
import {
  Award,
  Clock,
  Download,
  Flame,
  ListMusic,
  Music,
  Play,
  Plus,
  Star,
  UserCircle2,
  Users,
} from 'lucide-preact';
import type { MusicStats, RecommendationsData, SmartMix, UserRecord } from '../types/api';
import { api } from '../api/client';
import { CardHeader, PillButton, ProgressBar, StatCard, StatusBadge } from '../components/ui';
import { HourlyBarChart } from '../components/Charts';

export function RecommendationsView({
  admin,
  refreshKey,
  onNotify,
}: {
  admin: string;
  refreshKey: number;
  onNotify: (msg: string, ok?: boolean) => void;
}) {
  const [stats, setStats] = useState<MusicStats | null>(null);
  const [users, setUsers] = useState<string[]>([]);
  const [selectedUser, setSelectedUser] = useState<string>(admin || 'admin');
  const [rec, setRec] = useState<RecommendationsData | null>(null);

  const loadStatsAndUsers = async () => {
    const [s, uRaw] = await Promise.all([
      api<MusicStats>('/api/music/stats'),
      api<UserRecord[]>('/api/users'),
    ]);
    if (!s.error) setStats(s);
    const list = Array.isArray(uRaw)
      ? uRaw.filter((u) => u && u.username).map((u) => u.username)
      : [];
    if (admin && !list.includes(admin)) list.unshift(admin);
    setUsers(list);
    if (!selectedUser && list.length > 0) setSelectedUser(list[0]);
  };

  const loadRecs = async (username: string) => {
    if (!username) return;
    const res = await api<RecommendationsData>(
      `/api/music/recommendations/${encodeURIComponent(username)}`
    );
    if (!res.error) setRec(res);
  };

  useEffect(() => {
    loadStatsAndUsers();
  }, [refreshKey]);

  useEffect(() => {
    if (selectedUser) loadRecs(selectedUser);
  }, [selectedUser, refreshKey]);

  const exportM3U = async (mix: SmartMix) => {
    const res = await api<{ ok?: boolean; filename?: string; track_count?: number }>(
      '/api/music/playlists/export-m3u',
      'POST',
      { username: selectedUser, name: mix.name, tracks: mix.tracks || [] }
    );
    if (res.ok) {
      onNotify(`Exported ${res.filename} (${res.track_count} tracks) to Navidrome!`);
    } else {
      onNotify(res.error || 'Export failed', false);
    }
  };

  const savePlaylist = async (mix: SmartMix) => {
    const res = await api<{ ok?: boolean }>('/api/music/playlists', 'POST', {
      username: selectedUser,
      name: mix.name || 'Smart Mix',
      auto_generated: true,
      tracks: mix.tracks || [],
    });
    if (res.ok) onNotify(`Playlist "${mix.name}" saved!`);
    else onNotify(res.error || 'Could not save playlist', false);
  };

  const queueTrack = async (title: string, artist: string) => {
    const res = await api<{ ok?: boolean; title?: string; job_id?: number }>(
      '/api/music/recommendations/queue-track',
      'POST',
      { title, artist, quality: 'mp3_320' }
    );
    if (res.ok) onNotify(`Queued "${res.title}" (#${res.job_id})`);
    else onNotify(res.error || 'Failed to queue track', false);
  };

  const totalPlays = stats?.total_plays ?? stats?.total_scrobbles ?? 0;
  const topArtistDisplay =
    stats?.top_artist ||
    (stats?.top_tracks?.[0]
      ? `${stats.top_tracks[0].track_title || stats.top_tracks[0].title} (${stats.top_tracks[0].plays}×)`
      : 'No plays yet');

  const hours24 = Array(24).fill(0);
  const patterns = rec?.time_pattern || rec?.time_patterns || rec?.listening_clock || [];
  for (const p of patterns) {
    const h = p.hour_of_day ?? p.hour;
    if (h !== undefined && h >= 0 && h < 24) hours24[h] = p.plays;
  }

  const topArtists = rec?.top_artists || [];
  const topTracks = rec?.top_tracks || [];
  const maxArtistScore = Math.max(
    1,
    ...(topArtists.map((a) => a.completions || a.plays || 1))
  );
  const mixes =
    (rec?.smart_mixes && rec.smart_mixes.length > 0
      ? rec.smart_mixes
      : rec?.playlist_suggestions || rec?.suggestions) || [];

  const showOnboarding =
    totalPlays === 0 && topArtists.length === 0 && topTracks.length === 0;

  return (
    <div class="space-y-4">
      {/* Top stats + user picker */}
      <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
        <div class="bento-hero p-3.5 sm:p-4 col-span-2 sm:col-span-3 lg:col-span-1">
          <div class="flex items-center gap-2 mb-2">
            <span class="w-7 h-7 rounded-xl bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-950 flex items-center justify-center shrink-0">
              <UserCircle2 size={14} />
            </span>
            <span class="text-[11px] font-semibold text-zinc-500 dark:text-zinc-400">Listener</span>
          </div>
          <select
            value={selectedUser}
            onChange={(e) => setSelectedUser((e.target as HTMLSelectElement).value)}
            class="bento-input w-full py-1.5 text-xs font-semibold"
          >
            {users.map((u) => (
              <option key={u} value={u}>
                {u}
              </option>
            ))}
          </select>
        </div>

        <StatCard label="Total Plays" value={totalPlays.toLocaleString()} icon={<Play size={14} />} />
        <StatCard label="Listeners" value={stats?.unique_users ?? 0} icon={<Users size={14} />} />
        <StatCard label="Active Today" value={stats?.active_today ?? 0} icon={<Flame size={14} />} />
        <StatCard label="Top Favorite" value={topArtistDisplay} icon={<Award size={14} />} />
      </div>

      {showOnboarding && (
        <div class="bento-card p-6 border-dashed text-center">
          <div class="w-10 h-10 rounded-full bg-zinc-100 dark:bg-zinc-800 flex items-center justify-center mx-auto mb-2.5 text-zinc-700 dark:text-zinc-300">
            <Music size={18} />
          </div>
          <h3 class="text-sm font-bold text-zinc-900 dark:text-white">
            Listening History Onboarding
          </h3>
          <p class="text-xs text-zinc-500 dark:text-zinc-400 mt-1 max-w-md mx-auto">
            No scrobbles recorded yet. Connect Navidrome or your Subsonic client to Maloja to start
            building personalized discovery charts and smart mixes.
          </p>
        </div>
      )}

      {/* Artists & Tracks — matched height with smooth internal scroll */}
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-3.5 items-stretch">
        <div class="bento-card p-4 sm:p-5 lg:h-[300px] flex flex-col">
          <CardHeader title="Top Artists" icon={<Star size={14} />} />
          {topArtists.length > 0 ? (
            <div class="flex-1 min-h-0 overflow-y-auto pr-1.5 space-y-3">
              {topArtists.map((a, i) => {
                const name = a.artist || a.name || 'Unknown';
                const pct = Math.round(((a.completions || a.plays || 0) / maxArtistScore) * 100);
                return (
                  <div key={`${name}-${i}`} class="space-y-1.5">
                    <div class="flex items-center justify-between text-xs">
                      <div class="flex items-center gap-2.5 min-w-0">
                        <span class="text-[11px] font-bold text-zinc-400 w-4">{i + 1}</span>
                        <span class="font-semibold text-zinc-900 dark:text-white truncate">{name}</span>
                      </div>
                      <span class="text-[11px] text-zinc-500 shrink-0">
                        {a.plays} plays · {a.completions || 0} completed
                      </span>
                    </div>
                    <ProgressBar percent={pct} tone="mono" height="h-1" />
                  </div>
                );
              })}
            </div>
          ) : (
            <p class="text-xs text-zinc-400">No scrobbles recorded yet.</p>
          )}
        </div>

        <div class="bento-card p-4 sm:p-5 lg:h-[300px] flex flex-col">
          <CardHeader title="Top Tracks" icon={<Music size={14} />} />
          {topTracks.length > 0 ? (
            <div class="flex-1 min-h-0 overflow-y-auto pr-1.5 divide-y divide-zinc-200/60 dark:divide-zinc-800/70">
              {topTracks.slice(0, 8).map((t, i) => (
                <div key={i} class="py-2 flex items-center justify-between gap-3 text-xs">
                  <div class="flex items-center gap-2.5 min-w-0">
                    <span class="text-[11px] font-bold text-zinc-400 w-4">{i + 1}</span>
                    <div class="min-w-0">
                      <div class="font-semibold text-zinc-900 dark:text-white truncate">
                        {t.track_title || t.title || 'Unknown'}
                      </div>
                      <div class="text-[11px] text-zinc-500 truncate">{t.artist || '—'}</div>
                    </div>
                  </div>
                  <StatusBadge tone="neutral">{t.plays}×</StatusBadge>
                </div>
              ))}
            </div>
          ) : (
            <p class="text-xs text-zinc-400">No tracks yet.</p>
          )}
        </div>
      </div>

      {/* Listening Clock + Collaborative — matched height with scroll */}
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-3.5 items-stretch">
        <div class="bento-card p-4 sm:p-5 lg:h-[220px] flex flex-col justify-between">
          <CardHeader title="24-Hour Listening Pattern" icon={<Clock size={14} />} />
          <HourlyBarChart values={hours24} />
        </div>

        <div class="bento-card p-4 sm:p-5 lg:h-[220px] flex flex-col">
          <CardHeader title="Others Also Like" icon={<Users size={14} />} />
          {rec?.collaborative && rec.collaborative.length > 0 ? (
            <div class="flex-1 min-h-0 overflow-y-auto pr-1.5 divide-y divide-zinc-200/60 dark:divide-zinc-800/70">
              {rec.collaborative.map((t, i) => {
                const title = t.track_title || t.title || 'Unknown';
                const artist = t.artist || '';
                return (
                  <div key={i} class="py-2 flex items-center justify-between gap-3">
                    <div class="min-w-0">
                      <div class="text-xs font-semibold text-zinc-900 dark:text-white truncate">
                        {title}
                      </div>
                      <div class="text-[11px] text-zinc-500 truncate">{artist || '—'}</div>
                    </div>
                    <PillButton size="xs" variant="primary" onClick={() => queueTrack(title, artist)}>
                      <Download size={11} /> Queue
                    </PillButton>
                  </div>
                );
              })}
            </div>
          ) : (
            <p class="text-xs text-zinc-400">Need more listeners with overlapping taste.</p>
          )}
        </div>
      </div>

      {/* Smart Mix Playlists */}
      <div class="bento-card p-5 sm:p-6">
        <CardHeader title="Suggested Smart Mixes" icon={<ListMusic size={16} />} />
        {mixes.length > 0 ? (
          <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {mixes.map((mix, idx) => (
              <div key={`${mix.name}-${idx}`} class="bento-sub p-4 flex flex-col justify-between gap-3">
                <div>
                  <div class="flex items-center gap-2.5 mb-2">
                    <div class="w-8 h-8 rounded-xl bg-zinc-900 dark:bg-white text-white dark:text-zinc-950 flex items-center justify-center shrink-0">
                      <Music size={14} />
                    </div>
                    <div class="min-w-0">
                      <div class="text-xs font-bold text-zinc-900 dark:text-white truncate">
                        {mix.name}
                      </div>
                      <div class="text-[10px] text-zinc-500">
                        {(mix.based_on || 'smart').replace('_', ' ')}
                        {mix.tracks?.length ? ` · ${mix.tracks.length} tracks` : ''}
                      </div>
                    </div>
                  </div>
                  <p class="text-[11px] text-zinc-500 dark:text-zinc-400 leading-relaxed">
                    {mix.reason}
                  </p>
                </div>
                <div class="flex items-center gap-2">
                  <PillButton size="xs" variant="primary" className="flex-1" onClick={() => exportM3U(mix)}>
                    Export .m3u
                  </PillButton>
                  <PillButton size="xs" variant="secondary" onClick={() => savePlaylist(mix)}>
                    <Plus size={11} /> Save
                  </PillButton>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p class="text-xs text-zinc-400">Not enough listening history yet to generate smart mixes.</p>
        )}
      </div>
    </div>
  );
}
