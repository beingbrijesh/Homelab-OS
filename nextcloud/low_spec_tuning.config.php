<?php
/**
 * Homelab OS (HL-OS) — Low-Resource Nextcloud Configuration Snippet
 * Specially tuned for: 2015 2-Core Intel Celeron & 8GB RAM
 * 
 * Merge these keys into your nextcloud/config/config.php
 */

$CONFIG = array (
  // ── Cap Preview Dimensions to 1024x1024 (Prevents CPU 100% Lockups) ──────
  'enable_previews' => true,
  'preview_max_x' => 1024,
  'preview_max_y' => 1024,
  'preview_max_filesize_image' => 10, // Max 10MB images for preview generation

  // ── Disable Heavy Preview Extractors (Videos, PDF, SVG, Font) ─────────────
  // These extractors peg low-end Celeron CPUs; only allow fast image formats
  'enabledPreviewProviders' => array (
    'OC\\Preview\\PNG',
    'OC\\Preview\\JPEG',
    'OC\\Preview\\GIF',
    'OC\\Preview\\BMP',
  ),

  // ── Memory & Performance Optimization ─────────────────────────────────────
  'memory_consumption' => 128,
  'maintenance_window_start' => 2, // Heavy background jobs run at 2:00 AM UTC
  'trashbin_retention_obligation' => 'auto, 14', // Auto-expire deleted files after 14 days
);
