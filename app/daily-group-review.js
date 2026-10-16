export function renderDailyGroupReview(ui, group, items, options = {}) {
  const {main, esc, pageHead} = ui;
  let direction = options.direction || 'meaning';
  const revealed = new Set();
  const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)');
  const hideTimers = new Map();
  const eyeIcon = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6Z"/><circle cx="12" cy="12" r="2.5"/></svg>';
  const bookIcon = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v15M12 5C9 3.5 5.5 3.5 3 4.5v14c2.5-1 6-1 9 1.5 3-2.5 6.5-2.5 9-1.5v-14c-2.5-1-6-1-9 .5Z"/></svg>';
  return ui.commit(() => {
    main.innerHTML = `<div class="daily-group-breadcrumb"><a class="btn text" href="${esc(options.returnHref || '#review?collection=daily')}">← ${esc(options.returnLabel || '返回复习设置')}</a><span>生活口语 / ${esc(group.name)}</span>${options.browseHref ? `<a class="btn text" href="${esc(options.browseHref)}">查看词库</a>` : ''}</div>
      ${pageHead('RECALL', `${esc(group.name)} · 遮罩复习`, '先自己回忆，再逐个点击揭晓；再次点击可以重新遮住。')}
      <section class="daily-review-toolbar" aria-label="遮罩复习设置">
        <div class="daily-review-directions"><button type="button" class="btn light selected" data-daily-direction="meaning" aria-pressed="true">看英文想中文</button><button type="button" class="btn light" data-daily-direction="phrase" aria-pressed="false">看中文想英文</button></div>
        <div class="actions"><button type="button" class="btn light" data-daily-mask-all>重新遮住全部</button><button type="button" class="btn light" data-daily-reveal-all>展开全部</button></div>
        <p><span id="daily-reveal-progress" role="status" aria-live="polite"></span><small>自由回忆，不计入词汇掌握度或学习统计。</small></p>
      </section><section class="daily-review-grid" aria-label="${esc(group.name)}的词汇遮罩"></section>`;

    function updateProgress() {
      main.querySelector('#daily-reveal-progress').textContent = `已展开 ${revealed.size} / ${items.length}`;
    }
    function updateMask(item) {
      const button = main.querySelector(`[data-daily-mask="${item.id}"]`);
      const expanded = revealed.has(item.id);
      button.setAttribute('aria-expanded', String(expanded));
      const answerLabel = `第 ${items.indexOf(item) + 1} 条的${direction === 'meaning' ? '中文' : '英文'}答案`;
      button.setAttribute('aria-label', expanded ? `${answerLabel}：${item[direction]}。点击重新遮住` : `展开${answerLabel}`);
      button.classList.toggle('is-revealed', expanded);
      const answer = button.querySelector('.daily-answer-content');
      answer.setAttribute('aria-hidden', String(!expanded));
      clearTimeout(hideTimers.get(item.id));
      if (expanded) answer.querySelector('.daily-answer-value').textContent = item[direction];
      else {
        const clearAnswer = () => { if (!revealed.has(item.id)) answer.querySelector('.daily-answer-value').textContent = ''; };
        if (reduceMotion.matches) clearAnswer();
        else hideTimers.set(item.id, setTimeout(clearAnswer, 220));
      }
      button.querySelector('.daily-mask-prompt').setAttribute('aria-hidden', String(expanded));
      const extra = main.querySelector(`[data-daily-recall-extra="${item.id}"]`);
      if (extra) { extra.disabled = !expanded; extra.style.visibility = expanded ? 'visible' : 'hidden'; }
    }
    function reserveAnswerSpace() {
      // Measure off-DOM: hidden answers must not enter the page or accessibility tree before reveal.
      const canvas = document.createElement('canvas').getContext('2d');
      items.forEach(item => {
        const button = main.querySelector(`[data-daily-mask="${item.id}"]`);
        const style = getComputedStyle(button.querySelector('.daily-answer-value'));
        const width = button.clientWidth;
        canvas.font = style.font;
        let lines = 1, line = '';
        const tokens = String(item[direction]).match(/\n|[^\S\n]+|[a-zA-Z0-9]+(?:['’-][a-zA-Z0-9]+)*|./gu) || [];
        for (const token of tokens) {
          if (token === '\n') { lines++; line = ''; continue; }
          if (!line && /^\s+$/.test(token)) continue;
          if (canvas.measureText(line + token).width <= width) { line += token; continue; }
          if (canvas.measureText(token).width <= width) { lines++; line = token.trimStart(); continue; }
          for (const character of token) {
            if (canvas.measureText(line + character).width > width) { lines++; line = ''; }
            line += character;
          }
        }
        button.style.minHeight = `${Math.max(132, Math.ceil(lines * parseFloat(style.lineHeight)) + 90)}px`;
      });
    }
    function draw() {
      hideTimers.forEach(clearTimeout);
      hideTimers.clear();
      main.querySelector('.daily-review-grid').innerHTML = items.length ? items.map((item, index) => `<article class="daily-recall-tile" data-daily-recall-id="${item.id}"><span class="daily-recall-number">${String(index + 1).padStart(2, '0')}</span><h2 lang="${direction === 'meaning' ? 'en' : 'zh'}">${esc(item[direction === 'meaning' ? 'phrase' : 'meaning'])}</h2><button type="button" class="daily-answer-mask" data-daily-mask="${item.id}" aria-controls="daily-answer-${item.id}"><span class="daily-mask-prompt"><span class="daily-reveal-action">${eyeIcon}揭晓${direction === 'meaning' ? '释义' : '英文'}</span><small>先在心里回忆，再核对答案</small></span><span class="daily-answer-content" id="daily-answer-${item.id}" lang="${direction === 'meaning' ? 'zh' : 'en'}"><small class="daily-answer-label">${direction === 'meaning' ? '中文释义' : '英文表达'}</small><span class="daily-answer-value"></span><small class="daily-answer-reset">${eyeIcon}重新遮住</small></span></button><div class="daily-recall-extra">${item.example || item.translation || item.usage || item.pronunciation ? `<button type="button" class="daily-example-link" data-daily-recall-extra="${item.id}">${bookIcon}<span>例句与用法</span><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 6 6 6-6 6"/></svg></button>` : ''}</div></article>`).join('') : '<div class="empty"><h2>这个范围还没有内容</h2><p>返回复习设置，选择其他合集或分类。</p></div>';
      main.querySelectorAll('[data-daily-direction]').forEach(button => {
        const selected = button.dataset.dailyDirection === direction;
        button.classList.toggle('selected', selected);
        button.setAttribute('aria-pressed', String(selected));
      });
      reserveAnswerSpace();
      items.forEach(updateMask);
      updateProgress();
    }
    main.onclick = event => {
      const target = event.target.closest('[data-daily-mask],[data-daily-direction],[data-daily-mask-all],[data-daily-reveal-all],[data-daily-recall-extra]');
      if (!target || !ui.isCurrent()) return;
      if (target.hasAttribute('data-daily-mask')) {
        const item = items.find(item => item.id === Number(target.dataset.dailyMask));
        if (revealed.has(item.id)) revealed.delete(item.id); else revealed.add(item.id);
        updateMask(item);
        return updateProgress();
      }
      if (target.hasAttribute('data-daily-recall-extra')) {
        const item = items.find(item => item.id === Number(target.dataset.dailyRecallExtra));
        if (!revealed.has(item.id)) return;
        ui.openDialog(`<div class="dialog-card"><div class="section-head"><h2 lang="en">${esc(item.phrase)}</h2><button type="button" class="btn light" data-action="close-dialog">关闭</button></div><p>${esc(item.meaning)}</p>${item.pronunciation ? `<p class="daily-pronunciation">${esc(item.pronunciation)}</p>` : ''}${item.example ? `<p lang="en">${esc(item.example)}</p>` : ''}${item.translation ? `<p>${esc(item.translation)}</p>` : ''}${item.usage ? `<p>${esc(item.usage)}</p>` : ''}</div>`);
        return;
      }
      if (target.hasAttribute('data-daily-direction')) {
        direction = target.dataset.dailyDirection;
        revealed.clear();
        return draw();
      }
      revealed.clear();
      if (target.hasAttribute('data-daily-reveal-all')) items.forEach(item => revealed.add(item.id));
      items.forEach(updateMask);
      updateProgress();
    };
    draw();
    const grid = main.querySelector('.daily-review-grid');
    let lastWidth = grid.clientWidth;
    const resizeObserver = new ResizeObserver(() => {
      if (!ui.isCurrent() || !grid.isConnected) { resizeObserver.disconnect(); return; }
      if (lastWidth !== grid.clientWidth) { lastWidth = grid.clientWidth; reserveAnswerSpace(); }
    });
    resizeObserver.observe(grid);
  });
}
