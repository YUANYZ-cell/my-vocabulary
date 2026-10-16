// Supplied Text Loop's SVG path, fitted repetitions and two travelling copies.
// The existing local app uses native DOM APIs instead of React / GSAP.
const motionPreference = matchMedia('(prefers-reduced-motion: reduce)');

export function textLoopMarkup() {
  return `<section class="daily-loop-section" aria-label="每天遇见一句新表达">
    <div class="text-loop" data-text-loop aria-hidden="true">
      <svg class="text-loop-svg" viewBox="0 0 1200 100" preserveAspectRatio="xMidYMid meet">
        <path id="daily-loop-path" d="M -600 50 Q -300 24 0 50 T 600 50 T 1200 50 T 1800 50" fill="none"/>
        <text class="text-loop-measure">ONE LITTLE PHRASE · EVERY DAY · </text>
        <text class="text-loop-text" dominant-baseline="central" lengthAdjust="spacing"><textPath href="#daily-loop-path" data-loop-head></textPath></text>
        <text class="text-loop-text" dominant-baseline="central" lengthAdjust="spacing"><textPath href="#daily-loop-path" data-loop-tail></textPath></text>
      </svg>
    </div>
    <button type="button" class="text-loop-toggle" data-loop-toggle aria-pressed="false" aria-label="暂停文字环动效">
      <svg viewBox="0 0 20 20" aria-hidden="true"><g class="loop-pause"><path d="M7 5v10M13 5v10"/></g><path class="loop-play" d="m7 4 9 6-9 6Z"/></svg>
    </button>
  </section>`;
}

function mountLoop(root) {
  const path = root.querySelector('path');
  const measure = root.querySelector('.text-loop-measure');
  const head = root.querySelector('[data-loop-head]');
  const tail = root.querySelector('[data-loop-tail]');
  const toggle = root.parentElement.querySelector('[data-loop-toggle]');
  let length = 0, offset = 0, frame = 0, lastTime = 0;
  let visible = false, hovering = false, paused = false, disposed = false;
  const apply = () => {
    head.setAttribute('startOffset', String(-offset));
    tail.setAttribute('startOffset', String(length - offset));
  };
  const fit = () => {
    if (disposed) return;
    length = path.getTotalLength();
    const unit = measure.textContent;
    const unitWidth = measure.getComputedTextLength();
    const text = unit.repeat(Math.max(1, Math.round(length / Math.max(1, unitWidth))));
    for (const copy of [head, tail]) {
      copy.textContent = text;
      copy.parentElement.setAttribute('textLength', String(length));
    }
    offset %= length;
    apply();
  };
  const animate = time => {
    frame = 0;
    if (lastTime) offset = (offset + Math.min(time - lastTime, 80) * .017) % length;
    lastTime = time;
    apply();
    frame = requestAnimationFrame(animate);
  };
  const sync = () => {
    const canRun = !disposed && length && visible && !hovering && !paused && !document.hidden && !motionPreference.matches;
    root.dataset.loopState = canRun ? 'running' : 'paused';
    toggle.hidden = motionPreference.matches;
    toggle.dataset.paused = String(paused);
    toggle.setAttribute('aria-label', paused ? '播放文字环动效' : '暂停文字环动效');
    toggle.setAttribute('aria-pressed', String(paused));
    if (canRun && !frame) { lastTime = 0; frame = requestAnimationFrame(animate); }
    else if (!canRun) { cancelAnimationFrame(frame); frame = 0; lastTime = 0; }
  };
  const enter = () => { hovering = true; sync(); };
  const leave = () => { hovering = false; sync(); };
  const onToggle = () => { paused = !paused; sync(); };
  const observer = new IntersectionObserver(([entry]) => { visible = entry.isIntersecting; sync(); });
  fit();
  document.fonts?.ready.then(() => { fit(); sync(); });
  root.addEventListener('pointerenter', enter);
  root.addEventListener('pointerleave', leave);
  toggle.addEventListener('click', onToggle);
  document.addEventListener('visibilitychange', sync);
  motionPreference.addEventListener('change', sync);
  observer.observe(root);
  sync();
  return () => {
    disposed = true;
    cancelAnimationFrame(frame);
    observer.disconnect();
    root.removeEventListener('pointerenter', enter);
    root.removeEventListener('pointerleave', leave);
    toggle.removeEventListener('click', onToggle);
    document.removeEventListener('visibilitychange', sync);
    motionPreference.removeEventListener('change', sync);
  };
}

export function mountTextLoops(main) {
  const mounted = new Map();
  const refresh = () => {
    for (const [root, dispose] of mounted) {
      if (!root.isConnected) { dispose(); mounted.delete(root); }
    }
    main.querySelectorAll('[data-text-loop]').forEach(root => {
      if (!mounted.has(root)) mounted.set(root, mountLoop(root));
    });
  };
  new MutationObserver(refresh).observe(main, {childList: true, subtree: true});
  refresh();
}
