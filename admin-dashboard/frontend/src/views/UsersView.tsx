import { useEffect, useState } from 'preact/hooks';
import { Check, RefreshCw, Trash2, UserCheck, Users, X, Ban } from 'lucide-preact';
import type { UserRecord } from '../types/api';
import { api } from '../api/client';
import { CardHeader, PillButton, StatusBadge } from '../components/ui';

export function UsersView({
  refreshKey,
  onPendingChange,
  onNotify,
}: {
  refreshKey: number;
  onPendingChange: () => void;
  onNotify: (msg: string, ok?: boolean) => void;
}) {
  const [users, setUsers] = useState<UserRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [syncMsg, setSyncMsg] = useState<{ text: string; ok: boolean } | null>(null);

  const loadUsers = async () => {
    setLoading(true);
    const res = await api<UserRecord[]>('/api/users');
    if (Array.isArray(res)) setUsers(res);
    setLoading(false);
  };

  useEffect(() => {
    loadUsers();
  }, [refreshKey]);

  const handleAction = async (id: number, action: 'approve' | 'block' | 'unblock' | 'delete') => {
    if (!confirm(`${action.charAt(0).toUpperCase() + action.slice(1)} this user?`)) return;
    const res = await api(`/api/users/${id}/${action}`, 'POST');
    if (res.error) {
      onNotify(res.error, false);
    } else {
      onNotify(`User ${action}d successfully.`);
      loadUsers();
      onPendingChange();
    }
  };

  const handleSyncNextcloud = async () => {
    setSyncing(true);
    setSyncMsg(null);
    const res = await api<{ ok?: boolean; total?: number; synced?: number }>('/api/users/sync-nextcloud', 'POST');
    setSyncing(false);
    if (res.ok) {
      setSyncMsg({ text: `Synced ${res.total ?? 0} users (${res.synced ?? 0} new).`, ok: true });
      loadUsers();
    } else {
      setSyncMsg({ text: res.error || 'Nextcloud sync failed.', ok: false });
    }
  };

  const pending = users.filter((u) => u.status === 'pending');
  const rest = users.filter((u) => u.status !== 'pending');

  return (
    <div class="space-y-5">
      {/* Pending Approval Card */}
      <div class="bento-card p-5 sm:p-6">
        <CardHeader
          title="Pending Approval"
          subtitle="Review new account requests"
          icon={<UserCheck size={16} />}
          action={
            <StatusBadge tone={pending.length > 0 ? 'warn' : 'neutral'} dot>
              {pending.length} pending
            </StatusBadge>
          }
        />
        {pending.length > 0 ? (
          <div class="divide-y divide-zinc-200/70 dark:divide-zinc-800">
            {pending.map((u) => (
              <div key={u.id} class="py-3 flex flex-wrap items-center justify-between gap-3">
                <div class="flex items-center gap-3 min-w-0">
                  <div class="w-9 h-9 rounded-full bg-zinc-900 dark:bg-white text-white dark:text-zinc-950 font-bold text-xs flex items-center justify-center shrink-0">
                    {(u.username || '?')[0].toUpperCase()}
                  </div>
                  <div class="min-w-0">
                    <div class="text-sm font-semibold text-zinc-900 dark:text-white truncate">
                      {u.username}
                    </div>
                    <div class="text-xs text-zinc-500 dark:text-zinc-400 truncate">
                      {u.email} · {u.created_at?.slice(0, 10)}
                    </div>
                  </div>
                </div>
                <div class="flex items-center gap-2">
                  <PillButton size="xs" variant="ok" onClick={() => handleAction(u.id, 'approve')}>
                    <Check size={12} /> Approve
                  </PillButton>
                  <PillButton size="xs" variant="danger" onClick={() => handleAction(u.id, 'delete')}>
                    <X size={12} /> Reject
                  </PillButton>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div class="bento-sub p-4 text-xs text-zinc-500 dark:text-zinc-400">
            No pending account requests.
          </div>
        )}
      </div>

      {/* All Users Card */}
      <div class="bento-card p-5 sm:p-6">
        <CardHeader
          title="All Users"
          subtitle="Managed homelab accounts"
          icon={<Users size={16} />}
          action={
            <div class="flex items-center gap-2">
              <PillButton size="sm" variant="primary" disabled={syncing} onClick={handleSyncNextcloud}>
                <RefreshCw size={12} class={syncing ? 'animate-spin' : ''} />
                {syncing ? 'Syncing...' : 'Sync Nextcloud'}
              </PillButton>
            </div>
          }
        />

        {syncMsg && (
          <div
            class={`mb-4 px-3.5 py-2 rounded-2xl text-xs font-medium border ${
              syncMsg.ok
                ? 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-emerald-500/25'
                : 'bg-rose-500/10 text-rose-700 dark:text-rose-400 border-rose-500/25'
            }`}
          >
            {syncMsg.text}
          </div>
        )}

        {loading ? (
          <p class="text-xs text-zinc-400 py-4">Loading users...</p>
        ) : rest.length > 0 ? (
          <div class="overflow-x-auto">
            <table class="w-full text-left border-collapse text-xs">
              <thead>
                <tr class="border-b border-zinc-200/80 dark:border-zinc-800 text-[10px] font-semibold uppercase tracking-widest text-zinc-400">
                  <th class="py-2.5 pr-4">User</th>
                  <th class="py-2.5 pr-4">Email</th>
                  <th class="py-2.5 pr-4">Status</th>
                  <th class="py-2.5 pr-4">Joined</th>
                  <th class="py-2.5 text-right">Actions</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-zinc-200/60 dark:divide-zinc-800/70">
                {rest.map((u) => (
                  <tr key={u.id} class="hover:bg-zinc-50 dark:hover:bg-zinc-900/40 transition-colors">
                    <td class="py-3 pr-4">
                      <div class="flex items-center gap-2.5">
                        <div class="w-7 h-7 rounded-full bg-zinc-100 dark:bg-zinc-800 text-zinc-900 dark:text-white font-bold text-[11px] flex items-center justify-center shrink-0">
                          {(u.username || '?')[0].toUpperCase()}
                        </div>
                        <span class="font-semibold text-zinc-900 dark:text-white">{u.username}</span>
                      </div>
                    </td>
                    <td class="py-3 pr-4 text-zinc-500 dark:text-zinc-400">{u.email}</td>
                    <td class="py-3 pr-4">
                      <StatusBadge
                        tone={u.status === 'active' ? 'ok' : u.status === 'blocked' ? 'err' : 'neutral'}
                        dot
                      >
                        {u.status}
                      </StatusBadge>
                    </td>
                    <td class="py-3 pr-4 text-zinc-400 font-mono text-[11px]">
                      {u.created_at?.slice(0, 10)}
                    </td>
                    <td class="py-3 text-right">
                      <div class="inline-flex items-center gap-1.5">
                        {u.status === 'active' ? (
                          <PillButton size="xs" variant="warn" onClick={() => handleAction(u.id, 'block')}>
                            <Ban size={11} /> Block
                          </PillButton>
                        ) : (
                          <PillButton size="xs" variant="ok" onClick={() => handleAction(u.id, 'unblock')}>
                            <Check size={11} /> Unblock
                          </PillButton>
                        )}
                        <PillButton size="xs" variant="danger" onClick={() => handleAction(u.id, 'delete')}>
                          <Trash2 size={11} />
                        </PillButton>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div class="bento-sub p-5 text-center text-xs text-zinc-500">
            No users found. Use Sync Nextcloud above to import existing accounts.
          </div>
        )}
      </div>
    </div>
  );
}
