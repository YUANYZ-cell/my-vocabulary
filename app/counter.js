// Rolling statistic counters: each digit lives in a 0-9 strip that springs to its place
// value, so a number rolls into place instead of snapping.
// Vanilla port of the Motion <Counter /> component used on the stats page. The strip is
// built from rows that copy the line box the plain number occupied, so a rolled glyph lands
// on exactly the same baseline, inside exactly the same box, as the text it replaced.

const STIFFNESS = 100;      // matches the default useSpring feel: a short overshoot, then settle
const DAMPING = 10;
const MASS = 1;
const FIXED_STEP = 1 / 120; // fixed sub-step keeps the integration stable on any refresh rate
const REST_DISTANCE = 0.0005;
const REST_SPEED = 0.0005;
const MAX_DURATION = 4;     // hard stop, so a counter can never keep a frame loop alive
const WRITE_STEP = 0.002;   // below ~1/500 em a move is invisible, so the spring tail writes nothing

const springs = new Set();
let frameHandle = 0;
let previousTime = 0;

function pump(time) {
  frameHandle = 0;
  const delta = Math.min(0.048, previousTime ? (time - previousTime) / 1000 : 0.016);
  previousTime = time;
  springs.forEach(spring => {
    spring.advance(delta);
    spring.render();
    if (!spring.settled()) return;
    spring.finish();
    springs.delete(spring);
  });
  if (springs.size) frameHandle = requestAnimationFrame(pump);
  else previousTime = 0;
}

function prefersReducedMotion() {
  return typeof window !== 'undefined'
    && typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

// One spring per digit column, all driven by the single loop above.
function startSpring(target, onFrame) {
  const spring = {
    value: 0,
    velocity: 0,
    target,
    elapsed: 0,
    render(force) { onFrame(spring.value, force === true) },
    advance(delta) {
      let remaining = delta;
      while (remaining > 0) {
        const step = Math.min(FIXED_STEP, remaining);
        const force = -STIFFNESS * (spring.value - spring.target) - DAMPING * spring.velocity;
        spring.velocity += (force / MASS) * step;
        spring.value += spring.velocity * step;
        remaining -= step;
      }
      spring.elapsed += delta;
    },
    settled() {
      if (spring.elapsed > MAX_DURATION) return true;
      return Math.abs(spring.value - spring.target) < REST_DISTANCE && Math.abs(spring.velocity) < REST_SPEED;
    },
    finish() {
      spring.value = spring.target;
      spring.velocity = 0;
      spring.render(true);
    }
  };
  // Nothing to roll for a zero place value, and reduced motion goes straight to the value.
  if (target === 0 || prefersReducedMotion()) {
    spring.finish();
    return spring;
  }
  springs.add(spring);
  spring.render();
  if (!frameHandle) {
    previousTime = 0;
    frameHandle = requestAnimationFrame(pump);
  }
  return spring;
}

// Integer columns keep their place, the decimal point keeps its own slot.
export function placesFor(text) {
  const decimalIndex = text.indexOf('.');
  const places = [];
  for (let index = 0; index < text.length; index += 1) {
    const character = text[index];
    if (character === '.') {
      places.push({ place: '.', decimal: true });
      continue;
    }
    const power = decimalIndex === -1
      ? text.length - index - 1
      : (index < decimalIndex ? decimalIndex - index - 1 : -(index - decimalIndex));
    places.push({ place: 10 ** power, decimal: false });
  }
  return places;
}

// Where one glyph of the strip sits, in rows, for the current (fractional) place value.
// Glyphs more than half a turn away enter from the other side, so travel never exceeds 5 steps.
export function digitOffset(progress, digit) {
  const placeValue = progress % 10;
  const offset = (10 + digit - placeValue) % 10;
  return offset > 5 ? offset - 10 : offset;
}

// One row of travel is one line box, and `line-height: normal` is not 1em for every font.
// A pitch shorter than the line box would leave the next glyph poking into the window, so the
// pitch is measured from the host instead of assumed to be 1em. The host is a single-line
// inline-block, so its content height *is* the line box the plain number occupied.
function rowPitch(host) {
  if (typeof getComputedStyle !== 'function') return 1;
  const metrics = getComputedStyle(host);
  const font = parseFloat(metrics.fontSize);
  const rect = typeof host.getBoundingClientRect === 'function' ? host.getBoundingClientRect() : null;
  if (!font || !rect || !rect.height) return 1;
  const trim = (parseFloat(metrics.paddingTop) || 0) + (parseFloat(metrics.paddingBottom) || 0)
    + (parseFloat(metrics.borderTopWidth) || 0) + (parseFloat(metrics.borderBottomWidth) || 0);
  const lineBox = rect.height - trim;
  return lineBox > 0 ? lineBox / font : 1;
}

// A row count turns into a translate length on the glyph's own em.
function emLength(rows, pitch) {
  return Math.round(rows * pitch * 10000) / 10000;
}

// The plain number stays in the DOM as an invisible placeholder. It keeps the host exactly the
// size of the text it replaced — width and line box — so the strip can be laid over the top
// without the counter ever shifting the layout around it, and without a frozen copy of the
// digits showing through the rolling glyphs.
function isolateStaticText(host) {
  const strays = [...host.childNodes].filter(node => node.nodeType === 3 && node.textContent.trim() !== '');
  if (!strays.length) return null;
  const placeholder = document.createElement('span');
  placeholder.className = 'counter-static';
  placeholder.setAttribute('aria-hidden', 'true');
  strays.forEach(node => placeholder.append(node));
  host.append(placeholder);
  return placeholder;
}

function columnElement() {
  const column = document.createElement('span');
  column.className = 'counter-digit';
  const digits = [];
  for (let digit = 0; digit < 10; digit += 1) {
    const glyph = document.createElement('span');
    glyph.className = 'counter-number';
    glyph.textContent = String(digit);
    column.append(glyph);
    digits.push(glyph);
  }
  return { element: column, digits };
}

export function mountCounter(host) {
  if (host.getAttribute('data-counter-ready') === 'true') return;
  host.setAttribute('data-counter-ready', 'true');
  const text = String(host.getAttribute('data-counter') ?? '').trim();
  // Anything that is not a plain non-negative number stays as the static text it already shows.
  if (!/^\d+(\.\d+)?$/.test(text)) return;

  const value = Number(text);
  if (!Number.isFinite(value)) return;

  host.setAttribute('role', 'img');
  host.setAttribute('aria-label', text);

  // The strip must reproduce the box the plain number occupied, so the pitch is read from that
  // text before it turns into a placeholder: one row of travel is one line box.
  const pitch = rowPitch(host);
  isolateStaticText(host);

  const track = document.createElement('span');
  track.className = 'counter-track';
  track.setAttribute('aria-hidden', 'true');

  const columns = [];
  placesFor(text).forEach(entry => {
    if (entry.decimal) {
      const dot = document.createElement('span');
      dot.className = 'counter-dot';
      dot.textContent = '.';
      track.append(dot);
      return;
    }
    const column = columnElement();
    track.append(column.element);
    columns.push({ element: column.element, digits: column.digits, place: entry.place });
  });

  // The strip is out of flow, so the host keeps its own box: exactly the width of the text
  // it replaced (tabular digits are 1ch each) and the inherited line height.
  host.style.width = `${text.length}ch`;
  host.append(track);

  columns.forEach((column, index) => {
    // Higher places start faded in, so the number does not open with a block of leading zeros.
    let revealed = index === columns.length - 1;
    let drawn = -1;
    const onFrame = (progress, force) => {
      if (!force && Math.abs(progress - drawn) < WRITE_STEP) return;
      drawn = progress;
      column.digits.forEach((glyph, digit) => {
        glyph.style.transform = `translateY(${emLength(digitOffset(progress, digit), pitch)}em)`;
      });
      if (revealed) return;
      const opacity = Math.min(1, progress * 2);
      column.element.style.opacity = String(opacity);
      if (opacity >= 1) revealed = true;
    };
    startSpring(Math.floor(value / column.place), onFrame);
  });
}

// Anything newly inserted under `root` gets mounted; already mounted hosts are skipped,
// so the observer can safely run on every DOM change.
export function mountCounters(root) {
  root.querySelectorAll('[data-counter]:not([data-counter-ready])').forEach(mountCounter);
}
