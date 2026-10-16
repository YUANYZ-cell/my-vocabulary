import {renderDailyGroupReview} from './daily-group-review.js?v=3';

export function reviewSourcePicker(daily = false) {
  return `<nav class="review-source-picker" aria-label="复习版块"><a href="#review" ${daily ? '' : 'aria-current="page"'}>阅读写作与学术词汇</a><a href="#review?collection=daily" ${daily ? 'aria-current="page"' : ''}>生活口语</a></nav>`;
}

export async function renderDailyReview(ui) {
  const {main, esc, pageHead} = ui;
  const params = new URLSearchParams(location.hash.split('?')[1]);
  const [data, groupData] = await Promise.all([ui.request('/api/daily-expressions'), ui.request('/api/daily-groups')]);
  if (!ui.isCurrent()) return;
  const groupId = Number(params.get('group') || 0);
  const group = groupData.items.find(item => item.id === groupId);
  const categories = ['口语', '俚语', '习语', '谚语', '词汇'];
  const category = categories.includes(params.get('category')) ? params.get('category') : '';
  const favorites = params.get('favorites') === '1';
  const items = data.items.filter(item => (!groupId || item.group_id === groupId) && (!category || item.category === category) && (!favorites || item.is_favorite));
  if (params.get('start') === '1') {
    const selection = group?.name || (groupId ? '已移除的合集' : category || '全部生活口语');
    const returnParams = new URLSearchParams(params);
    returnParams.delete('start');
    return renderDailyGroupReview(ui, {name: selection}, items, {
      returnHref: `#review?${returnParams}`, returnLabel: '返回复习设置',
      browseHref: group ? `#daily?group=${group.id}` : '#daily',
      direction: params.get('direction') === 'phrase' ? 'phrase' : 'meaning',
    });
  }
  return ui.commit(() => {
    main.innerHTML = `${reviewSourcePicker(true)}${pageHead('REVIEW', '回忆生活里用得上的表达', '独立表达和词汇合集都可以在这里复习；先回忆，再揭晓答案。')}
      <section class="daily-review-setup setup-panel" aria-labelledby="daily-review-selection-title">
        <div class="setup-heading"><span>01</span><div><p class="choice-title">复习内容</p><h2 id="daily-review-selection-title">这次想回忆哪些？</h2></div></div>
        <form id="daily-review-form">
          <div class="field-grid">
            <div class="field"><label for="daily-review-group">主题合集</label><select id="daily-review-group" name="group"><option value="">全部内容（含独立表达）</option>${groupData.items.map(item => `<option value="${item.id}" ${item.id === groupId ? 'selected' : ''}>${esc(item.name)} · ${item.item_count} 条</option>`).join('')}</select></div>
            <div class="field"><label for="daily-review-category">内容分类</label><select id="daily-review-category" name="category"><option value="">全部分类</option>${categories.map(item => `<option ${item === category ? 'selected' : ''}>${item}</option>`).join('')}</select></div>
            <label class="favorite-check full"><input type="checkbox" name="favorites" value="1" ${favorites ? 'checked' : ''}> 只复习收藏</label>
          </div>
          <fieldset class="daily-review-direction-field"><legend>回忆方向</legend><label><input type="radio" name="direction" value="meaning" ${params.get('direction') !== 'phrase' ? 'checked' : ''}> 看英文想中文</label><label><input type="radio" name="direction" value="phrase" ${params.get('direction') === 'phrase' ? 'checked' : ''}> 看中文想英文</label></fieldset>
          <div class="daily-review-launch"><div><strong id="daily-review-count" role="status" aria-live="polite"></strong><p>本页自由回忆，不计入词汇掌握度或学习统计。</p></div><button type="submit" class="btn primary">开始遮罩复习</button></div>
        </form>
      </section>`;
    const form = main.querySelector('#daily-review-form');
    const selectedItems = () => data.items.filter(item => (!form.elements.group.value || item.group_id === Number(form.elements.group.value)) && (!form.elements.category.value || item.category === form.elements.category.value) && (!form.elements.favorites.checked || item.is_favorite));
    const updateCount = () => {
      const count = selectedItems().length;
      main.querySelector('#daily-review-count').textContent = count ? `${count} 条内容 · 同页逐个回忆` : '当前范围没有内容，试试其他合集或分类';
      form.querySelector('[type="submit"]').disabled = !count;
    };
    form.addEventListener('change', updateCount);
    form.addEventListener('submit', event => {
      event.preventDefault();
      if (!ui.isCurrent() || !selectedItems().length) return;
      const next = new URLSearchParams({collection: 'daily', start: '1'});
      for (const [key, value] of new FormData(form)) if (value) next.set(key, value);
      location.hash = `review?${next}`;
    });
    updateCount();
  });
}
