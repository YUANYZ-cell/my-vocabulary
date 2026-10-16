// One lifecycle for every search field: IME commits are text input, not submission.
const bindings = new WeakMap();

export function bindSearchInput(input, search, {delay = 220, isCurrent = () => true} = {}) {
  if (!input || bindings.has(input)) return;
  let timer, composing = false, revision = 0, lastValue = input.value;
  const active = () => input.isConnected && isCurrent();
  const cancel = () => { clearTimeout(timer); revision++; };
  const run = () => {
    if (!active() || composing || input.value === lastValue) return;
    const value = input.value, token = revision;
    lastValue = value;
    const current = () => active() && token === revision && !composing;
    Promise.resolve().then(() => { if (current()) return search(value, current); })
      .catch(() => { if (token === revision) lastValue = null; });
  };
  const schedule = () => { cancel(); timer = setTimeout(run, delay); };
  input.addEventListener('compositionstart', () => { composing = true; cancel(); });
  input.addEventListener('compositionend', () => { composing = false; schedule(); });
  input.addEventListener('input', event => {
    cancel();
    if (!composing && !event.isComposing) timer = setTimeout(run, delay);
  });
  input.addEventListener('keydown', event => {
    if (event.key !== 'Enter') return;
    // Leave the IME's confirmation key alone, including WebView2's legacy 229 events.
    if (composing || event.isComposing || event.keyCode === 229) return;
    event.preventDefault();
    // The input event already schedules a search; Enter must never blur this field.
  });
  bindings.set(input, value => { cancel(); input.value = value; lastValue = value; });
}

export function resetSearchInput(input, value = '') {
  const reset = bindings.get(input);
  if (reset) reset(value);
  else if (input) input.value = value;
}

// Keep the live toolbar connected even when an earlier request finishes during typing.
export function updateSearchRegion(container, html, selector) {
  const live = container.querySelector(selector);
  const template = document.createElement('template');
  template.innerHTML = html;
  const replacement = template.content.querySelector(selector);
  if (!live || !replacement || live.className !== replacement.className) {
    container.replaceChildren(template.content);
    return;
  }
  for (const child of [...container.childNodes]) if (child !== live) child.remove();
  let before = true;
  for (const child of [...template.content.childNodes]) {
    if (child === replacement) { before = false; continue; }
    container.insertBefore(child, before ? live : null);
  }
}
