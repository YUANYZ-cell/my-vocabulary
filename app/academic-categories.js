export function createAcademicCategories({state,api,esc,openDialog,closeDialog,notify,renderLibrary,routeTo,qs,syncCaptureForm,showDetail}) {
  let data={items:[],total:0,uncategorized:0};
  const setData=value=>{data=value};
  const options=(selected='',all=false)=>`${all?'<option value="">全部学术词汇</option>':''}<option value="${all?'uncategorized':''}" ${String(selected)===(all?'uncategorized':'')?'selected':''}>未分类</option>${data.items.map(category=>`<option value="${category.id}" ${String(selected)===String(category.id)?'selected':''}>${esc(category.name)}</option>`).join('')}`;
  const label=selected=>selected==='uncategorized'?'未分类':data.items.find(category=>String(category.id)===String(selected))?.name||'全部学术词汇';
  const reviewRoute=id=>`review?${qs({collection:'academic',category_id:id,scope:'topic',mode:'recall',start:1})}`;
  function shelf() {
    const selected=String(state.filters.category_id||'');
    if(selected) return `<section class="academic-category-shelf academic-topic-header" aria-label="当前合集"><header><div><button type="button" class="btn small text" data-academic-category="">← 返回词条与合集</button><h2>${esc(label(selected))}</h2><p>查看合集里的词条，或逐条回忆并揭晓释义。</p></div><div class="actions"><button type="button" class="btn small light" data-category-action="manage">管理合集</button><button type="button" class="btn small primary" data-route="${reviewRoute(selected)}">复习整个专题</button></div></header></section>`;
    return `<section class="academic-category-shelf academic-collection-controls" aria-label="查看词条或合集"><header><div><h2>词条与小合集</h2><p>合集和词条放在同一列表；打开合集查看其中内容。</p></div><div class="actions"><button type="button" class="btn small light" data-category-action="create">＋ 新建合集</button><button type="button" class="btn small text" data-category-action="manage">管理合集</button></div></header><div class="academic-view-switch" role="group" aria-label="查看方式">${[['mixed','词条与合集'],['all','全部词条'],['folders','只看合集']].map(([value,text])=>`<button type="button" data-academic-view="${value}" aria-pressed="${(state.academicView||'mixed')===value}">${text}</button>`).join('')}</div></section>`;
  }
  function rows(group) {
    if(state.filters.category_id||state.academicView==='all'||state.organize||state.categoryOrganize||state.filters.source||state.filters.tag||state.filters.status||(group!=='sentence'&&state.filters.item_type))return '';
    const query=state.filters.q.trim().toLocaleLowerCase();
    return data.items.filter(category=>!query||category.name.toLocaleLowerCase().includes(query)).map(category=>`<article class="library-row academic-collection-row" data-collection-id="${category.id}"><div class="term"><div><span class="term-head"><span class="type-pill">合集</span><strong>${esc(category.name)}</strong></span><small class="term-meaning">${category.count} 条词条 · 单词与固定搭配 ${category.vocabulary_count} · 长句 ${category.sentence_count}</small></div></div><div class="row-facts"><span><small>创建</small>${esc(category.created_at.slice(0,10))}</span></div>${group==='sentence'?'':`<div class="collection-count-label">${category.count} 条词条</div>`}<div class="row-actions"><div class="content-actions"><button type="button" class="content-action content-view" data-academic-category="${category.id}" aria-label="查看合集 ${esc(category.name)}">查看合集</button><details class="content-menu"><summary aria-label="更多操作：${esc(category.name)}" title="更多操作">⋯</summary><div class="content-menu-panel"><button type="button" data-route="${reviewRoute(category.id)}" ${category.count?'':'disabled'}>复习整个专题</button><button type="button" data-category-action="rename" data-category-id="${category.id}">改名</button><button type="button" data-category-action="delete" data-category-id="${category.id}">删除合集</button></div></details></div></div></article>`).join('');
  }
  const singleButton=item=>`<button type="button" class="btn small light" data-category-action="single" data-category-item="${item.id}">整理到合集…</button>`;
  async function assignSingle(itemId) {
    const [item,categories]=await Promise.all([api(`/api/items/${itemId}`),api('/api/academic-categories')]);setData(categories);
    openDialog(`<div class="dialog-card"><h2>整理到合集</h2><p>${esc(item.term)}</p><form id="single-category-form"><div class="field"><label for="single-category-target">目标合集</label><select id="single-category-target">${options(item.academic_category_id||'')}</select></div><p>归类会保留词条内容、掌握度与复习记录。</p><p class="error" role="alert"></p><div class="dialog-actions"><button type="button" class="btn light" data-action="close-dialog">取消</button><button type="submit" class="btn primary">保存归类</button></div></form></div>`);
    document.querySelector('#single-category-form').addEventListener('submit',async event=>{
      event.preventDefault();const form=event.currentTarget,submit=form.querySelector('[type="submit"]');if(submit.disabled)return;submit.disabled=true;
      try {await api('/api/academic-categories/assign',{method:'PUT',body:JSON.stringify({item_ids:[item.id],academic_category_id:form.querySelector('select').value||null})});closeDialog();notify('词条已归类');if(['library','reading','academic'].includes(state.route))await renderLibrary();await showDetail(item.id);}
      catch(error){form.querySelector('.error').textContent=error.message;submit.disabled=false;}
    });
  }
  function form(selected='') {
    return `<div class="academic-category-field field"><label for="item-academic-category">专业合集</label><div class="academic-category-input"><select id="item-academic-category" name="academic_category_id">${options(selected)}</select><button type="button" class="btn light" data-category-action="create">新建合集</button></div><small>选择这个词所属的专业或课程；也可以先保存在“未分类”。</small></div>`;
  }
  function bulkButton() {
    return `<button type="button" class="btn light" data-category-action="organize">${state.categoryOrganize?'退出归类':'批量归类'}</button>`;
  }
  function organizer() {
    return `<section class="group-panel organizer academic-category-organizer"><h3>把已有词条归入合集</h3><p>勾选词条后选择目标合集；掌握度与复习记录都会保留。</p><div class="academic-category-input"><label for="category-target">归入</label><select id="category-target">${options(state.categoryTarget||'')}</select><button type="button" class="btn primary" data-category-action="assign">保存归类</button><button type="button" class="btn light" data-action="clear-selection">清除选择</button></div><p class="hint" role="status">已选择 ${state.selected.size} 条。</p></section>`;
  }
  function selectCategory(value) {
    state.filters={...state.filters,category_id:String(value),page:1,q:'',source:'',tag:'',status:''};
    state.categoryOrganize=false;state.organize=false;state.selected.clear();state.editingGroup=null;
    routeTo(`academic${value!==''?'?'+qs({category_id:value}):''}`);
  }
  async function openManage() {
    setData(await api('/api/academic-categories'));
    openDialog(`<div class="dialog-card academic-category-manager"><div class="section-head"><h2>管理学术合集</h2><button type="button" class="btn small light" data-action="close-dialog">关闭</button></div><p>改名会同步更新所有词条；删除合集后，里面的词条会回到“未分类”。</p>${data.items.length?`<ul>${data.items.map(category=>`<li><div><strong>${esc(category.name)}</strong><small>${category.count} 条词条</small></div><div class="actions"><button type="button" class="link-btn" data-category-action="rename" data-category-id="${category.id}" aria-label="重命名 ${esc(category.name)}">改名</button><button type="button" class="link-btn" data-category-action="delete" data-category-id="${category.id}" aria-label="删除合集 ${esc(category.name)}">删除</button></div></li>`).join('')}</ul>`:'<div class="empty"><p>还没有自定义合集。</p></div>'}<div class="dialog-actions"><button type="button" class="btn primary" data-category-action="create" data-return-manage="true">新建合集</button></div></div>`);
  }
  function openEditor(categoryId=null,returnManage=false) {
    const existing=data.items.find(category=>category.id===categoryId),captureForm=document.querySelector('#item-form');
    openDialog(`<div class="dialog-card"><h2>${existing?'重命名合集':'新建学术合集'}</h2><p>例如单片机、自动控制或信号处理。</p><form id="academic-category-form"><div class="field"><label for="academic-category-name">合集名称</label><input id="academic-category-name" name="category_name" required maxlength="60" value="${esc(existing?.name||'')}" placeholder="例如：单片机" autocomplete="off"></div><p class="error" role="alert" id="academic-category-error"></p><div class="dialog-actions"><button type="button" class="btn light" data-action="close-dialog">取消</button><button type="submit" class="btn primary">${existing?'保存名称':'创建合集'}</button></div></form></div>`);
    document.querySelector('#academic-category-name').focus();
    document.querySelector('#academic-category-form').addEventListener('submit',async event=>{
      event.preventDefault();const editor=event.currentTarget,submit=editor.querySelector('[type="submit"]');if(submit.disabled)return;submit.disabled=true;
      try {
        const saved=await api(`/api/academic-categories${existing?'/'+existing.id:''}`,{method:existing?'PUT':'POST',body:JSON.stringify({name:editor.elements.category_name.value})});
        setData(await api('/api/academic-categories'));closeDialog();notify(existing?'合集名称已更新':'合集已创建');
        if(captureForm?.isConnected){captureForm.elements.academic_category_id.innerHTML=options(saved.id);syncCaptureForm();}
        else if(state.route==='academic') {if(existing||returnManage)await renderLibrary();else selectCategory(saved.id);}
        if(returnManage)await openManage();
      } catch(error) {editor.querySelector('#academic-category-error').textContent=error.message;submit.disabled=false;}
    });
  }
  function confirmDelete(categoryId) {
    const category=data.items.find(item=>item.id===categoryId);if(!category)return;
    openDialog(`<div class="dialog-card"><h2>删除“${esc(category.name)}”合集？</h2><p>${category.count} 条词条会回到“未分类”，单词内容、掌握度和复习记录都会保留。</p><div class="dialog-actions"><button type="button" class="btn light" data-category-action="manage">取消</button><button type="button" class="btn danger" data-category-action="confirm-delete" data-category-id="${categoryId}">确认删除合集</button></div></div>`);
  }
  document.addEventListener('change',event=>{if(event.target.id==='category-target')state.categoryTarget=event.target.value;});
  document.addEventListener('click',async event=>{
    const control=event.target.closest('[data-category-action],[data-academic-category],[data-academic-view]');if(!control)return;
    if(control.hasAttribute('data-academic-view')){state.academicView=control.dataset.academicView;state.filters.page=1;state.organize=false;state.categoryOrganize=false;state.selected.clear();renderLibrary().catch(error=>notify(error.message));return;}
    if(control.hasAttribute('data-academic-category')){selectCategory(control.dataset.academicCategory);return;}
    const action=control.dataset.categoryAction;
    try {
      if(action==='single')return await assignSingle(Number(control.dataset.categoryItem));
      if(action==='create')return openEditor(null,control.dataset.returnManage==='true');
      if(action==='manage')return await openManage();
      if(action==='rename')return openEditor(Number(control.dataset.categoryId),true);
      if(action==='delete')return confirmDelete(Number(control.dataset.categoryId));
      if(action==='confirm-delete') {
        if(control.disabled)return;control.disabled=true;
        await api(`/api/academic-categories/${control.dataset.categoryId}`,{method:'DELETE'});
        if(String(state.filters.category_id)===control.dataset.categoryId){state.filters.category_id='';history.replaceState(null,'','#academic');}
        closeDialog();notify('合集已删除，词条已保留');if(state.route==='academic')await renderLibrary();return await openManage();
      }
      if(action==='organize') {
        state.categoryOrganize=!state.categoryOrganize;state.organize=false;state.editingGroup=null;state.selected.clear();
        state.categoryTarget=state.filters.category_id==='uncategorized'?'':state.filters.category_id||'';
        return await renderLibrary();
      }
      if(action==='assign') {
        if(!state.selected.size)return notify('请先勾选要归类的学术词条');
        if(control.disabled)return;control.disabled=true;
        const result=await api('/api/academic-categories/assign',{method:'PUT',body:JSON.stringify({item_ids:[...state.selected],academic_category_id:document.querySelector('#category-target').value||null})});
        state.categoryOrganize=false;state.selected.clear();notify(`${result.updated} 条词条已归类`);return await renderLibrary();
      }
    } catch(error) {control.disabled=false;notify(error.message);}
  });
  return {setData,options,label,shelf,rows,singleButton,form,bulkButton,organizer};
}
