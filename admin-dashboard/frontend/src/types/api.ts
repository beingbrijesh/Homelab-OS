export type NavSection =
  | 'overview'
  | 'containers'
  | 'network'
  | 'users'
  | 'backup'
  | 'music'
  | 'download'
  | 'recommend'
  | 'updates'
  | 'power'
  | 'logs'
  | 'security'
  | 'settings';

export interface ApiError {
  error?: string;
  detail?: string;
  ok?: boolean;
}

export interface BatteryInfo {
  percent: number;
  charging: boolean;
  time_left?: number | null;
}

export interface DiskBackupInfo {
  used_gb: number;
  total_gb: number;
  percent?: number;
}

export interface SystemTelemetry extends ApiError {
  cpu_percent: number;
  cpu_count?: number;
  cpu_freq_ghz?: number | string;
  ram_percent: number;
  ram_used_gb: number;
  ram_total_gb: number;
  disk_percent: number;
  disk_used_gb: number;
  disk_total_gb: number;
  temperatures?: Record<string, number>;
  battery?: BatteryInfo | null;
  uptime: string;
  backup_mounted: boolean;
  disk_backup?: DiskBackupInfo | null;
}

export interface ContainerInfo {
  name: string;
  image: string;
  status: string;
  managed?: boolean;
  cpu_percent: number;
  mem_mb: number;
}

export interface UserRecord {
  id: number;
  username: string;
  email: string;
  status: 'pending' | 'active' | 'blocked' | string;
  created_at: string;
  nextcloud_uid?: string | null;
}

export interface BackupStatus extends ApiError {
  last_logs?: string[];
  mounted?: boolean;
}

export interface MusicStatus extends ApiError {
  navidrome_running: boolean;
  music_dir: string;
  music_dir_exists: boolean;
  music_file_count: number;
  artists_count?: number;
  albums_count?: number;
  last_scan?: string;
  navidrome_url?: string;
}

export interface DownloadJob {
  id: number;
  url: string;
  title?: string;
  platform?: string;
  status: 'queued' | 'downloading' | 'completed' | 'failed' | 'cancelled' | string;
  total_tracks: number;
  completed_tracks: number;
  current_track?: string;
  current_track_pct?: number;
  quality?: string;
  format?: string;
  error?: string;
  is_playlist?: number | boolean;
  created_at?: string;
}

export interface MusicStats extends ApiError {
  total_plays?: number;
  total_scrobbles?: number;
  unique_users?: number;
  active_today?: number;
  top_artist?: string;
  top_tracks?: Array<{ track_title?: string; title?: string; artist?: string; plays: number }>;
}

export interface SmartMix {
  name: string;
  reason: string;
  based_on?: string;
  tracks?: Array<{ track_path?: string; track_title?: string; title?: string; artist?: string }>;
}

export interface RecommendationsData extends ApiError {
  total_scrobbles?: number;
  top_artists?: Array<{ artist?: string; name?: string; plays: number; completions?: number }>;
  top_tracks?: Array<{ track_title?: string; title?: string; artist?: string; plays: number }>;
  time_pattern?: Array<{ hour_of_day?: number; hour?: number; plays: number }>;
  time_patterns?: Array<{ hour_of_day?: number; hour?: number; plays: number }>;
  listening_clock?: Array<{ hour_of_day?: number; hour?: number; plays: number }>;
  collaborative?: Array<{ track_title?: string; title?: string; artist?: string }>;
  smart_mixes?: SmartMix[];
  playlist_suggestions?: SmartMix[];
  suggestions?: SmartMix[];
}

export interface NetInterfaceLive {
  iface: string;
  bytes_in_rate?: number;
  bytes_out_rate?: number;
  rate_in_human?: string;
  rate_out_human?: string;
}

export interface NetContainerDelta {
  container: string;
  delta_in?: number;
  delta_out?: number;
}

export interface NetworkLive extends ApiError {
  interfaces?: NetInterfaceLive[];
  containers?: NetContainerDelta[];
}

export interface NetworkHistoryRow {
  iface: string;
  in_rate?: number;
  out_rate?: number;
  day?: string;
  ts?: string;
}

export interface NetworkSummaryRow {
  iface: string;
  bytes_in?: number;
  bytes_out?: number;
  tin?: number;
  tout?: number;
  human_in?: string;
  human_out?: string;
}

export interface NetworkTotalPair {
  bytes_in?: number;
  bytes_out?: number;
  in?: number;
  out?: number;
}

export interface NetworkSummary extends ApiError {
  today?: NetworkSummaryRow[];
  this_week?: NetworkSummaryRow[];
  week?: NetworkSummaryRow[];
  this_month?: NetworkSummaryRow[];
  month?: NetworkSummaryRow[];
  this_year?: NetworkSummaryRow[];
  year?: NetworkSummaryRow[];
  all_time?: NetworkSummaryRow[];
  totals?: {
    today?: NetworkTotalPair;
    this_week?: NetworkTotalPair;
    this_month?: NetworkTotalPair;
    this_year?: NetworkTotalPair;
    all_time?: NetworkTotalPair;
  };
}

export interface LogStats extends ApiError {
  total?: number;
  today?: number;
  warnings?: number;
  errors?: number;
  unresolved_events?: number;
}

export interface LogEntry {
  id?: number;
  timestamp: string;
  severity: string;
  category: string;
  actor: string;
  action: string;
  target?: string;
  detail?: string;
  duration_ms?: number;
  status: string;
}

export interface SystemEvent {
  id: number;
  timestamp: string;
  event_type: string;
  source?: string;
  message: string;
  severity: string;
  resolved: number | boolean;
}

export interface IpBan {
  id: number;
  ip: string;
  reason?: string;
  banned_at?: string;
  expires_at?: string | null;
}

export interface LoginAttempt {
  id?: number;
  attempted_at?: string;
  ip: string;
  username?: string;
  success: number | boolean;
  user_agent?: string;
}

export interface ZeroTrustSettings extends ApiError {
  enabled: boolean;
  allowed_emails: string[];
  bypass_local?: boolean;
}

export interface UpdateSettings {
  auto_update_enabled: boolean;
  schedule_freq: string;
  schedule_day: string;
  schedule_time: string;
  backup_before: boolean;
  update_nextcloud_apps: boolean;
}

export interface UpdateServiceItem {
  name: string;
  image?: string;
  source?: string;
  current_version?: string;
  latest_version?: string;
  update_available?: boolean;
  note?: string;
}

export interface UpdateJob {
  id: number;
  target: string;
  status: string;
  current_step?: string;
  progress_pct?: number;
  log?: string;
  error?: string;
  cancel_requested?: boolean;
  created_at?: string;
}

export interface UpdatesStatus extends ApiError {
  settings?: UpdateSettings;
  last_checked?: string;
  updates_available_count?: number;
  nextcloud_info?: {
    running?: boolean;
    version?: string;
    maintenance?: boolean;
    core_update_available?: boolean;
    available_version?: string;
    app_updates?: Array<{ id: string; current_version: string; available_version: string }>;
  };
  services?: UpdateServiceItem[];
  active_job?: UpdateJob | null;
}

export interface ResourceContainerLimit {
  name: string;
  status: string;
  mem_mb?: number;
  mem_limit_mb?: number;
  cpu_shares?: number;
  cpu_quota_pct?: number;
}

export interface SleepContainerIdle {
  service: string;
  sleeping: boolean;
  idle_minutes?: number;
}

export interface SleepStatus extends ApiError {
  eco_sleep_enabled?: boolean;
  sleep_mode?: string;
  sleep_targets?: string[];
  schedule_enabled?: boolean;
  sleep_start?: string;
  sleep_end?: string;
  idle_sleep_enabled?: boolean;
  idle_minutes?: number;
  container_idle_sleep_enabled?: boolean;
  container_idle_minutes?: number;
  server_idle_sleep_enabled?: boolean;
  server_idle_minutes?: number;
  wake_all_on_server_wake?: boolean;
  wake_timeout_sec?: number;
  host_sleep_enabled?: boolean;
  sleeping_now?: boolean;
  sleeping_containers?: string[];
  idle_elapsed_minutes?: number;
  wake_proxy_active?: boolean;
  containers_idle?: Record<string, SleepContainerIdle>;
}

export interface ResourcesStatus extends ApiError {
  profile?: 'eco' | 'balanced' | 'performance' | string;
  memory?: {
    percent: number;
    used_mb: number;
    total_mb: number;
    available_mb: number;
    cached_mb: number;
    swap_used_mb: number;
    swap_total_mb: number;
    swap_percent: number;
  };
  cpu?: {
    percent: number;
    load_avg?: number[];
    max_temp_c?: number | null;
    throttled?: boolean;
  };
  settings?: {
    mem_auto_reclaim_pct?: number;
    cpu_throttle_pct?: number;
    cpu_throttle_temp_c?: number;
    download_rate_limit?: string;
  };
  sleep?: SleepStatus;
  containers?: ResourceContainerLimit[];
}
