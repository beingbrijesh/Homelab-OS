import { useEffect, useRef, useState } from 'preact/hooks';
import { DownloadCloud, Link2, ListMusic, RotateCw, Trash2, X } from 'lucide-preact';
import type { DownloadJob } from '../types/api';
import { api } from '../api/client';
import { formatAudioBadge } from '../utils/format';
import { CardHeader, PillButton, ProgressBar, StatusBadge } from '../components/ui';

export function DownloadView({ refreshKey }: { refreshKey: number }) {
  const [url, setUrl] = useState('');
  const [quality, setQuality] = useState('mp3_320');
  const [embedThumb, setEmbedThumb] = useState(true);
  const [archiveSkip, setArchiveSkip] = useState(true);
  const [rateLimit, setRateLimit] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [feedback, setFeedback] = useState<{ text: string; ok: boolean } | null>(null);
  const [queue, setQueue] = useState<DownloadJob[]>([]);
  const timerRef = useRef<number | null>(null);

  const loadQueue = async (bg = false) => {
    const res = await api<DownloadJob[]>('/api/music/queue', 'GET', null, { bg });
    if (Array.isArray(res)) {
      setQueue(res);
      const hasActive = res.some((r) => r.status === 'downloading' || r.status === 'queued');
      if (timerRef.current) window.clearTimeout(timerRef.current);
      timerRef.current = window.setTimeout(() => loadQueue(true), hasActive ? 4000 : 20000);
    }
  };

  useEffect(() => {
    loadQueue(false);
    return () => {
      if (timerRef.current) window.clearTimeout(timerRef.current);
    };
  }, [refreshKey]);

  const handleSubmit = async (e: Event) => {
    e.preventDefault();
    if (!url.trim()) {
      setFeedback({ text: 'Please paste a media URL first.', ok: false });
      return;
    }
    setSubmitting(true);
    setFeedback(null);
    const res = await api<{ ok?: boolean; message?: string; is_playlist?: boolean }>(
      '/api/music/download',
      'POST',
      {
        url: url.trim(),
        quality,
        format: quality,
        embed_thumbnail: embedThumb,
        archive_skip: archiveSkip,
        rate_limit: rateLimit,
      }
    );
    setSubmitting(false);
    if (res.ok) {
      setFeedback({
        text: `${res.message || 'Added to queue'}${res.is_playlist ? ' — playlist detected' : ''}.`,
        ok: true,
      });
      setUrl('');
      setTimeout(() => loadQueue(false), 900);
    } else {
      setFeedback({ text: res.error || 'Download request failed.', ok: false });
    }
  };

  const jobAction = async (id: number, action: 'retry' | 'cancel' | 'delete') => {
    await api(`/api/music/queue/${id}/${action}`, 'POST');
    setTimeout(() => loadQueue(false), 450);
  };

  return (
    <div class="space-y-5">
      {/* Submission Bento Card */}
      <div class="bento-card p-5 sm:p-6">
        <CardHeader
          title="Queue Audio Download"
          subtitle="YouTube videos & playlists, SoundCloud, Bandcamp, Spotify (matched via YouTube)"
          icon={<Link2 size={16} />}
          action={<StatusBadge tone="ok" dot>Single-Worker Eco Queue</StatusBadge>}
        />

        <form onSubmit={handleSubmit} class="space-y-3.5">
          <div class="flex flex-col sm:flex-row gap-2.5">
            <input
              type="text"
              value={url}
              onInput={(e) => setUrl((e.target as HTMLInputElement).value)}
              placeholder="Paste YouTube, playlist, SoundCloud, Bandcamp or Spotify URL..."
              class="bento-input flex-1"
            />
            <select
              value={quality}
              onChange={(e) => setQuality((e.target as HTMLSelectElement).value)}
              class="bento-input sm:w-52"
            >
              <option value="flac">FLAC (Hi-Res Lossless)</option>
              <option value="opus">OPUS (High-Fidelity 160k+)</option>
              <option value="m4a">M4A / AAC (256 kbps)</option>
              <option value="mp3_320">MP3 (320 kbps Extreme)</option>
              <option value="mp3_256">MP3 (256 kbps Standard)</option>
              <option value="wav">WAV (Uncompressed PCM)</option>
            </select>
            <PillButton type="submit" variant="primary" disabled={submitting}>
              <DownloadCloud size={14} />
              {submitting ? 'Adding...' : 'Download'}
            </PillButton>
          </div>

          <div class="bento-sub px-4 py-3 flex flex-wrap items-center gap-4 text-xs text-zinc-700 dark:text-zinc-300">
            <label class="inline-flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={embedThumb}
                onChange={(e) => setEmbedThumb((e.target as HTMLInputElement).checked)}
                class="accent-zinc-900 dark:accent-white"
              />
              <span>Embed cover art</span>
            </label>
            <label class="inline-flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={archiveSkip}
                onChange={(e) => setArchiveSkip((e.target as HTMLInputElement).checked)}
                class="accent-zinc-900 dark:accent-white"
              />
              <span>Skip already downloaded</span>
            </label>
            <label class="inline-flex items-center gap-2 ml-auto">
              <span class="text-zinc-500">Speed limit:</span>
              <select
                value={rateLimit}
                onChange={(e) => setRateLimit((e.target as HTMLSelectElement).value)}
                class="bento-input py-1 px-2.5 text-xs"
              >
                <option value="">Auto (Profile)</option>
                <option value="2M">2 MB/s</option>
                <option value="1M">1 MB/s (Eco)</option>
                <option value="512K">512 KB/s (Ultra-Light)</option>
              </select>
            </label>
          </div>

          {feedback && (
            <div
              class={`px-3.5 py-2 rounded-2xl text-xs font-medium border ${
                feedback.ok
                  ? 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-emerald-500/25'
                  : 'bg-rose-500/10 text-rose-700 dark:text-rose-400 border-rose-500/25'
              }`}
            >
              {feedback.text}
            </div>
          )}
        </form>
      </div>

      {/* Queue List Card */}
      <div class="bento-card p-5 sm:p-6">
        <CardHeader
          title="Download Queue"
          subtitle="Auto-refreshes every 4s while downloading"
          icon={<ListMusic size={16} />}
          action={<StatusBadge tone="neutral">{queue.length} jobs</StatusBadge>}
        />

        {queue.length === 0 ? (
          <div class="bento-sub p-6 text-center text-xs text-zinc-500">
            No downloads queued yet. Paste a link above to begin.
          </div>
        ) : (
          <div class="space-y-3">
            {queue.map((job) => {
              const tone =
                job.status === 'completed'
                  ? 'ok'
                  : job.status === 'failed'
                  ? 'err'
                  : job.status === 'downloading'
                  ? 'dark'
                  : 'neutral';
              const isPlaylist = !!job.is_playlist && job.total_tracks > 1;
              const overallPct = isPlaylist
                ? Math.round(((job.completed_tracks || 0) / Math.max(1, job.total_tracks)) * 100)
                : job.current_track_pct || 0;

              return (
                <div key={job.id} class="bento-sub p-4 flex flex-col gap-2.5">
                  <div class="flex items-start justify-between gap-3">
                    <div class="min-w-0 flex-1">
                      <div class="flex flex-wrap items-center gap-1.5 mb-1.5">
                        <StatusBadge tone={tone} dot pulse={job.status === 'downloading'}>
                          {job.status}
                        </StatusBadge>
                        <StatusBadge tone="neutral">{job.platform || 'media'}</StatusBadge>
                        <StatusBadge tone="neutral">
                          {formatAudioBadge(job.format, job.quality)}
                        </StatusBadge>
                        {job.is_playlist ? <StatusBadge tone="neutral">playlist</StatusBadge> : null}
                      </div>
                      <div class="text-xs font-semibold text-zinc-900 dark:text-white truncate">
                        {job.title || job.url}
                      </div>
                      {job.error && (
                        <div class="text-[11px] text-rose-600 dark:text-rose-400 mt-1">
                          {job.error.slice(0, 120)}
                        </div>
                      )}
                    </div>

                    <div class="flex items-center gap-1.5 shrink-0">
                      {(job.status === 'failed' || job.status === 'cancelled') && (
                        <PillButton size="xs" variant="ok" onClick={() => jobAction(job.id, 'retry')}>
                          <RotateCw size={11} /> Retry
                        </PillButton>
                      )}
                      {(job.status === 'queued' || job.status === 'downloading') && (
                        <PillButton size="xs" variant="danger" onClick={() => jobAction(job.id, 'cancel')}>
                          <X size={11} /> Cancel
                        </PillButton>
                      )}
                      {(job.status === 'completed' || job.status === 'failed' || job.status === 'cancelled') && (
                        <PillButton size="xs" variant="ghost" onClick={() => jobAction(job.id, 'delete')}>
                          <Trash2 size={12} />
                        </PillButton>
                      )}
                    </div>
                  </div>

                  {job.status === 'downloading' && (
                    <div class="space-y-1.5 pt-1">
                      <div class="flex items-center justify-between text-[11px] text-zinc-500 dark:text-zinc-400">
                        <span class="truncate">
                          {isPlaylist
                            ? `Playlist: ${job.completed_tracks || 0} of ${job.total_tracks} tracks`
                            : job.current_track || 'Downloading...'}
                        </span>
                        <span class="font-semibold text-zinc-900 dark:text-white">{overallPct}%</span>
                      </div>
                      <ProgressBar percent={overallPct} tone="mono" />
                      {isPlaylist && job.current_track && (
                        <div class="space-y-1 pt-1">
                          <div class="flex items-center justify-between text-[10px] text-zinc-400">
                            <span class="truncate">Now: {job.current_track}</span>
                            <span>{job.current_track_pct || 0}%</span>
                          </div>
                          <ProgressBar percent={job.current_track_pct || 0} tone="ok" height="h-1" />
                        </div>
                      )}
                    </div>
                  )}

                  {job.status === 'completed' && isPlaylist && (
                    <div class="text-[11px] text-emerald-600 dark:text-emerald-400 font-medium">
                      ✓ All {job.total_tracks} tracks downloaded and queued for Navidrome scan
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
