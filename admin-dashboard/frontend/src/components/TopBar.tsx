import {
  Activity,
  ArrowUpCircle,
  Bell,
  Container,
  Disc3,
  DownloadCloud,
  HardDrive,
  LayoutGrid,
  Menu,
  Moon,
  Plus,
  RefreshCw,
  ScrollText,
  Settings,
  ShieldCheck,
  Sparkles,
  Sun,
  Users,
  WifiOff,
  Zap,
} from 'lucide-preact';
import type { NavSection } from '../types/api';
import type { ThemeMode } from '../hooks/useTheme';
import { StatusBadge } from './ui';

const SECTION_META: Record<NavSection, { title: string; subtitle: string; icon: any }> = {
  overview: { title: 'Dashboard', subtitle: 'Live telemetry & service health', icon: LayoutGrid },
  containers: { title: 'Docker Containers', subtitle: 'Running workloads & logs', icon: Container },
  network: { title: 'Network Monitor', subtitle: 'Bandwidth & multi-year rollups', icon: Activity },
  users: { title: 'User Management', subtitle: 'Approvals & Nextcloud sync', icon: Users },
  backup: { title: 'Backup Snapshots', subtitle: 'Storage & automated archives', icon: HardDrive },
  music: { title: 'Navidrome Media', subtitle: 'Library stats & Subsonic apps', icon: Disc3 },
  download: { title: 'Media Downloader', subtitle: 'yt-dlp queue & playlist sync', icon: DownloadCloud },
  recommend: { title: 'Music Discovery', subtitle: 'Scrobbles & smart mixes', icon: Sparkles },
  updates: { title: 'App-Store Updates', subtitle: 'Digests & Nextcloud automation', icon: ArrowUpCircle },
  power: { title: 'Power & Resources', subtitle: 'RAM compaction & Eco-Sleep', icon: Zap },
  logs: { title: 'Activity Log', subtitle: 'Audit trail & system alerts', icon: ScrollText },
  security: { title: 'Security & Zero Trust', subtitle: 'IP bans & Cloudflare Access', icon: ShieldCheck },
  settings: { title: 'Settings', subtitle: 'Account & theme preferences', icon: Settings },
};

export function TopBar({
  admin,
  active,
  theme,
  onOpenMobileMenu,
  onToggleTheme,
  offline,
  lastUpdated,
  pendingUsersCount,
  updatesAvailableCount,
  onQuickRefresh,
  onNavigate,
}: {
  admin: string;
  active: NavSection;
  theme: ThemeMode;
  onOpenMobileMenu: () => void;
  onToggleTheme: () => void;
  offline: boolean;
  lastUpdated: string;
  pendingUsersCount: number;
  updatesAvailableCount: number;
  onQuickRefresh: () => void;
  onNavigate: (s: NavSection) => void;
}) {
  const meta = SECTION_META[active];
  const PageIcon = meta.icon;
  const hasAlerts = pendingUsersCount > 0 || updatesAvailableCount > 0;

  return (
    <header class="flex items-center justify-between gap-2.5 pb-4">
      <div class="flex items-center gap-2.5 min-w-0">
        {/* Mobile/Tablet menu toggle */}
        <button
          type="button"
          onClick={onOpenMobileMenu}
          aria-label="Open navigation menu"
          class="lg:hidden w-9 h-9 rounded-full bg-white dark:bg-zinc-900 border border-zinc-200/90 dark:border-zinc-800 flex items-center justify-center text-zinc-800 dark:text-zinc-200 shrink-0 cursor-pointer shadow-xs"
        >
          <Menu size={17} />
        </button>

        {active !== 'overview' && (
          <div class="hidden sm:flex w-9 h-9 rounded-2xl bg-zinc-900 dark:bg-white text-white dark:text-zinc-950 items-center justify-center shrink-0">
            <PageIcon size={17} />
          </div>
        )}

        <div class="min-w-0">
          {active === 'overview' ? (
            <>
              <h1 class="text-xl sm:text-2xl font-bold tracking-tight text-zinc-900 dark:text-white leading-tight truncate">
                Hi, {admin}!
              </h1>
              <p class="text-[11px] text-zinc-500 dark:text-zinc-400 truncate">
                Homelab OS · {lastUpdated || 'Live telemetry'}
              </p>
            </>
          ) : (
            <>
              <h1 class="text-lg sm:text-xl font-bold tracking-tight text-zinc-900 dark:text-white leading-tight truncate">
                {meta.title}
              </h1>
              <p class="text-[11px] text-zinc-500 dark:text-zinc-400 truncate">{meta.subtitle}</p>
            </>
          )}
        </div>
      </div>

      {/* Right capsule actions */}
      <div class="flex items-center gap-1.5 sm:gap-2 shrink-0">
        {offline ? (
          <StatusBadge tone="warn" dot>
            <WifiOff size={11} /> <span class="hidden sm:inline">Offline Mode</span>
          </StatusBadge>
        ) : (
          <StatusBadge tone="ok" dot pulse className="hidden md:inline-flex">
            Live
          </StatusBadge>
        )}

        {active === 'overview' && (
          <button
            type="button"
            onClick={() => onNavigate('download')}
            class="hidden sm:inline-flex items-center gap-1.5 px-3.5 py-2 rounded-full bg-zinc-900 text-white hover:bg-zinc-800 dark:bg-white dark:text-zinc-950 dark:hover:bg-zinc-200 text-xs font-semibold shadow-sm transition-all cursor-pointer"
          >
            <Plus size={14} strokeWidth={2.5} />
            Queue Media
          </button>
        )}

        <button
          type="button"
          onClick={onQuickRefresh}
          title="Refresh current view"
          class="w-8 h-8 sm:w-9 sm:h-9 rounded-full bg-white dark:bg-zinc-900 border border-zinc-200/90 dark:border-zinc-800 flex items-center justify-center text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors cursor-pointer"
        >
          <RefreshCw size={14} />
        </button>

        <button
          type="button"
          onClick={onToggleTheme}
          title={theme === 'light' ? 'Switch to Dark Mode' : 'Switch to Light Mode'}
          aria-label="Toggle theme"
          class="w-8 h-8 sm:w-9 sm:h-9 rounded-full bg-white dark:bg-zinc-900 border border-zinc-200/90 dark:border-zinc-800 flex items-center justify-center text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors cursor-pointer"
        >
          {theme === 'light' ? <Moon size={14} /> : <Sun size={14} />}
        </button>

        <button
          type="button"
          onClick={() =>
            onNavigate(pendingUsersCount > 0 ? 'users' : updatesAvailableCount > 0 ? 'updates' : 'logs')
          }
          title="Notifications & Activity"
          class="relative w-8 h-8 sm:w-9 sm:h-9 rounded-full bg-white dark:bg-zinc-900 border border-zinc-200/90 dark:border-zinc-800 flex items-center justify-center text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors cursor-pointer"
        >
          <Bell size={14} />
          {hasAlerts && (
            <span class="absolute top-1.5 right-1.5 w-2 h-2 rounded-full bg-rose-500 ring-2 ring-white dark:ring-zinc-900" />
          )}
        </button>

        <button
          type="button"
          onClick={() => onNavigate('settings')}
          title={`Signed in as ${admin}`}
          class="hidden sm:flex w-9 h-9 rounded-full bg-zinc-900 dark:bg-white text-white dark:text-zinc-950 font-bold text-xs items-center justify-center shadow-sm cursor-pointer hover:opacity-90"
        >
          {(admin || 'A')[0].toUpperCase()}
        </button>
      </div>
    </header>
  );
}
