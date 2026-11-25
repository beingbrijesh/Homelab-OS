import {
  LayoutGrid,
  Container,
  Activity,
  Users,
  HardDrive,
  Disc3,
  DownloadCloud,
  Sparkles,
  ArrowUpCircle,
  Zap,
  ScrollText,
  ShieldCheck,
  Settings,
  LogOut,
  Server,
  X,
} from 'lucide-preact';
import type { NavSection } from '../types/api';

interface NavGroup {
  label: string;
  items: Array<{
    id: NavSection;
    label: string;
    icon: any;
    badge?: boolean;
    badgeTone?: 'ok' | 'err';
  }>;
}

export function Sidebar({
  active,
  mobileOpen,
  onCloseMobile,
  onSelect,
  pendingUsersCount,
  updatesAvailableCount,
  onLogout,
}: {
  active: NavSection;
  mobileOpen: boolean;
  onCloseMobile: () => void;
  onSelect: (id: NavSection) => void;
  pendingUsersCount: number;
  updatesAvailableCount: number;
  onLogout: () => void;
}) {
  const groups: NavGroup[] = [
    {
      label: 'Monitor',
      items: [
        { id: 'overview', label: 'Dashboard', icon: LayoutGrid },
        { id: 'containers', label: 'Containers', icon: Container },
        { id: 'network', label: 'Network', icon: Activity },
      ],
    },
    {
      label: 'Manage',
      items: [
        {
          id: 'users',
          label: 'Users',
          icon: Users,
          badge: pendingUsersCount > 0,
          badgeTone: 'err',
        },
        { id: 'backup', label: 'Backup', icon: HardDrive },
      ],
    },
    {
      label: 'Music',
      items: [
        { id: 'music', label: 'Navidrome', icon: Disc3 },
        { id: 'download', label: 'Download', icon: DownloadCloud },
        { id: 'recommend', label: 'Discover', icon: Sparkles },
      ],
    },
    {
      label: 'System',
      items: [
        {
          id: 'updates',
          label: 'Updates',
          icon: ArrowUpCircle,
          badge: updatesAvailableCount > 0,
          badgeTone: 'ok',
        },
        { id: 'power', label: 'Power & RAM', icon: Zap },
        { id: 'logs', label: 'Activity Log', icon: ScrollText },
        { id: 'security', label: 'Security', icon: ShieldCheck },
      ],
    },
  ];

  const handlePick = (id: NavSection) => {
    onSelect(id);
    onCloseMobile();
  };

  const navContent = (
    <div class="bento-card w-[236px] lg:w-[224px] h-full flex flex-col overflow-hidden select-none">
      {/* Brand mark */}
      <div class="px-4 pt-4 pb-3.5 flex items-center justify-between gap-2 border-b border-zinc-200/60 dark:border-zinc-800/70">
        <div class="flex items-center gap-2.5 min-w-0">
          <div class="w-8 h-8 rounded-xl bg-zinc-900 dark:bg-white text-white dark:text-zinc-950 flex items-center justify-center shrink-0 shadow-sm">
            <Server size={16} strokeWidth={2.2} />
          </div>
          <div class="min-w-0">
            <div class="text-sm font-bold tracking-tight text-zinc-900 dark:text-white leading-tight truncate">
              Homelab OS
            </div>
            <div class="text-[9.5px] font-semibold uppercase tracking-widest text-zinc-400 dark:text-zinc-500">
              Control Plane
            </div>
          </div>
        </div>
        <button
          type="button"
          onClick={onCloseMobile}
          aria-label="Close navigation"
          class="lg:hidden w-8 h-8 rounded-full flex items-center justify-center text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800 cursor-pointer"
        >
          <X size={16} />
        </button>
      </div>

      {/* Navigation groups */}
      <nav class="flex-1 overflow-y-auto px-2.5 py-3 space-y-3.5">
        {groups.map((group) => (
          <div key={group.label}>
            <div class="px-3 mb-1 text-[9.5px] font-bold uppercase tracking-widest text-zinc-400 dark:text-zinc-500">
              {group.label}
            </div>
            <div class="space-y-0.5">
              {group.items.map((item) => {
                const Icon = item.icon;
                const isActive = active === item.id;
                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => handlePick(item.id)}
                    class={`w-full flex items-center gap-2.5 px-3 py-2 rounded-full text-[12.5px] font-medium transition-all duration-150 cursor-pointer ${
                      isActive
                        ? 'bg-zinc-900 text-white dark:bg-white dark:text-zinc-950 shadow-sm font-semibold'
                        : 'text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800/80 dark:hover:text-white'
                    }`}
                  >
                    <Icon size={15} strokeWidth={isActive ? 2.2 : 1.8} class="shrink-0" />
                    <span class="truncate flex-1 text-left">{item.label}</span>
                    {item.badge && (
                      <span
                        class={`w-2 h-2 rounded-full shrink-0 ${
                          item.badgeTone === 'ok' ? 'bg-emerald-500' : 'bg-rose-500'
                        }`}
                      />
                    )}
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </nav>

      {/* Footer actions */}
      <div class="p-2.5 border-t border-zinc-200/70 dark:border-zinc-800/80 space-y-0.5">
        <button
          type="button"
          onClick={() => handlePick('settings')}
          class={`w-full flex items-center gap-2.5 px-3 py-2 rounded-full text-[12.5px] font-medium transition-all cursor-pointer ${
            active === 'settings'
              ? 'bg-zinc-900 text-white dark:bg-white dark:text-zinc-950 font-semibold shadow-sm'
              : 'text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800/80 dark:hover:text-white'
          }`}
        >
          <Settings size={15} strokeWidth={active === 'settings' ? 2.2 : 1.8} class="shrink-0" />
          <span>Settings</span>
        </button>
        <button
          type="button"
          onClick={() => {
            onCloseMobile();
            onLogout();
          }}
          class="w-full flex items-center gap-2.5 px-3 py-2 rounded-full text-[12.5px] font-medium text-zinc-500 hover:bg-rose-500/10 hover:text-rose-600 dark:text-zinc-400 dark:hover:text-rose-400 transition-all cursor-pointer"
        >
          <LogOut size={15} strokeWidth={1.8} class="shrink-0" />
          <span>Sign out</span>
        </button>
      </div>
    </div>
  );

  return (
    <>
      {/* Desktop persistent floating sidebar */}
      <aside class="hidden lg:block shrink-0 h-full">{navContent}</aside>

      {/* Mobile / Tablet slide-over drawer */}
      {mobileOpen && (
        <div
          class="fixed inset-0 z-50 lg:hidden flex bg-black/50 backdrop-blur-xs p-2.5"
          onClick={(e) => {
            if (e.target === e.currentTarget) onCloseMobile();
          }}
        >
          <div class="h-full max-h-full">{navContent}</div>
        </div>
      )}
    </>
  );
}
