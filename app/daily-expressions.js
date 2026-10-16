import {bindSearchInput,resetSearchInput} from './search-input.js?v=1';
import {textLoopMarkup} from './text-loop.js?v=3';

const categories = ['口语', '俚语', '习语', '谚语', '词汇'];
const filters = {q: '', category: '', favorites: false, sort: 'default'};
let removeDialogListener = () => {};
let previousGroupId = null;

export function dailyFormFields(item,esc,groups=[]) {
  return `      <div class="field"><label for="daily-phrase">英文表达 *</label><input id="daily-phrase" name="phrase" required maxlength="240" value="${esc(item?.phrase || '')}" placeholder="例如：Tomayto, tomahto."></div>
      <div class="field"><label for="daily-category">分类</label><select id="daily-category" name="category">${categories.map(category => `<option ${item?.category === category ? 'selected' : ''}>${category}</option>`).join('')}</select></div>
      <div class="field full"><label for="daily-group">所属合集</label><select id="daily-group" name="group_id"><option value="">不放入合集</option>${groups.map(group=>`<option value="${group.id}" ${Number(item?.group_id)===group.id?'selected':''}>${esc(group.name)}</option>`).join('')}</select></div>
      <div class="field full"><label for="daily-meaning">中文意思 *</label><input id="daily-meaning" name="meaning" required maxlength="1000" value="${esc(item?.meaning || '')}"></div>
      <div class="field full"><label for="daily-pronunciation">读音提示（可选）</label><input id="daily-pronunciation" name="pronunciation" maxlength="240" value="${esc(item?.pronunciation || '')}"></div>
      <div class="field full"><label for="daily-example">英文例句或小对话（可选）</label><textarea id="daily-example" name="example" maxlength="2000">${esc(item?.example || '')}</textarea></div>
      <div class="field full"><label for="daily-translation">例句中文（可选）</label><textarea id="daily-translation" name="translation" maxlength="2000">${esc(item?.translation || '')}</textarea></div>
      <div class="field full"><label for="daily-usage">使用场景 / 语气（可选）</label><textarea id="daily-usage" name="usage" maxlength="2000">${esc(item?.usage || '')}</textarea></div>
      <div class="field full"><label for="daily-source">来源（可选）</label><input id="daily-source" name="source" maxlength="1000" value="${esc(item?.source || '')}" placeholder="网址、电影或日常聊天"></div>
`;
}

export async function renderDailyExpressions(ui) {
  const {main, api, esc, icon, contentActions, pageHead, openDialog, closeDialog, notify} = ui;
  const incomingDetail=Number(new URLSearchParams(location.hash.split('?')[1]).get('detail')||0);
  if(incomingDetail){filters.q='';filters.category='';filters.favorites=false;}
  const params = new URLSearchParams(location.hash.split('?')[1]);
  const groupId = Number(params.get('group') || 0);
  const [data, groupData] = await Promise.all([ui.request('/api/daily-expressions'), ui.request('/api/daily-groups')]);
  if (!ui.isCurrent()) return;
  let groups = groupData.items;
  const currentGroup = groups.find(group=>group.id===groupId);
  if (previousGroupId !== groupId) { filters.q=''; filters.category=''; filters.favorites=false; }
  previousGroupId = groupId;
  if (params.get('review')==='1' && currentGroup) {
    removeDialogListener();
    location.replace(`#review?collection=daily&group=${groupId}&start=1`);
    return;
  }
  let items = data.items, deletedTotal = data.deleted_total || 0;
  let modalItem = null, modalKind = '', returnFocus = null;
  const dialog = document.querySelector('#dialog');
  const dialogBody = document.querySelector('#dialog-body');

  function favorite(item) {
    return `<button type="button" class="daily-favorite ${item.is_favorite ? 'is-favorite' : ''}" data-daily-favorite="${item.id}" aria-pressed="${item.is_favorite}" aria-label="${item.is_favorite ? '取消收藏' : '收藏'} ${esc(item.phrase)}" title="${item.is_favorite ? '取消收藏' : '收藏'}">${icon('bookmark')}</button>`;
  }
  function actions(item,details=false) {
    return contentActions(item.phrase, {view:details?{attributes:`data-daily-details="${item.id}" aria-haspopup="dialog"`,icon:'recent'}:null,
      edit:`data-daily-edit="${item.id}"`,remove:`data-daily-delete="${item.id}"`,wide:details});
  }
  function card(item) {
    return `<article class="daily-card" data-daily-id="${item.id}">
      <div class="daily-card-top"><span class="daily-category" data-category="${esc(item.category)}">${esc(item.category)}</span>${favorite(item)}</div>
      <div class="daily-card-copy"><h2 lang="en" title="${esc(item.phrase)}" data-scroll-reveal>${esc(item.phrase)}</h2><p class="daily-meaning" data-scroll-reveal>${esc(item.meaning)}</p></div>
      <footer>${actions(item,true)}</footer>
    </article>`;
  }
  function groupCard(group, members) {
    return `<article class="daily-card daily-group-card" data-daily-group-id="${group.id}"><div class="daily-card-top"><span class="daily-category">词汇合集</span><span>${members.length} 条</span></div><div class="daily-card-copy"><h2>${esc(group.name)}</h2><p class="daily-meaning">${esc(members.slice(0,3).map(item=>item.phrase).join(' · ') || '还没有内容，可以先建好合集')}</p></div><footer><a class="btn small light daily-group-open" href="#daily?group=${group.id}">查看合集</a></footer></article>`;
  }
  function matching() {
    const q = filters.q.trim().toLocaleLowerCase();
    return items.filter(item => (!currentGroup || item.group_id===currentGroup.id) && (!filters.category || item.category === filters.category)
      && (!filters.favorites || item.is_favorite)
      && (!q || groups.some(group=>group.id===item.group_id && group.name.toLocaleLowerCase().includes(q)) || ['phrase', 'meaning', 'pronunciation', 'example', 'translation', 'usage', 'source'].some(field => String(item[field] || '').toLocaleLowerCase().includes(q)))).sort((a,b) => {
      if (filters.sort === 'phrase') return a.phrase.localeCompare(b.phrase,'en',{sensitivity:'base'});
      if (filters.sort === 'newest' || filters.sort === 'oldest') {
        const order = String(a.created_at).localeCompare(String(b.created_at)) || a.id-b.id;
        return filters.sort === 'newest' ? -order : order;
      }
      return Number(!b.seed_key)-Number(!a.seed_key) || a.id-b.id;
    });
  }
  function refresh() {
    if (!ui.isCurrent() || document.body.dataset.route !== 'daily') return;
    const found = matching();
    const groupCount=main.querySelector('[data-daily-group-count]');
    if(groupCount)groupCount.textContent=`${items.filter(item=>item.group_id===groupId).length} 条内容`;
    const visibleGroups = currentGroup ? [] : groups.filter(group=>found.some(item=>item.group_id===group.id) || (!filters.category && !filters.favorites && (!filters.q || group.name.toLocaleLowerCase().includes(filters.q.toLocaleLowerCase()))));
    const standalone = currentGroup ? found : found.filter(item=>!item.group_id);
    main.querySelector('#daily-result-count').textContent = `${found.length} 条内容${visibleGroups.length ? ` · ${visibleGroups.length} 个合集` : ''}`;
    main.querySelector('#daily-results').innerHTML = visibleGroups.map(group=>groupCard(group,items.filter(item=>item.group_id===group.id))).join('') + (standalone.length ? standalone.map(card).join('') : visibleGroups.length ? '' : `<div class="empty"><h2>${filters.favorites ? '还没有符合条件的收藏' : '没有找到内容'}</h2><p>试试其他关键词或分类，也可以添加自己遇到的说法。</p></div>`);
    main.querySelectorAll('[data-daily-category]').forEach(button => {
      const category = button.dataset.dailyCategory;
      const active = category === filters.category;
      button.classList.toggle('selected', active);
      button.setAttribute('aria-pressed', String(active));
      const members = currentGroup ? items.filter(item=>item.group_id===currentGroup.id) : items;
      button.querySelector('small').textContent = category ? members.filter(item => item.category === category).length : members.length;
    });
    const favorites = main.querySelector('[data-daily-favorites]');
    favorites.classList.toggle('selected', filters.favorites);
    favorites.setAttribute('aria-pressed', String(filters.favorites));
    const trash = main.querySelector('[data-daily-trash]');
    trash.hidden = !deletedTotal;
    trash.textContent = `最近删除 (${deletedTotal})`;
  }
  function openDaily(html, kind, item = null) {
    if (!dialog.open) {
      const active = document.activeElement;
      const attribute = ['data-daily-details', 'data-daily-edit', 'data-daily-delete', 'data-daily-random', 'data-daily-add', 'data-daily-trash'].find(name => active?.hasAttribute(name));
      returnFocus = attribute ? `[${attribute}="${active.getAttribute(attribute)}"]` : null;
    }
    modalKind = kind;
    modalItem = item;
    dialog.classList.add('daily-dialog');
    dialog.dataset.dailyDialog = 'true';
    dialog.setAttribute('aria-labelledby', 'daily-dialog-title');
    openDialog(html);
    dialogBody.onclick = onClick;
    dialogBody.querySelector('[data-daily-close]')?.focus({preventScroll: true});
  }
  async function showDetails(item, random = false) {
    if(!item)return;
    const originals=await ui.contentMoves.retained('daily',item.id);
    if(!ui.isCurrent())return;
    const source = /^https?:\/\//i.test(item.source) ? `<a href="${esc(item.source)}" target="_blank" rel="noopener noreferrer">查看来源 ↗</a>` : (item.source ? `<span>${esc(item.source)}</span>` : '');
    openDaily(`<div class="dialog-card daily-detail-dialog" data-daily-detail-id="${item.id}">
      <div class="daily-detail-head"><span class="daily-category" data-category="${esc(item.category)}">${esc(item.category)}</span><div>${favorite(item)}<button type="button" class="btn small light" data-daily-close aria-label="关闭详细信息">${icon('close')}</button></div></div>
      ${random ? '<p class="daily-random-caption">随手遇见一句</p>' : ''}<h2 id="daily-dialog-title" lang="en">${esc(item.phrase)}</h2>
      <p class="daily-detail-meaning">${esc(item.meaning)}</p>${item.pronunciation ? `<p class="daily-pronunciation">${esc(item.pronunciation)}</p>` : ''}
      <div class="daily-detail-body">
        ${item.example || item.translation ? `<section class="daily-example"><h3>例句与翻译</h3>${item.example ? `<p lang="en">${esc(item.example)}</p>` : ''}${item.translation ? `<p>${esc(item.translation)}</p>` : ''}</section>` : ''}
        ${item.usage ? `<section class="daily-usage"><h3>怎么用</h3><p>${esc(item.usage)}</p></section>` : ''}
        ${!item.example && !item.translation && !item.usage ? '<p class="daily-usage">可以通过“编辑”补充例句和使用场景。</p>' : ''}
        ${source ? `<div class="daily-source">${source}</div>` : ''}
      </div>
      ${originals}<footer class="daily-detail-footer"><span>${item.seed_key ? '日常小表达' : '自己收集的表达'}</span>${ui.contentMoves.button('daily',item.id)}${actions(item)}</footer>
      ${random ? `<button type="button" class="btn light daily-next" data-daily-random>再看一条 ${icon('recent')}</button>` : ''}
    </div>`, random ? 'random' : 'detail', item);
  }
  function confirmDelete(item) {
    openDaily(`<div class="dialog-card daily-confirm-dialog"><h2 id="daily-dialog-title">删除这条表达？</h2><p class="daily-delete-phrase" lang="en">${esc(item.phrase)}</p><p>删除后不再显示；需要时可在“最近删除”中恢复。</p><div class="dialog-actions"><button type="button" class="btn light" data-daily-close autofocus>取消</button><button type="button" class="btn danger" data-daily-confirm-delete="${item.id}">确认删除</button></div></div>`, 'delete', item);
    dialogBody.querySelector('[data-daily-close]').focus();
  }
  async function showTrash() {
    const trash = await api('/api/daily-expressions/trash');
    if (!ui.isCurrent()) return;
    deletedTotal = trash.total;
    openDaily(`<div class="dialog-card daily-trash-dialog"><div class="daily-detail-head"><h2 id="daily-dialog-title">最近删除</h2><button type="button" class="btn small light" data-daily-close aria-label="关闭最近删除">${icon('close')}</button></div><p class="daily-form-hint">恢复后，收藏、例句和自己的修改都会保留。</p><div class="daily-trash-list">${trash.items.length ? trash.items.map(item => `<article><div><strong lang="en">${esc(item.phrase)}</strong><p>${esc(item.meaning)}</p></div><button type="button" class="btn small light" data-daily-restore="${item.id}" aria-label="恢复 ${esc(item.phrase)}">恢复</button></article>`).join('') : '<p>没有已删除的表达。</p>'}</div></div>`, 'trash');
  }
  function edit(item = null) {
    openDaily(`<div class="dialog-card daily-form-dialog"><h2 id="daily-dialog-title">${item ? '编辑生活口语' : '添加生活口语'}</h2><p class="daily-form-hint">收集一句喜欢的说法，随时回来看看。</p><form id="daily-form" class="field-grid">
      ${dailyFormFields(item || {group_id:currentGroup?.id,category:currentGroup?'词汇':'口语'},esc,groups)}
      <p id="daily-form-error" class="error full" role="alert"></p><div class="actions full"><button type="button" class="btn light" data-daily-close>取消</button><button type="submit" class="btn primary">保存表达</button></div></form></div>`, 'edit', item);
    const form = dialogBody.querySelector('#daily-form');
    form.addEventListener('submit', async event => {
      event.preventDefault();
      const submit = form.querySelector('[type="submit"]');
      submit.disabled = true;
      try {
        const saved = await api(item ? `/api/daily-expressions/${item.id}` : '/api/daily-expressions', {method: item ? 'PUT' : 'POST', body: JSON.stringify(Object.fromEntries(new FormData(form)))});
        if (!ui.isCurrent()) return;
        if (item) Object.assign(item, saved);
        else { items.unshift(saved); filters.q = ''; filters.category = ''; filters.favorites = false; resetSearchInput(main.querySelector('#daily-search')); }
        refresh();
        closeDialog();
        notify('生活口语已保存');
      } catch (error) { form.querySelector('#daily-form-error').textContent = error.message; }
      finally { submit.disabled = false; }
    });
    form.querySelector('#daily-phrase').focus();
  }
  function editGroup(group=null) {
    openDaily(`<div class="dialog-card"><h2 id="daily-dialog-title">${group?'重命名合集':'新建合集'}</h2><form id="daily-group-form" class="field-grid"><div class="field full"><label for="daily-group-name">合集名称</label><input id="daily-group-name" name="name" required maxlength="80" value="${esc(group?.name || '')}" placeholder="例如：厨房、旅行、健身房"></div><p class="error full" role="alert"></p><div class="actions full"><button type="button" class="btn light" data-daily-close>取消</button><button type="submit" class="btn primary">保存合集</button></div></form></div>`, 'group');
    const form = dialogBody.querySelector('form');
    form.addEventListener('submit', async event=>{
      event.preventDefault();
      const submit=form.querySelector('[type="submit"]'); submit.disabled=true;
      try {
        const saved=await api(group?`/api/daily-groups/${group.id}`:'/api/daily-groups',{method:group?'PUT':'POST',body:JSON.stringify({name:form.elements.name.value})});
        if(!ui.isCurrent())return;
        if(group) {
          Object.assign(group,saved);
          main.querySelector('[data-daily-group-title]').textContent=saved.name;
        } else groups.push(saved);
        refresh(); closeDialog(); notify('合集已保存');
      } catch(error) { form.querySelector('.error').textContent=error.message; }
      finally { submit.disabled=false; }
    });
    form.elements.name.focus();
  }
  function confirmGroupDelete() {
    openDaily(`<div class="dialog-card"><h2 id="daily-dialog-title">解散“${esc(currentGroup.name)}”？</h2><p>只移除合集，里面的全部词条都会保留，回到生活口语列表。</p><div class="actions"><button type="button" class="btn light" data-daily-close>取消</button><button type="button" class="btn danger" data-daily-confirm-group-delete>解散并保留词条</button></div></div>`, 'group-delete');
  }
  async function onClick(event) {
    const target = event.target.closest('[data-daily-clear],[data-daily-category],[data-daily-favorites],[data-daily-random],[data-daily-add],[data-daily-edit],[data-daily-favorite],[data-daily-details],[data-daily-delete],[data-daily-confirm-delete],[data-daily-trash],[data-daily-restore],[data-daily-close],[data-daily-new-group],[data-daily-rename-group],[data-daily-delete-group],[data-daily-confirm-group-delete]');
    if (!target || !ui.isCurrent()) return;
    try {
      if (target.hasAttribute('data-daily-close')) return closeDialog();
      if (target.hasAttribute('data-daily-new-group')) return editGroup();
      if (target.hasAttribute('data-daily-rename-group')) return editGroup(currentGroup);
      if (target.hasAttribute('data-daily-delete-group')) return confirmGroupDelete();
      if (target.hasAttribute('data-daily-confirm-group-delete')) {
        target.disabled=true;
        await api(`/api/daily-groups/${currentGroup.id}`,{method:'DELETE'});
        closeDialog(); notify('合集已解散，词条全部保留'); location.hash='#daily'; return;
      }
      if (target.hasAttribute('data-daily-clear')) {
        filters.q=''; filters.category=''; filters.favorites=false;
        resetSearchInput(main.querySelector('#daily-search'));
        return refresh();
      }
      if (target.hasAttribute('data-daily-category')) { filters.category = target.dataset.dailyCategory; return refresh(); }
      if (target.hasAttribute('data-daily-favorites')) { filters.favorites = !filters.favorites; return refresh(); }
      if (target.hasAttribute('data-daily-add')) return edit();
      if (target.hasAttribute('data-daily-trash')) return await showTrash();
      if (target.hasAttribute('data-daily-random')) {
        const found = matching();
        if (!found.length) return notify('当前筛选下没有可浏览的表达。');
        const pool = found.filter(item => item.id !== modalItem?.id);
        const choices = pool.length ? pool : found;
        return showDetails(choices[Math.floor(Math.random() * choices.length)], true);
      }
      if (target.hasAttribute('data-daily-restore')) {
        target.disabled = true;
        const saved = await api(`/api/daily-expressions/${target.dataset.dailyRestore}/restore`, {method: 'POST', body: '{}'});
        if (!ui.isCurrent()) return;
        items.push(saved);
        items.sort((a, b) => Number(!b.seed_key) - Number(!a.seed_key) || a.id - b.id);
        deletedTotal--;
        refresh();
        await showTrash();
        notify('生活口语已恢复');
        return;
      }
      if (target.hasAttribute('data-daily-confirm-delete')) {
        target.disabled = true;
        const id = Number(target.dataset.dailyConfirmDelete);
        await api(`/api/daily-expressions/${id}`, {method: 'DELETE'});
        if (!ui.isCurrent()) return;
        items = items.filter(item => item.id !== id);
        deletedTotal++;
        refresh();
        closeDialog();
        notify('已删除，可在“最近删除”中恢复');
        return;
      }
      if (target.hasAttribute('data-daily-details')) return showDetails(items.find(item => item.id === Number(target.dataset.dailyDetails)));
      if (target.hasAttribute('data-daily-edit')) return edit(items.find(item => item.id === Number(target.dataset.dailyEdit)));
      if (target.hasAttribute('data-daily-delete')) return confirmDelete(items.find(item => item.id === Number(target.dataset.dailyDelete)));
      if (target.hasAttribute('data-daily-favorite')) {
        const item = items.find(item => item.id === Number(target.dataset.dailyFavorite));
        target.disabled = true;
        const saved = await api(`/api/daily-expressions/${item.id}`, {method: 'PUT', body: JSON.stringify({is_favorite: !item.is_favorite})});
        if (!ui.isCurrent()) return;
        Object.assign(item, saved);
        refresh();
        if (dialog.open && modalItem?.id === item.id && ['detail', 'random'].includes(modalKind)) {
          const control = dialogBody.querySelector('[data-daily-favorite]');
          control.outerHTML = favorite(item);
          dialogBody.querySelector('[data-daily-favorite]').focus();
        } else main.querySelector(`[data-daily-favorite="${item.id}"]`)?.focus({preventScroll: true});
      }
    } catch (error) {
      target.disabled = false;
      if (ui.isCurrent()) notify(error.message);
    }
  }

  return ui.commit(() => {
    removeDialogListener();
    const onClose = () => {
      if (!dialog.dataset.dailyDialog) return;
      dialog.classList.remove('daily-dialog');
      delete dialog.dataset.dailyDialog;
      dialog.removeAttribute('aria-labelledby');
      modalItem = null; modalKind = '';
      if (ui.isCurrent()) queueMicrotask(() => {
        const target = returnFocus && main.querySelector(returnFocus);
        (target && !target.hidden && target.getClientRects().length ? target : main).focus({preventScroll: true});
      });
    };
    dialog.addEventListener('close', onClose);
    removeDialogListener = () => dialog.removeEventListener('close', onClose);
    main.innerHTML = `${currentGroup?'<div class="daily-group-breadcrumb"><a class="btn text" href="#daily">← 返回生活口语</a><span>词汇合集</span></div>':''}${pageHead('EVERYDAY', '生活口语', '日常词汇、俚语、习语、谚语，按主题放在一起。')}
      ${textLoopMarkup()}
      <section class="daily-intro"><div><span class="daily-intro-mark">${icon('sparkles')}</span><div><strong>有空，随手翻一翻</strong><p>这里直接查看内容；想练习时，到复习页选择生活口语。</p></div></div><div class="actions"><button type="button" class="btn light" data-daily-new-group>新建合集</button><button type="button" class="btn light" data-daily-random>随便看看 ${icon('recent')}</button><button type="button" class="btn primary" data-daily-add>${icon('add')} 添加内容</button></div></section>
      ${currentGroup?`<section class="daily-group-controls"><strong data-daily-group-title>${esc(currentGroup.name)}</strong><span data-daily-group-count>${items.filter(item=>item.group_id===groupId).length} 条内容</span><button type="button" class="btn light" data-daily-rename-group>重命名</button><button type="button" class="btn text" data-daily-delete-group>解散合集</button></section>`:''}
      <section class="daily-browser" aria-label="浏览生活口语"><div class="daily-search-row"><label class="daily-search"><span>${icon('book')}</span><input id="daily-search" type="search" aria-label="搜索生活口语" placeholder="搜英文、中文意思或使用场景…" value="${esc(filters.q)}"></label><button type="button" class="btn light daily-favorites-filter" data-daily-favorites aria-pressed="${filters.favorites}">${icon('bookmark')} 只看收藏</button></div>
      <div class="daily-filter-row"><div class="daily-categories" aria-label="表达分类">${['', ...categories].map(category => `<button type="button" data-daily-category="${category}" aria-pressed="${filters.category === category}">${category || '全部'}<small></small></button>`).join('')}</div><div class="daily-result-meta"><button type="button" class="btn text" data-daily-clear>清除筛选</button><select data-daily-sort aria-label="排序方式"><option value="default" ${filters.sort==='default'?'selected':''}>默认顺序</option><option value="newest" ${filters.sort==='newest'?'selected':''}>录入时间：从新到旧</option><option value="oldest" ${filters.sort==='oldest'?'selected':''}>录入时间：从旧到新</option><option value="phrase" ${filters.sort==='phrase'?'selected':''}>英文：A → Z</option></select><button type="button" class="btn text daily-trash-link" data-daily-trash hidden>最近删除</button><span id="daily-result-count" role="status" aria-live="polite"></span></div></div></section>
      <div id="daily-results" class="daily-grid"></div>`;
    bindSearchInput(main.querySelector('#daily-search'), value => { filters.q = value; refresh(); }, {isCurrent:ui.isCurrent});
    main.querySelector('[data-daily-sort]').addEventListener('change', event => {filters.sort=event.target.value; refresh();});
    main.onclick = onClick;
    dialogBody.onclick = onClick;
    refresh();
    const detailId=Number(new URLSearchParams(location.hash.split('?')[1]).get('detail')||0);
    if(detailId)showDetails(items.find(item=>item.id===detailId)).catch(error=>notify(error.message));
  });
}
