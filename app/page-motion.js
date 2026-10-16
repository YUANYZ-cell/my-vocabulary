// Fetch while the current page stays visible; snapshot only the completed DOM swap.
export function createPageMotion(main, request) {
  const reduce = matchMedia('(prefers-reduced-motion: reduce)');
  let revision = 0, controller, transition, fallback, loaded = false, lastHash;

  function current() {
    const id = revision;
    const isCurrent = () => id === revision;
    return {
      hash: location.hash,
      isCurrent,
      request,
      commit: update => { if (isCurrent()) return update(); }
    };
  }

  async function navigate({hash, onCommit, onError}, renderPage) {
    const id = ++revision;
    controller?.abort();
    transition?.skipTransition();
    fallback?.cancel();
    const pending = controller = new AbortController();
    const isCurrent = () => id === revision && !pending.signal.aborted;
    const hadPage = loaded;
    let painted = false, fallbackAnimation;
    main.setAttribute('aria-busy', 'true');
    main.inert = true;
    main.dataset.routePhase = hadPage ? 'loading' : 'initial';
    if (hadPage) main.classList.add('route-managed');
    const busyTimer = setTimeout(() => {
      if (isCurrent() && !painted) document.body.classList.add('route-pending');
    }, 220);

    const commit = async update => {
      if (!isCurrent()) return;
      if (painted) return update();
      painted = true;
      clearTimeout(busyTimer);
      document.body.classList.remove('route-pending');
      const apply = () => {
        if (!isCurrent()) return;
        onCommit();
        main.dataset.routePhase = hadPage ? 'entering' : 'initial';
        update();
        if (hadPage && hash !== lastHash) window.scrollTo({top: 0, behavior: 'instant'});
        lastHash = hash;
        main.removeAttribute('aria-busy');
        main.inert = false;
        main.focus({preventScroll: true});
        loaded = true;
        if (!hadPage) main.classList.add('page-enter');
      };
      if (hadPage && !reduce.matches && document.startViewTransition) {
        const active = document.startViewTransition(apply);
        transition = active;
        active.ready.catch(() => {});
        await active.updateCallbackDone;
        await active.finished.catch(() => {});
        if (transition === active) transition = null;
      } else {
        apply();
        if (hadPage && !reduce.matches && main.animate) {
          fallbackAnimation = main.animate([
            {opacity: .65, transform: 'translateY(6px)'},
            {opacity: 1, transform: 'translateY(0)'}
          ], {duration: 320, easing: 'cubic-bezier(.22,1,.36,1)'});
          fallback = fallbackAnimation;
          await fallbackAnimation.finished.catch(() => {});
          if (fallback === fallbackAnimation) fallback = null;
        }
      }
    };
    const context = {
      hash, isCurrent, commit,
      request: async (path, options = {}) => {
        const data = await request(path, {...options, signal: pending.signal});
        if (!isCurrent()) throw new DOMException('Navigation superseded', 'AbortError');
        return data;
      }
    };
    try {
      await renderPage(context);
    } catch (error) {
      if (isCurrent() && error.name !== 'AbortError') await commit(() => onError(error));
    } finally {
      clearTimeout(busyTimer);
      if (isCurrent()) {
        main.inert = false;
        main.removeAttribute('aria-busy');
        main.dataset.routePhase = 'idle';
        document.body.classList.remove('route-pending');
      } else fallbackAnimation?.cancel();
    }
  }

  reduce.addEventListener('change', () => {
    if (reduce.matches) { transition?.skipTransition(); fallback?.cancel(); }
  });
  return {navigate, current};
}
