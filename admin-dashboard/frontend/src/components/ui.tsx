import type { ComponentChildren } from 'preact';
import { X } from 'lucide-preact';

export type BadgeTone = 'neutral' | 'dark' | 'ok' | 'warn' | 'err';

export function StatusBadge({
  tone = 'neutral',
  dot = false,
  pulse = false,
  className = '',
  children,
}: {
  tone?: BadgeTone;
  dot?: boolean;
  pulse?: boolean;
  className?: string;
  children: ComponentChildren;
}) {
  const styles: Record<BadgeTone, string> = {
    neutral:
      'bg-zinc-100 text-zinc-700 border-zinc-200/80 dark:bg-zinc-800/80 dark:text-zinc-300 dark:border-zinc-700/70',
    dark: 'bg-zinc-900 text-white border-zinc-900 dark:bg-white dark:text-zinc-950 dark:border-white',
    ok: 'bg-emerald-500/10 text-emerald-700 border-emerald-500/25 dark:bg-emerald-500/15 dark:text-emerald-400 dark:border-emerald-500/25',
    warn: 'bg-amber-500/10 text-amber-700 border-amber-500/25 dark:bg-amber-500/15 dark:text-amber-400 dark:border-amber-500/25',
    err: 'bg-rose-500/10 text-rose-700 border-rose-500/25 dark:bg-rose-500/15 dark:text-rose-400 dark:border-rose-500/25',
  };

  const dotStyles: Record<BadgeTone, string> = {
    neutral: 'bg-zinc-400',
    dark: 'bg-white dark:bg-zinc-950',
    ok: 'bg-emerald-500',
    warn: 'bg-amber-500',
    err: 'bg-rose-500',
  };

  return (
    <span
      class={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-semibold border whitespace-nowrap ${styles[tone]} ${className}`}
    >
      {dot && (
        <span
          class={`w-1.5 h-1.5 rounded-full shrink-0 ${dotStyles[tone]} ${
            pulse ? 'animate-soft-pulse' : ''
          }`}
        />
      )}
      {children}
    </span>
  );
}

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'ok' | 'warn' | 'danger';

export function PillButton({
  variant = 'secondary',
  size = 'md',
  className = '',
  disabled = false,
  type = 'button',
  onClick,
  children,
  title,
  id,
}: {
  variant?: ButtonVariant;
  size?: 'xs' | 'sm' | 'md';
  className?: string;
  disabled?: boolean;
  type?: 'button' | 'submit' | 'reset';
  onClick?: (e: MouseEvent) => void;
  children: ComponentChildren;
  title?: string;
  id?: string;
}) {
  const variants: Record<ButtonVariant, string> = {
    primary:
      'bg-zinc-900 text-white hover:bg-zinc-800 dark:bg-zinc-100 dark:text-zinc-950 dark:hover:bg-zinc-200 border border-transparent shadow-sm',
    secondary:
      'bg-white text-zinc-900 hover:bg-zinc-100 dark:bg-zinc-800/90 dark:text-zinc-100 dark:hover:bg-zinc-700/90 border border-zinc-200/90 dark:border-zinc-700/80',
    ghost:
      'bg-transparent text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800/80 dark:hover:text-white border border-transparent',
    ok: 'bg-emerald-600/10 text-emerald-700 hover:bg-emerald-600/20 dark:bg-emerald-500/15 dark:text-emerald-400 dark:hover:bg-emerald-500/25 border border-emerald-500/25',
    warn: 'bg-amber-500/10 text-amber-700 hover:bg-amber-500/20 dark:bg-amber-500/15 dark:text-amber-400 dark:hover:bg-amber-500/25 border border-amber-500/25',
    danger:
      'bg-rose-500/10 text-rose-700 hover:bg-rose-500/20 dark:bg-rose-500/15 dark:text-rose-400 dark:hover:bg-rose-500/25 border border-rose-500/25',
  };

  const sizes: Record<'xs' | 'sm' | 'md', string> = {
    xs: 'px-2.5 py-1 text-[11px] gap-1',
    sm: 'px-3 py-1.5 text-xs gap-1.5',
    md: 'px-4 py-2 text-xs font-semibold gap-1.5',
  };

  return (
    <button
      id={id}
      type={type}
      title={title}
      disabled={disabled}
      onClick={onClick}
      class={`inline-flex items-center justify-center rounded-full font-semibold transition-all duration-150 cursor-pointer disabled:opacity-45 disabled:cursor-not-allowed whitespace-nowrap ${variants[variant]} ${sizes[size]} ${className}`}
    >
      {children}
    </button>
  );
}

export function CardHeader({
  title,
  subtitle,
  icon,
  action,
  dark = false,
}: {
  title: string;
  subtitle?: string;
  icon?: ComponentChildren;
  action?: ComponentChildren;
  dark?: boolean;
}) {
  return (
    <div class="flex items-center justify-between gap-2.5 mb-3">
      <div class="flex items-center gap-2.5 min-w-0">
        {icon && (
          <span
            class={`w-7 h-7 rounded-xl flex items-center justify-center shrink-0 ${
              dark
                ? 'bg-white/10 text-white'
                : 'bg-zinc-100 text-zinc-700 dark:bg-zinc-800/90 dark:text-zinc-200'
            }`}
          >
            {icon}
          </span>
        )}
        <div class="min-w-0">
          <h3
            class={`text-[13px] font-bold tracking-tight truncate ${
              dark ? 'text-white' : 'text-zinc-900 dark:text-zinc-100'
            }`}
          >
            {title}
          </h3>
          {subtitle && (
            <p
              class={`text-[11px] truncate ${
                dark ? 'text-zinc-400' : 'text-zinc-500 dark:text-zinc-400'
              }`}
            >
              {subtitle}
            </p>
          )}
        </div>
      </div>
      {action && <div class="shrink-0">{action}</div>}
    </div>
  );
}

export function StatCard({
  label,
  value,
  sub,
  icon,
  tone = 'default',
  hero = false,
  action,
}: {
  label: string;
  value: string | number;
  sub?: string;
  icon: ComponentChildren;
  tone?: 'default' | 'ok' | 'warn' | 'err';
  hero?: boolean;
  action?: ComponentChildren;
}) {
  const valTone =
    tone === 'ok'
      ? 'text-emerald-600 dark:text-emerald-400'
      : tone === 'warn'
      ? 'text-amber-600 dark:text-amber-400'
      : tone === 'err'
      ? 'text-rose-600 dark:text-rose-400'
      : 'text-zinc-900 dark:text-white';

  const iconWrap = hero
    ? 'bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-950'
    : tone === 'ok'
    ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400'
    : tone === 'warn'
    ? 'bg-amber-500/10 text-amber-600 dark:text-amber-400'
    : tone === 'err'
    ? 'bg-rose-500/10 text-rose-600 dark:text-rose-400'
    : 'bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-200';

  return (
    <div class={`${hero ? 'bento-hero' : 'bento-card'} p-3.5 sm:p-4 h-full flex flex-col justify-between`}>
      <div>
        <div class="flex items-center justify-between gap-2 mb-2">
          <div class="flex items-center gap-2 min-w-0">
            <span class={`w-7 h-7 rounded-xl flex items-center justify-center shrink-0 ${iconWrap}`}>
              {icon}
            </span>
            <span class="text-[11px] font-semibold truncate text-zinc-500 dark:text-zinc-400">
              {label}
            </span>
          </div>
          {action && <div class="shrink-0">{action}</div>}
        </div>
        <div class={`text-xl sm:text-2xl font-bold tracking-tight tabular-nums leading-tight truncate ${valTone}`}>
          {value}
        </div>
      </div>
      {sub && (
        <div class="text-[11px] mt-1.5 truncate text-zinc-500 dark:text-zinc-400">
          {sub}
        </div>
      )}
    </div>
  );
}

/**
 * Distinct, recognizable vector icons tailored to each Homelab service
 */
export function ServiceIcon({ name, size = 16 }: { name: string; size?: number }) {
  const n = name.toLowerCase();

  // Nextcloud: 3 interlocking circles
  if (n.includes('nextcloud')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1">
        <circle cx="12" cy="12" r="4.2" />
        <circle cx="5.2" cy="12" r="2.6" />
        <circle cx="18.8" cy="12" r="2.6" />
      </svg>
    );
  }

  // MariaDB / MySQL: stacked database drum
  if (n.includes('maria') || n.includes('mysql') || n.includes('db')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
        <ellipse cx="12" cy="5.5" rx="7.5" ry="2.8" />
        <path d="M4.5 5.5v13c0 1.55 3.36 2.8 7.5 2.8s7.5-1.25 7.5-2.8v-13" />
        <path d="M4.5 12c0 1.55 3.36 2.8 7.5 2.8s7.5-1.25 7.5-2.8" />
      </svg>
    );
  }

  // Redis: layered cache diamond stack
  if (n.includes('redis')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round">
        <polygon points="12 3 21 8 12 13 3 8 12 3" />
        <polyline points="3 12.5 12 17.5 21 12.5" />
        <polyline points="3 16.5 12 21.5 21 16.5" />
      </svg>
    );
  }

  // Pi-hole: DNS shield + bullseye filter
  if (n.includes('pihole')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
        <circle cx="12" cy="11.5" r="2.5" />
      </svg>
    );
  }

  // Navidrome: vinyl disc with note center
  if (n.includes('navidrome')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="12" cy="12" r="9" />
        <circle cx="12" cy="12" r="2.5" />
        <path d="M12 3a9 9 0 0 1 6.3 2.6" stroke-linecap="round" />
      </svg>
    );
  }

  // Maloja: audio equalizer / scrobble waveform
  if (n.includes('maloja')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round">
        <line x1="4" y1="10" x2="4" y2="14" />
        <line x1="8" y1="6" x2="8" y2="18" />
        <line x1="12" y1="3" x2="12" y2="21" />
        <line x1="16" y1="7" x2="16" y2="17" />
        <line x1="20" y1="10" x2="20" y2="14" />
      </svg>
    );
  }

  // Nginx Proxy: reverse proxy routing hexagon
  if (n.includes('nginx') || n.includes('proxy')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round" stroke-linecap="round">
        <polygon points="12 2 21 7 21 17 12 22 3 17 3 7 12 2" />
        <path d="M9 16V8l6 8V8" />
      </svg>
    );
  }

  // Samba: networked shared folder
  if (n.includes('samba')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round" stroke-linecap="round">
        <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z" />
        <path d="M8 21h8M12 18v3" />
      </svg>
    );
  }

  // Admin Dashboard: bento 4-tile grid
  if (n.includes('dashboard')) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <rect x="3" y="3" width="7.5" height="7.5" rx="2" />
        <rect x="13.5" y="3" width="7.5" height="7.5" rx="2" />
        <rect x="3" y="13.5" width="7.5" height="7.5" rx="2" />
        <rect x="13.5" y="13.5" width="7.5" height="7.5" rx="2" />
      </svg>
    );
  }

  // Default Docker container cube
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round">
      <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" />
      <polyline points="3.27 6.96 12 12.01 20.73 6.96" />
      <line x1="12" y1="22.08" x2="12" y2="12" />
    </svg>
  );
}

export function Modal({
  open,
  title,
  onClose,
  children,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ComponentChildren;
}) {
  if (!open) return null;
  return (
    <div
      class="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-3 sm:p-4"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div class="bento-card w-full max-w-3xl max-h-[88dvh] flex flex-col overflow-hidden">
        <div class="px-4 sm:px-5 py-3.5 border-b border-zinc-200/80 dark:border-zinc-800 flex items-center justify-between gap-2">
          <span class="text-sm font-semibold text-zinc-900 dark:text-white truncate">{title}</span>
          <button
            type="button"
            onClick={onClose}
            class="w-8 h-8 rounded-full flex items-center justify-center text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900 dark:hover:bg-zinc-800 dark:hover:text-white transition-colors cursor-pointer shrink-0"
            aria-label="Close modal"
          >
            <X size={16} />
          </button>
        </div>
        <div class="p-4 sm:p-5 overflow-y-auto flex-1">{children}</div>
      </div>
    </div>
  );
}

export function ProgressBar({
  percent,
  tone = 'mono',
  height = 'h-1.5',
}: {
  percent: number;
  tone?: 'mono' | 'ok' | 'warn' | 'err';
  height?: string;
}) {
  const clamped = Math.max(0, Math.min(100, Math.round(percent || 0)));
  const fill: Record<string, string> = {
    mono: 'bg-zinc-900 dark:bg-white',
    ok: 'bg-emerald-500',
    warn: 'bg-amber-500',
    err: 'bg-rose-500',
  };
  return (
    <div class={`w-full ${height} rounded-full bg-zinc-200/80 dark:bg-zinc-800 overflow-hidden`}>
      <div
        class={`h-full rounded-full transition-all duration-500 ${fill[tone]}`}
        style={{ width: `${clamped}%` }}
      />
    </div>
  );
}
