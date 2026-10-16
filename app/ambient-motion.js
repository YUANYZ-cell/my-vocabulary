// Fold Text's top hinge and stagger, adapted to the existing local desktop app.
// Only display headings unfold; inputs, counters and learning content stay intact.
const titles = '.page-head h1, .unit-banner h1, .path-intro h2';
const motionPreference = matchMedia('(prefers-reduced-motion: reduce)');
const mounted = new WeakMap();
const running = new Map();

function unfold(title) {
  const text = title.textContent;
  if (!text || mounted.get(title) === text) return;
  mounted.set(title, text);
  // Route snapshots already carry the entrance. Folding their text again causes a second flash.
  if (title.closest('[data-route-phase="entering"]')) return;
  if (motionPreference.matches || !title.animate) return;

  running.get(title)?.finish();
  const originalLabel = title.getAttribute('aria-label');
  title.setAttribute('aria-label', text);
  const visual = document.createElement('span');
  visual.className = 'fold-visual';
  visual.setAttribute('aria-hidden', 'true');
  const characters = Array.from(text);
  const pieces = [];
  characters.forEach((character, index) => {
    if (/\s/.test(character)) {
      visual.append(document.createTextNode(character));
      return;
    }
    const segment = document.createElement('span');
    segment.className = 'fold-segment';
    const piece = document.createElement('span');
    piece.className = 'fold-piece';
    piece.textContent = character;
    piece.style.setProperty('--fold-delay', `${Math.min(index * 18, 180)}ms`);
    segment.append(piece);
    visual.append(segment);
    pieces.push(piece);
  });
  title.replaceChildren(visual);
  const animations = pieces.map((piece, index) => piece.animate([
    { opacity: 0, transform: 'rotateX(-78deg) translateY(-.04em)' },
    { opacity: 1, transform: 'rotateX(0deg) translateY(0)' }
  ], { duration: 580, delay: Math.min(index * 18, 180), easing: 'cubic-bezier(.16,1,.3,1)', fill: 'both' }));
  const entry = {
    finish() {
      animations.forEach(animation => animation.cancel());
      // An in-place title update must never be overwritten by an earlier animation.
      if (title.firstChild === visual) {
        title.textContent = text;
      }
      if (title.getAttribute('aria-label') === text) {
        if (originalLabel === null) title.removeAttribute('aria-label');
        else title.setAttribute('aria-label', originalLabel);
      }
      if (running.get(title) === entry) running.delete(title);
    }
  };
  running.set(title, entry);
  Promise.all(animations.map(animation => animation.finished)).then(() => entry.finish(), () => {});
}

export function mountAmbientMotion(main) {
  // BlurText's soft blur / settle / clear sequence, only for text below the fold.
  // Visible text keeps the existing page entrance and never waits for a scroll event.
  const seen = new WeakSet(), pending = new Set(), reveals = new Map();
  const revealSelectors = '[data-scroll-reveal], .expression-card h2, .expression-card > p, .library-row .term > div, .word-row .term, .section-head h2';
  const finishReveal = element => {
    reveals.get(element)?.cancel();
    reveals.delete(element);
    pending.delete(element);
    revealObserver.unobserve(element);
    element.style.removeProperty('opacity');
    element.style.removeProperty('filter');
    element.style.removeProperty('transform');
    element.dataset.scrollRevealState = 'done';
  };
  const revealObserver = new IntersectionObserver(entries => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      const element = entry.target;
      pending.delete(element);
      revealObserver.unobserve(element);
      if (motionPreference.matches || document.hidden || !element.animate) { finishReveal(element); continue; }
      element.dataset.scrollRevealState = 'entering';
      const animation = element.animate([
        {filter: 'blur(5px)', opacity: 0, transform: 'translateY(8px)'},
        {filter: 'blur(2px)', opacity: .65, transform: 'translateY(-1px)', offset: .5},
        {filter: 'blur(0px)', opacity: 1, transform: 'translateY(0)'}
      ], {duration: 480, delay: element.matches('p') ? 50 : 0, easing: 'cubic-bezier(.22,1,.36,1)', fill: 'both'});
      reveals.set(element, animation);
      animation.finished.then(() => finishReveal(element), () => {});
    }
  }, {threshold: .1, rootMargin: '0px 0px -24px 0px'});
  const finishReveals = () => {
    for (const element of [...pending, ...reveals.keys()]) finishReveal(element);
  };
  const refresh = () => {
    for (const [title, entry] of running) if (!title.isConnected) entry.finish();
    main.querySelectorAll(titles).forEach(unfold);
    for (const element of [...pending, ...reveals.keys()]) if (!element.isConnected) finishReveal(element);
    main.querySelectorAll(revealSelectors).forEach(element => {
      if (seen.has(element)) return;
      seen.add(element);
      if (motionPreference.matches || document.hidden || element.getBoundingClientRect().top < innerHeight - 24) {
        element.dataset.scrollRevealState = 'done';
        return;
      }
      element.dataset.scrollRevealState = 'pending';
      pending.add(element);
      revealObserver.observe(element);
    });
  };
  new MutationObserver(refresh).observe(main, { childList: true, subtree: true });
  motionPreference.addEventListener('change', () => {
    if (motionPreference.matches) {
      for (const entry of running.values()) entry.finish();
      finishReveals();
    }
  });
  const visibility = () => {
    document.body.classList.toggle('ambient-paused', document.hidden);
    if (document.hidden) {
      for (const entry of running.values()) entry.finish();
      finishReveals();
    }
  };
  document.addEventListener('visibilitychange', visibility);
  visibility();
  refresh();
}
