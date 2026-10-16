const modules = {general:'阅读写作', academic:'学术词汇', expressions:'阅读素材', daily:'生活口语'};

export function createContentMoves({api,esc,openDialog,closeDialog,notify,routeTo,state,dialogBody}) {
  let pending = null, requestVersion = 0;
  const button = (source,id) => `<button type="button" class="btn small light content-move-button" data-content-move="${source}" data-move-id="${id}">移动到…</button>`;
  async function retained(source,id) {
    const result = await api(`/api/content-moves/retained?${new URLSearchParams({source,item_id:id})}`);
    if (!result.items.length) return '';
    return `<details class="move-retained"><summary>查看原模块资料 <span>移动时已保留</span></summary><p>这里保存移动前的完整资料；移回原模块时恢复对应记录。</p>${result.items.map(item=>`<section><h3>${esc(item.label)}</h3><strong lang="en">${esc(item.term)}</strong>${item.meaning?`<p>${esc(item.meaning)}</p>`:''}${item.fields.map(field=>`<p><b>${esc(field.label)}：</b>${esc(field.value)}</p>`).join('')}${item.history_count||item.read_count?`<small>保留 ${item.history_count} 条复习记录 · ${item.read_count} 条阅读记录</small>`:''}</section>`).join('')}</details>`;
  }
  function targetFields(preview,categories) {
    const isReading = pending.target === 'expressions';
    return `<div class="field"><label for="move-term">${isReading?'英文原文':'英文词条 / 表达'} *</label><textarea id="move-term" name="term" required maxlength="${isReading?200000:240}" rows="${isReading?4:2}">${esc(preview.term)}</textarea></div><div class="field"><label for="move-meaning">中文${isReading?'翻译（可选）':'意思 *'}</label><textarea id="move-meaning" name="meaning" ${isReading?'':'required'} maxlength="${isReading?200000:1000}" rows="2">${esc(preview.meaning)}</textarea></div>${pending.target==='academic'?`<div class="move-options"><div class="field"><label for="move-category">目标合集</label><select id="move-category" name="academic_category_id"><option value="">未归入合集</option>${categories.items.map(category=>`<option value="${category.id}" ${category.id===preview.academic_category_id?'selected':''}>${esc(category.name)}</option>`).join('')}</select></div>${vocabularyType(preview)}</div>`:pending.target==='general'?vocabularyType(preview):pending.target==='daily'?`<div class="field"><label for="move-category">口语分类</label><select id="move-category" name="category">${['口语','俚语','习语','谚语'].map(value=>`<option ${value===preview.category?'selected':''}>${value}</option>`).join('')}</select></div>`:''}${preview.long_text?'<p class="move-long-note">原文较长，请为目标填写简短的英文和中文。完整原文会保留，可在目标详情中展开“原模块资料”。</p>':''}`;
  }
  function vocabularyType(preview) {
    return `<div class="field"><label for="move-item-type">词条类型</label><select id="move-item-type" name="item_type">${[['word','单词'],['phrase','固定搭配'],['sentence','长句']].map(([value,label])=>`<option value="${value}" ${value===preview.item_type?'selected':''}>${label}</option>`).join('')}</select></div>`;
  }
  async function previewTarget() {
    const version = ++requestVersion, current = pending;
    const form = dialogBody.querySelector('#content-move-form'), fields = form.querySelector('[data-move-fields]'), submit = form.querySelector('[type="submit"]');
    submit.disabled=true; fields.setAttribute('aria-busy','true');
    form.querySelector('[data-move-error]').textContent='';
    try {
      const [preview,categories] = await Promise.all([api('/api/content-moves/preview',{method:'POST',body:JSON.stringify(current)}),current.target==='academic'?api('/api/academic-categories'):Promise.resolve({items:[]})]);
      if(version!==requestVersion||pending!==current||!form.isConnected)return;
      fields.innerHTML=targetFields(preview,categories);
      form.dataset.sourceVersion=preview.source_version;
      form.querySelector('[data-move-impact]').textContent=['general','academic'].includes(current.target)?'移入后参与这个模块的词汇复习；已有掌握度与复习记录会恢复。':current.target==='daily'?'移入后只浏览和收藏，不进入复习或学习统计。原学习资料和记录会保留。':'移入后用于收藏和阅读，不进入词汇复习。原学习资料和记录会保留。';
      submit.disabled=false;
    } catch(error) {if(version===requestVersion&&form.isConnected)form.querySelector('[data-move-error]').textContent=error.message;}
    finally {if(version===requestVersion)fields.removeAttribute('aria-busy');}
  }
  async function open(source,id) {
    pending={source,item_id:Number(id),target:source==='expressions'?'daily':source==='daily'?'expressions':source==='academic'?'general':'academic'};
    // Release any module-specific dialog handlers before taking over the shared dialog.
    closeDialog();dialogBody.onclick=null;
    openDialog(`<div class="dialog-card content-move-dialog"><div class="section-head"><h2>移动内容</h2><button type="button" class="btn small light" data-move-cancel>取消</button></div><p>从 <b>${esc(modules[source])}</b> 移出，放入你选择的模块。</p><form id="content-move-form"><div class="field"><label for="move-target">目标模块</label><select id="move-target" name="target">${Object.entries(modules).filter(([key])=>key!==source).map(([key,label])=>`<option value="${key}" ${key===pending.target?'selected':''}>${label}</option>`).join('')}</select></div><div data-move-fields></div><p class="move-impact" data-move-impact></p><p class="error" role="alert" data-move-error></p><div class="dialog-actions"><button type="button" class="btn light" data-move-cancel>取消</button><button type="submit" class="btn primary" disabled>确认移动</button></div></form></div>`);
    const form=dialogBody.querySelector('#content-move-form');
    form.querySelector('#move-target').addEventListener('change',event=>{pending={...pending,target:event.target.value};previewTarget();});
    form.addEventListener('submit',async event=>{
      event.preventDefault();const submit=form.querySelector('[type="submit"]');if(submit.disabled)return;
      submit.disabled=true;form.querySelector('#move-target').disabled=true;
      try {
        const moved=await api('/api/content-moves',{method:'POST',body:JSON.stringify({...pending,...Object.fromEntries(new FormData(form)),source_version:form.dataset.sourceVersion})});
        const destination=moved.target;pending=null;++requestVersion;closeDialog();
        state.expressionReader=null;state.review=null;state.selected.clear();state.captureReturn=null;
        state.expressionFilters={...state.expressionFilters,q:'',type:'',exam:'',topic:'',tag:'',favorite:''};
        notify(`已移动到${modules[destination]}`);
        if(['general','academic'].includes(destination)) {
          const route=destination==='academic'?'academic':'reading';
          state.libraryRestore={route,filters:{...state.filters,page:1,q:'',source:'',tag:'',status:'',item_group:moved.item_type==='sentence'?'sentence':'vocabulary',category_id:destination==='academic'?String(moved.academic_category_id||'uncategorized'):''}};
          state.filters={...state.libraryRestore.filters};
          routeTo(`${route}?${new URLSearchParams({detail:moved.item_id,...(destination==='academic'?{category_id:moved.academic_category_id||'uncategorized'}:{})})}`);
        } else routeTo(destination==='expressions'?`expressions?read=${moved.item_id}`:`daily?detail=${moved.item_id}`);
      } catch(error) {form.querySelector('[data-move-error]').textContent=error.message;submit.disabled=false;form.querySelector('#move-target').disabled=false;}
    });
    await previewTarget();form.querySelector('#move-target').focus();
  }
  document.addEventListener('click',event=>{
    const move=event.target.closest('[data-content-move]');
    if(move){event.preventDefault();open(move.dataset.contentMove,move.dataset.moveId).catch(error=>notify(error.message));}
    if(event.target.closest('[data-move-cancel]')) {pending=null;++requestVersion;closeDialog();}
  });
  return {button,retained};
}
