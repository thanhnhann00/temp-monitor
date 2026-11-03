// Chart helpers. Line/area charts use Chart.js (window.Chart); the pill chart and gauge are DOM/SVG.
import { esc, hourLabel, isNum } from './fmt.js';

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const live = new Set();

// Re-colour every chart when the theme changes.
new MutationObserver(() => live.forEach((c) => c.restyle())).observe(document.documentElement, {
  attributes: true, attributeFilter: ['data-theme'],
});

// Dashed vertical lines with a small label, e.g. cooling-mode changes: [{ x: ts, label }]
const markerPlugin = {
  id: 'markers',
  afterDatasetsDraw(chart) {
    const list = chart.options.plugins.markers?.list ?? [];
    const { ctx: g, chartArea: a, scales: { x } } = chart;
    g.save();
    g.strokeStyle = css('--stripe'); g.fillStyle = css('--muted'); g.setLineDash([4, 4]); g.lineWidth = 1.5;
    g.font = '12px "Plus Jakarta Sans", sans-serif';
    let lastPx = -Infinity; let row = 0;
    for (const m of list) {
      const px = x.getPixelForValue(m.x);
      if (px < a.left || px > a.right) continue;
      g.beginPath(); g.moveTo(px, a.top); g.lineTo(px, a.bottom); g.stroke();
      row = px - lastPx < 110 ? row + 1 : 0; // stack labels of markers that are close together
      lastPx = px;
      g.fillText(m.label, Math.min(px + 6, a.right - g.measureText(m.label).width - 4), a.top + 14 + row * 15);
    }
    g.restore();
  },
};

// series: [{ label, color?: cssVar, fill?: bool, dash?: bool, axis?: 'y' | 'y2', unit? }]
export function areaChart(canvas, { series, yMax = null, yUnit = '', grid = true, spark = false, xRange = 60 }) {
  const chart = new window.Chart(canvas, {
    type: 'line',
    plugins: [markerPlugin],
    data: { datasets: series.map((s) => ({ label: s.label, data: [], pointRadius: 0, borderWidth: spark ? 1.6 : 2, tension: 0.25, fill: s.fill ?? true, borderDash: s.dash ? [5, 4] : [], yAxisID: s.axis ?? 'y', unit: s.unit ?? yUnit })) },
    options: {
      animation: false,
      responsive: true,
      maintainAspectRatio: false,
      parsing: false,
      normalized: true,
      interaction: { intersect: false, mode: 'index' },
      plugins: {
        legend: { display: false },
        tooltip: {
          enabled: !spark,
          callbacks: {
            title: (items) => (items.length ? new Date(items[0].parsed.x * 1000).toLocaleTimeString() : ''),
            label: (item) => ` ${item.dataset.label}: ${item.parsed.y.toFixed(item.dataset.unit === ' RPM' ? 0 : 1)}${item.dataset.unit}`,
          },
        },
      },
      scales: {
        x: { type: 'linear', display: !spark && grid, ticks: { display: false }, grid: { drawTicks: false }, border: { display: false } },
        y: { display: !spark && grid, min: 0, max: yMax ?? undefined, ticks: { display: false, maxTicksLimit: 5 }, grid: { drawTicks: false }, border: { display: false } },
        ...(series.some((s) => s.axis === 'y2') ? { y2: { display: false, min: 0 } } : {}),
      },
    },
  });
  const handle = {
    chart,
    restyle() {
      const line = css('--line');
      chart.options.scales.x.grid.color = line;
      chart.options.scales.y.grid.color = line;
      chart.data.datasets.forEach((ds, i) => {
        const s = series[i];
        const color = s.onHero ? '#ffffff' : css(s.color ?? '--chart-a');
        ds.borderColor = color;
        ds.backgroundColor = s.onHero ? 'rgba(255,255,255,.25)' : (s.color && s.color !== '--chart-a' ? 'transparent' : css('--chart-fill'));
      });
      chart.update('none');
    },
    // data: array of point arrays [[ts, v], ...], one per series
    set(data, now) {
      data.forEach((pts, i) => { chart.data.datasets[i].data = (pts ?? []).map(([x, y]) => ({ x, y })); });
      const end = now ?? Math.max(0, ...data.flatMap((p) => (p?.length ? [p[p.length - 1][0]] : [])));
      chart.options.scales.x.min = end - xRange;
      chart.options.scales.x.max = end;
      chart.update('none');
    },
    setMarkers(list) { chart.options.plugins.markers = { list }; chart.update('none'); },
    setOnHero(onHero) { series.forEach((s) => { s.onHero = onHero; }); handle.restyle(); },
    destroy() { live.delete(handle); chart.destroy(); },
  };
  live.add(handle);
  handle.restyle();
  return handle;
}

// hourly: [{hour_ts, avg}] oldest first. Bands follow the spec: <60 cool, 60–74 warm, 75–84 mid, 85+ hot.
export function pillChart(el, hourly, hours = 7) {
  if (!hourly.length) {
    el.innerHTML = '<p class="empty">No history yet. Bars appear after the first hour of monitoring.</p>';
    return;
  }
  const lo = 30;
  const hi = Math.max(95, ...hourly.map((h) => h.avg));
  const shown = hourly.slice(-hours);
  el.innerHTML = shown.map((h, i) => {
    const band = h.avg >= 85 ? 'hot' : h.avg >= 75 ? 'mid' : h.avg >= 60 ? 'warm' : 'cool';
    const height = 20 + ((h.avg - lo) / (hi - lo)) * 140;
    return `<div class="bar${i === shown.length - 1 ? ' last' : ''}">
      <div class="pill ${band}" style="height:${Math.max(20, height).toFixed(0)}px" title="Average ${h.avg.toFixed(0)} °C">
        <span class="tip">avg ${h.avg.toFixed(0)}°</span></div>
      <small>${esc(hourLabel(h.hour_ts))}</small></div>`;
  }).join('');
}

// Semicircle gauge: used/max with a striped "headroom" track.
export function gauge(svg, used, max) {
  const frac = isNum(used) && max > 0 ? Math.min(1, Math.max(0, used / max)) : 0;
  const r = 85; const cx = 105; const cy = 110;
  const angle = Math.PI * (1 - frac);
  const x = cx + r * Math.cos(angle); const y = cy - r * Math.sin(angle);
  const arc = frac > 0 ? `<path d="M${cx - r} ${cy} A${r} ${r} 0 0 1 ${x.toFixed(1)} ${y.toFixed(1)}" fill="none" stroke="var(--o500)" stroke-width="30" stroke-linecap="${frac < 1 ? 'butt' : 'round'}"/>` : '';
  svg.innerHTML = `
    <defs><pattern id="gst" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
      <rect width="6" height="6" fill="var(--stripe-bg)"/><rect width="2" height="6" fill="var(--stripe)"/></pattern></defs>
    <path d="M${cx - r} ${cy} A${r} ${r} 0 0 1 ${cx + r} ${cy}" fill="none" stroke="url(#gst)" stroke-width="30"/>${arc}`;
}
