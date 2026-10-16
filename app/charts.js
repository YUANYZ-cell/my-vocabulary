// Insight charts for the statistics page.
//
// Every builder returns markup that already carries its final geometry, so nothing about a chart
// reflows while it draws: the entrance is a transition on `stroke-dashoffset`, `opacity` and
// `transform`, started once by `mountCharts` adding `is-drawn` to the chart root. Starting values
// live in CSS custom properties instead of inline declarations, because an inline `stroke-dashoffset`
// would outrank the `.is-drawn` rule that finishes the draw.
//
// No builder animates width, height, top or left after mount, and none of them loops.

const esc = value => String(value ?? '').replace(/[&<>'"]/g, character => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[character]
));

// The tooltip text is authored as HTML by the caller and read back by `element.dataset.tip`,
// so escaping the whole fragment here is what keeps a term with a quote in it from breaking out.
const tip = html => (html ? ` data-tip="${esc(html)}"` : '');

let gradientSeed = 0;

// A hand-picked step ladder keeps the axis on round numbers: 25 becomes 0/10/20/30 rather than
// 0/12.5/25, and a busy week does not end up with eight gridlines.
function axisScale(max) {
  if (!(max > 0)) return { ceiling: 4, step: 2 };
  for (const step of [1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000]) {
    const divisions = Math.ceil(max / step);
    if (divisions <= 3) return { ceiling: step * divisions, step };
  }
  return { ceiling: max, step: max / 2 };
}

const fixed = value => Math.round(value * 10) / 10;

// `fixed` keeps a pixel coordinate readable, but it is the wrong precision for a *fraction of a
// turn*: the ring normalises its dashes through `pathLength="1"`, so one decimal there is 36
// degrees. Rounding an arc to 36-degree steps stops the slices tiling - the arc sits at its exact
// start angle, falls short of the next slice and paints its overrun on top of it. Four decimals of
// a turn is 0.04 degrees, well under a hundredth of a pixel.
const ratio = value => Math.round(value * 10000) / 10000;

// Line + light area, with the value written next to each node when the series is short enough
// to carry the numbers. `points` entries are {label, value|null, tip}; a null value leaves a gap
// in the line and no node, which is how a day without a graded answer stays honest.
export function lineChart({ points, max = null, ticks = null, showValues = false, suffix = '', summary = '' }) {
  const width = 320;
  const height = 152;
  const left = 30;
  const right = 12;
  const top = 16;
  const bottom = 24;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const baseline = top + plotHeight;
  const values = points.map(point => point.value).filter(value => value !== null);
  const scale = ticks
    ? { ceiling: Math.max(...ticks), step: null }
    : axisScale(max === null ? Math.max(0, ...values) : max);
  const ladder = ticks || Array.from({ length: scale.ceiling / scale.step + 1 }, (_, index) => index * scale.step);
  const ceiling = Math.max(1, Math.max(...ladder));
  const spacing = points.length > 1 ? plotWidth / (points.length - 1) : 0;
  const x = index => (points.length > 1 ? left + spacing * index : left + plotWidth / 2);
  const y = value => baseline - (Math.max(0, value) / ceiling) * plotHeight;

  const coords = points.map((point, index) => ({
    ...point,
    cx: x(index),
    cy: point.value === null ? null : y(point.value)
  }));
  const drawn = coords.filter(point => point.cy !== null);
  const linePath = drawn.map((point, index) => `${index ? 'L' : 'M'}${fixed(point.cx)} ${fixed(point.cy)}`).join(' ');
  const areaPath = drawn.length > 1 && scale.ceiling > 0
    ? `${linePath} L${fixed(drawn.at(-1).cx)} ${fixed(baseline)} L${fixed(drawn[0].cx)} ${fixed(baseline)} Z`
    : '';

  // Labels are sampled so a long window does not print every bucket, but the last point always
  // keeps its date. When that last label would land right beside the previous one the previous
  // one is dropped instead, because two half-overlapping dates read worse than a wider gap.
  const labelEvery = Math.max(1, Math.ceil(points.length / 7));
  const labelIndices = [];
  for (let index = 0; index < coords.length; index += labelEvery) labelIndices.push(index);
  const lastIndex = coords.length - 1;
  if (coords.length && labelIndices.at(-1) !== lastIndex) {
    if (lastIndex - labelIndices.at(-1) < labelEvery) labelIndices.pop();
    labelIndices.push(lastIndex);
  }
  const labelled = new Set(labelIndices);
  const gradient = `insight-area-${(gradientSeed += 1)}`;
  const grid = ladder.map(value => {
    const lineY = fixed(y(value));
    const strong = value === 0 ? ' insight-grid-base' : '';
    return `<line class="insight-grid-line${strong}" x1="${left}" y1="${lineY}" x2="${width - right}" y2="${lineY}"/>`
      + `<text class="insight-axis-label" x="${left - 6}" y="${lineY + 3}" text-anchor="end">${value}${suffix}</text>`;
  }).join('');
  const labels = coords.map((point, index) => (
    labelled.has(index)
      ? `<text class="insight-axis-label" x="${fixed(point.cx)}" y="${height - 7}" text-anchor="middle">${esc(point.label)}</text>`
      : ''
  )).join('');
  const areas = areaPath
    ? `<path class="insight-area" d="${areaPath}" fill="url(#${gradient})"/>`
    : '';
  const line = linePath
    ? `<path class="insight-line" pathLength="1" d="${linePath}"/>`
    : '';
  const nodes = drawn.map((point, index) => (
    `<circle class="insight-node" cx="${fixed(point.cx)}" cy="${fixed(point.cy)}" r="3.6" style="--node-delay:${240 + index * 34}ms"${tip(point.tip)}/>`
  )).join('');
  const numbers = showValues
    ? drawn.map((point, index) => (
      `<text class="insight-node-value" x="${fixed(Math.min(Math.max(point.cx, left + 8), width - right - 8))}" y="${fixed(point.cy - 9)}" text-anchor="middle" style="--node-delay:${300 + index * 34}ms">${point.text || point.value}</text>`
    )).join('')
    : '';

  return `<svg class="insight-svg" data-chart="line" viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(summary)}" focusable="false">
    <defs><linearGradient id="${gradient}" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#79b94d" stop-opacity=".26"/>
      <stop offset="1" stop-color="#79b94d" stop-opacity="0"/>
    </linearGradient></defs>
    ${grid}${areas}${line}${nodes}${numbers}${labels}
  </svg>`;
}

// Ring chart. Each arc is the same circle rotated to its own start angle, so an arc can grow from
// its own beginning instead of unrolling the whole ring: `stroke-dashoffset` runs from the arc
// length down to zero, which lengthens the dash forward from the rotation point. The length is
// emitted through `ratio`, not `fixed`, so that consecutive arcs still meet exactly.
export function donutChart({ segments, center, caption = '总词数', summary = '' }) {
  const size = 140;
  const radius = 52;
  const middle = size / 2;
  const total = segments.reduce((sum, segment) => sum + segment.value, 0);
  const denominator = total || 1;
  let cursor = 0;
  // The original index travels with each arc so an empty slice can drop out of the ring without
  // shifting the legend row it belongs to.
  const arcs = segments.map((segment, index) => ({ segment, index }))
    .filter(entry => entry.segment.value > 0)
    .map(entry => {
      const length = entry.segment.value / denominator;
      const rotation = fixed(-90 + cursor * 360);
      cursor += length;
      return `<circle class="insight-arc" cx="${middle}" cy="${middle}" r="${radius}" pathLength="1"
      transform="rotate(${rotation} ${middle} ${middle})"
      stroke="${entry.segment.color}" style="--arc-len:${ratio(length)};--arc-delay:${entry.index * 60}ms"
      data-arc-index="${entry.index}"${tip(entry.segment.tip)}/>`;
    }).join('');

  return `<div class="donut-figure" data-chart="donut" role="img" aria-label="${esc(summary)}">
    <svg class="insight-svg" viewBox="0 0 ${size} ${size}" focusable="false" aria-hidden="true">
      <circle class="insight-arc-track" cx="${middle}" cy="${middle}" r="${radius}"/>
      ${arcs}
    </svg>
    <div class="donut-center"><strong>${center}</strong><span>${esc(caption)}</span></div>
  </div>`;
}

// Small bar column. The bar height is written once and never revisited; the growth is a
// bottom-anchored scale on the bar itself, and the value rides above it on its own layer so the
// scale it is anchored to can never stretch the digits.
export function barChart({ bars, summary = '' }) {
  const track = 92;
  const max = Math.max(1, ...bars.map(bar => bar.value));
  return `<div class="hour-bars" data-chart="bars" role="img" aria-label="${esc(summary)}">${bars.map((bar, index) => {
    const height = Math.max(4, Math.round(bar.value / max * track));
    return `<div class="hour-bar"${tip(bar.tip)}>
      <div class="hour-bar-track">
        <i style="height:${height}px;--grow-delay:${index * 55}ms"></i>
        <span class="hour-bar-value" style="bottom:${height + 6}px;--grow-delay:${index * 55 + 210}ms">${bar.text ?? bar.value}</span>
      </div>
      <span class="bar-label">${esc(bar.label)}</span>
    </div>`;
  }).join('')}</div>`;
}

export function prefersReducedMotion() {
  return typeof window !== 'undefined'
    && typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

// Defer the draw until the figure is visible, including charts below the desktop fold.
const pendingCharts = new Set();
const drawChart = chart => {
  pendingCharts.delete(chart);
  chartObserver?.unobserve(chart);
  // Commit the starting style before changing it, even when both happen in one frame.
  chart.getBoundingClientRect();
  requestAnimationFrame(() => chart.classList.remove('is-undrawn'));
};
const chartObserver = typeof IntersectionObserver === 'function'
  ? new IntersectionObserver(entries => {
      entries.forEach(entry => {
        if (entry.isIntersecting) drawChart(entry.target);
      });
    }, {threshold: 0.15})
  : null;

export function mountCharts(root) {
  for (const chart of pendingCharts) {
    if (!chart.isConnected) {
      chartObserver?.unobserve(chart);
      pendingCharts.delete(chart);
    }
  }
  root.querySelectorAll('[data-chart]:not([data-chart-ready])').forEach(chart => {
    chart.setAttribute('data-chart-ready', 'true');
    if (prefersReducedMotion()) return;
    chart.classList.add('is-undrawn');
    if (chartObserver) {
      pendingCharts.add(chart);
      chartObserver.observe(chart);
    } else drawChart(chart);
  });
}
