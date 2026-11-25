export function fmtBytes(bytes?: number | null): string {
  if (!bytes || bytes === 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.min(
    units.length - 1,
    Math.floor(Math.log(Math.max(1, Math.abs(bytes))) / Math.log(1024))
  );
  return `${(bytes / Math.pow(1024, i)).toFixed(i > 1 ? 1 : 0)} ${units[i]}`;
}

export function fmtBytesPerSec(bytes?: number | null): string {
  return `${fmtBytes(bytes)}/s`;
}

export function friendlyTempName(key: string): string {
  const map: Array<[string, string]> = [
    ['acpitz', 'Motherboard (ACPI)'],
    ['coretemp', 'CPU Core'],
    ['soc_dts0', 'SoC Sensor 0'],
    ['soc_dts1', 'SoC Sensor 1'],
    ['iwlwifi', 'Wi-Fi Adapter'],
    ['nvme', 'NVMe SSD'],
    ['pch', 'PCH Chipset'],
    ['k10temp', 'AMD CPU Die'],
    ['thinkpad', 'ThinkPad BIOS'],
  ];
  const lower = key.toLowerCase();
  for (const [prefix, label] of map) {
    if (lower.startsWith(prefix)) return label;
  }
  return key;
}

export function formatAudioBadge(format?: string, quality?: string): string {
  const val = (format || quality || 'mp3_320').toString().toLowerCase();
  if (val.includes('flac')) return 'FLAC';
  if (val.includes('opus')) return 'OPUS';
  if (val.includes('m4a') || val.includes('aac')) return 'M4A';
  if (val.includes('wav')) return 'WAV';
  if (val.includes('256')) return 'MP3 256k';
  return 'MP3 320k';
}
