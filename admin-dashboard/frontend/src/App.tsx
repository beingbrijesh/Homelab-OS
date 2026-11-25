import { useCallback, useEffect, useState } from 'preact/hooks';
import type { ContainerInfo, NavSection, SystemTelemetry } from './types/api';
import { api } from './api/client';
import { useTheme } from './hooks/useTheme';
import { Sidebar } from './components/Sidebar';
import { TopBar } from './components/TopBar';
import { LoginView } from './views/LoginView';
import { RegisterView } from './views/RegisterView';
import { OverviewView, type TelemetryHistory } from './views/OverviewView';
import { ContainersView } from './views/ContainersView';
import { NetworkView } from './views/NetworkView';
import { UsersView } from './views/UsersView';
import { BackupView } from './views/BackupView';
import { MusicView } from './views/MusicView';
import { DownloadView } from './views/DownloadView';
import { RecommendationsView } from './views/RecommendationsView';
import { UpdatesView } from './views/UpdatesView';
import { PowerView } from './views/PowerView';
import { LogsView } from './views/LogsView';
import { SecurityView } from './views/SecurityView';
import { SettingsView } from './views/SettingsView';

type AuthPage = 'loading' | 'login' | 'register' | 'dashboard';

const HISTORY_KEY = 'homelab-sys-history-v1';

function loadCachedHistory(): TelemetryHistory {
  try {
    const raw = sessionStorage.getItem(HISTORY_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed?.labels) && Array.isArray(parsed?.cpu)) {
        return {
          labels: parsed.labels.slice(-20),
          cpu: parsed.cpu.slice(-20),
          ram: (parsed.ram || []).slice(-20),
          disk: (parsed.disk || []).slice(-20),
        };
      }
    }
  } catch {}
  return { labels: [], cpu: [], ram: [], disk: [] };
}

export function App() {
  const { theme, toggleTheme } = useTheme();
  const [page, setPage] = useState<AuthPage>('loading');
  const [admin, setAdmin] = useState('admin');
  const [active, setActive] = useState<NavSection>('overview');
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);

  const [sys, setSys] = useState<SystemTelemetry | null>(null);
  const [history, setHistory] = useState<TelemetryHistory>(loadCachedHistory);
  const [containers, setContainers] = useState<ContainerInfo[]>([]);
  const [containersError, setContainersError] = useState('');
  const [lastUpdated, setLastUpdated] = useState('');
  const [pendingUsersCount, setPendingUsersCount] = useState(0);
  const [updatesAvailableCount, setUpdatesAvailableCount] = useState(0);
  const [offline, setOffline] = useState(!navigator.onLine);
  const [toast, setToast] = useState<{ msg: string; ok: boolean } | null>(null);

  const notify = useCallback((msg: string, ok = true) => {
    setToast({ msg, ok });
  }, []);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 4000);
    return () => clearTimeout(t);
  }, [toast]);

  // PWA Service Worker & online/offline listeners
  useEffect(() => {
    const onOnline = () => setOffline(false);
    const onOffline = () => setOffline(true);
    window.addEventListener('online', onOnline);
    window.addEventListener('offline', onOffline);

    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('/static/sw.js').catch(() => {});
    }
    return () => {
      window.removeEventListener('online', onOnline);
      window.removeEventListener('offline', onOffline);
    };
  }, []);

  // Resolve initial auth state & URL path
  useEffect(() => {
    const path = window.location.pathname;
    if (path === '/register') {
      setPage('register');
      return;
    }
    api<{ authenticated?: boolean; username?: string }>('/api/auth/me').then((res) => {
      if (res && res.authenticated) {
        setAdmin(res.username || 'admin');
        setPage('dashboard');
        if (window.location.pathname !== '/dashboard') {
          window.history.replaceState(null, '', '/dashboard');
        }
      } else {
        setPage(path === '/register' ? 'register' : 'login');
      }
    });
  }, []);

  const loadSystem = useCallback(async (bg = false) => {
    const d = await api<SystemTelemetry>('/api/system', 'GET', null, { bg });
    if (d.error) {
      if (d.error === 'Unauthorized') setPage('login');
      return;
    }
    setSys(d);
    const ts = new Date().toLocaleTimeString('en', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    });
    setLastUpdated(`Updated ${ts}`);
    setHistory((prev) => {
      const next: TelemetryHistory = {
        labels: [...prev.labels, ts].slice(-20),
        cpu: [...prev.cpu, Number(d.cpu_percent) || 0].slice(-20),
        ram: [...prev.ram, Number(d.ram_percent) || 0].slice(-20),
        disk: [...prev.disk, Number(d.disk_percent) || 0].slice(-20),
      };
      try {
        sessionStorage.setItem(HISTORY_KEY, JSON.stringify(next));
      } catch {}
      return next;
    });
  }, []);

  const loadContainers = useCallback(async (bg = false) => {
    const data = await api<ContainerInfo[]>('/api/containers', 'GET', null, { bg });
    if (Array.isArray(data)) {
      setContainers(data);
      setContainersError('');
    } else if (data && typeof data === 'object' && 'error' in data && (data as any).error) {
      setContainersError(String((data as any).error));
    }
  }, []);

  const loadBadges = useCallback(async (bg = false) => {
    const p = await api<{ count?: number }>('/api/users/pending-count', 'GET', null, { bg });
    if (!p.error && typeof p.count === 'number') setPendingUsersCount(p.count);
  }, []);

  // Initial dashboard hydration + fast 2nd sample so graph immediately renders a smooth line
  useEffect(() => {
    if (page !== 'dashboard') return;
    loadSystem(false);
    loadContainers(false);
    loadBadges(false);
    const quickFollowup = setTimeout(() => loadSystem(true), 2200);
    api<{ updates_available_count?: number }>('/api/updates/status', 'GET', null, { bg: true }).then(
      (u) => {
        if (!u.error && typeof u.updates_available_count === 'number') {
          setUpdatesAvailableCount(u.updates_available_count);
        }
      }
    );
    return () => clearTimeout(quickFollowup);
  }, [page, loadSystem, loadContainers, loadBadges]);

  // 8-second background telemetry loop
  useEffect(() => {
    if (page !== 'dashboard') return;
    const timer = setInterval(() => {
      if (active === 'overview' || active === 'backup') loadSystem(true);
      if (active === 'overview' || active === 'containers') loadContainers(true);
      loadBadges(true);
    }, 8000);
    return () => clearInterval(timer);
  }, [page, active, loadSystem, loadContainers, loadBadges]);

  const handleQuickRefresh = () => {
    setRefreshKey((k) => k + 1);
    if (active === 'overview' || active === 'backup') loadSystem(false);
    if (active === 'overview' || active === 'containers') loadContainers(false);
    loadBadges(false);
  };

  const handleLogout = async () => {
    await fetch('/logout', { credentials: 'same-origin' }).catch(() => {});
    window.history.replaceState(null, '', '/login');
    setPage('login');
  };

  if (page === 'loading') {
    return (
      <div class="min-h-[100dvh] w-full flex items-center justify-center text-xs font-medium text-zinc-500">
        Loading Homelab OS...
      </div>
    );
  }

  if (page === 'login') {
    return (
      <LoginView
        theme={theme}
        onToggleTheme={toggleTheme}
        onSuccess={(username) => {
          setAdmin(username);
          window.history.replaceState(null, '', '/dashboard');
          setPage('dashboard');
        }}
        onGoRegister={() => {
          window.history.replaceState(null, '', '/register');
          setPage('register');
        }}
      />
    );
  }

  if (page === 'register') {
    return (
      <RegisterView
        theme={theme}
        onToggleTheme={toggleTheme}
        onGoLogin={() => {
          window.history.replaceState(null, '', '/login');
          setPage('login');
        }}
      />
    );
  }

  const isDark = theme === 'dark';

  return (
    <div class="min-h-[100dvh] lg:h-[100dvh] w-full lg:overflow-hidden flex gap-3.5 p-2.5 sm:p-4">
      {/* Desktop persistent floating sidebar + Mobile slide-over drawer */}
      <Sidebar
        active={active}
        mobileOpen={mobileMenuOpen}
        onCloseMobile={() => setMobileMenuOpen(false)}
        onSelect={(s) => {
          setActive(s);
          if (s === 'containers') loadContainers(false);
          if (s === 'overview' || s === 'backup') loadSystem(false);
        }}
        pendingUsersCount={pendingUsersCount}
        updatesAvailableCount={updatesAvailableCount}
        onLogout={handleLogout}
      />

      {/* Full-Window Responsive Bento Workspace */}
      <main class="flex-1 min-w-0 lg:h-full lg:overflow-y-auto px-0.5 sm:px-1.5 pb-6">
        <TopBar
          admin={admin}
          active={active}
          theme={theme}
          onOpenMobileMenu={() => setMobileMenuOpen(true)}
          onToggleTheme={toggleTheme}
          offline={offline}
          lastUpdated={lastUpdated}
          pendingUsersCount={pendingUsersCount}
          updatesAvailableCount={updatesAvailableCount}
          onQuickRefresh={handleQuickRefresh}
          onNavigate={setActive}
        />

        {active === 'overview' && (
          <OverviewView
            sys={sys}
            containers={containers}
            history={history}
            isDark={isDark}
            onNavigate={setActive}
          />
        )}
        {active === 'containers' && (
          <ContainersView
            containers={containers}
            error={containersError}
            onReload={() => loadContainers(false)}
            onNotify={notify}
          />
        )}
        {active === 'network' && <NetworkView refreshKey={refreshKey} isDark={isDark} />}
        {active === 'users' && (
          <UsersView
            refreshKey={refreshKey}
            onPendingChange={() => loadBadges(false)}
            onNotify={notify}
          />
        )}
        {active === 'backup' && (
          <BackupView sys={sys} refreshKey={refreshKey} onReloadSys={() => loadSystem(false)} />
        )}
        {active === 'music' && <MusicView refreshKey={refreshKey} />}
        {active === 'download' && <DownloadView refreshKey={refreshKey} />}
        {active === 'recommend' && (
          <RecommendationsView admin={admin} refreshKey={refreshKey} onNotify={notify} />
        )}
        {active === 'updates' && (
          <UpdatesView
            refreshKey={refreshKey}
            onBadgeChange={setUpdatesAvailableCount}
            onNotify={notify}
          />
        )}
        {active === 'power' && <PowerView refreshKey={refreshKey} onNotify={notify} />}
        {active === 'logs' && <LogsView refreshKey={refreshKey} />}
        {active === 'security' && <SecurityView refreshKey={refreshKey} onNotify={notify} />}
        {active === 'settings' && <SettingsView theme={theme} onToggleTheme={toggleTheme} />}
      </main>

      {/* Subtle Floating Toast Notification */}
      {toast && (
        <div
          class={`fixed bottom-4 right-4 z-50 px-4 py-2.5 rounded-full text-xs font-semibold shadow-xl border flex items-center gap-2 transition-all max-w-[90vw] ${
            toast.ok
              ? 'bg-zinc-900 text-white border-zinc-800 dark:bg-white dark:text-zinc-950'
              : 'bg-rose-600 text-white border-rose-500'
          }`}
        >
          <span class={`w-2 h-2 rounded-full shrink-0 ${toast.ok ? 'bg-emerald-400' : 'bg-white'}`} />
          <span class="truncate">{toast.msg}</span>
        </div>
      )}
    </div>
  );
}
