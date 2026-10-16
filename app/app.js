import {bindSearchInput,resetSearchInput,updateSearchRegion} from './search-input.js?v=1';
import {updateCaptureType} from './content-types.js?v=2';
import {parseDictionaryText} from './dictionary-parser.js?v=17';
import {mountCounters} from './counter.js?v=2';
import {barChart,donutChart,lineChart,mountCharts} from './charts.js?v=4';
import {renderDailyExpressions,dailyFormFields} from './daily-expressions.js?v=13';
import {renderDailyReview,reviewSourcePicker} from './daily-review.js?v=2';
import {mountAmbientMotion} from './ambient-motion.js?v=10';
import {mountTextLoops} from './text-loop.js?v=3';
import {createPageMotion} from './page-motion.js?v=1';
import {createAcademicCategories} from './academic-categories.js?v=6';
import {createContentMoves} from './content-moves.js?v=2';
const main=document.querySelector('#app-main'),dialog=document.querySelector('#dialog'),dialogBody=document.querySelector('#dialog-body'),toast=document.querySelector('#toast');
mountTextLoops(main);
const savedSort=localStorage.getItem('library-sort');
const state={route:'today',filters:{page:1,q:'',category_id:'',item_group:'vocabulary',item_type:'',source:'',tag:'',status:'',sort:['newest','oldest','term_asc','term_desc'].includes(savedSort)?savedSort:'newest'},expressionFilters:{q:'',type:'',exam:'',topic:'',tag:'',favorite:'',sort:'recent'},expressionReader:null,organize:false,categoryOrganize:false,selected:new Set(),editingGroup:null,review:null,reviewSetup:null,errorMap:null,errorMapDays:'7',errorDrawer:null};
// Keep every mastery picker ordered from the least secure state to the most secure one.
const statusText={wrong:'易错',new:'新词',learning:'学习中',familiar:'较熟悉',mastered:'已掌握'};
const masteryOrder=['wrong','new','learning','familiar','mastered'];
const masteryBoostTarget={wrong:'new',new:'learning',learning:'familiar',familiar:'mastered'};
const reviewLimitPresets=[10,20,30,50,100];
const ratingText={forgot:'忘记',fuzzy:'模糊',remembered:'记住',easy:'很熟'};
const modeText={recall:'遮罩自评',cloze:'挖空补全',zh_to_en:'看中文写英文',en_to_zh:'看英文想中文'};
const scopeText={random:'全局复习',recent:'最近添加',study:'学习模式',today:'今日内容',mistakes:'错题重练',group:'易混专项',topic:'专题复习'};
const itemTypeText={word:'单词',phrase:'固定搭配',sentence:'长句'};
const libraryGroupText={vocabulary:'单词与固定搭配',sentence:'长句'};
const reviewTypeText={...itemTypeText,vocabulary:'单词与固定搭配',topic:"专题词条"};
const collectionText={all:'总词库',general:'阅读写作',academic:'学术词汇'};
const reviewContentChoices={
  general:[['vocabulary','单词与固定搭配','两类内容一起复习'],['word','只复习单词','雅思与阅读积累'],['phrase','只复习短语','固定搭配与简短句'],['sentence','只复习长句','写作表达与完整句']],
  academic:[['word','学术单词','专业课术语'],['phrase','学术短语','专业搭配与词组'],['sentence','学术长句','专业语境中的句式']],
};
function reviewContentPicker(){
  const s=state.reviewSetup;
  return `<section class="review-content-picker" aria-labelledby="review-content-title"><div class="setup-heading review-content-heading"><span>01</span><div><p class="choice-title">复习内容</p><h2 id="review-content-title">选择这轮的复习内容</h2><p>阅读词汇可同时复习单词与固定搭配，也可单独选择一种内容。</p></div></div>${Object.entries(reviewContentChoices).map(([collection,choices])=>`<div class="review-content-group"><h3 id="review-content-${collection}">${collectionText[collection]}<span>${collection==='academic'?'专业课积累，可按合集筛选':'雅思与日常阅读'}</span></h3><div class="content-type-switch ${collection==='general'?'reading-content-switch':''}" role="group" aria-labelledby="review-content-${collection}">${choices.map(([type,title,hint])=>`<button type="button" data-review-collection="${collection}" data-review-type="${type}" aria-pressed="${s.collection===collection&&s.itemType===type}"><strong>${title}</strong><small>${hint}</small><span class="review-content-count"></span></button>`).join('')}</div></div>`).join('')}<div class="collection-picker review-academic-category ${s.collection==='academic'?'':'hidden'}"><div><strong>按专业合集筛选</strong><small>可集中复习一个课程或专题中的所选类型。</small></div><select id="review-category" aria-label="复习学术分类">${academicCategories.options(s.categoryId,true)}</select></div><div id="review-empty-hint" class="review-empty-hint hidden" role="status"><span>这类内容暂时为空，添加后即可复习。</span><button type="button" class="btn small light" data-route="add">添加内容</button></div></section>`;
}
function selectReviewContent(collection,itemType){
  const s=state.reviewSetup;
  if(s.collection!==collection){
    s.collection=collection;s.categoryId='';s.confirmedCategoryId='';s.groupId=null;s.categoryPending=false;s.categoryRequest++;
    s.contentCounts.academic=s.academicCountsAll;
    document.querySelector('#review-category').value='';
    document.querySelector('#review-group').innerHTML='<option value="">请选择</option>'+s.groups[collection].map(g=>`<option value="${g.id}">${esc(g.name)} (${g.items.length})</option>`).join('');
  }
  s.itemType=itemType;syncReviewSetupUi(s.scope);
}
async function selectReviewCategory(categoryId,ctx){
  const s=state.reviewSetup,previous=s.confirmedCategoryId,request=++s.categoryRequest;
  const isCurrent=()=>ctx.isCurrent()&&state.reviewSetup===s&&s.collection==='academic'&&s.categoryRequest===request;
  s.categoryId=categoryId;s.categoryPending=true;syncReviewSetupUi(s.scope);
  try{
    const facets=await ctx.request(`/api/facets?${qs({collection:'academic',category_id:categoryId})}`);
    if(!isCurrent())return;
    s.contentCounts.academic=facets.type_counts;s.confirmedCategoryId=categoryId;
  }catch(error){
    if(!isCurrent())return;
    s.categoryId=previous;document.querySelector('#review-category').value=previous;notify(error.message);
  }finally{
    if(isCurrent()){s.categoryPending=false;syncReviewSetupUi(s.scope)}
  }
}
function libraryCollection(){return state.route==='library'?'all':state.route==='academic'?'academic':'general'}
function captureChoices(collection,itemType,locked=false){
  const choice=locked?itemType:'auto';
  return `<fieldset class="capture-entry-switch"><legend>02 · ${collectionText[collection]}中的内容类型</legend><div>${[['auto','自动识别','输入英文后自动判断'],['word','单词','一个英文词'],['phrase','短语 / 固定搭配','词组、搭配与简短表达'],['sentence','长句 / 表达句式','较长句子与表达模板']].map(([key,label,hint])=>`<label><input type="radio" name="type_choice" value="${key}" ${key===choice?'checked':''}><span><b>${label}</b><small>${hint}</small></span></label>`).join('')}</div></fieldset><input type="hidden" name="collection" value="${collection}"><input type="hidden" name="item_type" value="${itemType}"><p class="capture-destination" role="status" aria-live="polite"></p>`;
}
function syncCaptureForm(){
  const form=document.querySelector('#item-form');if(!form)return;
  const academic=form.elements.collection.value==='academic',type=updateCaptureType(form);
  document.querySelector('.academic-category-field').classList.toggle('hidden',!academic);form.elements.academic_category_id.disabled=!academic;
  document.querySelector('[data-mastery-field]')?.classList.toggle('hidden',type==='sentence');
  const hasTerm=!!form.elements.term.value.trim(),automatic=form.elements.type_choice.value==='auto';
  const label=type==='phrase'?'短语 / 固定搭配':itemTypeText[type];
  const result=automatic?(hasTerm?`自动识别：${label}。`:'输入英文后会自动识别单词、短语 / 固定搭配或长句。'):`已手动选择：${label}。`;
  document.querySelector('.capture-destination').textContent=`${result} 保存到${academic?'学术词汇 · '+academicCategories.label(form.elements.academic_category_id.value||'uncategorized'):'阅读写作'}${hasTerm?' · '+label:''}，也会显示在总词库中。${automatic&&hasTerm?'如有偏差，可点选上方类型修正。':''}`;
}
function bindCaptureForm(){
  document.querySelectorAll('[name="type_choice"],[name="academic_category_id"]').forEach(input=>input.addEventListener('change',syncCaptureForm));
  document.querySelector('#item-form').elements.term.addEventListener('input',syncCaptureForm);
  syncCaptureForm();
}

const iconPaths={
  book:'<path d="M4 5.5c3-.7 5.5-.1 8 1.6v12.5c-2.5-1.7-5-2.3-8-1.6V5.5Zm16 0c-3-.7-5.5-.1-8 1.6v12.5c2.5-1.7 5-2.3 8-1.6V5.5Z"/>',
  sparkles:'<path d="m12 3 1.35 4.15L17.5 8.5l-4.15 1.35L12 14l-1.35-4.15L6.5 8.5l4.15-1.35L12 3Zm6.2 10.6.8 2.4 2.4.8-2.4.8-.8 2.4-.8-2.4-2.4-.8 2.4-.8.8-2.4ZM5.1 14.2l.65 1.95 1.95.65-1.95.65-.65 1.95-.65-1.95-1.95-.65 1.95-.65.65-1.95Z"/>',
  recall:'<path d="M12 3.5a8.5 8.5 0 1 0 8.1 11M12 7v5l3 2M17 4v4h4"/>',
  spelling:'<path d="M4 6h16v12H4zM7 10h2m2 0h2m2 0h2M7 14h7"/>',
  retry:'<path d="M19.5 8.5A8 8 0 1 0 20 15M19.5 3.5v5h-5"/>',
  sun:'<circle cx="12" cy="12" r="3.5"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4m0-14.2-1.4 1.4M6.3 17.7l-1.4 1.4"/>',
  check:'<path d="m5 12 4 4L19 6"/>',
  pencil:'<path d="m4 20 4.2-1 10.9-10.9a2.2 2.2 0 0 0-3.2-3.2L5 15.8 4 20Z"/><path d="m14.5 6.5 3 3"/>',
  bolt:'<path d="m13 2-8 12h7l-1 8 8-12h-7l1-8Z"/>',
  mastered:'<path d="m12 3 2.2 4.6 5 .7-3.6 3.5.9 5-4.5-2.4-4.5 2.4.9-5-3.6-3.5 5-.7L12 3Z"/>',
  bookmark:'<path d="M6 3.5h12a1 1 0 0 1 1 1V21l-7-5-7 5V4.5a1 1 0 0 1 1-1Z"/>',
  add:'<path d="M12 5v14M5 12h14"/>',
  globe:'<circle cx="12" cy="12" r="9"/><path d="M3.5 12h17M12 3c2.3 2.5 3.5 5.5 3.5 9S14.3 18.5 12 21c-2.3-2.5-3.5-5.5-3.5-9S9.7 5.5 12 3Z"/>',
  recent:'<path d="M8 5h11v11M19 5 5 19"/>',
  today:'<rect x="3.5" y="5" width="17" height="15" rx="2"/><path d="M7 3v4m10-4v4M3.5 10h17"/>',
  mistake:'<path d="M12 4 3.8 19h16.4L12 4Z"/><path d="M12 9v4m0 3h.01"/>',
  group:'<path d="M8 7h12M4 7h.01M8 12h12M4 12h.01M8 17h12M4 17h.01"/>',
  cloze:'<path d="M4 6h16M4 18h16M7 10h3m4 0h3M8 14h8"/>',
  clock:'<circle cx="12" cy="12" r="9"/><path d="M12 7.2V12l3.2 2"/>',
  trend:'<path d="M4 16.5 9.5 11l3.5 3.5L20 7.5"/><path d="M15.5 7.5H20v4.5"/>',
  chevron:'<path d="m9.5 5.5 6.5 6.5-6.5 6.5"/>',
  close:'<path d="M6.5 6.5l11 11m0-11-11 11"/>',
  trash:'<path d="M4 7h16M9 7V4h6v3M6 7l1 14h10l1-14M10 11v6m4-6v6"/>',
  more:'<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>'
};
function icon(name,className=''){return `<svg class="ui-icon ${className}" viewBox="0 0 24 24" aria-hidden="true" focusable="false">${iconPaths[name]||iconPaths.sparkles}</svg>`}
function contentActions(label,{view,edit,remove,wide=false}){
  const manage=view?`<details class="content-menu"><summary aria-label="更多操作：${esc(label)}" title="更多操作">${icon('more')}</summary><div class="content-menu-panel"><button type="button" ${edit} aria-label="编辑 ${esc(label)}">${icon('pencil')} 编辑</button><button type="button" ${remove} aria-label="删除 ${esc(label)}">${icon('trash')} 删除</button></div></details>`:`<span class="content-manage"><button type="button" class="content-action content-edit" ${edit} aria-label="编辑 ${esc(label)}">编辑</button><button type="button" class="content-action content-remove" ${remove} aria-label="删除 ${esc(label)}">删除</button></span>`;
  return `<div class="content-actions ${wide?'spread':''}" role="group" aria-label="${esc(label)} 的操作">${view?`<button type="button" class="content-action content-view" ${view.attributes} aria-label="查看 ${esc(label)} 的${esc(view.text||'详细信息')}">${esc(view.text||'详细信息')}${view.icon?icon(view.icon):''}</button>`:''}${manage}</div>`;
}
document.addEventListener('click',event=>{document.querySelectorAll('.content-menu[open],.library-tools[open]').forEach(menu=>{if(!menu.contains(event.target)||event.target.closest('button,input[type="file"]'))menu.open=false})});
document.addEventListener('keydown',event=>{if(event.key!=='Escape')return;const menu=event.target.closest('.content-menu[open],.library-tools[open]');if(menu){event.preventDefault();menu.open=false;menu.querySelector('summary').focus()}});
function masteryStars(status,item=null){const level=Math.max(1,masteryOrder.indexOf(status)+1);if(!item)return `<span class="mastery-stars" role="img" aria-label="${statusText[status]}，五颗星中的 ${level} 颗"><span aria-hidden="true">${masteryOrder.map((_,index)=>`<i class="${index<level?'lit':''}">★</i>`).join('')}</span></span>`;return `<span class="mastery-stars interactive" role="radiogroup" aria-label="设置 ${esc(item.term)} 的掌握度">${masteryOrder.map((key,index)=>`<button type="button" data-mastery-star data-item-id="${item.id}" data-status="${key}" role="radio" aria-checked="${key===status}" aria-label="${index+1} 星，${statusText[key]}" title="${statusText[key]}"><i class="${index<level?'lit':''}" aria-hidden="true">★</i></button>`).join('')}</span>`}
function masteryBoost(item){const from=statusText[item.status]?item.status:'new',to=masteryBoostTarget[from];if(!to)return `<span class="mastery-boost-wrap"><span class="mastery-boost is-complete" role="img" aria-label="${esc(item.term)} 已达到最高掌握度"><span class="mastery-boost-fill"></span><span class="mastery-boost-label">已到最高档</span><span class="mastery-boost-thumb">${icon('check')}</span></span><small>已掌握</small></span>`;const jump=masteryOrder.indexOf(to)-masteryOrder.indexOf(from);return `<span class="mastery-boost-wrap"><span class="mastery-boost" data-mastery-boost data-item-id="${item.id}" data-from="${from}" data-to="${to}" role="slider" tabindex="0" aria-label="斩词：把 ${esc(item.term)} 从${statusText[from]}提升到${statusText[to]}" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0" aria-valuetext="尚未斩词"><span class="mastery-boost-fill"></span><span class="mastery-boost-label">向右斩词 · +${jump} 档</span><span class="mastery-boost-thumb">${icon('chevron')}</span><span class="boost-sparks" aria-hidden="true"><i></i><i></i><i></i></span></span><small>${statusText[from]} → ${statusText[to]}</small></span>`}
function reviewMasteryPanel(item){return `<div class="review-mastery"><div><strong>斩词提档</strong><small>每次提升一档，斩词后直接继续。</small></div>${masteryBoost(item)}</div>`}
const esc=v=>String(v??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
const qs=o=>new URLSearchParams(Object.entries(o).filter(([,v])=>v!==''&&v!=null)).toString();
const normalizeEnglish=v=>v.trim().toLowerCase().replace(/\s+/g,' ');
async function api(path,options={}){const response=await fetch(path,{...options,headers:{...(options.body instanceof Blob?{}:{'Content-Type':'application/json'}),...(options.headers||{})}});if(!response.ok){let message='本地服务请求失败。';try{message=(await response.json()).error.message}catch{}throw new Error(message)}return response.status===204?null:response.json()}
const pageMotion=createPageMotion(main,api);
const academicCategories=createAcademicCategories({state,api,esc,openDialog,closeDialog,notify,renderLibrary,routeTo,qs,syncCaptureForm,showDetail});
const contentMoves=createContentMoves({api,esc,openDialog,closeDialog,notify,routeTo,state,dialogBody});
function notify(message){toast.textContent=message;toast.classList.add('show');clearTimeout(notify.timer);notify.timer=setTimeout(()=>toast.classList.remove('show'),2400)}
function openDialog(html){dialogBody.innerHTML=html;if(!dialog.open)dialog.showModal()}
function closeDialog(){dialog.close();dialogBody.innerHTML='';dialog.classList.remove('is-drawer')}
// The error map's full list reuses the one dialog the app already owns, laid out as a right-hand
// sheet. Close paths are the ones already wired for every dialog: the button, the backdrop and Esc.
function openDrawer(html){dialog.classList.add('is-drawer');openDialog(html)}
// One tooltip for every chart on the page. It is positioned with a transform on a fixed layer so
// showing it can never reflow the card underneath, and the markup it prints comes from the
// author's own escaped HTML in `data-tip` rather than from the browser's default title bubble.
const chartTip=document.createElement('div');
chartTip.className='chart-tip';chartTip.setAttribute('role','tooltip');chartTip.hidden=true;
document.body.append(chartTip);
function showChartTip(target){
  const html=target.getAttribute('data-tip');
  if(!html)return;
  chartTip.innerHTML=`<div class="chart-tip-body">${html}</div>`;
  chartTip.hidden=false;
  const box=target.getBoundingClientRect(),tipBox=chartTip.getBoundingClientRect();
  const left=Math.max(10,Math.min(box.left+box.width/2-tipBox.width/2,innerWidth-tipBox.width-10));
  const above=box.top-tipBox.height-10;
  chartTip.style.transform=`translate(${Math.round(left)}px, ${Math.round(above<8?box.bottom+10:above)}px)`;
  chartTip.classList.add('show');
}
function hideChartTip(){chartTip.classList.remove('show');chartTip.hidden=true}
document.addEventListener('pointerover',event=>{const target=event.target.closest?.('[data-tip]');if(target)showChartTip(target)});
document.addEventListener('pointerout',event=>{const target=event.target.closest?.('[data-tip]');if(target&&!target.contains(event.relatedTarget))hideChartTip()});
window.addEventListener('scroll',hideChartTip,{passive:true});
const motivationText={
  general:[
    '不用赶着变厉害，持续回来就已经很了不起。',
    '今天愿意学一点，未来就多一分从容。',
    '语言的成长很安静，但每一步都会留下来。',
    '给自己一点时间，熟练本来就是慢慢发生的。',
    '不必和别人比较，只要比昨天多懂一点。',
    '专注眼前这一小步，远处的路会自然展开。',
    '偶尔忘记很正常，重新想起就是一次加固。',
    '保持好奇，新的表达会在需要时找到你。',
    '学习可以轻一点，但每一次都认真一点。',
    '今天的耐心，会变成以后开口时的底气。',
    '把难题拆小，进步就会重新变得可见。',
    '哪怕只学几分钟，也是在照顾长远的自己。',
    '允许自己慢慢来，真正的掌握不需要表演。',
    '每个曾经陌生的词，都可能成为日后的熟人。',
    '状态有高低，愿意开始就值得肯定。',
    '不求一次完美，只求下一次更熟悉。',
    '学到的东西会沉淀，不必时时证明它存在。',
    '今天留下一点印象，明天就有地方继续生长。',
    '越愿意主动回忆，知识就越愿意留下。',
    '把注意力放回此刻，完成眼前这一小段。',
    '真正的进步，常藏在那些普通的练习里。',
    '给困难一点耐心，也给自己一点信心。',
    '词汇不是清单，是你逐渐打开的表达空间。',
    '今天学到哪里都可以，重要的是确实走过。',
    '把一个词真正想起来，比匆匆看过一页更有收获。',
    '留一点余地给好奇心，学习就会多一点乐趣。',
    '今天的五分钟，也可以是明天流畅表达的起点。',
    '记忆有时会绕路，但每次重逢都在缩短距离。',
    '把已经会的用起来，把还不会的慢慢带上。',
    '遇到难词，先和它打个照面，下次再靠近一点。',
    '学会一个贴切的词，就多了一种说清自己的办法。',
    '你不需要每天都满格，能继续就有新的可能。'
  ],
  add:[
    '今天收下的词，会在未来某次表达里亮起来。',
    '先记下一词，日后就多一种准确表达。',
    '把刚遇见的词留下，理解便有了回来的路。',
    '每一次认真记录，都在为流利积攒材料。',
    '词义写得清楚，下一次回忆就更轻松。',
    '一条好例句，能让新词真正住进语境里。',
    '不必一次记牢，先把值得学的词安顿好。',
    '今天多收一个词，明天就多一个选择。',
    '记录不是终点，而是熟悉一个词的开始。',
    '把此刻的疑问记下，留给未来的自己解答。',
    '认真整理一个词，也是在整理自己的表达。',
    '慢慢丰富词库，语言会一点点变得顺手。'
  ],
  edit:[
    '认真整理一次，记忆就多一条清晰的路。',
    '补全一点信息，下一次理解就少一点迟疑。',
    '把模糊处写清楚，记忆也会跟着变清楚。',
    '好的词条会生长，今天只是让它更完整。',
    '改准一个释义，比匆忙记下十个更可靠。',
    '例句越贴近自己，这个词就越容易留下。',
    '整理不是返工，是让知识真正变得可用。',
    '为词条补一块拼图，也为表达补一条路。',
    '细小的修正，会在下一次回忆时帮到你。',
    '把容易混淆的地方标清，复习会更有方向。',
    '今天修正的细节，会变成明天的笃定。',
    '让每条记录都简明、准确，也更像你自己。'
  ],
  library:[
    '你保存的不只是词汇，也是理解世界的新入口。',
    '词库不必庞大，常回来走走才会越来越熟。',
    '每个词都有来处，也会在新的语境里再见。',
    '翻一翻旧词，常常能发现新的理解。',
    '真正属于你的词库，会留下你的阅读轨迹。',
    '看见积累，也别忘了挑几条重新认识。',
    '会用的词，往往来自一次次不着急的重逢。',
    '从熟悉到会用，中间只差几次主动回忆。',
    '词条在这里排好队，等你把它们带进表达。',
    '偶尔整理词库，也是在整理自己的知识地图。',
    '留下重要的，复习需要的，删去不再合适的。',
    '每一次回看，都让这些词更像你的词。'
  ],
  review:[
    '记不住不是退步，它只是在提示下一步练哪里。',
    '先试着想，再看答案，记忆才真正参与进来。',
    '答错一次不可怕，它让下一次复习更有方向。',
    '今天不求全会，只求比开始时多记住一点。',
    '停顿一下再回答，也是在认真训练回忆。',
    '熟悉感不等于会用，主动想起才算真的掌握。',
    '每次费力想起，都是记忆正在变结实。',
    '把容易的练稳，把模糊的再见一面。',
    '不用和速度较劲，准确想起更重要。',
    '重复不是原地踏步，而是在加深通往答案的路。',
    '今天愿意再想一次，明天就会更顺一点。',
    '如实判断掌握程度，复习才能真正帮到你。'
  ],
  insights:[
    '别只看数字，也看见自己一次次回到这里。',
    '稳定的小步，往往比偶尔的冲刺走得更远。',
    '数据记录了投入，却定义不了你的上限。',
    '有起伏很正常，愿意回来就是新的开始。',
    '今天的几次练习，也在悄悄改变长期曲线。',
    '看看哪里在进步，也看看哪里值得再照顾。',
    '连续并非唯一答案，重新开始同样有力量。',
    '数字是路标，不是压力；用它找到下一步。',
    '掌握得慢一点，也可以掌握得更扎实。',
    '每一次真实作答，都让学习路线更清楚。',
    '积累看似安静，时间会替它说明分量。',
    '回顾是为了看清方向，不是为了苛责过去。'
  ],
  done:[
    '完成不必很大，今天向前一点就很好。',
    '这一轮已经结束，记忆却还在慢慢生长。',
    '把今天会的带走，把模糊的留给下次相见。',
    '小小的完成，也值得认真算进进步里。',
    '你刚刚练过的每一次回忆，都不会白费。',
    '先停在这里也很好，学习需要呼吸的间隔。',
    '完成一轮不是句号，而是下一次更轻松的铺垫。',
    '今天的投入已经留下痕迹，可以安心收尾。',
    '记住多少都算收获，诚实作答尤其可贵。',
    '给自己一点肯定，再带着余裕继续前进。',
    '一次一小轮，词汇会慢慢变成自然反应。',
    '今天已经比开始练习时，多走了一段路。'
  ]
};
function localDayNumber(date=new Date()){return Math.floor(Date.UTC(date.getFullYear(),date.getMonth(),date.getDate())/86400000)}
function dailyMotivation(key,date=new Date()){const contextual=motivationText[key]||motivationText[state.route]||[],messages=[...motivationText.general,...contextual];const keyOffset=[...String(key)].reduce((total,char)=>total+char.charCodeAt(0),0);return messages[(localDayNumber(date)+keyOffset)%messages.length]}
function pageHead(kicker,title,subtitle='',actions=''){const key=String(kicker).toLowerCase(),encouragement=dailyMotivation(key);return `<div class="page-head"><div class="page-title-copy">${kicker?`<span class="page-kicker">${esc(kicker)}</span>`:''}<h1>${esc(title)}</h1>${subtitle?`<p>${esc(subtitle)}</p>`:''}</div><div class="page-head-side">${encouragement?`<div class="focus-note">${icon('sparkles')}<span><small>给今天的你</small>${esc(encouragement)}</span></div>`:''}${actions}</div></div>`}
function button(label,action,kind=''){return `<button class="btn ${kind}" type="button" data-action="${action}">${label}</button>`}
// Statistics render as plain text first and roll into place once mounted — see counter.js.
function counter(value){const text=String(Number(value)||0);return `<span class="counter" data-counter="${text}">${text}</span>`}
function formatDate(value,full=false){if(!value)return '—';const d=new Date(value);return full?`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`:`${String(d.getMonth()+1).padStart(2,'0')}/${String(d.getDate()).padStart(2,'0')}`}
// Square-root scaling retains low-activity days without crowding typical days into the darkest levels.
function activityLevel(score,maxScore){if(!score)return 0;const normalized=Math.sqrt(score/Math.max(1,maxScore));return Math.max(1,Math.min(12,Math.ceil(normalized*12)))}
function activityColor(level){if(!level)return '#e9ede8';const intensity=(level-1)/11,saturation=Math.round(32+intensity*10),lightness=Math.round(87-intensity*46);return `hsl(108 ${saturation}% ${lightness}%)`}
async function initBookSproutEyes(){
  const image=main.querySelector('.unit-art img');
  if(!image)return;
  try{
    const response=await fetch('assets/book-sprout.svg');
    if(!response.ok||!image.isConnected)return;
    const svg=new DOMParser().parseFromString(await response.text(),'image/svg+xml').documentElement;
    if(svg.localName!=='svg'||!image.isConnected)return;
    const eyes=[...svg.querySelectorAll('ellipse')].filter(eye=>eye.getAttribute('cy')==='89'&&['98','140'].includes(eye.getAttribute('cx')));
    if(eyes.length!==2)return;
    svg.classList.add('book-sprout-art');
    svg.setAttribute('aria-hidden','true');
    eyes.forEach(eye=>eye.classList.add('book-sprout-eye'));
    image.replaceWith(svg);
  }catch{ /* Keep the static illustration if the local asset is unavailable. */ }
}
const reducedMotion=window.matchMedia('(prefers-reduced-motion: reduce)');
document.addEventListener('pointermove',event=>{
  if(reducedMotion.matches||event.pointerType==='touch')return;
  const svg=main.querySelector('.book-sprout-art');
  if(!svg)return;
  const rect=svg.getBoundingClientRect(),centerX=rect.left+rect.width*119/240,centerY=rect.top+rect.height*89/190;
  const dx=Math.max(-4,Math.min(4,(event.clientX-centerX)/38)),dy=Math.max(-2.5,Math.min(2.5,(event.clientY-centerY)/42));
  svg.querySelectorAll('.book-sprout-eye').forEach(eye=>eye.setAttribute('transform',`translate(${dx.toFixed(2)} ${dy.toFixed(2)})`));
});
function activityGrid(data){
  const maxScore=Math.max(1,...data.series.map(point=>Number(point.score)||0));
  const first=new Date(`${data.series[0].date}T12:00:00`),leading=(first.getDay()+6)%7,cells=[...Array(leading).fill(null),...data.series];
  while(cells.length%7)cells.push(null);
  const weeks=cells.length/7,months=[];
  let lastMonth='';
  data.series.forEach((point,index)=>{
    const date=new Date(`${point.date}T12:00:00`),month=`${date.getMonth()+1}月`;
    if(month!==lastMonth){months.push({month,week:Math.floor((leading+index)/7)+1});lastMonth=month}
  });
  // The year fills in cell by cell rather than fading in as one block: the delay is spread over
  // roughly a quarter of a second and never exceeded, so the whole card is settled well inside
  // the time the rest of the page needs for its own entrance.
  const dayCell=(cell,index)=>{
    if(!cell)return '<span class="activity-cell filler" aria-hidden="true"></span>';
    if(!cell.score)return '<span class="activity-cell level-0" aria-hidden="true"></span>';
    const level=activityLevel(cell.score,maxScore),expressionReads=Number(cell.expression_reads)||0;
    const accuracy=cell.graded===undefined?'<span>正确率需更新统计服务后显示</span>':cell.graded?`<span>正确率 ${Math.round(cell.correct/cell.graded*100)}%（作答 ${cell.graded} 次）</span>`:'<span>当天没有判定对错的作答</span>';
    return `<span class="activity-cell level-${level}" style="background-color:${activityColor(level)};--cell-delay:${Math.round(index/cells.length*260)}ms" data-tip="<b>${cell.date}</b><span>新增 ${cell.added} 条 · 单词练习 ${cell.reviews} 次</span><span>表达阅读 ${expressionReads} 次</span>${accuracy}<span>活跃值 ${cell.score}</span>" aria-label="${cell.date}，新增 ${cell.added} 条，单词练习 ${cell.reviews} 次，表达阅读 ${expressionReads} 次，活跃值 ${cell.score}"></span>`;
  };
  return `<section class="activity-card" aria-labelledby="activity-title" data-enter style="--enter-delay:210ms"><div class="activity-head"><div><span class="eyebrow">MEMORY RHYTHM</span><h2 id="activity-title">学习活跃</h2><p>记录词汇录入、单词练习与表达阅读；颜色越深，表示当天投入越多。</p></div><div class="activity-summary"><strong>${counter(data.current_streak)}</strong><span>连续活跃天数</span><small>近一年活跃 ${counter(data.active_days)} 天 · 最长 ${counter(data.longest_streak)} 天</small></div></div><div class="activity-scroll" tabindex="0" aria-label="近一年每日学习活跃记录"><div class="activity-months" style="--weeks:${weeks}">${months.map(x=>`<span style="grid-column:${x.week}">${x.month}</span>`).join('')}</div><div class="activity-map"><div class="activity-weekdays" aria-hidden="true"><span>一</span><span></span><span>三</span><span></span><span>五</span><span></span><span>日</span></div><div class="activity-grid" style="--weeks:${weeks}">${cells.map(dayCell).join('')}</div></div></div><div class="activity-legend"><span>少</span>${Array.from({length:13},(_,level)=>`<i class="activity-cell level-${level}" style="background-color:${activityColor(level)}" aria-hidden="true"></i>`).join('')}<span>多</span><small>每个非零活跃日都会着色，并按相对投入使用 12 级连续梯度。</small></div></section>`;
}
// Every chart on the statistics page is summed from the same window, so the aggregation accepts
// the fields each view needs instead of silently dropping the accuracy counters.
function zeroed(keys){const totals={};keys.forEach(key=>{totals[key]=0});return totals}
function monthlyStats(series,keys=['added','reviews']){const months=new Map();series.forEach(point=>{const key=point.date.slice(0,7);if(!months.has(key))months.set(key,{date:`${key}-01`,...zeroed(keys)});const month=months.get(key);keys.forEach(field=>{month[field]+=point[field]||0})});return [...months.values()]}
function bucketStats(series,size,keys=['added','reviews']){const buckets=[];for(let index=0;index<series.length;index+=size){const points=series.slice(index,index+size),first=points[0],last=points.at(-1),from=formatDate(first.date),to=formatDate(last.date),label=from.slice(0,3)===to.slice(0,3)?`${from}–${to.slice(3)}`:`${from}–${to}`;const totals=zeroed(keys);keys.forEach(field=>{totals[field]=points.reduce((sum,point)=>sum+(point[field]||0),0)});buckets.push({date:last.date,label,...totals})}return buckets}
function navActive(){document.querySelectorAll('a[data-route], button[data-route]').forEach(a=>{const active=a.dataset.route===state.route;a.classList.toggle('active',active);if(active)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current')})}
function connectFieldLabels(){main.querySelectorAll('[data-scope],[data-mode]').forEach(x=>x.setAttribute('aria-pressed',String(x.classList.contains('selected'))));main.querySelectorAll('.field').forEach((field,index)=>{const label=field.querySelector('label'),control=field.querySelector('input:not([type="hidden"]),textarea,select');if(label&&control){const stableId=control.name==='phonetic'?'item-phonetic':(control.id||control.name||`field-${index}`);control.id=stableId;label.htmlFor=control.id}})}
new MutationObserver(connectFieldLabels).observe(main,{childList:true,subtree:true});
new MutationObserver(()=>mountCounters(main)).observe(main,{childList:true,subtree:true});
new MutationObserver(()=>mountCharts(main)).observe(main,{childList:true,subtree:true});
mountAmbientMotion(main);
function routeTo(route){if(route.split('?')[0]==='add'&&state.route!=='add')state.captureReturn=['library','reading','academic'].includes(state.route)?{route:state.route,filters:{...state.filters}}:null;const next=`#${route}`;if(state.expressionReader)persistExpressionState().catch(()=>{});state.review=null;if(location.hash===next)render();else location.hash=route}
function returnToLibrary(item=null,detail=false){const saved=state.captureReturn,collection=item?.collection||document.querySelector('[name=collection]')?.value,route=saved?.route||(collection==='academic'?'academic':'reading');state.libraryRestore={route,filters:saved?.filters||{...state.filters,page:1,item_group:item?.item_type==='sentence'?'sentence':'vocabulary'}};state.captureReturn=null;const query=qs({category_id:route==='academic'?state.libraryRestore.filters.category_id:null,detail:detail?item.id:null});routeTo(`${route}${query?'?'+query:''}`)}
document.addEventListener('click',event=>{const globalReview=event.target.closest('[data-action="review-global"]');if(!globalReview)return;event.preventDefault();event.stopImmediatePropagation();routeTo('review?scope=random')},true);
document.addEventListener('click',event=>{const action=event.target.closest('[data-action="go-study"],[data-action="study-next"]');if(!action)return;event.preventDefault();event.stopImmediatePropagation();if(action.dataset.action==='go-study')return routeTo('review?scope=study');const r=state.review;if(!r||r.scope!=='study'||!r.answered||r.preview)return;r.previous={index:r.index,input:r.input,correct:r.correct};r.index++;r.answered=false;r.input='';r.correct=null;renderReviewCard()},true);
document.addEventListener('click',event=>{const action=event.target.closest('[data-action="review-previous"],[data-action="review-continue"]');if(!action)return;event.preventDefault();event.stopImmediatePropagation();if(action.dataset.action==='review-previous')showPreviousReview();else continueReview()},true);
document.addEventListener('click',event=>{if(event.target.closest('[data-action="retry-wrong"]')&&state.review){state.review.previous=null;state.review.preview=false}},true);
document.addEventListener('click',async event=>{const reset=event.target.closest('[data-action="reset-round"]');if(!reset)return;event.preventDefault();event.stopImmediatePropagation();try{await api('/api/review-round/reset',{method:'POST',body:JSON.stringify({mode:state.reviewSetup.mode,item_type:state.reviewSetup.itemType,collection:state.reviewSetup.collection,category_id:state.reviewSetup.categoryId})});notify(`${reviewTypeText[state.reviewSetup.itemType]} · ${modeText[state.reviewSetup.mode]}的新一轮已开始`)}catch(error){notify(error.message)}},true);
document.addEventListener('click',event=>{const choice=event.target.closest('[data-review-type]');if(!choice||!state.reviewSetup)return;event.preventDefault();event.stopImmediatePropagation();selectReviewContent(choice.dataset.reviewCollection,choice.dataset.reviewType)},true);
document.addEventListener('click',event=>{
  const strategy=event.target.closest('[data-strategy]');
  if(strategy&&state.reviewSetup){event.preventDefault();event.stopImmediatePropagation();state.reviewSetup.strategy=strategy.dataset.strategy;document.querySelectorAll('[data-strategy]').forEach(button=>{const selected=button===strategy;button.classList.toggle('selected',selected);button.setAttribute('aria-pressed',String(selected))});return}
  const scope=event.target.closest('[data-scope]');
  if(!scope||!state.reviewSetup||!document.querySelector('.review-studio'))return;
  event.preventDefault();event.stopImmediatePropagation();state.reviewSetup.scope=scope.dataset.scope;
  const isStudy=scope.dataset.scope==='study';
  document.querySelector('.page-head .page-kicker').textContent=isStudy?'STUDY':'REVIEW';
  document.querySelector('.page-head h1').textContent=isStudy?'先练一练刚加入的内容':'为这次复习定一条清晰路线';
  document.querySelector('.page-head .page-title-copy p').textContent=isStudy?'选择内容、数量和练法，过程不记录对错。':'选择单词与固定搭配一起复习，或单独练习单词、短语、长句。';
  if(scope.dataset.scope==='today')state.reviewSetup.mode='recall';
  document.querySelectorAll('[data-scope]').forEach(button=>{const selected=button===scope;button.classList.toggle('selected',selected);button.setAttribute('aria-pressed',String(selected))});
  document.querySelectorAll('[data-mode]').forEach(button=>{const selected=button.dataset.mode===state.reviewSetup.mode;button.classList.toggle('selected',selected);button.setAttribute('aria-pressed',String(selected))});
  syncReviewSetupUi(scope.dataset.scope);
},true);
async function render(){
  const hash=location.hash||'#today';
  const requested=hash.slice(1).split('?')[0];
  const route=['today','review','library','reading','academic','expressions','daily','add','stats'].includes(requested)?requested:'today';
  if(['library','reading','academic'].includes(route)&&state.route!==route){state.filters=state.libraryRestore?.route===route?state.libraryRestore.filters:{...state.filters,page:1,q:'',source:'',tag:'',status:'',category_id:'',item_group:'vocabulary',item_type:''};state.libraryRestore=null;state.organize=false;state.categoryOrganize=false;state.selected.clear();state.editingGroup=null}
  if(route==='academic'){const p=new URLSearchParams(hash.split('?')[1]);if(p.has('category_id'))state.filters.category_id=p.get('category_id');else if(state.route==='academic'&&!p.has('detail'))state.filters.category_id='';}
  state.route=route;hideChartTip();navActive();
  return pageMotion.navigate({hash,
    onCommit:()=>{document.body.dataset.route=route},
    onError:error=>{main.innerHTML=`<div class="empty"><h2>暂时无法加载</h2><p>${esc(error.message)}</p>${button('重试','retry','primary')}</div>`}
  },async ctx=>{
    if(route==='today')return renderToday(ctx);
    if(route==='add')return renderAdd(null,ctx);
    if(['library','reading','academic'].includes(route))return renderLibrary(ctx);
    if(route==='expressions')return renderExpressions(ctx);
    if(route==='daily')return renderDailyExpressions({main,api,request:ctx.request,isCurrent:ctx.isCurrent,commit:ctx.commit,esc,icon,contentActions,pageHead,openDialog,closeDialog,notify,contentMoves});
    if(route==='review')return renderReview(ctx);
    if(route==='stats')return renderStats(ctx);
  });
}
async function renderToday(ctx=pageMotion.current()){
  const [m,recallRound,spellingRound,mistakes,expressions]=await Promise.all([ctx.request('/api/dashboard'),ctx.request('/api/review-round?mode=recall'),ctx.request('/api/review-round?mode=zh_to_en'),ctx.request('/api/reviews?scope=mistakes&limit=100'),ctx.request('/api/expression-summary')]);
  return ctx.commit(()=>{main.innerHTML=`<div class="home-top"><span class="course-label"><span class="language-badge">${icon('book')}</span><span><small>PERSONAL ENGLISH</small>我的英语练习</span></span><a class="collection-count" href="#library"><strong>${m.total}</strong> 个词条 <span>已收藏</span></a></div>
  <div class="learning-layout"><section class="learning-column" aria-label="学习路径">
    <div class="unit-banner"><div class="unit-banner-copy"><p>今天的学习航线</p><h1>让单词成为你的老朋友</h1><span class="unit-subtitle">坚持一点点，遇见更大的自己。</span><div class="unit-meta"><span>${icon('today')} 今日录入 <b>${m.added_today}</b></span><span>${icon('bolt')} 本周练习 <b>${m.learned_this_week}</b></span></div></div><div class="unit-art" aria-hidden="true"><img src="assets/book-sprout.svg" alt=""><span>好词<br>让生活更丰富<br>一点</span></div></div>
    <div class="path-intro"><h2>今天，从轻松回忆开始</h2><p>选一种练法，走好自己的一小步。</p></div>
    <div class="learning-path">
      <svg class="path-route" viewBox="0 0 900 180" preserveAspectRatio="none" aria-hidden="true" focusable="false"><path class="path-route-shadow" d="M 145 98 C 270 98 300 40 450 40 C 600 40 630 98 755 98"/><path class="path-route-line" d="M 145 98 C 270 98 300 40 450 40 C 600 40 630 98 755 98"/></svg>
      <div class="path-grid">
        <div class="path-step step-recall"><div class="start-bubble">从这里开始</div><button class="path-node green ${recallRound.remaining?'':'is-finished'}" data-route="review?scope=random&mode=recall&start=1" aria-label="直接开始遮罩自评"><span>${icon('recall')}</span><em>${roundCaption(recallRound)}</em></button><h3>想一想中文</h3><p>看英文 · 揭晓 · 判断对错</p><small>${recallRound.remaining?`遮罩自评还可练 ${recallRound.remaining} 条`:'遮罩自评今日已完成'}</small></div>
        <div class="path-step step-spelling"><button class="path-node blue ${spellingRound.remaining?'':'is-finished'}" data-route="review?scope=random&mode=zh_to_en&start=1" aria-label="直接开始英文拼写"><span>${icon('spelling')}</span><em>${roundCaption(spellingRound)}</em></button><h3>把英文拼出来</h3><p>看中文，练主动回忆</p><small>${spellingRound.remaining?`拼写练习还可练 ${spellingRound.remaining} 条`:'拼写练习今日已完成'}</small></div>
        <div class="path-step step-mistakes"><button class="path-node gold ${mistakes.items.length?'':'is-finished'}" data-route="review?scope=mistakes&mode=cloze&start=1" aria-label="直接开始错词重练"><span>${icon(mistakes.items.length?'retry':'check')}</span><em>${mistakes.items.length||'完成'}</em></button><h3>和错词再见一面</h3><p>多练一次，就更熟一点</p><small>${mistakes.items.length?`${mistakes.items.length} 条错词等你再练`:'目前没有待重练错词'}</small></div>
      </div>
      <div class="path-companion" aria-hidden="true"><div class="book-buddy"><i></i><b></b></div><span>你比昨天<br>又多会了一点！</span></div>
    </div>
    <div class="path-footer"><span>刚加入的单词，先轻松练一遍</span><div class="actions">${button('学习模式 · 练新词','go-study','light')}${button('查看全部复习方式','go-review','light')}</div></div>
  </section><aside class="learning-aside">
    <section class="daily-mission"><div class="section-head"><div><span class="card-kicker">TODAY</span><h2>今天的小任务</h2></div><span class="mini-sun">${icon('sun')}</span></div><p>从整个词库随机抽查，给记忆一次短而有效的唤醒。</p><div class="mission-fact"><span class="mission-icon">${icon('globe')}</span><div><strong>全局复习</strong><small>从 ${m.total} 条词条中智能抽取</small></div></div>${button('开始全局复习','review-global','home-action mission')}</section>
    <section class="growth-panel ${m.added_today?'has-today-review':''}"><div class="section-head growth-head"><div><span class="card-kicker">PROGRESS</span><h2>每一点进步，都算数</h2></div><a href="#stats" class="stats-link">学习统计 <span>→</span></a></div><div class="growth-row"><span class="growth-icon blue">${icon('pencil')}</span><span>今天录入</span><strong>${m.added_today}</strong></div><div class="growth-row"><span class="growth-icon gold">${icon('bolt')}</span><span>本周练习</span><strong>${m.learned_this_week}</strong></div><div class="growth-row"><span class="growth-icon green">${icon('mastered')}</span><span>已经掌握</span><strong>${m.mastered}</strong></div>${m.added_today?button(`复习今日单词 · ${m.added_today}`,'review-today','home-action progress'):''}</section>
    <section class="pocket-note"><span>${icon('add')}</span><div><span class="card-kicker">CAPTURE</span><h2>遇见新单词了？</h2><p>把它收进口袋，下次就能练。</p></div>${button('添加单词或词组','go-add','home-action capture')}</section>
  </aside></div>${expressionHomeCard(expressions)}`;
  initBookSproutEyes();
  });
}
function roundCaption(round){return round.remaining?`${round.remaining} 条`:(round.total?'完成':'空')}
function wordRow(item){return `<div class="word-row" data-action="detail" data-id="${item.id}" tabindex="0"><span class="word-index">${String(item.id).padStart(2,'0')}</span><div class="term"><strong>${esc(item.term)}</strong><small>${esc(item.chinese_meaning)}</small></div><div class="meta">${itemTypeText[item.item_type]||'词条'}</div><div><span class="status">${esc(statusText[item.status])}</span></div></div>`}
function pastePanel(){return `<section class="paste-import"><div><span class="eyebrow">QUICK CAPTURE</span><h2>从词典或翻译软件粘贴</h2><p>支持 Google AI / 词典、Cambridge、Merriam-Webster、Dictionary.com、Collins、Britannica，也可识别 Google 翻译、DeepL、有道等双语文本。中文只会从粘贴内容中提取，不会联网猜译。入库后词库列表只显示英文和中文；近义词会独立保存在详情中。</p></div><textarea id="dictionary-paste" aria-label="粘贴词典或翻译内容" placeholder="粘贴一条完整的词典解释，或“英文 + 中文翻译”…"></textarea><div class="actions"><button type="button" class="btn primary" data-action="clipboard-paste">粘贴并识别</button><button type="button" class="btn light" data-action="parse-dictionary">识别已输入内容</button><span id="parse-status" class="hint" role="status"></span></div></section>`}

function captureKindSwitch(active,locked=false){
  const choices=[['general','阅读写作','要背的单词与固定搭配','add?collection=general'],['academic','学术词汇','专业课术语与表达','add?collection=academic'],['expression','阅读素材','话题表达、例句与范文','add?kind=expression'],['daily','生活口语','口语、俚语与习语','add?kind=daily']];
  return `<section class="capture-board-picker" aria-label="添加到哪个版块"><p class="capture-board-title">01 · 添加到哪个版块？</p><div class="capture-kind-switch">${choices.map(([key,label,hint,route])=>`<button type="button" class="${key===active?'active':''}" data-route="${route}" aria-pressed="${key===active}" ${locked?'disabled':''}><span>${label}</span><small>${hint}</small></button>`).join('')}</div><p class="capture-board-note">总词库汇总阅读写作与学术词汇；阅读素材和生活口语独立收录，不混入词库背词。${locked?'编辑时保留所属版块；移动内容请使用详情中的“移动到”。':''}</p></section>`;
}
async function renderAdd(item=null,ctx=pageMotion.current()){const params=new URLSearchParams(ctx.hash.split('?')[1]);if(!item&&params.get('kind')==='daily')return renderDailyCapture(ctx);if(!item&&(params.get('kind')==='expression'||params.get('expression')))return renderExpressionForm(params.get('expression'),ctx);if(!item&&params.get('edit'))item=await ctx.request(`/api/items/${params.get('edit')}`);const requestedType=['word','phrase','sentence'].includes(params.get('type'))?params.get('type'):'word',initialType=item?.item_type||requestedType,collection=item?.collection||(params.get('collection')==='academic'?'academic':'general');const categoryData=await ctx.request('/api/academic-categories');if(!ctx.isCurrent())return;academicCategories.setData(categoryData);const categoryId=item?item.academic_category_id||'':params.get('category_id')||'';return ctx.commit(()=>{main.innerHTML=`${pageHead(item?'EDIT':'ADD',item?'编辑词条':collection==='academic'?'添加学术词汇':'添加阅读写作词汇',item?'录入时间不会改变，复习历史也会保留。':'先选择版块，输入英文后自动识别内容类型。')}${captureKindSwitch(collection,!!item)}<div id="add-success" class="add-success" role="status" aria-live="polite"></div><form id="item-form" class="form">${captureChoices(collection,initialType,!!item)}${academicCategories.form(categoryId)}${pastePanel()}<div class="form-section"><div class="field-grid"><div class="field"><label>英文词条 *</label><input name="term" required maxlength="240" value="${esc(item?.term||'')}" placeholder="例如 sparse / play a crucial role in / The figure saw a gradual decline…" autocomplete="off"></div><div class="field"><label>中文释义 *</label><input name="chinese_meaning" required maxlength="1000" value="${esc(item?.chinese_meaning||'')}"></div><div class="field full subtle-field"><label>同义词 / 替换词</label><input name="synonyms" value="${esc((item?.synonyms||[]).join('，'))}" placeholder="例如 scarce，limited，thinly spread（用逗号分隔）"><small>独立保存，用于搜索和详情；不在词库列表中显示。</small></div></div></div><button type="button" class="btn text" data-action="toggle-more">${item?'收起 / 展开更多资料':'填写更多资料'} <span>↘</span></button><div class="more-fields ${item||collection==='academic'?'open':''}" id="more-fields"><div class="form-section field-grid"><div class="field"><label>音标</label><input name="phonetic" value="${esc(item?.phonetic||'')}"></div><div class="field"><label>词性</label><input name="part_of_speech" value="${esc(item?.part_of_speech||'')}"></div><div class="field full"><label>英文释义</label><textarea name="english_definition">${esc(item?.english_definition||'')}</textarea></div><div class="field full"><label>原句</label><textarea name="source_sentence">${esc(item?.source_sentence||'')}</textarea></div><div class="field full"><label>自己的例句</label><textarea name="own_sentence">${esc(item?.own_sentence||'')}</textarea></div><div class="field full"><label>常见搭配</label><textarea name="collocations" placeholder="每行一条">${esc((item?.collocations||[]).join('\n'))}</textarea></div><div class="field"><label>来源 / 课程</label><input name="source" value="${esc(item?.source||'')}" placeholder="例如 IELTS Reading / 工程热力学"></div><div class="field"><label>标签</label><input name="tags" value="${esc((item?.tags||[]).join('，'))}" placeholder="用逗号分隔"></div><div class="field full"><label>备注</label><textarea name="notes">${esc(item?.notes||'')}</textarea></div><div class="field ${initialType==='sentence'?'hidden':''}" data-mastery-field><label>掌握状态</label><select name="status">${Object.entries(statusText).map(([k,v])=>`<option value="${k}" ${item?.status===k?'selected':''}>${v}</option>`).join('')}</select></div></div></div><div id="form-error" class="error"></div><div class="actions sticky-actions"><button class="btn primary" type="submit">${item?'保存修改':'保存并继续添加'}</button>${button('取消','go-library','light')}</div><input type="hidden" name="id" value="${item?.id||''}"></form>`;document.querySelector('#item-form').addEventListener('submit',saveItem);document.querySelector('#dictionary-paste').addEventListener('paste',()=>setTimeout(fillDictionaryFields,0));bindCaptureForm()});}
async function renderDailyCapture(ctx=pageMotion.current()){
  const groups=await ctx.request('/api/daily-groups');
  if(!ctx.isCurrent())return;
  return ctx.commit(()=>{
    main.innerHTML=`${pageHead('ADD','添加生活口语','收集日常说法与词汇，可以按合集一起回忆。')}${captureKindSwitch('daily')}<form id="daily-capture-form" class="form"><div class="form-section field-grid">${dailyFormFields(null,esc,groups.items)}<p id="daily-capture-error" class="error full" role="alert"></p></div><div class="actions sticky-actions"><button type="submit" class="btn primary">保存并继续添加</button><button type="button" class="btn light" data-route="daily">返回生活口语</button></div></form>`;
    const form=document.querySelector('#daily-capture-form');
    form.addEventListener('submit',async event=>{
      event.preventDefault();const submit=form.querySelector('[type="submit"]');if(submit.disabled)return;submit.disabled=true;
      const category=form.elements.category.value,groupId=form.elements.group_id.value;
      try{await api('/api/daily-expressions',{method:'POST',body:JSON.stringify(Object.fromEntries(new FormData(form)))});if(!ctx.isCurrent())return;notify('已保存到生活口语');form.reset();form.elements.category.value=category;form.elements.group_id.value=groupId;form.querySelector('#daily-capture-error').textContent='';form.elements.phrase.focus()}
      catch(error){form.querySelector('#daily-capture-error').textContent=error.message}finally{submit.disabled=false}
    });
  });
}

async function renderExpressionForm(id,ctx=pageMotion.current()){const item=id?await ctx.request(`/api/expressions/${id}`):null;return ctx.commit(()=>{main.innerHTML=`${pageHead(item?'EDIT':'ADD',item?'编辑阅读素材':'添加阅读素材',item?'阅读次数和最近阅读时间会保留。':'可直接粘贴长篇文章；空行与原始段落会原样保存。')}${captureKindSwitch('expression',!!item)}<form id="expression-form" class="form expression-form"><div class="expression-form-note"><span>${icon('book')}</span><p><strong>只收藏与阅读</strong><small>阅读素材不会进入单词复习、错词统计、掌握度或正确率。</small></p></div><div class="form-section field-grid"><div class="field"><label>内容类型 *</label><input name="content_type" list="expression-type-options" required maxlength="80" value="${esc(item?.content_type||'句式')}" placeholder="句式 / 段落 / 范文"><datalist id="expression-type-options"><option value="句式"><option value="段落"><option value="范文"></datalist><small>可直接输入新的类型，后续会自动成为筛选项。</small></div><div class="field"><label>标题 *</label><input name="title" required maxlength="240" value="${esc(item?.title||'')}" placeholder="例如：表达支持观点的句式"></div><div class="field full"><label>英文原文 *</label><textarea class="expression-long-text" name="english_text" required placeholder="粘贴英文原文；长篇范文请用空行保留自然段。">${esc(item?.english_text||'')}</textarea><small>保存时不会合并段落，也不会生成题目。</small></div><div class="field full"><label>中文翻译（可选）</label><textarea class="expression-long-text translation-input" name="chinese_text" placeholder="可稍后补充；多段翻译建议与英文段落一一对应。">${esc(item?.chinese_text||'')}</textarea></div><div class="field"><label>配图路径</label><input name="illustration_path" maxlength="500" value="${esc(item?.illustration_path||'')}" placeholder="/assets/expression-charts/line-chart.png"><small>图片保存在应用 assets 目录中。</small></div><div class="field"><label>考试类型</label><input name="exam_type" list="expression-exam-options" maxlength="80" value="${esc(item?.exam_type||'')}" placeholder="雅思 / CET-6 / 通用"><datalist id="expression-exam-options"><option value="雅思"><option value="CET-6"><option value="通用"></datalist></div><div class="field"><label>主题分类</label><input name="topic" list="expression-topic-options" maxlength="120" value="${esc(item?.topic||'')}" placeholder="例如 教育与科技"><datalist id="expression-topic-options"><option value="观点与论证"><option value="教育与科技"><option value="社会与发展"><option value="连接与过渡"><option value="生活口语"></datalist></div><div class="field"><label>自定义标签</label><input name="tags" value="${esc((item?.tags||[]).join('，'))}" placeholder="Task 2，开头，环保"></div><div class="field"><label>来源（可选）</label><input name="source" maxlength="1000" value="${esc(item?.source||'')}" placeholder="个人笔记 / 书籍 / 来源链接"></div><div class="field full"><label>个人备注（可选）</label><textarea name="notes" placeholder="记录适用场景、易混用法或整理说明。">${esc(item?.notes||'')}</textarea></div><label class="favorite-check full"><input type="checkbox" name="is_favorite" ${item?.is_favorite?'checked':''}> <span>${icon('bookmark')}保存后加入收藏</span></label></div><div id="expression-form-error" class="error"></div><div class="actions sticky-actions"><button class="btn primary" type="submit">${item?'保存修改':'保存到阅读素材'}</button><button class="btn light" type="button" data-route="expressions">返回阅读素材</button></div><input type="hidden" name="id" value="${item?.id||''}"></form>`;document.querySelector('#expression-form').addEventListener('submit',saveExpressionForm);document.querySelector('[name="title"]')?.focus()});}
async function saveExpressionForm(event){event.preventDefault();const form=event.currentTarget,data=Object.fromEntries(new FormData(form));data.tags=String(data.tags||'').split(/[，,;；]/).map(value=>value.trim()).filter(Boolean);data.is_favorite=form.elements.is_favorite.checked;const id=data.id;delete data.id;const error=document.querySelector('#expression-form-error');try{const saved=await api(id?`/api/expressions/${id}`:'/api/expressions',{method:id?'PUT':'POST',body:JSON.stringify(data)});notify(id?'阅读素材已更新':'已保存到阅读素材');state.expressionReader=null;routeTo(`expressions?read=${saved.id}`)}catch(problem){error.textContent=problem.message}}
function expressionTypeClass(type){return type==='范文'?'essay':(type==='段落'?'paragraph':'sentence')}
function expressionPreview(value,limit=185){const clean=String(value||'').replace(/\s+/g,' ').trim();return clean.length>limit?`${clean.slice(0,limit).trim()}…`:clean}
function expressionHomeCard(summary){const current=summary.continue_reading;return `<section class="expression-home-card"><div class="expression-home-copy"><span class="expression-home-mark">${icon('book')}</span><div><span class="card-kicker">EXPRESSION LIBRARY</span><h2>${current?'继续读一点表达':'把好表达收进自己的书架'}</h2><p>${current?esc(current.title):'句式、段落和范文都可以独立收藏，不加入单词复习。'}</p><div class="expression-home-facts"><span>${summary.total} 则素材</span><span>${summary.favorite_count} 则收藏</span><span>${summary.total_reads} 次阅读</span></div></div></div><div class="actions">${current?`<button class="btn primary" type="button" data-route="expressions?read=${current.id}">继续阅读</button>`:''}<button class="btn light" type="button" data-route="expressions">浏览素材</button></div></section>`}
function expressionStatsMarkup(summary){const types=summary.counts_by_type||{};const typeEntries=Object.entries(types);return `<section class="expression-stats" data-enter style="--enter-delay:320ms"><header><div><span class="eyebrow">READING COLLECTION</span><h2>阅读素材</h2><p>只记录收藏与阅读，不参与单词正确率和掌握度。</p></div><button class="btn light" type="button" data-route="expressions">打开阅读素材</button></header><div class="expression-stat-grid"><article><span>${icon('book')}</span><div><strong>${counter(summary.total)}</strong><small>素材总数</small></div></article><article><span>${icon('bookmark')}</span><div><strong>${counter(summary.favorite_count)}</strong><small>已收藏</small></div></article><article><span>${icon('recent')}</span><div><strong>${counter(summary.total_reads)}</strong><small>阅读次数</small></div></article><article class="expression-type-summary"><span>${icon('sparkles')}</span><div><strong>${typeEntries.length?typeEntries.map(([type,count])=>`${esc(type)} ${count}`).join(' · '):'尚未添加'}</strong><small>按内容类型分布</small></div></article></div>${summary.continue_reading?`<button class="expression-recent-row" type="button" data-route="expressions?read=${summary.continue_reading.id}"><span><small>最近阅读</small><strong>${esc(summary.continue_reading.title)}</strong></span><em>继续阅读 →</em></button>`:''}</section>`}
function expressionCard(item){const tone=expressionTypeClass(item.content_type);return `<article class="expression-card ${tone}"><div class="expression-card-top"><span class="expression-type ${tone}">${esc(item.content_type)}</span><button class="expression-favorite ${item.is_favorite?'active':''}" type="button" data-expression-action="favorite" data-id="${item.id}" data-favorite="${item.is_favorite?'0':'1'}" aria-pressed="${item.is_favorite}" aria-label="${item.is_favorite?'取消收藏':'收藏'} ${esc(item.title)}" title="${item.is_favorite?'取消收藏':'收藏'}">${icon('bookmark')}</button></div>${item.illustration_path?`<img class="expression-card-illustration" src="${esc(item.illustration_path)}" alt="${esc(item.title)}图表示例" loading="lazy">`:''}<h2>${esc(item.title)}</h2><p>${esc(expressionPreview(item.english_text))}</p><div class="expression-tags">${item.exam_type?`<span>${esc(item.exam_type)}</span>`:''}${item.topic?`<span>${esc(item.topic)}</span>`:''}${item.tags.slice(0,2).map(tag=>`<span>#${esc(tag)}</span>`).join('')}</div><footer><span>${item.read_count?`阅读 ${item.read_count} 次 · ${formatDate(item.last_read_at,true)}`:'尚未阅读'}</span>${contentActions(item.title,{view:{text:"阅读",attributes:`data-route="expressions?read=${item.id}"`},edit:`data-route="add?kind=expression&expression=${item.id}"`,remove:`data-expression-action="delete" data-id="${item.id}"`})}</footer></article>`}
function expressionFilterOptions(values,current,empty){return `<option value="">${empty}</option>${values.map(value=>`<option value="${esc(value)}" ${current===value?'selected':''}>${esc(value)}</option>`).join('')}`}
async function renderExpressions(ctx=pageMotion.current()){const params=new URLSearchParams(ctx.hash.split('?')[1]);const readerId=Number(params.get('read')||0);if(readerId)return renderExpressionReader(readerId,ctx);state.expressionReader=null;const query=qs({...state.expressionFilters,page_size:100});const [data,facets,summary]=await Promise.all([ctx.request(`/api/expressions?${query}`),ctx.request('/api/expression-facets'),ctx.request('/api/expression-summary')]);const current=summary.continue_reading;return ctx.commit(()=>{main.innerHTML=`${pageHead('EXPRESSION LIBRARY','阅读素材','句式 · 段落 · 范文',`<button class="btn primary" type="button" data-route="add?kind=expression">添加阅读素材</button>`)}${current?`<section class="continue-expression"><div><span class="eyebrow">CONTINUE READING</span><h2>${esc(current.title)}</h2><p>${esc(expressionPreview(current.english_text,130))}</p><div><span>${esc(current.content_type)}</span>${current.topic?`<span>${esc(current.topic)}</span>`:''}<span>上次阅读 ${formatDate(current.last_read_at,true)}</span></div></div><button class="btn primary" type="button" data-route="expressions?read=${current.id}">继续阅读</button></section>`:''}<section class="expression-filter-shelf" aria-label="阅读素材筛选"><div class="expression-search"><span>${icon('sparkles')}</span><input id="expression-search" type="search" aria-label="搜索阅读素材" value="${esc(state.expressionFilters.q)}" placeholder="搜索标题、原文、翻译、来源或标签"></div><div class="expression-filter-row"><select data-expression-filter="type" aria-label="内容类型">${expressionFilterOptions(facets.types,state.expressionFilters.type,'全部类型')}</select><select data-expression-filter="exam" aria-label="考试类型">${expressionFilterOptions(facets.exams,state.expressionFilters.exam,'全部考试')}</select><select data-expression-filter="topic" aria-label="主题分类">${expressionFilterOptions(facets.topics,state.expressionFilters.topic,'全部主题')}</select><select data-expression-filter="tag" aria-label="自定义标签">${expressionFilterOptions(facets.tags,state.expressionFilters.tag,'全部标签')}</select><label class="expression-favorite-filter"><input type="checkbox" data-expression-favorite-filter ${state.expressionFilters.favorite?'checked':''}>${icon('bookmark')}只看收藏</label><select data-expression-filter="sort" aria-label="排序"><option value="recent" ${state.expressionFilters.sort==='recent'?'selected':''}>最近阅读</option><option value="newest" ${state.expressionFilters.sort==='newest'?'selected':''}>最新添加</option><option value="oldest" ${state.expressionFilters.sort==='oldest'?'selected':''}>最早添加</option><option value="title" ${state.expressionFilters.sort==='title'?'selected':''}>标题 A–Z</option><option value="most_read" ${state.expressionFilters.sort==='most_read'?'selected':''}>阅读最多</option></select></div></section><div data-expression-results>${expressionResults(data,summary)}</div>`;bindExpressionFilters(summary)});}
function expressionResults(data,summary){return `<div class="expression-results-head"><span>共 ${data.total} 则素材</span><button type="button" class="btn text" data-expression-action="clear-filters">清除筛选</button></div>${data.items.length?`<section class="expression-grid">${data.items.map(expressionCard).join('')}</section>`:`<section class="empty expression-empty"><h2>${summary.total?'没有匹配的素材':'阅读素材还是空的'}</h2><p>${summary.total?'试试减少筛选条件。':'从一句常用表达或一篇范文开始。'}</p>${summary.total?'<button class="btn light" type="button" data-expression-action="clear-filters">清除筛选</button>':'<button class="btn primary" type="button" data-route="add?kind=expression">添加第一则素材</button>'}</section>`}`}
function bindExpressionFilters(summary){const input=document.querySelector('#expression-search'),container=document.querySelector('[data-expression-results]');
  bindSearchInput(input,async(value,current)=>{
    state.expressionFilters.q=value;
    container.setAttribute('aria-busy','true');
    try{
      const data=await api(`/api/expressions?${qs({...state.expressionFilters,page_size:100})}`);
      if(current()&&container.isConnected)container.innerHTML=expressionResults(data,summary);
    }catch(error){notify(error.message);throw error}
    finally{container.removeAttribute('aria-busy')}
  },{delay:240,isCurrent:()=>state.route==='expressions'&&!state.expressionReader});document.querySelectorAll('[data-expression-filter]').forEach(select=>select.addEventListener('change',()=>{state.expressionFilters[select.dataset.expressionFilter]=select.value;renderExpressions()}));document.querySelector('[data-expression-favorite-filter]')?.addEventListener('change',event=>{state.expressionFilters.favorite=event.target.checked?'true':'';renderExpressions()})}
function expressionParagraphs(value){return String(value||'').trim().split(/\n\s*\n/).filter(Boolean)}
function expressionText(value){return esc(value).replace(/\n/g,'<br>')}
function expressionReadingBlocks(item){const english=expressionParagraphs(item.english_text),chinese=expressionParagraphs(item.chinese_text);return english.map((paragraph,index)=>`<section class="expression-reading-block"><p class="english-paragraph">${expressionText(paragraph)}</p>${chinese[index]?`<p class="chinese-paragraph">${expressionText(chinese[index])}</p>`:''}</section>`).join('')+(chinese.length>english.length?`<section class="expression-reading-block translation-extra">${chinese.slice(english.length).map(paragraph=>`<p class="chinese-paragraph">${expressionText(paragraph)}</p>`).join('')}</section>`:'')}
async function renderExpressionReader(id,ctx=pageMotion.current()){const same=state.expressionReader?.id===id;const item=same?await ctx.request(`/api/expressions/${id}`):await ctx.request(`/api/expressions/${id}/open`,{method:'POST',body:'{}'});const [listing,originals]=await Promise.all([ctx.request('/api/expressions?page_size=100&sort=recent'),contentMoves.retained('expressions',id)]);if(!ctx.isCurrent())return;state.expressionReader=item;const index=listing.items.findIndex(entry=>entry.id===id),previous=listing.items[index-1],next=listing.items[index+1];return ctx.commit(()=>{main.innerHTML=`<div class="expression-reader-top"><button class="btn text" type="button" data-expression-action="back">← 返回阅读素材</button><span class="expression-type ${expressionTypeClass(item.content_type)}">${esc(item.content_type)}</span><div class="expression-reader-nav"><button class="btn small light" type="button" data-route="${previous?`expressions?read=${previous.id}`:'expressions'}" ${previous?'':'disabled'} aria-label="上一则">←</button><span>${index+1} / ${listing.items.length}</span><button class="btn small light" type="button" data-route="${next?`expressions?read=${next.id}`:'expressions'}" ${next?'':'disabled'} aria-label="下一则">→</button></div></div><div class="expression-reader-layout"><article class="expression-paper ${item.translation_visible?'show-translation':'hide-translation'}" style="--reader-scale:${item.font_scale};--reader-leading:${item.line_height}"><header><div class="expression-reader-meta">${item.exam_type?`<span>${esc(item.exam_type)}</span>`:''}${item.topic?`<span>${esc(item.topic)}</span>`:''}${item.tags.map(tag=>`<span>#${esc(tag)}</span>`).join('')}</div><h1>${esc(item.title)}</h1><p>${item.source?`来源：${esc(item.source)} · `:''}阅读 ${item.read_count} 次${item.last_read_at?` · 最近 ${formatDate(item.last_read_at,true)}`:''}</p></header>${item.illustration_path?`<figure class="expression-illustration"><img src="${esc(item.illustration_path)}" alt="${esc(item.title)}图表示例"><figcaption>来源图片中的图表示例</figcaption></figure>`:''}<div class="expression-prose">${expressionReadingBlocks(item)}</div>${originals}${item.notes?`<footer class="expression-notes"><span>个人备注</span><p>${expressionText(item.notes)}</p></footer>`:''}</article><aside class="expression-reader-panel"><div><span class="eyebrow">READING SETTINGS</span><h2>只保留阅读需要的控制</h2><p>没有答题、评分、打卡或间隔复习。</p></div><button class="reader-setting-wide" type="button" data-expression-action="translation" aria-pressed="${item.translation_visible}"><span>${item.translation_visible?'隐藏中文翻译':'显示中文翻译'}</span><i class="reader-switch ${item.translation_visible?'on':''}"></i></button><div class="reader-setting"><span>字号</span><div><button type="button" data-expression-action="font-down" aria-label="减小字号">A−</button><button type="button" data-expression-action="font-up" aria-label="增大字号">A＋</button></div></div><div class="reader-setting"><span>行距</span><div><button type="button" data-expression-action="line-compact">紧凑</button><button type="button" data-expression-action="line-comfy">舒展</button></div></div><button class="reader-favorite ${item.is_favorite?'active':''}" type="button" data-expression-action="favorite" data-id="${item.id}" data-favorite="${item.is_favorite?'0':'1'}" aria-pressed="${item.is_favorite}">${icon('bookmark')}<span>${item.is_favorite?'取消收藏':'收藏这则素材'}</span></button>${item.chinese_text?'':'<p class="reader-no-translation">这则素材暂时没有中文翻译，可在编辑页后续补充。</p>'}<div class="reader-panel-actions">${contentMoves.button('expressions',item.id)}${contentActions(item.title,{edit:`data-route="add?kind=expression&expression=${item.id}"`,remove:`data-expression-action="delete" data-id="${item.id}"`})}</div></aside></div>`;requestAnimationFrame(()=>{const max=Math.max(0,document.documentElement.scrollHeight-innerHeight);window.scrollTo({top:max*item.scroll_ratio,behavior:'auto'})})});}
function currentReaderSettings(){const paper=document.querySelector('.expression-paper'),item=state.expressionReader;if(!paper||!item)return null;return {scroll_ratio:item.scroll_ratio||0,translation_visible:paper.classList.contains('show-translation'),font_scale:Number(item.font_scale)||1,line_height:Number(item.line_height)||1.85}}
async function persistExpressionState(){const item=state.expressionReader,settings=currentReaderSettings();if(!item||!settings)return;const max=Math.max(1,document.documentElement.scrollHeight-innerHeight);settings.scroll_ratio=Math.min(1,Math.max(0,scrollY/max));item.scroll_ratio=settings.scroll_ratio;await api(`/api/expressions/${item.id}/state`,{method:'PUT',body:JSON.stringify(settings)})}
function updateReaderPaper(){const paper=document.querySelector('.expression-paper'),item=state.expressionReader;if(!paper||!item)return;paper.style.setProperty('--reader-scale',item.font_scale);paper.style.setProperty('--reader-leading',item.line_height)}
let expressionScrollTimer;
window.addEventListener('scroll',()=>{if(state.route!=='expressions'||!state.expressionReader)return;clearTimeout(expressionScrollTimer);expressionScrollTimer=setTimeout(()=>persistExpressionState().catch(()=>{}),650)},{passive:true});
document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='hidden'&&state.expressionReader)persistExpressionState().catch(()=>{})});
function showAddSuccess(item){const panel=document.querySelector('#add-success');if(!panel)return;panel.innerHTML=`<span class="success-mark">${icon('check')}</span><div><strong>${esc(item.term)} 已收进词汇本</strong><small>今日活跃已记录 · 已保存到${collectionText[item.collection]}</small></div><span class="success-sparks" aria-hidden="true"><i></i><i></i><i></i></span>`;panel.classList.remove('show');void panel.offsetWidth;panel.classList.add('show');clearTimeout(showAddSuccess.timer);showAddSuccess.timer=setTimeout(()=>panel.classList.remove('show'),4200)}
async function saveItem(event){event.preventDefault();const form=event.currentTarget;syncCaptureForm();const data=Object.fromEntries(new FormData(form));data.tags=data.tags.split(/[，,]/).map(x=>x.trim()).filter(Boolean);data.synonyms=data.synonyms.split(/[，,;；]/).map(x=>x.trim()).filter(Boolean);data.collocations=data.collocations.split(/\r?\n/).map(x=>x.trim()).filter(Boolean);const id=data.id;delete data.id;delete data.type_choice;data.academic_category_id=data.collection==='academic'?(data.academic_category_id||null):null;try{const saved=await api(id?`/api/items/${id}`:'/api/items',{method:id?'PUT':'POST',body:JSON.stringify(data)});notify(id?'修改已保存':`${saved.term} 已添加`);if(id)returnToLibrary(saved,true);else{form.reset();document.querySelector('#parse-status').textContent='';form.elements.collection.value=saved.collection;form.elements.item_type.value=saved.item_type;form.elements.academic_category_id.value=saved.academic_category_id||'';form.elements.type_choice.value='auto';syncCaptureForm();document.querySelector('#dictionary-paste').value='';document.querySelector('#more-fields').classList.toggle('open',saved.collection==='academic');document.querySelector('#form-error').textContent='';showAddSuccess(saved);form.elements.term.focus();window.scrollTo({top:0,behavior:'smooth'})}}catch(error){document.querySelector('#form-error').textContent=error.message}}
function fillDictionaryFields(){const input=document.querySelector('#dictionary-paste'),status=document.querySelector('#parse-status'),form=document.querySelector('#item-form');try{const parsed=parseDictionaryText(input.value);for(const [name,value] of Object.entries(parsed)){const field=form.querySelector(`[name="${name}"]`);if(!field||!value)continue;if(Array.isArray(value)){const existing=field.value.split(/[，,]/).map(x=>x.trim()).filter(Boolean);field.value=[...new Set([...existing,...value])].join('，')}else if(!field.value.trim())field.value=value}syncCaptureForm();document.querySelector('#more-fields').classList.add('open');const found=['英文词条',parsed.chinese_meaning&&'中文释义',parsed.phonetic&&'音标',parsed.part_of_speech&&'词性',parsed.english_definition&&`英文释义 ${parsed.definition_count||1} 条`,parsed.source_sentence&&'例句',parsed.synonyms.length&&'近义词'].filter(Boolean);const chineseNotice=parsed.chinese_meaning?'中文释义已从原文填入。':'原文没有中文释义；英文内容已填入下方“英文释义”，请手动补一行中文后保存。';status.textContent=`已识别 ${parsed.term}（${parsed.detected_format}）：${found.join('、')}。${chineseNotice}${parsed.warnings?' '+parsed.warnings:''}`;form.elements.chinese_meaning.focus();form.elements.chinese_meaning.select()}catch(error){status.textContent=error.message}}
async function pasteFromClipboard(){const input=document.querySelector('#dictionary-paste');try{input.value=await navigator.clipboard.readText();fillDictionaryFields()}catch{input.focus();notify('浏览器未允许直接读取，请按 Ctrl+V 粘贴后再识别。')}}
let libraryRequestVersion=0;
const boundLibraryFilters=new WeakSet();
function libraryDescription(group,total){const label=group==='vocabulary'&&state.filters.item_type?itemTypeText[state.filters.item_type]:libraryGroupText[group]||libraryGroupText.vocabulary,description=group==='sentence'?(libraryCollection()==='academic'?'课程中的完整表达与较长句式。':libraryCollection()==='all'?'两类词库的完整句子与较长表达。':'完整的雅思描述句型和较长表达模板。'):state.filters.item_type==='word'?'只显示单词，固定搭配可单独查看。':state.filters.item_type==='phrase'?'只显示简短词组与固定搭配。':(libraryCollection()==='academic'?'专业术语和简短固定搭配。':'单词和 peal of laughter 这类简短固定搭配。');return `${libraryCollection()==='all'?'汇总阅读写作与学术词汇':libraryCollection()==='academic'?'专业课词汇单独收录与复习':'阅读和写作中积累的词汇'} · 共 ${total} 条${label}；${description}`}
function academicRoot(){return libraryCollection()==='academic'&&!state.filters.category_id}
function libraryFiltering(){return Boolean(state.filters.q||state.filters.source||state.filters.tag||state.filters.status||(state.filters.item_group!=='sentence'&&state.filters.item_type))}
function libraryQuery(group){const mixed=academicRoot()&&(state.academicView||'mixed')!=='all'&&!libraryFiltering()&&!state.organize&&!state.categoryOrganize;return qs({...state.filters,category_id:mixed?'uncategorized':state.filters.category_id,collection:libraryCollection(),item_type:group==='sentence'?'':state.filters.item_type,status:group==='sentence'?'':state.filters.status,page_size:100})}
async function loadLibraryData(group,request=api){const [data,facets,groups,categories]=await Promise.all([request(`/api/items?${libraryQuery(group)}`),request(`/api/facets?${qs({collection:libraryCollection(),category_id:state.filters.category_id})}`),request(`/api/confusion-groups?collection=${libraryCollection()}`),libraryCollection()==='academic'?request('/api/academic-categories'):Promise.resolve(null)]);return {data,facets,groups,categories}}
function libraryTypeFilter(group){
  if(group==='sentence')return '';
  return `<div class="library-type-filter" role="group" aria-label="词条类型筛选"><span>查看内容</span>${[['','全部'],['word','只看单词'],['phrase','只看固定搭配']].map(([type,label])=>`<button type="button" class="btn small light" data-library-type="${type}" aria-pressed="${(state.filters.item_type||'')===type}">${label}</button>`).join('')}</div>`;
}
function libraryToolbar(facets,group){return `<div class="toolbar ${group==='sentence'?'without-mastery':''}"><input id="search" type="search" aria-label="搜索词库" placeholder="搜索英文、中文、同义词或例句" value="${esc(state.filters.q)}"><select data-filter="source" aria-label="来源 / 课程"><option value="">全部来源</option>${facets.sources.map(x=>`<option ${state.filters.source===x?'selected':''}>${esc(x)}</option>`).join('')}</select><select data-filter="tag" aria-label="标签"><option value="">全部标签</option>${facets.tags.map(x=>`<option ${state.filters.tag===x?'selected':''}>${esc(x)}</option>`).join('')}</select>${group==='sentence'?'':`<select data-filter="status" aria-label="掌握度"><option value="">全部掌握度</option>${Object.entries(statusText).map(([k,v])=>`<option value="${k}" ${state.filters.status===k?'selected':''}>${v}</option>`).join('')}</select>`}<select data-filter="sort" aria-label="排序方式"><option value="newest" ${state.filters.sort==='newest'?'selected':''}>录入时间：从新到旧</option><option value="oldest" ${state.filters.sort==='oldest'?'selected':''}>录入时间：从旧到新</option><option value="term_asc" ${state.filters.sort==='term_asc'?'selected':''}>英文：A → Z</option><option value="term_desc" ${state.filters.sort==='term_desc'?'selected':''}>英文：Z → A</option></select></div>`}
function libraryPagination(data){
  if(data.total<=data.page_size)return '';
  const pages=Math.ceil(data.total/data.page_size);
  return `<nav class="library-pagination" aria-label="词库分页"><button type="button" class="btn light" data-library-page="${data.page-1}" ${data.page===1?'disabled':''}>上一页</button><span>第 ${data.page} / ${pages} 页 · 共 ${data.total} 条</span><button type="button" class="btn light" data-library-page="${data.page+1}" ${data.page>=pages?'disabled':''}>下一页</button></nav>`;
}
function libraryContent(data,facets,groups,group){const collectionRows=academicRoot()?academicCategories.rows(group):'',onlyCollections=academicRoot()&&state.academicView==='folders'&&!state.organize&&!state.categoryOrganize,entries=onlyCollections?[]:data.items;const firstColumn=group==='sentence'?'长句':itemTypeText[state.filters.item_type]||'单词 / 固定搭配';return `${libraryTypeFilter(group)}<details class="library-tools"><summary>词库工具 ${icon("more")}</summary><div class="utility library-tools-panel">${button(state.organize?'退出整理':'建立易混词组','toggle-organize',state.organize?'primary':'light')}${libraryCollection()==='academic'?academicCategories.bulkButton():''}${button('下载 CSV 模板','csv-template','light')}${button('导出 CSV','csv-export','light')}<label class="btn light">导入 CSV<input id="csv-file" type="file" accept=".csv,text/csv" hidden></label></div></details>${groups.items.length?`<div class="group-panel"><strong>已建立的易混词组</strong><div class="group-list">${groups.items.map(g=>`<span class="group-chip">${libraryCollection()==='all'?collectionText[g.items[0]?.collection]+' · ':''}${esc(g.name)} · ${g.items.length}<button class="link-btn" data-action="edit-group" data-id="${g.id}">编辑</button><button class="link-btn" data-action="delete-group" data-id="${g.id}">删除</button></span>`).join('')}</div></div>`:''}${libraryToolbar(facets,group)}<div class="filter-reset-row" ${libraryFiltering()?'':'hidden'}><button type="button" class="btn text" data-action="clear-library-filters">清除筛选</button></div>${state.organize?`<div class="group-panel organizer"><h3>建立易混词组</h3><p>在同一词库内勾选至少两个容易混淆的词，再给这组命名。</p><div class="field-grid"><div class="field"><label>组名</label><input id="group-name" value="${esc(state.editingGroup?.name||'')}" placeholder="例如 adapt / adopt"></div><div class="actions">${button(state.editingGroup?'保存分组':'建立分组','save-group','primary')}${button('清除选择','clear-selection','light')}</div></div><p class="hint">已选择 ${state.selected.size} 条。</p></div>`:''}${state.categoryOrganize?academicCategories.organizer():''}${collectionRows||entries.length?`<div class="library-list ${group==='sentence'?'sentence-list':''}"><div class="library-head"><span>${firstColumn}</span><span>录入时间</span>${group==='sentence'?'':'<span>掌握度</span>'}<span>操作</span></div>${collectionRows}${entries.map(libraryRow).join('')}</div>${onlyCollections?'':libraryPagination(data)}`:`<div class="empty"><h2>${onlyCollections?'还没有匹配的合集':'这个分组里还没有匹配的内容'}</h2>${button('添加第一条','go-add','primary')}</div>`}`}
function updateLibraryTabs(group,counts){document.querySelectorAll('[data-library-group]').forEach(button=>{const active=button.dataset.libraryGroup===group;button.classList.toggle('active',active);button.setAttribute('aria-selected',String(active));const count=button.querySelector('b');if(count&&counts)count.textContent=String(counts[button.dataset.libraryGroup]||0)})}
async function refreshLibraryContent(searchCurrent=()=>true){const group=state.filters.item_group||'vocabulary',request=++libraryRequestVersion,container=document.querySelector('[data-library-content]');if(container)container.setAttribute('aria-busy','true');try{const {data,facets,groups}=await loadLibraryData(group);if(!searchCurrent()||!container?.isConnected||container!==document.querySelector('[data-library-content]')||request!==libraryRequestVersion||!['library','reading','academic'].includes(state.route)||state.filters.item_group!==group)return;document.querySelector('.page-head .page-title-copy p').textContent=libraryDescription(group,academicRoot()&&!libraryFiltering()?facets.group_counts[group]||0:data.total);updateLibraryTabs(group,facets.group_counts);updateSearchRegion(container,libraryContent(data,facets,groups,group),'.toolbar');bindLibraryControls()}finally{if(request===libraryRequestVersion)container?.removeAttribute('aria-busy')}}
async function renderLibrary(ctx=pageMotion.current()){const group=state.filters.item_group||'vocabulary',request=++libraryRequestVersion,{data,facets,groups,categories}=await loadLibraryData(group,ctx.request);if(request!==libraryRequestVersion)return;if(categories)academicCategories.setData(categories);const counts=facets.group_counts||{vocabulary:0,sentence:0},rootAcademic=academicRoot();await ctx.commit(()=>{main.innerHTML=`${pageHead(libraryCollection()==='academic'?'ACADEMIC':libraryCollection()==='general'?'READING & WRITING':'LIBRARY',collectionText[libraryCollection()],libraryDescription(group,rootAcademic&&!libraryFiltering()?counts[group]||0:data.total),`<button type="button" class="btn primary" data-action="go-add">${icon("add")} 添加内容</button>`)}${libraryCollection()==='all'?`<div class="library-collections" aria-label="词库分类"><a href="#reading"><span>阅读写作</span><strong>${facets.collection_counts.general} 条</strong></a><a href="#academic"><span>学术词汇</span><strong>${facets.collection_counts.academic} 条</strong></a></div>`:''}${libraryCollection()==='academic'?academicCategories.shelf():''}${`<section class="library-group-switch" role="tablist" aria-label="词库分组"><button type="button" role="tab" data-library-group="vocabulary" aria-selected="${group==='vocabulary'}" class="${group==='vocabulary'?'active':''}"><span><strong>单词与固定搭配</strong><small>可只看单词或只看固定搭配</small></span><b>${counts.vocabulary||0}</b></button><button type="button" role="tab" data-library-group="sentence" aria-selected="${group==='sentence'}" class="${group==='sentence'?'active':''}"><span><strong>长句</strong><small>${libraryCollection()==='all'?'两类词库的长句单独存放':libraryCollection()==='academic'?'课程中的完整表达单独存放':'雅思句型与完整描述句单独存放'}</small></span><b>${counts.sentence||0}</b></button></section><div data-library-content>${libraryContent(data,facets,groups,group)}</div>`}`;bindLibrary()});
  // View-transition snapshots paint above modal dialogs until the page swap finishes.
  const params=new URLSearchParams(ctx.hash.split('?')[1]);
  if(ctx.isCurrent()&&ctx.hash===location.hash&&params.get('detail'))await showDetail(params.get('detail'),ctx);
}
function libraryRow(item){
  const partOfSpeech=String(item.part_of_speech||'').trim();
  const posBadge=partOfSpeech?`<span class="pos-pill" title="词性：${esc(partOfSpeech)}">${esc(partOfSpeech)}</span>`:(item.item_type==='word'?'<span class="pos-pill missing">词性待补充</span>':'');
  const status=statusText[item.status]?item.status:'new';
  const mastery=item.item_type==='sentence'?'':`<div class="mastery-control"><small>掌握度</small><span class="mastery-display status-${status}"><span class="mastery-summary">${masteryStars(status,item)}<select class="mastery-select" data-status-id="${item.id}" data-original-status="${status}" aria-label="修改 ${esc(item.term)} 的掌握度">${Object.entries(statusText).map(([key,label])=>`<option value="${key}" ${item.status===key?'selected':''}>${label}</option>`).join('')}</select></span></span></div>`;
  return `<article class="library-row type-${item.item_type}"><div class="term row-check">${state.organize||state.categoryOrganize?`<input type="checkbox" aria-label="选择 ${esc(item.term)}" data-select-id="${item.id}" ${state.selected.has(item.id)?'checked':''}>`:''}<div><span class="term-head"><span class="type-pill">${collectionText[item.collection]} · ${itemTypeText[item.item_type]||'词条'}</span><strong>${esc(item.term)}</strong>${posBadge}</span><small class="term-meaning">${esc(item.chinese_meaning)}</small>${item.collection==='academic'&&!state.filters.category_id?`<small class="academic-category-badge" title="专业分类">${esc(item.academic_category_name||'未分类')}</small>`:''}</div></div><div class="row-facts"><span><small>录入</small>${formatDate(item.created_at,true)}</span></div>${mastery}<div class="row-actions">${contentActions(item.term,{view:{text:"详情",attributes:`data-action="detail-${item.id}" aria-haspopup="dialog"`},edit:`data-action="edit-${item.id}"`,remove:`data-action="delete-${item.id}"`})}</div></article>`
}
function bindLibrary(){
  document.querySelectorAll('[data-library-group]').forEach(button=>button.addEventListener('click',async()=>{const group=button.dataset.libraryGroup,previous=state.filters.item_group,previousPage=state.filters.page;if(previous===group)return;state.filters.item_group=group;state.filters.page=1;state.organize=false;state.categoryOrganize=false;state.selected.clear();state.editingGroup=null;updateLibraryTabs(group);try{await refreshLibraryContent()}catch(error){state.filters.item_group=previous;state.filters.page=previousPage;updateLibraryTabs(previous);notify(error.message)}}));
  bindLibraryControls();
}
function bindLibraryControls(){
  document.querySelectorAll('[data-library-type]').forEach(button=>button.addEventListener('click',async()=>{
    const type=button.dataset.libraryType,previous=state.filters.item_type,previousPage=state.filters.page;
    if((previous||'')===type)return;
    state.filters.item_type=type;state.filters.page=1;state.organize=false;state.categoryOrganize=false;state.selected.clear();state.editingGroup=null;
    if(type&&academicRoot()&&state.academicView==='folders'){state.academicView='all';document.querySelectorAll('[data-academic-view]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.academicView==='all')))}
    try{await refreshLibraryContent()}catch(error){if(state.filters.item_type===type){state.filters.item_type=previous;state.filters.page=previousPage}notify(error.message)}
  }));
  document.querySelectorAll('[data-library-page]').forEach(button=>button.addEventListener('click',async()=>{const previous=state.filters.page;state.filters.page=Number(button.dataset.libraryPage);try{await refreshLibraryContent();document.querySelector('.library-group-switch')?.scrollIntoView({block:'start',behavior:'auto'})}catch(error){state.filters.page=previous;notify(error.message)}}));
  bindSearchInput(document.querySelector('#search'),async(value,current)=>{state.filters.q=value;state.filters.page=1;try{await refreshLibraryContent(current)}catch(error){notify(error.message);throw error}});
  document.querySelectorAll('[data-filter]').forEach(el=>{if(boundLibraryFilters.has(el))return;boundLibraryFilters.add(el);el.addEventListener('change',()=>{state.filters[el.dataset.filter]=el.value;state.filters.page=1;if(el.dataset.filter==='sort')localStorage.setItem('library-sort',el.value);refreshLibraryContent().catch(error=>notify(error.message))})});
  document.querySelectorAll('[data-status-id]').forEach(el=>el.addEventListener('change',async()=>{const previous=el.dataset.originalStatus||'new';el.disabled=true;try{await api(`/api/items/${el.dataset.statusId}`,{method:'PUT',body:JSON.stringify({status:el.value})});notify(`掌握度已改为“${statusText[el.value]}”`);await refreshLibraryContent()}catch(error){el.value=previous;el.disabled=false;notify(error.message)}}));
  document.querySelectorAll('[data-mastery-star]').forEach(star=>star.addEventListener('click',async()=>{const group=star.closest('.mastery-stars');group.querySelectorAll('button').forEach(button=>button.disabled=true);try{await api(`/api/items/${star.dataset.itemId}`,{method:'PUT',body:JSON.stringify({status:star.dataset.status})});notify(`掌握度已改为“${statusText[star.dataset.status]}”`);await refreshLibraryContent()}catch(error){group.querySelectorAll('button').forEach(button=>button.disabled=false);notify(error.message)}}));
  document.querySelectorAll('[data-select-id]').forEach(el=>el.addEventListener('change',()=>{const id=Number(el.dataset.selectId);el.checked?state.selected.add(id):state.selected.delete(id);document.querySelector('.organizer .hint').textContent=`已选择 ${state.selected.size} 条。`}));
  document.querySelector('#csv-file')?.addEventListener('change',importCsv);
}
function bindMasteryBoost(){
  document.querySelectorAll('[data-mastery-boost]').forEach(track=>{
    const thumb=track.querySelector('.mastery-boost-thumb'),label=track.querySelector('.mastery-boost-label');
    let dragging=false,progress=0,grab=0;
    const travel=()=>Math.max(1,track.clientWidth-thumb.offsetWidth-8);
    const paint=value=>{
      progress=Math.min(100,Math.max(0,value));
      track.style.setProperty('--boost-x',`${travel()*progress/100}px`);
      track.style.setProperty('--boost-progress',String(progress/100));
      track.classList.toggle('is-ready',progress>=92);
      label.textContent=progress>=92?'松开斩词 · 继续下一条':'向右斩词 · +1 档';
      track.setAttribute('aria-valuenow',String(Math.round(progress)));
      track.setAttribute('aria-valuetext',progress>=92?`松开即可提升到${statusText[track.dataset.to]}并继续下一条`:`已滑动 ${Math.round(progress)}%`);
    };
    const reset=()=>{track.removeAttribute('data-dragging');paint(0)};
    const commit=async()=>{
      if(track.dataset.busy||state.review?.saving)return;
      track.dataset.busy='true';track.removeAttribute('data-dragging');paint(100);
      track.classList.add('is-committing');label.textContent='正在斩词…';
      const success=await rateReview('remembered',{boost:true,track});
      if(!success&&track.isConnected){delete track.dataset.busy;track.classList.remove('is-committing','is-success');thumb.innerHTML=icon('chevron');reset()}
    };
    track.addEventListener('pointerdown',event=>{
      if(event.button!==0||track.dataset.busy||state.review?.saving)return;
      const rect=track.getBoundingClientRect(),thumbLeft=rect.left+4+travel()*progress/100;
      grab=event.target.closest('.mastery-boost-thumb')?event.clientX-thumbLeft:thumb.offsetWidth/2;
      dragging=true;track.dataset.dragging='true';track.setPointerCapture(event.pointerId);
      paint((event.clientX-rect.left-4-grab)/travel()*100);
    });
    track.addEventListener('pointermove',event=>{if(!dragging)return;const rect=track.getBoundingClientRect();paint((event.clientX-rect.left-4-grab)/travel()*100)});
    track.addEventListener('pointerup',event=>{if(!dragging)return;dragging=false;try{track.releasePointerCapture(event.pointerId)}catch{};progress>=92?commit():reset()});
    track.addEventListener('pointercancel',()=>{dragging=false;reset()});
    track.addEventListener('lostpointercapture',()=>{if(dragging){dragging=false;reset()}});
    track.addEventListener('keydown',event=>{
      if(track.dataset.busy||state.review?.saving)return;
      let next=null;
      if(event.key==='ArrowRight'||event.key==='ArrowUp')next=progress+20;
      if(event.key==='ArrowLeft'||event.key==='ArrowDown')next=progress-20;
      if(event.key==='Home')next=0;if(event.key==='End')next=100;
      if(next!==null){event.preventDefault();paint(next);return}
      if(event.key==='Enter'||event.key===' '){event.preventDefault();commit()}
    });
    paint(0);
  });
}
async function showDetail(id,ctx=pageMotion.current()){const [item,suggestions]=await Promise.all([api(`/api/items/${id}`),api(`/api/confusion-suggestions?item_id=${id}`)]);const originals=await contentMoves.retained(item.collection,item.id);if(!ctx.isCurrent()||ctx.hash!==location.hash)return;const activity=item.item_type==='sentence'?`录入于 ${esc(formatDate(item.created_at,true))}`:`录入于 ${esc(formatDate(item.created_at,true))} · 复习 ${item.review_count} 次 · 答对 ${item.correct_count} 次`;openDialog(`<div class="dialog-card"><div class="section-head"><div><span class="type-pill">${collectionText[item.collection]} · ${itemTypeText[item.item_type]||'词条'}</span><h2>${esc(item.term)}</h2></div><button class="btn small light" data-action="close-dialog">关闭</button></div><p class="meaning">${esc(item.chinese_meaning)}</p>${item.synonyms.length?`<p class="detail-subtle"><strong>同义 / 替换：</strong>${esc(item.synonyms.join('、'))}</p>`:''}${item.collection==='academic'?`<p><strong>专业分类：</strong>${esc(item.academic_category_name||'未分类')}</p>`:''}${item.source?`<p><strong>来源 / 课程：</strong>${esc(item.source)}</p>`:''}${item.tags.length?`<p><strong>标签：</strong>${item.tags.map(esc).join('、')}</p>`:''}${item.phonetic?`<p><strong>音标：</strong>${esc(item.phonetic)}</p>`:''}${item.part_of_speech?`<p><strong>词性：</strong>${esc(item.part_of_speech)}</p>`:''}${item.english_definition?`<p><strong>英文：</strong>${esc(item.english_definition)}</p>`:''}${item.collocations.length?`<p><strong>常见搭配：</strong>${esc(item.collocations.join('、'))}</p>`:''}${item.source_sentence?`<p><strong>原句：</strong>${esc(item.source_sentence)}</p>`:''}${item.own_sentence?`<p><strong>我的例句：</strong>${esc(item.own_sentence)}</p>`:''}${item.notes?`<p class="detail-notes"><strong>备注：</strong>${esc(item.notes)}</p>`:''}<p class="detail-subtle">${activity}</p>${item.groups.length?`<p><strong>易混词组：</strong>${item.groups.map(g=>esc(g.name)).join('、')}</p>`:''}${suggestions.items.length?`<div class="group-panel"><strong>可能易混</strong><p>${suggestions.items.map(x=>esc(x.term)).join('、')}</p><button class="btn small" data-action="organize-with" data-id="${item.id}" data-suggest="${suggestions.items.map(x=>x.id).join(',')}">整理成组</button></div>`:''}${originals}<div class="dialog-actions">${item.collection==='academic'?academicCategories.singleButton(item):''}${contentMoves.button(item.collection,item.id)}${contentActions(item.term,{edit:`data-action="edit-${item.id}"`,remove:`data-action="delete-${item.id}"`})}</div></div>`)}
async function renderReview(ctx=pageMotion.current()){
  if(new URLSearchParams(ctx.hash.split('?')[1]).get('collection')==='daily')return renderDailyReview({main,esc,pageHead,openDialog,request:ctx.request,isCurrent:ctx.isCurrent,commit:ctx.commit});
  if(state.review?.queue)return ctx.commit(()=>renderReviewCard())
  const params=new URLSearchParams(ctx.hash.split('?')[1]);
  const collection=params.get('collection')==='academic'?'academic':'general';
  const categoryId=collection==='academic'?params.get('category_id')||'':'';
  const [generalGroups,academicGroups,categoryData,generalFacets,academicFacets,academicAllFacets]=await Promise.all([
    ctx.request('/api/confusion-groups?collection=general'),ctx.request('/api/confusion-groups?collection=academic'),
    ctx.request('/api/academic-categories'),ctx.request('/api/facets?collection=general'),
    ctx.request(`/api/facets?${qs({collection:'academic',category_id:categoryId})}`),
    categoryId?ctx.request('/api/facets?collection=academic'):Promise.resolve(null),
  ]);
  const groups=collection==='academic'?academicGroups:generalGroups;
  if(!ctx.isCurrent())return;academicCategories.setData(categoryData);
  const requestedScope=params.get('scope');
  const initialScope=['random','recent','study','today','mistakes','group','topic'].includes(requestedScope)?requestedScope:'random';
  const requestedMode=params.get('mode'),initialMode=initialScope==='today'?'recall':(['recall','zh_to_en','cloze'].includes(requestedMode)?requestedMode:'recall');
  const requestedItemType=params.get('item_type');
  const initialItemType=reviewContentChoices[collection].some(([type])=>type===requestedItemType)?requestedItemType:(collection==='general'?'vocabulary':'word');
  state.reviewSetup={collection,categoryId,scope:initialScope,mode:initialMode,itemType:initialItemType,groupId:null,limit:20,strategy:'balanced',
    groups:{general:generalGroups.items,academic:academicGroups.items},
    contentCounts:{general:generalFacets.type_counts,academic:academicFacets.type_counts},
    academicCountsAll:(academicAllFacets||academicFacets).type_counts,
    confirmedCategoryId:categoryId,categoryPending:false,categoryRequest:0};
  if(params.get('start')==='1'){if(await startReview(ctx))return;if(initialScope==='topic')return routeTo(`academic?${qs({category_id:categoryId})}`);}
  const scopeChoices=[
    ['random','globe','全局复习','从所选内容库智能抽取'],
    ['recent','recent','最近添加','从同类内容里按录入时间选取'],
    ['study','book','学习模式','练多少由你预设，不保存对错'],
    ['today','today','复习今日内容','只取当天录入的同类内容'],
    ['mistakes','mistake','错题重练','只练同类内容中上次出错的条目'],
    ['group','group','易混专项','按自建分组集中练'],
  ];
  const modeChoices={recall:['recall','遮罩自评','先回忆，再揭晓中文'],zh_to_en:['spelling','看中文写英文','主动拼出英文'],cloze:['cloze','挖空补全','补全词或词组']};
  return ctx.commit(()=>{main.innerHTML=`${reviewSourcePicker()}${pageHead(initialScope==='study'?'STUDY':'REVIEW',initialScope==='study'?'先练一练刚加入的内容':'为这次复习定一条清晰路线',initialScope==='study'?'选择内容、数量和练法，过程不记录对错。':'选择单词与固定搭配一起复习，或单独练习单词、短语、长句。')}<section class="review-setup review-studio">
    ${reviewContentPicker()}
    <div class="review-plan-grid">
      <section class="setup-panel scope-panel" aria-labelledby="review-scope-title"><div class="setup-heading"><span>02</span><div><p class="choice-title">复习范围</p><h2 id="review-scope-title">这次从哪里选？</h2></div></div><div class="choice-grid scopes">${scopeChoices.map(([key,iconName,title,description])=>`<button class="choice scope-choice ${initialScope===key?'selected':''}" data-scope="${key}" aria-pressed="${initialScope===key}"><span class="mode-symbol">${icon(iconName)}</span><strong>${title}</strong><small>${description}</small></button>`).join('')}</div></section>
      <section class="setup-panel mode-panel" aria-labelledby="review-mode-title"><div class="setup-heading"><span>03</span><div><p class="choice-title">练习方式</p><h2 id="review-mode-title">你想怎么练？</h2></div></div><div class="choice-grid modes">${Object.entries(modeChoices).map(([key,[iconName,title,description]])=>`<button class="choice mode-choice ${key===state.reviewSetup.mode?'selected':''}" data-mode="${key}" aria-pressed="${key===state.reviewSetup.mode}"><span class="mode-symbol">${icon(iconName)}</span><strong>${title}</strong><small>${description}</small></button>`).join('')}</div></section>
    </div>
    <div class="setup-options review-round-options">
          <div id="global-options" class="option-card ${initialScope==='random'?'':'hidden'}"><div><strong>全局抽取逻辑</strong><small>两种逻辑都保留随机性，不会把词永久固定在某一档。</small></div><div class="strategy-switch" role="group" aria-label="全局抽取逻辑"><button class="selected" data-strategy="balanced" aria-pressed="true"><strong>综合权重</strong><small id="balanced-strategy-detail">遗忘风险 + 掌握度 + 错题表现</small></button><button data-strategy="forgetting" aria-pressed="false"><strong>遗忘曲线</strong><small>优先接近遗忘点的词</small></button></div></div>
          <div id="limit-options" class="option-card review-limit-card ${['random','recent','study'].includes(initialScope)?'':'hidden'}"><div><strong id="review-limit-title">本轮预设数量</strong><small id="review-limit-description">拖动胶囊，或在右侧直接输入想练的数量。</small></div><div class="review-limit-picker"><div class="limit-readout" aria-hidden="true"><span>本轮</span><strong id="review-limit-value">20</strong><small>条</small></div><div class="limit-slider-shell" style="--limit-progress:25%"><span class="limit-liquid" aria-hidden="true"></span><span class="limit-thumb" aria-hidden="true"></span><input id="review-limit" type="range" min="0" max="4" step="1" value="1" aria-label="本轮复习数量预设" aria-valuetext="20 条"><div class="limit-marks" aria-hidden="true">${reviewLimitPresets.map((value,index)=>`<button type="button" tabindex="-1" data-limit-index="${index}">${value}</button>`).join('')}</div></div><label class="limit-custom"><span>自定义</span><span><input id="review-limit-custom" type="number" inputmode="numeric" min="1" max="100" value="20" aria-label="自定义本轮复习数量"><small>条</small></span></label></div></div>
          <div id="group-select" class="option-card ${initialScope==='group'?'':'hidden'}"><div><strong>易混词组</strong><small>选择一个已经建立的词组。</small></div><label class="compact-control">分组<select id="review-group"><option value="">请选择</option>${groups.items.map(g=>`<option value="${g.id}">${esc(g.name)} (${g.items.length})</option>`).join('')}</select></label></div>
        </div>
    <div id="weight-note" class="weight-note ${initialScope==='study'?'hidden':''}"><span class="curve-mark" aria-hidden="true"></span><div><strong>错词会优先巩固</strong><p id="review-adaptation-note"></p></div></div>
    <div class="review-launch launch-dock"><div><strong>准备好了</strong><small id="review-save-note">${initialScope==='study'?'学习模式不保存对错、统计或掌握状态。':'练习会写入统计，但不改正式到期排程。'}</small></div><div>${button('重置全局抽词','reset-round',initialScope==='random'?'text':'text hidden')}${button('开始这一轮','start-review','primary')}</div></div>
  </section>`;
  document.querySelector('#review-category').addEventListener('change',event=>selectReviewCategory(event.target.value,ctx));
  bindReviewLimitControl();
  syncReviewSetupUi(initialScope);
  });
}
function bindReviewLimitControl(){const input=document.querySelector('#review-limit'),custom=document.querySelector('#review-limit-custom'),shell=document.querySelector('.limit-slider-shell'),valueEl=document.querySelector('#review-limit-value');if(!input||!custom||!shell)return;const progressFor=value=>{if(value<=reviewLimitPresets[0])return 0;for(let index=1;index<reviewLimitPresets.length;index++){if(value<=reviewLimitPresets[index])return (index-1+(value-reviewLimitPresets[index-1])/(reviewLimitPresets[index]-reviewLimitPresets[index-1]))/(reviewLimitPresets.length-1)*100}return 100};const apply=value=>{value=Math.min(100,Math.max(1,Math.round(Number(value)||20)));state.reviewSetup.limit=value;custom.value=String(value);input.setAttribute('aria-valuetext',`${value} 条`);shell.style.setProperty('--limit-progress',`${progressFor(value)}%`);if(valueEl)valueEl.textContent=String(value);shell.querySelectorAll('[data-limit-index]').forEach((mark,index)=>mark.classList.toggle('active',reviewLimitPresets[index]===value))};const syncPreset=()=>{const index=Math.min(reviewLimitPresets.length-1,Math.max(0,Number(input.value)));apply(reviewLimitPresets[index])};input.addEventListener('input',syncPreset);input.addEventListener('change',syncPreset);custom.addEventListener('input',()=>{if(custom.value!=='')apply(custom.value)});custom.addEventListener('change',()=>apply(custom.value));shell.querySelectorAll('[data-limit-index]').forEach(mark=>mark.addEventListener('click',()=>{input.value=mark.dataset.limitIndex;syncPreset()}));apply(state.reviewSetup.limit||20)}
function reviewContentCount(setup,collection,type){
  const counts=setup.contentCounts[collection];
  return type==='vocabulary'?(counts.word||0)+(counts.phrase||0):counts[type]||0;
}
function syncReviewSetupUi(scope){
  const s=state.reviewSetup;
  document.querySelectorAll('[data-review-type]').forEach(choice=>{
    const collection=choice.dataset.reviewCollection,type=choice.dataset.reviewType,selected=s.collection===collection&&s.itemType===type;
    const count=reviewContentCount(s,collection,type),pending=collection==='academic'&&s.categoryPending;
    choice.classList.toggle('selected',selected);choice.setAttribute('aria-pressed',String(selected));
    choice.classList.toggle('is-empty',!pending&&count===0);
    choice.querySelector('.review-content-count').textContent=pending?'读取中…':count===0?'0 条 · 待添加':`${count} 条`;
  });
  document.querySelector('.review-academic-category')?.classList.toggle('hidden',s.collection!=='academic');
  const empty=scope!=='topic'&&!s.categoryPending&&reviewContentCount(s,s.collection,s.itemType)===0;
  const emptyHint=document.querySelector('#review-empty-hint');
  emptyHint?.classList.toggle('hidden',!empty);
  if(emptyHint)emptyHint.querySelector('[data-route]').dataset.route=`add?${qs({collection:s.collection,type:s.itemType==='vocabulary'?'word':s.itemType,category_id:s.categoryId==='uncategorized'?'':s.categoryId})}`;
  const start=document.querySelector('[data-action="start-review"]');if(start)start.disabled=s.categoryPending||empty;
  const variable=['random','recent','study'].includes(scope),sentence=state.reviewSetup?.itemType==='sentence',noun=reviewTypeText[state.reviewSetup?.itemType]||'内容';document.querySelector('#global-options')?.classList.toggle('hidden',scope!=='random');document.querySelector('#limit-options')?.classList.toggle('hidden',!variable);document.querySelector('#group-select')?.classList.toggle('hidden',scope!=='group');document.querySelector('#weight-note')?.classList.toggle('hidden',scope==='study');document.querySelector('[data-action="reset-round"]')?.classList.toggle('hidden',scope!=='random');const title=document.querySelector('#review-limit-title'),description=document.querySelector('#review-limit-description'),note=document.querySelector('#review-save-note'),balanced=document.querySelector('#balanced-strategy-detail');if(title)title.textContent=scope==='study'?`学习${noun}数量`:scope==='recent'?'最近添加数量':'本轮预设数量';if(description)description.textContent=scope==='study'?`只取最近录入的${noun}；可选预设，也可直接输入数量。`:scope==='recent'?`按录入时间倒序选取${noun}；可滑动预设或直接输入数量。`:'拖动胶囊，或在右侧直接输入想练的数量。';if(note)note.textContent=scope==='study'?(sentence?'学习模式只练长句，不保存对错或统计。':`学习模式只练${noun}，不保存对错、统计或掌握状态。`):`本轮只复习${collectionText[state.reviewSetup.collection]}${state.reviewSetup.categoryId?' · '+academicCategories.label(state.reviewSetup.categoryId):''}中的${noun}；会写入统计，但不改正式到期排程。`;if(balanced)balanced.textContent=sentence?'遗忘风险 + 错题表现':'遗忘风险 + 掌握度 + 错题表现';const adaptation=document.querySelector('#review-adaptation-note');if(adaptation)adaptation.textContent='近期答错会提高后续全局抽取权重，遮罩、拼写与补全共享错题表现；同一轮已抽过的内容仍不重复。'+(sentence?'长句不调整熟练度。':'最近 5 次错满 3 次，熟练度下降一档，之后重新累计；答对会逐步降低错题权重。')}
async function startReview(ctx=pageMotion.current()){
  const s={...state.reviewSetup};
  if(s.categoryPending)return notify('正在读取合集内容，请稍候');
  if(s.scope!=='topic'&&reviewContentCount(s,s.collection,s.itemType)===0)return notify('这类内容暂时为空，请先添加');
  if(['random','recent','study'].includes(s.scope))s.limit=Math.min(100,Math.max(1,Number(s.limit)||20));
  if(s.scope==='group'){s.groupId=Number(document.querySelector('#review-group').value);if(!s.groupId)return notify('请先选择一个易混词组')}
  let data;
  if(s.scope==='random')data=await ctx.request('/api/review-round',{method:'POST',body:JSON.stringify({mode:s.mode,limit:s.limit,strategy:s.strategy,item_type:s.itemType,collection:s.collection,category_id:s.categoryId})});
  else data=await ctx.request(`/api/reviews?${qs({scope:s.scope,group_id:s.groupId,item_type:s.itemType,collection:s.collection,category_id:s.categoryId,limit:['recent','study'].includes(s.scope)?s.limit:100})}`);
  if(!ctx.isCurrent())return false;
  const noun=s.scope==='topic'?'专题词条':reviewTypeText[s.itemType];
  if(!data.items.length){notify(s.scope==='random'?`今天的${noun} · ${modeText[s.mode]}已经抽完，可以重置后再来`:s.scope==='mistakes'?`目前没有待重练的${noun}`:s.scope==='study'?`还没有可学习的${noun}，请先添加`:`这个范围没有可复习的${noun}`);return false;}
  state.review={queue:data.items,index:0,mode:s.mode,scope:s.scope,itemType:s.scope==='topic'?'topic':s.itemType,collection:s.collection,categoryId:s.categoryId,categoryName:s.categoryId?academicCategories.label(s.categoryId):'',answered:false,input:'',correct:null,saving:false,token:null,previous:null,preview:false,wrongIds:new Set(),round:data.round,remaining:data.remaining,strategy:data.strategy};
  await ctx.commit(()=>renderReviewCard());
  return ctx.isCurrent();
}
function renderReviewCard(){
  const r=state.review,item=r.queue[r.index];
  // The round chrome stays mounted; only the changing card regions are updated.
  main.classList.remove('page-enter');
  if(r.preview)return renderPreviousReviewCard(r);
  if(!item){const study=r.scope==='study';main.innerHTML=`${pageHead('DONE','好样的，又完成了一小步！',study?'这轮学习只在当前页面进行，没有保存作答。':'练习结果已经保存在本机。')}<div class="finish-card"><div class="finish-mark">${icon('sparkles')}</div><h2>${r.queue.length} 条已完成</h2><p>${study?'可以再学一轮，或者回到词库继续添加。':r.wrongIds.size?`其中 ${r.wrongIds.size} 条需要再巩固。`:'这一轮没有留下待重练内容。'}</p><div class="actions">${r.previous?button('上一条','review-previous','light'):''}${!study&&r.wrongIds.size?button(`再练错题 · ${r.wrongIds.size}`,'retry-wrong','primary'):''}${r.itemType==='topic'?`<button class="btn light" data-route="review?${qs({collection:'academic',category_id:r.categoryId,scope:'topic',mode:'recall',start:1})}">再复习本专题</button>`:button('再选一轮','new-review','light')}${button(r.collection==='academic'&&r.categoryId?'返回专题':'返回今日','finish-review','text')}</div></div>`;return}
  const recall=r.mode==='recall',prompt=r.mode==='cloze'?item.cloze:r.mode==='zh_to_en'?item.chinese_meaning:item.term;
  const switching=r.motionIndex!==undefined&&r.motionIndex!==r.index;
  r.motionIndex=r.index;
  const noun=reviewTypeText[r.itemType]||reviewTypeText[item.item_type]||'内容';
  const html=`<div class="lesson-top">${button('退出练习','new-review','text')}${r.previous?button('上一条','review-previous','text'):''}<div class="lesson-progress" role="progressbar" aria-label="本轮进度" aria-valuenow="${r.index}" aria-valuemin="0" aria-valuemax="${r.queue.length}"><i style="width:${r.index/r.queue.length*100}%"></i></div><strong>${r.index+1} / ${r.queue.length}</strong></div>${pageHead(scopeText[r.scope],`${collectionText[r.collection||'general']}${r.categoryName?' · '+esc(r.categoryName):''} · ${noun} · ${modeText[r.mode]}`,r.scope==='study'?`只练刚加入的${noun}；答错也不会留下记录。`:r.itemType==='topic'?'按专题逐条回忆，点击查看中文揭晓释义。':`本轮只复习${noun}，不会混入其他类型。`)}<section class="review-card ${recall?'recall-card':''} ${switching?'review-card-switch':''}" data-card-index="${r.index}">
    <p class="lesson-instruction">${recall?(item.item_type==='word'?'这个词是什么意思？先在心里想一想。':item.item_type==='phrase'?'这个固定搭配是什么意思？先在心里想一想。':'这句话是什么意思？先在心里想一想。'):'先回忆一下，再写出你的答案。'}</p><div class="prompt">${esc(prompt)}</div>${recall&&item.phonetic?`<p class="phonetic">${esc(item.phonetic)}</p>`:''}
     ${recall?`<div class="meaning-slot" aria-live="polite">${r.answered?`<div class="meaning-uncovered"><span>中文释义</span><h2>${esc(item.chinese_meaning)}</h2>${button('查看详情',`detail-${item.id}`,'small light')}</div>`:`<div class="meaning-covered" aria-label="中文释义已遮住，正在回忆"><span class="cover-dots" aria-hidden="true"><i></i><i></i><i></i><i></i></span><p>先想一想，想好再揭晓</p></div>`}</div>${r.answered?`${r.scope==='study'||item.item_type==='sentence'?'':reviewMasteryPanel(item)}<div class="self-check">${r.scope==='study'?`<p>对照一下释义，准备好就继续。</p>${button('下一条','study-next','primary')}`:`<p>刚才的回忆和释义一致吗？</p><div class="self-ratings"><button class="btn unrecalled" data-rating="unrecalled">${icon('retry')}<span>未能回忆</span></button><button class="btn incorrect" data-rating="forgot">${icon('mistake')}<span>回忆有误</span></button><button class="btn primary" data-rating="remembered">${icon('check')}<span>回忆正确</span></button></div><small>“未能回忆”会获得更高的后续抽查权重。</small>`}</div>`:`<div class="recall-actions">${button('查看中文','reveal-meaning','primary')}<small>无需输入答案</small></div>`}`:`<form id="answer-form" class="answer-form"><div class="field"><label>${r.mode==='en_to_zh'?'输入你想到的中文意思':'输入完整英文答案'}</label><input id="answer" autocomplete="off" spellcheck="false" value="${esc(r.input)}" ${r.answered?'disabled':''}></div>${!r.answered?`<div class="actions"><button class="btn primary" type="submit">查看答案</button></div>`:''}</form>${r.answered?answerReveal(item,r):''}`}</section>`;
  updateReviewMarkup(html,r);
  bindMasteryBoost();
  if(recall)document.querySelector(r.answered?(r.scope==='study'?'[data-action="study-next"]':'[data-rating="remembered"]'):'[data-action="reveal-meaning"]')?.focus({preventScroll:true});
  else{document.querySelector('#answer-form').addEventListener('submit',submitAnswer);document.querySelector('#answer')?.focus({preventScroll:true})}
}
function updateReviewMarkup(html,r){
  const template=document.createElement('template');template.innerHTML=html;
  const incoming=template.content.querySelector('.review-card'),current=main.querySelector('.review-card');
  const chromeKey=[r.scope,r.collection,r.categoryId,r.itemType,r.mode].join(':');
  if(r.chromeKey!==chromeKey||!main.querySelector('.lesson-top')||main.querySelector('.review-lookback')){
    main.replaceChildren(template.content);r.chromeKey=chromeKey;return;
  }
  const top=main.querySelector('.lesson-top'),nextTop=template.content.querySelector('.lesson-top');
  const progress=top.querySelector('.lesson-progress'),nextProgress=nextTop.querySelector('.lesson-progress');
  progress.setAttribute('aria-valuenow',nextProgress.getAttribute('aria-valuenow'));
  progress.querySelector('i').style.width=nextProgress.querySelector('i').style.width;
  top.querySelector('strong').textContent=nextTop.querySelector('strong').textContent;
  const previous=nextTop.querySelector('[data-action="review-previous"]');
  if(previous&&!top.querySelector('[data-action="review-previous"]'))progress.before(previous);
  if(current?.dataset.cardIndex===incoming.dataset.cardIndex){
    // Revealing changes the meaning and controls; the prompt and surrounding components stay mounted.
    const slot=current.querySelector('.meaning-slot'),nextSlot=incoming.querySelector('.meaning-slot');
    if(slot&&nextSlot){
      slot.replaceChildren(...nextSlot.childNodes);
      while(slot.nextSibling)slot.nextSibling.remove();
      while(nextSlot.nextSibling)current.append(nextSlot.nextSibling);
    }else{
      const form=current.querySelector('#answer-form'),nextForm=incoming.querySelector('#answer-form');
      if(form&&nextForm){
        form.querySelector('#answer').disabled=nextForm.querySelector('#answer').disabled;
        form.querySelector('.actions')?.remove();
        while(form.nextSibling)form.nextSibling.remove();
        while(nextForm.nextSibling)current.append(nextForm.nextSibling);
      }
    }
  }else current.replaceWith(incoming);
}
function renderPreviousReviewCard(r){
  const previous=r.previous,item=r.queue[previous.index],prompt=r.mode==='cloze'?item.cloze:r.mode==='zh_to_en'?item.chinese_meaning:item.term;
  const returnLabel=r.index===r.queue.length?'返回本轮结果':'继续当前单词';
  main.innerHTML=`<div class="lesson-top">${button('退出练习','new-review','text')}${button(returnLabel,'review-continue','text')}<div class="lesson-progress" role="progressbar" aria-label="本轮进度" aria-valuenow="${r.index}" aria-valuemin="0" aria-valuemax="${r.queue.length}"><i style="width:${r.index/r.queue.length*100}%"></i></div><strong>${previous.index+1} / ${r.queue.length}</strong></div>${pageHead(scopeText[r.scope],'回看上一个单词','这条已经学过，查看不会重复记录。')}<section class="review-card review-lookback" data-card-index="${previous.index}"><p class="lesson-instruction">刚刚学过</p><div class="prompt">${esc(prompt)}</div><div class="answer-reveal"><span class="result-label">答案回看</span><h2>${esc(item.term)}</h2><p>${esc(item.chinese_meaning)}</p>${previous.input?`<p class="muted">刚才输入：${esc(previous.input)}</p>`:''}${item.synonyms?.length?`<p class="detail-subtle">可替换：${esc(item.synonyms.join('、'))}</p>`:''}${item.english_definition?`<p class="muted">${esc(item.english_definition)}</p>`:''}${item.source_sentence?`<blockquote>${esc(item.source_sentence)}</blockquote>`:''}${button('查看详情',`detail-${item.id}`,'small light')}</div><div class="lookback-actions">${button(returnLabel,'review-continue','primary')}</div></section>`;
  document.querySelector('[data-action="review-continue"]')?.focus({preventScroll:true});
}
function showPreviousReview(){const r=state.review;if(!r?.previous||r.preview||r.saving)return;const answer=document.querySelector('#answer');if(answer&&!r.answered)r.input=answer.value;r.preview=true;renderReviewCard()}
function continueReview(){const r=state.review;if(!r?.preview)return;r.preview=false;renderReviewCard()}
 function answerReveal(item,r){const self=r.mode==='en_to_zh',recommended=self?'':(r.correct?'remembered':'forgot');return `<div class="answer-reveal"><span class="result-label ${r.correct===false?'wrong':''}">${self?'请自行对照':r.correct===null?'先对照答案':'首轮答案'+(r.correct?'正确':'不正确')}</span><h2>${esc(item.term)}</h2><p>${esc(item.chinese_meaning)}</p>${item.synonyms?.length?`<p class="detail-subtle">可替换：${esc(item.synonyms.join('、'))}</p>`:''}${item.english_definition?`<p class="muted">${esc(item.english_definition)}</p>`:''}${item.source_sentence?`<blockquote>${esc(item.source_sentence)}</blockquote>`:''}${r.scope==='study'?`<p class="rating-prompt">对照完就继续，本次结果不会保存。</p>${button('下一条','study-next','primary')}`:`${item.item_type==='sentence'?'':reviewMasteryPanel(item)}<p class="rating-prompt">${item.item_type==='sentence'?'这次回忆得怎么样？':'这次掌握得怎么样？'}</p><div class="ratings">${Object.entries(ratingText).map(([k,label])=>`<button class="rating ${k===recommended?'recommended':''}" data-rating="${k}">${label}</button>`).join('')}</div>`}</div>`}
function submitAnswer(event){event.preventDefault();const answer=document.querySelector('#answer').value.trim();const r=state.review;if(!answer&&r.scope!=='study')return notify('请先输入答案');r.input=answer;r.correct=r.mode==='en_to_zh'||!answer?null:normalizeEnglish(answer)===normalizeEnglish(r.queue[r.index].term);r.answered=true;renderReviewCard()}
async function rateReview(rating,{boost=false,track=null}={}){
  const r=state.review;
  if(!r||r.scope==='study'||!r.answered||r.saving||r.preview||!r.queue[r.index])return;
  const item=r.queue[r.index],correct=['en_to_zh','recall'].includes(r.mode)?['remembered','easy'].includes(rating):r.correct;
  r.saving=true;r.token??=crypto.randomUUID();
  document.querySelectorAll('[data-rating]').forEach(x=>x.disabled=true);
  try{
    if(!boost&&document.querySelector('[data-mastery-boost][data-dragging]'))renderReviewCard();
    const payload={item_id:item.id,rating,mode:r.mode,answer:r.input,first_try_correct:correct,affects_schedule:r.scope==='due',scope:r.scope,client_token:r.token};
    let saved;
    try{saved=await api(boost?'/api/reviews/boost':'/api/reviews',{method:'POST',body:JSON.stringify(payload)})}
    catch(error){
      // A window may still be connected to the pre-recall local service until its idle timeout.
      if(boost||r.mode!=='recall'||!error.message.includes('复习模式无效'))throw error;
      saved=await api('/api/reviews',{method:'POST',body:JSON.stringify({...payload,mode:'en_to_zh',answer:'[遮罩自评]'})});
    }
    const from=item.status;Object.assign(item,saved);
    if(boost&&track?.isConnected&&state.review===r){
      track.classList.add('is-success');track.querySelector('.mastery-boost-thumb').innerHTML=icon('check');
      track.querySelector('.mastery-boost-label').textContent=`斩词成功 · ${statusText[saved.status]}`;
      const card=track.closest('.review-card');
      if(card){card.classList.add('is-slashed');const prompt=card.querySelector('.prompt');card.style.setProperty('--slash-y',`${prompt.getBoundingClientRect().top-card.getBoundingClientRect().top+prompt.offsetHeight*.55}px`)}
      if(!matchMedia('(prefers-reduced-motion: reduce)').matches)await new Promise(resolve=>setTimeout(resolve,460));
    }
    if(!correct)r.wrongIds.add(item.id);else r.wrongIds.delete(item.id);
    r.previous={index:r.index,input:r.input,correct:r.correct,rating};
    r.index++;r.answered=false;r.input='';r.correct=null;r.token=null;
    if(state.review===r){renderReviewCard();notify(boost?`斩词成功：${statusText[from]} → ${statusText[saved.status]}`:masteryOrder.indexOf(saved.status)<masteryOrder.indexOf(from)?`近期反复出错：${statusText[from]} → ${statusText[saved.status]}，已提高后续抽取权重。`:(!correct||['forgot','fuzzy','unrecalled'].includes(rating))?'已记录错误，提高后续全局抽取权重。':'回忆正确，继续加油！')}
    return true;
  }catch(error){notify(`保存失败：${error.message} 请重试，当前词条已保留。`);return false}
  finally{r.saving=false;if(state.review===r)document.querySelectorAll('[data-rating]').forEach(x=>x.disabled=false)}
}
function statsComparison(series,days,key){
  if(days==='all')return null;
  const count=Number(days),current=series.slice(-count),previous=series.slice(-count*2,-count);
  return current.reduce((sum,day)=>sum+day[key],0)-previous.reduce((sum,day)=>sum+day[key],0);
}
function statsMetric(label,value,symbol,comparison,detail,delay=70){
  const trend=comparison===null||comparison===0?'—':comparison>0?'+'+comparison+' ↑':comparison+' ↓';
  const trendClass=comparison===null||comparison===0?'flat':comparison>0?'up':'down';
  const context=detail.kind==='ring'?`<span class="metric-context ring"><span class="metric-progress" style="--metric-progress:${Math.max(0,Math.min(100,detail.progress))*3.6}deg"><i>${detail.value}</i></span><small>${detail.label}</small></span>`:`<span class="metric-context"><small>${detail.label}</small><b>${detail.value}</b></span>`;
  return '<div class="metric" data-enter style="--enter-delay:'+delay+'ms"><span class="metric-icon">'+icon(symbol)+'</span><div class="metric-copy"><span class="metric-label">'+label+'</span><strong>'+counter(value)+'</strong><span class="metric-trend">较上周期 <b class="'+trendClass+'">'+trend+'</b></span></div>'+context+'</div>';
}
// The local service can be a process that was started before the backend was updated, in which
// case it answers with the payload it was built for. Normalising at the boundary keeps an
// unrecognised shape from failing the whole route, and `detailed` names the one part that genuinely
// cannot be drawn so the insight module can say so instead of leaving a blank card behind.
function statsWindow(raw){
  const series=Array.isArray(raw?.series)?raw.series:[];
  return {...raw,series,
    mistakes:Array.isArray(raw?.mistakes)?raw.mistakes:[],
    error_map:errorMapWindow(raw?.error_map),
    status:raw?.status||null,
    hours:Array.isArray(raw?.hours)?raw.hours:null,
    accuracy:Array.isArray(raw?.accuracy)?raw.accuracy:null,
    accuracy_summary:raw?.accuracy_summary||null,
    detailed:Boolean(raw?.status)&&Array.isArray(raw?.hours)&&Array.isArray(raw?.accuracy)};
}
// The error map is one more field on the same payload, so a service that predates it simply has
// no key. It is normalised into a shape the card can always read: `null` means "this build cannot
// answer that question", which the card reports, and every number below is either real or null -
// never NaN, never undefined, and never a stray string that would print inside a counter.
function errorMapWindow(raw){
  if(!raw||!Array.isArray(raw.words))return null;
  const number=value=>(value===null||value===undefined||value==='')?null:(Number.isFinite(Number(value))?Number(value):null);
  const summary=raw.summary||{};
  return {...raw,
    attempts:number(raw.attempts)||0,
    summary:{errors:number(summary.errors)||0,words:number(summary.words)||0,error_rate:number(summary.error_rate),avg_streak:number(summary.avg_streak)},
    deltas:raw.deltas||{},
    bands:Array.isArray(raw.bands)?raw.bands:[],
    words:raw.words.map(word=>({...word,errors:number(word.errors)||0,attempts:number(word.attempts)||0,error_rate:number(word.error_rate)}))};
}
function activityWindow(raw){return {...raw,series:Array.isArray(raw?.series)?raw.series:[]}}
// Shown in place of the four panels when the service behind the page is older than the page. The
// rest of the statistics still render, so this reports one unavailable module rather than an error.
function staleInsight(){
  return `<header class="insight-head"><div class="insight-head-copy"><span class="eyebrow">BEHAVIOUR</span><h2>学习行为洞察</h2><p>从多个维度了解你的学习习惯，找到更适合自己的节奏。</p></div></header><p class="insight-stale">${icon('clock')}<span>统计服务仍是更新前的版本，行为数据暂时不可用。关闭并重新打开应用后即可恢复。</span></p>`;
}
async function renderStats(ctx=pageMotion.current()){
  const days=sessionStorage.getItem('stats-days')||'7';
  const [rawStats,rawActivity,expressionSummary]=await Promise.all([ctx.request(`/api/stats?days=${days}`),ctx.request('/api/activity?days=371'),ctx.request('/api/expression-summary')]);
  if(!ctx.isCurrent())return;
  const data=statsWindow(rawStats),activity=activityWindow(rawActivity);
  // The drawer lists the very records this render is summarising, so the payload the card came
  // from is what it opens with - one window, one set of numbers, no second fetch to drift.
  state.errorMap=data.error_map;state.errorMapDays=days;
  // A range switch repaints the numbers and the four charts inside the view that is already on
  // screen; only a route change builds the page from scratch. That is what keeps the staged
  // entrance from replaying while the reader compares two windows.
  if(main.querySelector('.insight-card'))return ctx.commit(()=>swapStatsView(data,activity,days));
  return ctx.commit(()=>{main.innerHTML=`${pageHead('INSIGHTS','学习统计','单词复习与表达阅读分开记录，各自保持原有含义。',statsRangeSwitch(days))}<div class="metric-rail stats-metrics">${statsMetricsMarkup(data,activity,days)}</div>${activityGrid(activity)}<section class="stats-grid"><section class="insight-card" data-enter style="--enter-delay:270ms"><div class="insight-outline">${insightOutline(data,days)}</div></section>${errorMapCard(data,days)}</section>${expressionStatsMarkup(expressionSummary)}`;
  });
}
function statsRangeSwitch(days){
  return `<div class="stats-switch">${button('7 天','stats-7',days==='7'?'primary':'light')}${button('30 天','stats-30',days==='30'?'primary':'light')}${button('全部','stats-all',days==='all'?'primary':'light')}</div>`;
}
function statsMetricsMarkup(data,activity,days){
  const additions=data.series.reduce((n,x)=>n+x.added,0),reviews=data.series.reduce((n,x)=>n+x.reviews,0),periodDays=Math.max(1,data.series.length);
  const activityWindow=days==='all'?activity.series:activity.series.slice(-Number(days));
  const activeDays=activityWindow.filter(point=>Number(point.score)>0).length;
  const totalWords=Object.values(data.status||{}).reduce((sum,value)=>sum+(Number(value)||0),0);
  const masteredRate=totalWords?Math.round(data.mastered/totalWords*100):0;
  return statsMetric('新增词汇',additions,'pencil',statsComparison(activity.series,days,'added'),{label:'本周期日均',value:(additions/periodDays).toFixed(1)},70)
    +statsMetric('练习次数',reviews,'bolt',statsComparison(activity.series,days,'reviews'),{label:'活跃天数',value:`${activeDays} / ${activityWindow.length}`},115)
    +statsMetric('已掌握',data.mastered,'bookmark',null,{label:'占词库比例',value:`${masteredRate}%`,progress:masteredRate,kind:'ring'},160);
}
// ---- Error map ------------------------------------------------------------
// The right-hand card answers two questions only: how much of the collection is going wrong, and
// which words are behind it. It reads one window of the same records as the rest of the page, so
// the ranking, the four figures and the ring can never disagree with each other.
const errorBandColors={high:'#e5928a',mid:'#f0ce6b',low:'#9ed073',rare:'#c9d3c6'};
const errorBandFallback=['#e5928a','#f0ce6b','#9ed073','#c9d3c6'];
// The ranking's ceiling. Five rows is what the card holds beside the four figures and the ring, and
// it is a line count rather than a count of words - which is why it is stated once and shared by the
// list, the tail and the top-up below.
const RANKING_ROWS=5;
// The band list is taken from the payload rather than hardcoded here, so a band the service
// defines and this page does not know about still gets a slice instead of silently leaving the
// ring short of the total printed in its middle.
function errorBands(map){
  return map.bands.map((band,index)=>({key:band.key,label:band.label,value:Number(band.value)||0,color:errorBandColors[band.key]||errorBandFallback[index%errorBandFallback.length]}));
}
function errorRangeSelect(days){
  const options=[['7','近 7 天'],['30','近 30 天'],['all','全部']];
  return `<label class="em-range"><select data-error-range aria-label="错误统计的时间范围">${options.map(([value,label])=>`<option value="${value}"${String(days)===value?' selected':''}>${label}</option>`).join('')}</select>${icon('chevron')}</label>`;
}
// Lower is better for all four figures, so an increase is the unfavourable direction here and is
// coloured as such rather than following the usual "up is green" reading.
function errorKpi(label,value,delta,delay){
  const missing=delta===null||delta===undefined;
  const trend=missing||delta===0?'flat':delta>0?'up':'down';
  const text=missing?'—':delta===0?'0%':`${delta>0?'↑':'↓'} ${Math.abs(delta)}%`;
  return `<div class="em-kpi" data-enter style="--enter-delay:${delay}ms"><strong>${value}</strong><span class="em-kpi-label">${label}</span><span class="em-trend ${trend}">${text}</span></div>`;
}
function errorTip(word){
  return `<b>${esc(word.term)}</b><span>${esc(word.chinese_meaning||'—')}</span><span>${word.errors} 错 / ${word.attempts} 次 · 错误率 ${word.error_rate}%</span><span>最近错误 ${word.last_error_at?formatDate(word.last_error_at):'—'}</span>`;
}
function errorRow(word,index,{band='',tip='',outside=false}={}){
  return `<li class="mistake-row${band?' em-drawer-row':''}${outside?' is-outside':''}"${tip?` data-tip="${esc(tip)}"`:''}><b>${index+1}</b><span><strong>${esc(word.term)}</strong><small>${esc(word.chinese_meaning||'—')}</small></span>${band?`<i class="em-band">${esc(band)}</i>`:''}<em>${word.errors} 错 / ${word.attempts} 次</em>${band?`<u class="em-rate">${word.error_rate}%</u>`:''}</li>`;
}
// Keep the selected window first, then use the existing all-time mistake list to fill any empty
// ranks. A short window can contain only three wrong words, but that must not make ranks four and
// five look as though the words were deleted. The figures and ring below remain window-specific.
function errorRanking(map,allTimeWords=[]){
  const words=map.words.slice(0,RANKING_ROWS),seen=new Set(words.map(word=>word.id));
  for(const word of allTimeWords){
    if(words.length>=RANKING_ROWS)break;
    if(!seen.has(word.id)){words.push(word);seen.add(word.id)}
  }
  const items=words.map((word,index)=>errorRow(word,index,{tip:errorTip(word)}));
  return `<ol class="em-ranking">${items.join('')}</ol>`;
}
function errorMapBody(data,days){
  const map=data.error_map;
  if(!map)return '<header class="em-head"><div><span class="eyebrow">ERROR MAP</span><h2>易错词</h2></div></header><p class="em-stale">'+icon('clock')+'<span>统计服务仍是更新前的版本，错词统计暂时不可用。关闭并重新打开应用后即可恢复。</span></p>';
  const summary=map.summary,deltas=map.deltas||{};
  const bands=errorBands(map),total=bands.reduce((sum,band)=>sum+band.value,0),denominator=total||1;
  const kpis=[
    ['总错误次数',counter(summary.errors),deltas.errors],
    ['涉及词汇数',counter(summary.words),deltas.words],
    ['平均错误率',summary.error_rate===null?'—':counter(summary.error_rate)+'%',deltas.error_rate],
    ['平均连续错误',summary.avg_streak===null?'—':counter(summary.avg_streak),deltas.avg_streak]
  ];
  // The tail rides inside the list rather than beside it: as a sibling of the list it would also
  // pick up the body's own gap, and that extra 12px is exactly the room the ring needs to stay on
  // screen once the ranking reaches its five-row ceiling.
  const ranking=map.words.length||data.mistakes.length
    ? errorRanking(map,data.mistakes)
    : `<div class="em-empty">${icon('check')}<strong>本周期暂无错词</strong><span>继续保持这个节奏</span></div>`;
  return `<header class="em-head"><div><span class="eyebrow">ERROR MAP</span><h2>易错词</h2></div>${map.words.length?`<button class="btn small light em-all" type="button" data-action="error-map-all">查看全部${icon('chevron')}</button>`:''}</header>
    <div class="em-body">
      ${ranking}
      <section class="em-block em-summary"><header class="em-block-head"><h3>整体错误情况</h3>${errorRangeSelect(days)}</header><div class="em-kpis">${kpis.map(([label,value,delta],index)=>errorKpi(label,value,delta,320+index*30)).join('')}</div></section>
      <section class="em-block em-dist"><header class="em-block-head"><h3>错误词状态分布</h3></header><div class="donut-layout em-donut" data-donut>${donutChart({segments:bands.map(band=>({...band,tip:`<b>${band.label}</b><span>${band.value} 个词 · ${Math.round(band.value/denominator*100)}%</span>`})),center:counter(summary.words),caption:'错词数',summary:`本周期有错误记录的 ${summary.words} 个词，按错误程度分为四类。`})}<ul class="donut-legend">${bands.map((band,index)=>`<li data-arc="${index}"><i style="background:${band.color}"></i><span>${band.label}</span><b>${band.value}</b><em>${Math.round(band.value/denominator*100)}%</em></li>`).join('')}</ul></div></section>
    </div>`;
}
// The wrapper is what a range switch repaints in place, so the card's own entrance animation is
// never replayed while the reader compares two windows.
function errorMapOutline(data,days){
  return `<div class="em-outline">${errorMapBody(data,days)}</div>`;
}
function errorMapCard(data,days){
  return `<div class="mistake-card error-card" data-enter style="--enter-delay:320ms">${errorMapOutline(data,days)}</div>`;
}
// Every word with a wrong answer in the window, not just the five on the card. It reads the
// payload the card was built from, so what the drawer lists is exactly what the figures counted.
function errorDrawerRows(words,bands){
  return words.length
    ? words.map((word,index)=>errorRow(word,index,{band:bands[word.band]||'错误',tip:errorTip(word)})).join('')
    : '<li class="em-drawer-none">没有匹配的错词</li>';
}
function errorDrawer(map,days,labels){
  const scope=days==='all'?'全部记录':`近 ${days} 天`;
  return `<div class="em-drawer-card">
    <header class="em-drawer-head"><div><span class="eyebrow">ERROR MAP</span><h2>全部错词</h2><p>${scope}内 <b data-error-count>${map.words.length}</b> 个词出现过错误，合计 ${map.summary.errors} 次；错误率 = 错误次数 ÷ 作答次数。</p></div><button class="btn small light em-drawer-close" type="button" data-action="close-dialog" aria-label="关闭全部错词">${icon('close')}</button></header>
    ${map.words.length?`<div class="em-drawer-tools"><input type="search" data-error-search placeholder="搜索错词或中文释义" aria-label="搜索错词"></div>`:''}
    <ol class="em-drawer-list" data-error-list>${errorDrawerRows(map.words,labels)}</ol>
    <footer class="em-drawer-foot"><span>按错误次数、错误率、最近错误时间排序</span>${map.words.length?button('开始错词重练','review-mistakes','small light'):''}</footer>
  </div>`;
}
// The four panels share one window: the 30-day view sums every three days instead of sampling
// dates, and the monthly view sums whole months, so no window silently drops a day of practice.
function statsViews(data,days){
  const graded=new Map((data.accuracy||[]).map(point=>[point.date,point]));
  const merged=data.series.map(point=>({...point,...(graded.get(point.date)||{attempts:0,correct:0})}));
  if(days==='all')return {rhythm:monthlyStats(data.series),accuracy:monthlyStats(merged,['attempts','correct'])};
  if(days==='30')return {rhythm:bucketStats(data.series,3),accuracy:bucketStats(merged,3,['attempts','correct'])};
  return {rhythm:data.series,accuracy:merged};
}
function rangeLabel(point,days){
  if(days==='all')return point.date.slice(0,7).replace('-','/');
  return point.label||formatDate(point.date);
}
function slashDate(value){return value?value.replace(/-/g,'/'):'—'}
const hourPeriods=['清晨','上午','下午','晚上'];
function donutSegments(status){
  const count=key=>Number(status?.[key])||0;
  return [
    {label:'已掌握',value:count('mastered'),color:'#5faa38'},
    {label:'熟悉中',value:count('familiar')+count('learning'),color:'#9ed073'},
    {label:'陌生',value:count('new'),color:'#f0ce6b'},
    {label:'易错',value:count('wrong'),color:'#e5928a'}
  ];
}
function insightOutline(data,days){
  if(!data.detailed)return staleInsight();
  const views=statsViews(data,days);
  const first=data.series[0]?.date,last=data.series[data.series.length-1]?.date;
  const range=first&&last?`${slashDate(first)} – ${slashDate(last)}`:'—';
  const rhythm=views.rhythm.map(x=>({label:rangeLabel(x,days),value:x.reviews,tip:`<b>${rangeLabel(x,days)}</b><span>练习 ${x.reviews} 次</span><span>新增 ${x.added} 个词条</span>`}));
  const accuracy=views.accuracy.map(x=>{
    const attempts=x.attempts||0;
    return {label:rangeLabel(x,days),value:attempts?Math.round(x.correct/attempts*100):null,tip:`<b>${rangeLabel(x,days)}</b><span>正确率 ${attempts?Math.round(x.correct/attempts*100):0}%</span><span>作答 ${attempts} 次</span>`};
  });
  const segments=donutSegments(data.status),total=segments.reduce((sum,segment)=>sum+segment.value,0),denominator=total||1;
  const hours=data.hours||[],best=hours.reduce((top,item)=>(!top||item.reviews>top.reviews?item:top),null);
  const hourChip=best&&best.reviews
    ? `<span class="insight-chip">${icon('clock')}<span><strong>${hourPeriods[hours.indexOf(best)]}是你的高效时段</strong><small>继续保持这个节奏</small></span></span>`
    : '';
  const accuracySummary=data.accuracy_summary||{};
  const accuracyChip=accuracySummary.rate==null
    ? ''
    : `<span class="insight-chip">${icon('trend')}<span><strong>最近正确率 ${accuracySummary.rate}%</strong><small>${accuracySummary.delta==null?'还没有可比的上周期':`比上周期 ${accuracySummary.delta>0?'+':''}${accuracySummary.delta}%`}</small></span></span>`;
  const hoursMax=Math.max(1,...hours.map(item=>item.reviews));
  const bars=hours.map(x=>({label:x.label,value:x.reviews,text:counter(x.reviews),tip:`<b>${x.label}</b><span>练习 ${x.reviews} 次 · 占比 ${Math.round(x.reviews/hoursMax*100)}%</span>`}));
  return `<header class="insight-head"><div class="insight-head-copy"><span class="eyebrow">BEHAVIOUR</span><h2>学习行为洞察</h2><p>从多个维度了解你的学习习惯，找到更适合自己的节奏。</p></div><span class="insight-range">${range}</span></header>
    <div class="insight-grid">
      <article class="insight-block"><header class="insight-block-head"><h3>${days==='all'?'月度练习节奏':'最近练习节奏'}</h3>${button('近 7 天','stats-7',`insight-filter small ${days==='7'?'primary':'light'}`)}</header><div class="insight-figure">${lineChart({points:rhythm,showValues:days==='7',summary:`最近练习节奏，共 ${rhythm.length} 个数据点。`})}</div></article>
      <article class="insight-block"><header class="insight-block-head"><h3>单词状态分布</h3><small class="insight-note">共 ${total} 个词条</small></header><div class="donut-layout" data-donut>${donutChart({segments:segments.map(segment=>({...segment,tip:`<b>${segment.label}</b><span>${segment.value} 个词条 · ${Math.round(segment.value/denominator*100)}%</span>`})),center:counter(total),caption:'总词数',summary:`共 ${total} 个词条，已掌握 ${segments[0].value} 个。`})}<ul class="donut-legend">${segments.map((segment,index)=>`<li data-arc="${index}"><i style="background:${segment.color}"></i><span>${segment.label}</span><b>${segment.value}</b><em>${Math.round(segment.value/denominator*100)}%</em></li>`).join('')}</ul></div></article>
      <article class="insight-block"><header class="insight-block-head"><h3>各时段练习分布</h3>${hourChip}</header>${barChart({bars,summary:'按四个时段统计的练习次数。'})}</article>
      <article class="insight-block"><header class="insight-block-head"><h3>正确率趋势</h3>${accuracyChip}</header><div class="insight-figure">${lineChart({points:accuracy,ticks:[0,50,100],suffix:'%',summary:'最近正确率趋势，上限 100%。'})}</div></article>
    </div>`;
}
// Ring focus is driven from either side: an arc lights its legend row and a legend row lights its
// arc, and the rest of the ring steps back rather than the chart spinning or resizing.
function clearDonut(node){
  node.classList.remove('is-focused');
  node.querySelectorAll('.insight-arc.is-active').forEach(arc=>arc.classList.remove('is-active'));
  node.querySelectorAll('.donut-legend li.is-active').forEach(item=>item.classList.remove('is-active'));
}
document.addEventListener('pointerover',event=>{
  const entry=event.target.closest?.('.insight-arc, .donut-legend li');
  const layout=entry&&entry.closest('[data-donut]');
  document.querySelectorAll('[data-donut].is-focused').forEach(node=>{if(node!==layout)clearDonut(node)});
  if(!layout)return;
  const index=Number(entry.dataset.arcIndex??entry.dataset.arc);
  layout.classList.add('is-focused');
  layout.querySelectorAll('.insight-arc').forEach(arc=>arc.classList.toggle('is-active',Number(arc.dataset.arcIndex)===index));
  layout.querySelectorAll('.donut-legend li').forEach(item=>item.classList.toggle('is-active',Number(item.dataset.arc)===index));
});
document.addEventListener('pointerout',event=>{
  const entry=event.target.closest?.('.insight-arc, .donut-legend li');
  const layout=entry&&entry.closest('[data-donut]');
  if(layout&&!layout.contains(event.relatedTarget))clearDonut(layout);
});
// Rapid clicks cannot interleave: every swap carries a token, and a swap that has been superseded
// leaves the DOM to the newer one instead of writing its own stale numbers over the top.
let statsSwapToken=0;
function swapStatsView(data,activity,days){
  const rail=main.querySelector('.stats-metrics'),outline=main.querySelector('.insight-outline'),errors=main.querySelector('.em-outline');
  if(!rail||!outline)return;
  // The staged entrance belongs to the first paint of the page. Dropping it here lets the rewritten
  // cards land in their finished state instead of re-running the whole choreography.
  main.classList.remove('page-enter');
  hideChartTip();
  updateRangeControls(days);
  // The drawer must list the window that is on screen, so it is re-pointed at every swap.
  state.errorMap=data.error_map;state.errorMapDays=days;
  const token=(statsSwapToken+=1);
  rail.classList.add('is-swapping');
  outline.classList.add('is-swapping');
  errors?.classList.add('is-swapping');
  setTimeout(()=>{
    if(token!==statsSwapToken||!rail.isConnected||!outline.isConnected)return;
    rail.innerHTML=statsMetricsMarkup(data,activity,days);
    outline.innerHTML=insightOutline(data,days);
    rail.classList.remove('is-swapping');
    outline.classList.remove('is-swapping');
    if(errors&&errors.isConnected){
      errors.innerHTML=errorMapBody(data,days);
      errors.classList.remove('is-swapping');
    }
  },140);
}
// ---- Error map entry points ----------------------------------------------
function errorBandLabels(map){
  const labels={};
  map.bands.forEach(band=>{labels[band.key]=band.label});
  return labels;
}
// 查看全部 promises every wrong word, so it has to mean every wrong word. The card's ranking, its
// four figures and the ring all describe the range the reader picked - that is what the range
// selector is for - but this drawer is the one surface that answers "what have I got wrong at all".
// Reading it through the card's window is how a range selector two blocks further down turns an
// error word from ten days ago into an apparently deleted one.
async function allTimeErrorMap(){
  try{return errorMapWindow((await api('/api/stats?days=all'))?.error_map)}catch{return null}
}
async function openErrorDrawer(){
  const all=await allTimeErrorMap();
  const map=all||state.errorMap,days=all?'all':state.errorMapDays;
  if(!map||!map.words.length)return;
  state.errorDrawer={map,days};
  openDrawer(errorDrawer(map,days,errorBandLabels(map)));
}
// The list is filtered in place: the payload is already in memory and nothing about it changes,
// so searching never waits on the service and never loses the reader's place in the drawer.
function filterErrorDrawer(input){
  const list=document.querySelector('[data-error-list]'),map=state.errorDrawer?.map;
  if(!list||!map)return;
  const query=input.value.trim().toLowerCase();
  const words=query?map.words.filter(word=>`${word.term} ${word.chinese_meaning||''}`.toLowerCase().includes(query)):map.words;
  list.innerHTML=errorDrawerRows(words,errorBandLabels(map));
  const count=document.querySelector('[data-error-count]');
  if(count)count.textContent=String(words.length);
  list.scrollTop=0;
}
new MutationObserver(()=>{
  const input=dialogBody.querySelector('[data-error-search]');
  bindSearchInput(input,()=>filterErrorDrawer(input),{delay:120,isCurrent:()=>dialog.open});
}).observe(dialogBody,{childList:true,subtree:true});
document.addEventListener('change',async event=>{
  const select=event.target.closest?.('[data-error-range]');
  if(!select)return;
  // One range for the whole page: the card's dropdown writes the same value the page-level switch
  // does, so the four figures, the ring and the ranking always describe one window.
  sessionStorage.setItem('stats-days',select.value);
  state.errorMapDays=select.value;
  try{await renderStats()}catch(error){notify(error.message)}
});
function updateRangeControls(days){
  main.querySelectorAll('[data-action^="stats-"]').forEach(node=>{
    const on=(node.dataset.action==='stats-all'?'all':(node.dataset.action==='stats-30'?'30':'7'))===days;
    node.classList.toggle('primary',on);
    node.classList.toggle('light',!on);
    node.setAttribute('aria-pressed',String(on));
  });
}
async function importCsv(event){const file=event.target.files[0];if(!file)return;try{const response=await fetch(`/api/import.csv?${qs({collection:libraryCollection(),category_id:state.filters.category_id})}`,{method:'POST',headers:{'Content-Type':'text/csv'},body:file}),data=await response.json();if(!response.ok)throw new Error(data.error?.message||'导入失败');notify(`导入完成：新增 ${data.created}，跳过 ${data.skipped}，失败 ${data.failed}`);renderLibrary()}catch(error){notify(error.message)}finally{event.target.value=''}}
function download(path){const a=document.createElement('a');a.href=path;document.body.append(a);a.click();a.remove()}
// Match only real navigation controls. `<body>` also carries `data-route` (the stats page keys its
// entry animations off `body[data-route="stats"]`), so an unanchored attribute lookup resolves to
// the body for every click in the app and turns each one into a routeTo() — which clears
// state.review and re-renders, cancelling downloads and discarding half-typed forms.
document.addEventListener('click',event=>{const t=event.target.closest('a[data-route], button[data-route]');if(t){event.preventDefault();routeTo(t.dataset.route)}},true);
document.addEventListener('click',async event=>{const control=event.target.closest('[data-expression-action]');if(!control)return;event.preventDefault();const action=control.dataset.expressionAction;try{if(action==='clear-filters'){state.expressionFilters={q:'',type:'',exam:'',topic:'',tag:'',favorite:'',sort:'recent'};return renderExpressions()}if(action==='back')return routeTo('expressions');if(action==='favorite'){const id=Number(control.dataset.id),favorite=control.dataset.favorite==='1';const saved=await api(`/api/expressions/${id}/favorite`,{method:'PUT',body:JSON.stringify({favorite})});notify(favorite?'已收藏':'已取消收藏');if(state.expressionReader?.id===id){state.expressionReader={...state.expressionReader,is_favorite:saved.is_favorite};return renderExpressionReader(id)}return renderExpressions()}if(action==='delete'){const item=await api(`/api/expressions/${control.dataset.id}`);return openDialog(`<div class="dialog-card"><h2>删除“${esc(item.title)}”？</h2><p>素材与阅读记录都会删除，这一步无法撤销；单词数据不会受到影响。</p><div class="dialog-actions"><button class="btn light" type="button" data-action="close-dialog">取消</button><button class="btn danger" type="button" data-expression-action="confirm-delete" data-id="${item.id}">确认删除</button></div></div>`)}if(action==='confirm-delete'){if(control.disabled)return;control.disabled=true;try{await api(`/api/expressions/${control.dataset.id}`,{method:'DELETE'});clearTimeout(expressionScrollTimer);state.expressionReader=null;closeDialog();notify('阅读素材已删除');return routeTo('expressions')}finally{control.disabled=false}}const item=state.expressionReader,paper=document.querySelector('.expression-paper');if(!item||!paper)return;if(action==='translation'){const visible=!paper.classList.contains('show-translation');paper.classList.toggle('show-translation',visible);paper.classList.toggle('hide-translation',!visible);item.translation_visible=visible;control.setAttribute('aria-pressed',String(visible));control.querySelector('span').textContent=visible?'隐藏中文翻译':'显示中文翻译';control.querySelector('i').classList.toggle('on',visible);return persistExpressionState()}if(action==='font-down'||action==='font-up'){item.font_scale=Math.min(1.35,Math.max(.85,(Number(item.font_scale)||1)+(action==='font-up'?.05:-.05)));updateReaderPaper();return persistExpressionState()}if(action==='line-compact'||action==='line-comfy'){item.line_height=action==='line-comfy'?2.05:1.62;updateReaderPaper();return persistExpressionState()}}catch(error){notify(error.message)}});
document.addEventListener('click',async event=>{const t=event.target.closest('[data-action],[data-scope],[data-mode],[data-rating]');if(!t)return;try{if(t.dataset.scope){state.reviewSetup.scope=t.dataset.scope;if(t.dataset.scope==='today')state.reviewSetup.mode='recall';document.querySelectorAll('[data-scope]').forEach(x=>{x.classList.toggle('selected',x===t);x.setAttribute('aria-pressed',String(x===t))});document.querySelectorAll('[data-mode]').forEach(x=>{const selected=x.dataset.mode===state.reviewSetup.mode;x.classList.toggle('selected',selected);x.setAttribute('aria-pressed',String(selected))});syncReviewSetupUi(t.dataset.scope);return}if(t.dataset.mode){state.reviewSetup.mode=t.dataset.mode;document.querySelectorAll('[data-mode]').forEach(x=>{x.classList.toggle('selected',x===t);x.setAttribute('aria-pressed',String(x===t))});return}if(t.dataset.rating)return rateReview(t.dataset.rating);const a=t.dataset.action;if(!a)return;if(a==='reveal-meaning'){if(state.review?.mode==='recall'&&!state.review.answered){state.review.answered=true;renderReviewCard()}return}if(a==='quick-recall')return routeTo('review?mode=recall');if(a==='quick-spelling')return routeTo('review?mode=zh_to_en');if(a==='review-due')return routeTo('review?scope=due');if(a==='review-today')return routeTo('review?scope=today&mode=recall&start=1');if(a==='go-add')return routeTo(`add?collection=${libraryCollection()==='academic'?'academic':'general'}&type=${['library','reading','academic'].includes(state.route)&&state.filters.item_group==='sentence'?'sentence':state.filters.item_type||'word'}${libraryCollection()==='academic'&&state.filters.category_id&&state.filters.category_id!=='uncategorized'?'&category_id='+encodeURIComponent(state.filters.category_id):''}`);if(a==='clear-library-filters'){resetSearchInput(document.querySelector('#search'));document.querySelectorAll('[data-filter]').forEach(select=>{if(select.dataset.filter!=='sort')select.value=''});state.filters={...state.filters,page:1,q:'',item_type:'',source:'',tag:'',status:''};return refreshLibraryContent()}if(a==='add-phrase')return routeTo('add?type=phrase');if(a==='new-review'&&state.review?.itemType==='topic')return routeTo(`academic?${qs({category_id:state.review.categoryId})}`);if(a==='go-review'||a==='new-review')return routeTo(state.review?.collection==='academic'?`review?${qs({collection:'academic',category_id:state.review?.categoryId})}`:'review');if(a==='review-mistakes'){if(dialog.open)closeDialog();return routeTo('review?scope=mistakes')}if(a==='retry')return routeTo(state.route);if(a==='go-library')return returnToLibrary();if(a==='clipboard-paste')return pasteFromClipboard();if(a==='parse-dictionary')return fillDictionaryFields();if(a==='toggle-more')return document.querySelector('#more-fields').classList.toggle('open');if(a==='error-map-all')return openErrorDrawer();if(a==='detail')return showDetail(t.dataset.id);if(a.startsWith('detail-'))return showDetail(a.split('-')[1]);if(/^edit-\d+$/.test(a)){if(dialog.open)closeDialog();return routeTo(`add?edit=${a.split('-')[1]}`)}if(/^delete-\d+$/.test(a)){const id=a.split('-')[1],item=await api(`/api/items/${id}`);return openDialog(`<div class="dialog-card" data-delete-collection="${item.collection}"><h2>删除“${esc(item.term)}”？</h2><p>词条及其复习记录会被删除，这一步无法撤销。</p><div class="dialog-actions">${button('取消','close-dialog','light')}${button('确认删除',`confirm-delete-${id}`,'danger')}</div></div>`)}if(a.startsWith('confirm-delete-')){if(t.disabled)return;const id=Number(a.split('-').pop()),collection=dialogBody.querySelector('[data-delete-collection]')?.dataset.deleteCollection;t.disabled=true;try{await api(`/api/items/${id}`,{method:'DELETE'});state.selected.delete(id);closeDialog();notify('词条已删除');if(['library','reading','academic'].includes(state.route)){if(main.querySelectorAll('.library-row').length===1&&state.filters.page>1)state.filters.page--;return renderLibrary()}return routeTo(collection==='academic'?'academic':'reading')}finally{t.disabled=false}}if(a==='close-dialog')return closeDialog();if(a==='toggle-organize'){state.categoryOrganize=false;state.organize=!state.organize;state.selected.clear();state.editingGroup=null;return renderLibrary()}if(a==='clear-selection'){state.selected.clear();return renderLibrary()}if(a==='organize-with'){state.categoryOrganize=false;state.organize=true;state.selected=new Set([Number(t.dataset.id),...t.dataset.suggest.split(',').map(Number)]);closeDialog();if(['library','reading','academic'].includes(state.route))return renderLibrary();routeTo(libraryCollection()==='academic'?'academic':'reading');return renderLibrary()}if(a==='save-group'){const payload={name:document.querySelector('#group-name').value,item_ids:[...state.selected]};if(state.editingGroup)await api(`/api/confusion-groups/${state.editingGroup.id}`,{method:'PUT',body:JSON.stringify(payload)});else await api('/api/confusion-groups',{method:'POST',body:JSON.stringify(payload)});state.organize=false;state.selected.clear();state.editingGroup=null;notify('易混词组已保存');return renderLibrary()}if(a==='edit-group'){const g=await api(`/api/confusion-groups/${t.dataset.id}`);state.categoryOrganize=false;state.organize=true;state.editingGroup=g;state.selected=new Set(g.items.map(x=>x.id));return renderLibrary()}if(a==='delete-group'){const g=await api(`/api/confusion-groups/${t.dataset.id}`);return openDialog(`<div class="dialog-card"><h2>删除“${esc(g.name)}”？</h2><p>分组中的词条会保留。</p><div class="dialog-actions">${button('取消','close-dialog','light')}${button('确认删除分组',`confirm-group-delete-${g.id}`,'danger')}</div></div>`)}if(a.startsWith('confirm-group-delete-')){await api(`/api/confusion-groups/${a.split('-').pop()}`,{method:'DELETE'});closeDialog();notify('分组已删除');return renderLibrary()}if(a==='csv-template')return download('/api/template.csv');if(a==='csv-export')return download(`/api/export.csv?${qs({collection:libraryCollection(),category_id:state.filters.category_id})}`);if(a==='start-review'){t.disabled=true;try{await startReview()}finally{t.disabled=false}return}if(a==='reset-round'){await api('/api/review-round/reset',{method:'POST',body:'{}'});notify('新的今日轮次已开始');return}if(a==='retry-wrong'){const r=state.review,ids=new Set(r.wrongIds);r.queue=r.queue.filter(x=>ids.has(x.id));r.index=0;r.scope='mistakes';r.answered=false;r.input='';r.correct=null;r.saving=false;r.token=null;r.wrongIds=new Set();return renderReviewCard()}if(a==='finish-review'){const r=state.review;return routeTo(r?.collection==='academic'&&r.categoryId?`academic?${qs({category_id:r.categoryId})}`:'today')}if(['stats-7','stats-30','stats-all'].includes(a)){sessionStorage.setItem('stats-days',a==='stats-all'?'all':(a.endsWith('7')?'7':'30'));return renderStats()}}catch(error){notify(error.message)}});
window.addEventListener('hashchange',()=>{state.review=null;render()});dialog.addEventListener('click',e=>{if(e.target===dialog)closeDialog()});dialog.addEventListener('close',()=>dialog.classList.remove('is-drawer'));setInterval(()=>fetch('/api/heartbeat',{method:'POST'}).catch(()=>{}),60000);fetch('/api/heartbeat',{method:'POST'}).catch(()=>{});render();

function submitItemFormFromPageEnter(e){
  if(e.key!=='Enter'||e.defaultPrevented||e.isComposing||e.repeat||e.ctrlKey||e.altKey||e.metaKey||e.shiftKey||state.route!=='add'||dialog.open)return;
  if(e.target instanceof Element&&e.target.closest('input, textarea, select, button, a, [contenteditable="true"], [role="button"]'))return;
  const form=document.querySelector('#item-form');
  if(!form)return;
  e.preventDefault();
  form.requestSubmit()
}
document.addEventListener('keydown',submitItemFormFromPageEnter);
document.addEventListener('keydown',e=>{if((e.key==='Enter'||e.key===' ')&&e.target.matches('.word-row')){e.preventDefault();showDetail(e.target.dataset.id).catch(error=>notify(error.message))}});
