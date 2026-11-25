import { useEffect, useRef, useState } from 'preact/hooks';

let chartUid = 0;

export interface RingSeries {
  label: string;
  percent: number;
  detail?: string;
  strokeClass?: string;
}

export function ConcentricRingGauge({
  rings,
  centerValue,
  centerLabel,
  size = 128,
}: {
  rings: RingSeries[];
  centerValue: string;
  centerLabel?: string;
  size?: number;
}) {
  const center = size / 2;
  const strokeWidth = 7;
  const gap = 11;
  const baseRadius = size / 2 - strokeWidth - 2;

  const defaultStrokes = [
    'stroke-indigo-600 dark:stroke-indigo-400',
    'stroke-sky-500 dark:stroke-sky-400',
    'stroke-emerald-500 dark:stroke-emerald-400',
  ];

  return (
    <div
      class="relative inline-flex items-center justify-center shrink-0"
      style={{ width: size, height: size }}
    >
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} class="-rotate-90">
        {rings.slice(0, 3).map((ring, idx) => {
          const r = Math.max(16, baseRadius - idx * gap);
          const c = 2 * Math.PI * r;
          const pct = Math.max(0, Math.min(100, ring.percent || 0));
          const offset = c - (pct / 100) * c;
          const strokeClass =
            ring.strokeClass ||
            (pct >= 90
              ? 'stroke-rose-500'
              : pct >= 78
              ? 'stroke-amber-500'
              : defaultStrokes[idx % defaultStrokes.length]);

          return (
            <g key={ring.label}>
              <circle
                cx={center}
                cy={center}
                r={r}
                fill="none"
                stroke-width={strokeWidth}
                class="stroke-zinc-200/80 dark:stroke-zinc-800"
              />
              <circle
                cx={center}
                cy={center}
                r={r}
                fill="none"
                stroke-width={strokeWidth}
                stroke-linecap="round"
                stroke-dasharray={c}
                stroke-dashoffset={offset}
                class={`${strokeClass} transition-all duration-700 ease-out`}
              />
            </g>
          );
        })}
      </svg>
      <div class="absolute inset-0 flex flex-col items-center justify-center text-center pointer-events-none">
        <span class="text-lg font-bold tracking-tight text-zinc-900 dark:text-white leading-none tabular-nums">
          {centerValue}
        </span>
        {centerLabel && (
          <span class="text-[10px] font-medium text-zinc-500 dark:text-zinc-400 mt-1">
            {centerLabel}
          </span>
        )}
      </div>
    </div>
  );
}

export interface LineSeries {
  label: string;
  data: number[];
  stroke: string;
  darkStroke?: string;
  dashed?: boolean;
  fill?: boolean;
}

function buildMonotonePath(
  points: Array<{ x: number; y: number }>,
  minY: number,
  maxY: number
): string {
  const n = points.length;
  if (n === 0) return '';
  if (n === 1) return `M ${points[0].x.toFixed(1)} ${points[0].y.toFixed(1)}`;
  if (n === 2) {
    return `M ${points[0].x.toFixed(1)} ${points[0].y.toFixed(1)} L ${points[1].x.toFixed(1)} ${points[1].y.toFixed(1)}`;
  }

  const dx: number[] = [];
  const dy: number[] = [];
  const m: number[] = [];
  for (let i = 0; i < n - 1; i++) {
    dx.push(Math.max(0.001, points[i + 1].x - points[i].x));
    dy.push(points[i + 1].y - points[i].y);
    m.push(dy[i] / dx[i]);
  }

  const tangents: number[] = new Array(n).fill(0);
  tangents[0] = m[0];
  tangents[n - 1] = m[n - 2];
  for (let i = 1; i < n - 1; i++) {
    tangents[i] = m[i - 1] * m[i] <= 0 ? 0 : (m[i - 1] + m[i]) / 2;
  }

  for (let i = 0; i < n - 1; i++) {
    if (Math.abs(m[i]) < 1e-6) {
      tangents[i] = 0;
      tangents[i + 1] = 0;
    } else {
      const a = tangents[i] / m[i];
      const b = tangents[i + 1] / m[i];
      const h = Math.hypot(a, b);
      if (h > 3) {
        const t = 3 / h;
        tangents[i] = t * a * m[i];
        tangents[i + 1] = t * b * m[i];
      }
    }
  }

  const clampY = (y: number) => Math.max(minY, Math.min(maxY, y));
  let d = `M ${points[0].x.toFixed(1)} ${points[0].y.toFixed(1)}`;
  for (let i = 0; i < n - 1; i++) {
    const step = dx[i] / 3;
    const cp1x = points[i].x + step;
    const cp1y = clampY(points[i].y + tangents[i] * step);
    const cp2x = points[i + 1].x - step;
    const cp2y = clampY(points[i + 1].y - tangents[i + 1] * step);
    d += ` C ${cp1x.toFixed(1)} ${cp1y.toFixed(1)}, ${cp2x.toFixed(1)} ${cp2y.toFixed(1)}, ${points[i + 1].x.toFixed(1)} ${points[i + 1].y.toFixed(1)}`;
  }
  return d;
}

function downsampleData(labels: string[], series: LineSeries[], maxBuckets = 68) {
  const n = Math.max(labels.length, ...series.map((s) => s.data.length), 0);
  if (n <= maxBuckets) return { labels, series, count: n };

  const bucketSize = n / maxBuckets;
  const outLabels: string[] = [];
  const outSeries: LineSeries[] = series.map((s) => ({ ...s, data: [] }));

  for (let b = 0; b < maxBuckets; b++) {
    const start = Math.floor(b * bucketSize);
    const end = Math.min(n, Math.max(start + 1, Math.floor((b + 1) * bucketSize)));
    const mid = Math.floor((start + end - 1) / 2);
    outLabels.push(labels[mid] || labels[start] || '');

    for (let si = 0; si < series.length; si++) {
      let peak = 0;
      for (let i = start; i < end; i++) {
        const val = series[si].data[i] || 0;
        if (val > peak) peak = val;
      }
      outSeries[si].data.push(peak);
    }
  }
  return { labels: outLabels, series: outSeries, count: maxBuckets };
}

export function SmoothLineChart({
  labels,
  series,
  height = 185,
  maxY,
  scale = 'linear',
  logBase = 512,
  isDark = false,
  formatValue = (v: number) => `${Math.round(v)}%`,
  emptyText = 'Collecting telemetry...',
}: {
  labels: string[];
  series: LineSeries[];
  height?: number;
  maxY?: number;
  scale?: 'linear' | 'log';
  logBase?: number;
  isDark?: boolean;
  formatValue?: (v: number) => string;
  emptyText?: string;
}) {
  const uidRef = useRef<number>(++chartUid);
  const wrapRef = useRef<HTMLDivElement>(null);
  const [boxWidth, setBoxWidth] = useState(480);
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const measure = () => {
      const w = el.clientWidth;
      if (w > 40) setBoxWidth(w);
    };
    measure();
    if (typeof ResizeObserver !== 'undefined') {
      const ro = new ResizeObserver(measure);
      ro.observe(el);
      return () => ro.disconnect();
    }
    window.addEventListener('resize', measure);
    return () => window.removeEventListener('resize', measure);
  }, []);

  const sampled = downsampleData(labels, series, boxWidth < 400 ? 40 : 68);
  const n = sampled.count;

  if (n === 0) {
    return (
      <div
        ref={wrapRef}
        class="w-full flex items-center justify-center text-xs text-zinc-400 dark:text-zinc-500 rounded-2xl bg-zinc-50 dark:bg-zinc-900/50 border border-dashed border-zinc-200 dark:border-zinc-800"
        style={{ height }}
      >
        {emptyText}
      </div>
    );
  }

  const allVals = sampled.series.flatMap((s) => s.data);
  const rawMax = Math.max(0, ...allVals);
  const computedMax = maxY ?? (rawMax <= 0 ? 1024 : rawMax * 1.15);

  const transformVal = (v: number): number => {
    const clean = Math.max(0, v || 0);
    if (scale === 'log') {
      return Math.log10(1 + clean / logBase);
    }
    return clean;
  };
  const inverseVal = (t: number): number => {
    if (scale === 'log') {
      return Math.max(0, logBase * (Math.pow(10, t) - 1));
    }
    return t;
  };

  const maxT = Math.max(1e-6, transformVal(computedMax));

  const svgWidth = Math.max(200, boxWidth - 16);
  const padLeft = svgWidth < 360 ? 48 : 56;
  const padRight = 10;
  const padTop = 12;
  const padBottom = 22;
  const chartW = Math.max(60, svgWidth - padLeft - padRight);
  const chartH = Math.max(60, height - padTop - padBottom);

  const getX = (i: number) =>
    n <= 1 ? padLeft + chartW : padLeft + (i / (n - 1)) * chartW;
  const getY = (val: number) => {
    const ratio = Math.max(0, Math.min(1, transformVal(val) / maxT));
    return padTop + chartH - ratio * chartH;
  };

  const activeIdx = hoverIdx !== null && hoverIdx < n ? hoverIdx : n - 1;
  const maxTicks = svgWidth < 360 ? 4 : svgWidth < 600 ? 5 : 7;
  const tickStep = Math.max(1, Math.ceil(n / maxTicks));
  const yRatios = [1, 0.5, 0];

  const gridStroke = isDark ? 'rgba(255,255,255,0.09)' : 'rgba(15,23,42,0.08)';
  const axisText = isDark ? '#a1a1aa' : '#71717a';
  const activeText = isDark ? '#ffffff' : '#111827';
  const dotStroke = isDark ? '#121216' : '#ffffff';

  const handlePointer = (clientX: number) => {
    const el = wrapRef.current;
    if (!el || n <= 1) return;
    const rect = el.getBoundingClientRect();
    const relX = clientX - rect.left - 8 - padLeft;
    const frac = Math.max(0, Math.min(1, relX / chartW));
    setHoverIdx(Math.round(frac * (n - 1)));
  };

  return (
    <div ref={wrapRef} class="w-full select-none">
      {/* Legend + active time pill */}
      <div class="flex flex-wrap items-center justify-between gap-2 mb-2">
        <div class="flex items-center gap-x-3 gap-y-1 flex-wrap">
          {sampled.series.map((s) => {
            const color = isDark && s.darkStroke ? s.darkStroke : s.stroke;
            return (
              <div
                key={s.label}
                class="flex items-center gap-1.5 text-[11px] font-medium text-zinc-600 dark:text-zinc-300"
              >
                <span
                  class="w-2.5 h-2.5 rounded-full shrink-0"
                  style={{ backgroundColor: color }}
                />
                <span>{s.label}</span>
                <span class="font-bold text-zinc-900 dark:text-white tabular-nums">
                  {formatValue(s.data[activeIdx] ?? 0)}
                </span>
              </div>
            );
          })}
        </div>
        {sampled.labels[activeIdx] && (
          <span class="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-950 tabular-nums">
            {sampled.labels[activeIdx]}
          </span>
        )}
      </div>

      {/* Subtle framed plot area guarantees crisp contrast in both Light and Dark themes */}
      <div class="rounded-2xl bg-zinc-50/90 dark:bg-zinc-950/70 border border-zinc-200/70 dark:border-zinc-800/90 px-2 pt-1.5 pb-1">
        <svg
          width={svgWidth}
          height={height}
          viewBox={`0 0 ${svgWidth} ${height}`}
          class="w-full block touch-pan-y cursor-crosshair"
          onMouseMove={(e) => handlePointer(e.clientX)}
          onTouchMove={(e) => {
            if (e.touches[0]) handlePointer(e.touches[0].clientX);
          }}
          onMouseLeave={() => setHoverIdx(null)}
          onTouchEnd={() => setHoverIdx(null)}
        >
          <defs>
            {sampled.series.map((s, si) => {
              const color = isDark && s.darkStroke ? s.darkStroke : s.stroke;
              return (
                <linearGradient
                  key={`grad-${si}`}
                  id={`cg-${uidRef.current}-${si}`}
                  x1="0"
                  y1="0"
                  x2="0"
                  y2="1"
                >
                  <stop offset="0%" stop-color={color} stop-opacity={isDark ? '0.28' : '0.18'} />
                  <stop offset="100%" stop-color={color} stop-opacity="0.01" />
                </linearGradient>
              );
            })}
          </defs>

          {/* Horizontal grid lines + explicit Y-axis labels */}
          {yRatios.map((ratio) => {
            const y = padTop + chartH * (1 - ratio);
            const val = inverseVal(maxT * ratio);
            return (
              <g key={ratio}>
                <line
                  x1={padLeft}
                  x2={svgWidth - padRight}
                  y1={y}
                  y2={y}
                  stroke={gridStroke}
                  stroke-width="1"
                  stroke-dasharray={ratio === 0 ? undefined : '3 4'}
                />
                <text
                  x={padLeft - 8}
                  y={y + 3.5}
                  text-anchor="end"
                  fill={axisText}
                  font-size="9.5"
                  font-weight="600"
                >
                  {formatValue(val)}
                </text>
              </g>
            );
          })}

          {/* Smooth curves + gradient fill */}
          {sampled.series.map((s, si) => {
            const color = isDark && s.darkStroke ? s.darkStroke : s.stroke;
            const pts =
              n === 1
                ? [
                    { x: padLeft, y: getY(s.data[0] || 0) },
                    { x: svgWidth - padRight, y: getY(s.data[0] || 0) },
                  ]
                : s.data.map((v, i) => ({ x: getX(i), y: getY(v || 0) }));
            const linePath = buildMonotonePath(pts, padTop, padTop + chartH);
            const areaPath =
              pts.length > 1
                ? `${linePath} L ${pts[pts.length - 1].x.toFixed(1)} ${(padTop + chartH).toFixed(1)} L ${pts[0].x.toFixed(1)} ${(padTop + chartH).toFixed(1)} Z`
                : '';
            const activePt = n === 1 ? pts[1] : pts[activeIdx];

            return (
              <g key={s.label}>
                {s.fill && areaPath && (
                  <path d={areaPath} fill={`url(#cg-${uidRef.current}-${si})`} />
                )}
                <path
                  d={linePath}
                  fill="none"
                  stroke={color}
                  stroke-width={si === 0 ? '2.4' : '2'}
                  stroke-dasharray={s.dashed ? '5 4' : undefined}
                  stroke-linecap="round"
                  stroke-linejoin="round"
                />
                {n <= 24 &&
                  pts.map((pt, pi) => (
                    <circle
                      key={pi}
                      cx={pt.x}
                      cy={pt.y}
                      r={pi === activeIdx ? 4 : 2.3}
                      fill={color}
                      stroke={dotStroke}
                      stroke-width="1.4"
                    />
                  ))}
                {n > 24 && activePt && (
                  <circle
                    cx={activePt.x}
                    cy={activePt.y}
                    r={hoverIdx !== null ? 4.2 : 3.2}
                    fill={color}
                    stroke={dotStroke}
                    stroke-width="1.8"
                  />
                )}
              </g>
            );
          })}

          {/* Hover vertical crosshair */}
          {hoverIdx !== null && hoverIdx < n && n > 1 && (
            <line
              x1={getX(hoverIdx)}
              x2={getX(hoverIdx)}
              y1={padTop}
              y2={padTop + chartH}
              stroke={isDark ? 'rgba(255,255,255,0.35)' : 'rgba(15,23,42,0.3)'}
              stroke-width="1"
              stroke-dasharray="3 3"
            />
          )}

          {/* X-Axis labels */}
          {sampled.labels.map((lbl, i) => {
            if (!lbl) return null;
            if (i % tickStep !== 0 && i !== n - 1) return null;
            const isSelected = i === activeIdx && hoverIdx !== null;
            return (
              <text
                key={`${lbl}-${i}`}
                x={n === 1 ? padLeft + chartW / 2 : getX(i)}
                y={height - 4}
                text-anchor={
                  n === 1 ? 'middle' : i === 0 ? 'start' : i === n - 1 ? 'end' : 'middle'
                }
                fill={isSelected ? activeText : axisText}
                font-size="9.5"
                font-weight={isSelected ? '700' : '500'}
              >
                {lbl}
              </text>
            );
          })}
        </svg>
      </div>
    </div>
  );
}

export function HourlyBarChart({ values }: { values: number[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const max = Math.max(1, ...values);

  return (
    <div class="w-full">
      <div class="flex items-end gap-1 h-24 pt-3">
        {values.map((v, hour) => {
          const pct = Math.max(6, Math.round((v / max) * 100));
          const isActive = hover === hour;
          return (
            <div
              key={hour}
              class="flex-1 h-full flex flex-col justify-end items-center cursor-pointer"
              onMouseEnter={() => setHover(hour)}
              onMouseLeave={() => setHover(null)}
              title={`${hour}:00 — ${v} plays`}
            >
              <div
                class={`w-full rounded-t-md transition-all duration-150 ${
                  v === 0
                    ? 'bg-zinc-200/80 dark:bg-zinc-800/80'
                    : isActive
                    ? 'bg-indigo-600 dark:bg-indigo-400'
                    : 'bg-zinc-700/85 dark:bg-zinc-300/80'
                }`}
                style={{ height: `${v === 0 ? 6 : pct}%` }}
              />
            </div>
          );
        })}
      </div>
      <div class="flex items-center justify-between text-[10px] text-zinc-400 dark:text-zinc-500 mt-2">
        <span>00:00</span>
        <span>06:00</span>
        <span>12:00</span>
        <span>18:00</span>
        <span class="font-semibold text-zinc-700 dark:text-zinc-300">
          {hover !== null ? `${hover}:00 · ${values[hover]} plays` : '23:00'}
        </span>
      </div>
    </div>
  );
}
