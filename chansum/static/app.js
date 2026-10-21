'use strict';
let csrf = document.querySelector('meta[name=chansum-token]').content;
const $ = (s, root=document) => root.querySelector(s);
const state = {lists:[],items:[],jobs:[],selected:new Set(),q:'',sort:'latest',kind:'',view:'library',listId:'',detail:null,tab:'summary'};
const activeStates = new Set(['queued','collecting','summarizing','editing','rendering','interrupted']);
const labels = {queued:'대기',collecting:'수집 중',summarizing:'요약 중',editing:'보고서 구성 중',rendering:'출력 중',complete:'완료',partial:'부분 완료',failed:'실패',interrupted:'중단 · 재개 대기',cancelled:'취소됨'};
const kinds = {youtube:'유튜브',web:'웹페이지',file:'파일'};
const kindLabels = {fact:'핵심',argument:'논거',condition:'조건',exception:'예외',formula:'수식'};
const paths = {
 library:['M3 5h18v16H3z','M8 5v16','M12 10h5','M12 14h5'],
 star:['m12 3 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2-5.6-3-5.6 3 1.1-6.2L3 9.6l6.2-.9z'],
 jobs:['M8 3h8v4H8z','M8 5H5v16h14V5h-3','m8 14 2 2 5-5'],
 trash:['M3 6h18','M9 6V3h6v3','M5 6l1 15h12l1-15','M10 10v7','M14 10v7'],
 settings:['M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8','m9 3-.7 2.3-2.2 1L4 6l-1 3 1.8 1.5v3L3 15l1 3 2.1-.3 2.2 1L9 21h6l.7-2.3 2.2-1 2.1.3 1-3-1.8-1.5v-3L21 9l-1-3-2.1.3-2.2-1L15 3z'],
 search:['M10 3a7 7 0 1 0 0 14 7 7 0 0 0 0-14','m15 15 6 6'],
 plus:['M12 5v14','M5 12h14'],
 youtube:['M4 5h16v14H4z','m10 9 5 3-5 3z'],
 web:['M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20','M2 12h20','M12 2c6 6 6 14 0 20-6-6-6-14 0-20'],
 file:['M5 3h9l5 5v13H5z','M14 3v6h5','M8 13h8','M8 17h6'],
 download:['M12 3v12','m7 10 5 5 5-5','M4 15v6h16v-6'],
 external:['M14 3h7v7','m21 3-11 11','M10 3H3v18h18v-7'],
 back:['m14 6-6 6 6 6'],
 close:['M5 5l14 14','M19 5 5 19'],
 edit:['m14 5 5 5','M4 15v5h5L21 8l-5-5z'],
 refresh:['M20 8a9 9 0 1 0 1 7','M20 3v5h-5'],
 folder:['M3 6h7l2 3h9v12H3z'],
};
function icon(name) {
  const node=document.createElementNS('http://www.w3.org/2000/svg','svg');
  node.setAttribute('viewBox','0 0 24 24');node.setAttribute('class','icon');node.setAttribute('aria-hidden','true');
  (paths[name]||paths.file).forEach(d=>{const p=document.createElementNS(node.namespaceURI,'path');p.setAttribute('d',d);node.append(p);});
  return node;
}
function el(tag,attrs={},...children) {
  const node=document.createElement(tag);
  for(const [key,value] of Object.entries(attrs)) {
    if(value===null||value===undefined||value===false)continue;
    if(key==='class')node.className=value;
    else if(key.startsWith('on'))node.addEventListener(key.slice(2).toLowerCase(),value);
    else if(['value','checked','disabled','selected','hidden'].includes(key))node[key]=value;
    else node.setAttribute(key,value===true?'':value);
  }
  children.flat(Infinity).forEach(child=>{if(child!==null&&child!==undefined)node.append(child instanceof Node?child:document.createTextNode(String(child)));});
  return node;
}
function button(text,action,cls='',ico=null,attrs={}) {return el('button',{type:'button',class:cls,onClick:action,...attrs},ico?icon(ico):null,text);}
function field(label,input,hint='') {const id=input.id||'field-'+crypto.randomUUID();input.id=id;return el('div',{class:'field'},el('label',{for:id},label),input,hint?el('small',{},hint):null);}
function option(value,label,selected=false) {return el('option',{value,selected},label);}
function date(value){return new Intl.DateTimeFormat('ko-KR',{year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(value));}
function externalHref(value){try{const url=new URL(value);return ['http:','https:'].includes(url.protocol)&&!url.username&&!url.password?url.href:'#';}catch{return '#';}}
let toastTimer;
function toast(message,error=false){const box=$('#toast');box.textContent=message;box.className='toast'+(error?' error':'');box.hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>box.hidden=true,5500);}
async function api(path,options={},retried=false) {
  const headers={'X-Chansum-Token':csrf,...options.headers};
  if(options.body && !(options.body instanceof FormData) && typeof options.body!=='string'){headers['Content-Type']='application/json';options={...options,body:JSON.stringify(options.body)};}
  let response;
  try{response=await fetch('/api'+path,{...options,headers});}catch{throw new Error('서버에 연결할 수 없습니다. 실행 창이 열려 있는지 확인해 주세요.');}
  if(response.status===403&&!retried){const current=await fetch('/api/session');if(current.ok){csrf=(await current.json()).token;return api(path,{...options,headers:{...headers,'X-Chansum-Token':csrf}},true);}}
  if(!response.ok){let error;try{error=await response.json();}catch{error={};}throw new Error(typeof error.detail==='string'?error.detail:'입력이나 처리 상태를 확인해 주세요.');}
  return options.blob?response.blob():response.json();
}
async function safely(fn){try{return await fn();}catch(e){toast(e.message,true);}}
function saveBlob(blob,filename){const url=URL.createObjectURL(blob);const a=el('a',{href:url,download:filename});document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),10000);}
function dialog(title,body,actions=[]) {
  const node=el('dialog',{},el('div',{class:'dialog-head'},el('h2',{},title),button('',()=>node.close(),'icon-button','close',{'aria-label':'닫기'})),el('div',{class:'dialog-body'},body));
  const footer=el('div',{class:'dialog-footer'});
  footer.append(button('닫기',()=>node.close()));
  actions.forEach(action=>footer.append(button(action.label,async(event)=>{
    const target=event.currentTarget;target.disabled=true;
    try{await action.run(node,target);}catch(e){toast(e.message,true);}finally{target.disabled=false;}
  },action.class||'primary')));
  node.append(footer);document.body.append(node);node.addEventListener('close',()=>node.remove());node.showModal();return node;
}
function empty(title,message,action=null,ico='library') {return el('div',{class:'empty'},icon(ico),el('h2',{},title),el('p',{},message),action);}
function status(value){return el('span',{class:'status '+value},labels[value]||value);}
function heading(title,subtitle,actions=[]) {return el('div',{class:'page-heading'},el('div',{},el('h1',{},title),el('p',{class:'subtitle'},subtitle)),el('div',{class:'heading-actions'},actions));}
function listPicker(selected=[]) {
  const group=el('div',{class:'list-picker'});
  if(!state.lists.length)group.append(el('span',{class:'hint'},'아직 목록이 없습니다. 왼쪽 + 버튼으로 만들 수 있습니다.'));
  state.lists.forEach(list=>group.append(el('label',{},el('input',{type:'checkbox',value:list.id,checked:selected.includes(list.id)}),list.name)));
  group.values=()=>[...group.querySelectorAll('input:checked')].map(i=>i.value);return group;
}
function renderNav() {
  const nav=$('#primary-nav');nav.replaceChildren();
  for(const [key,label,ico] of [['library','전체 라이브러리','library'],['favorite','즐겨찾기','star'],['jobs','작업 현황','jobs'],['trash','휴지통','trash']]) {
    const count=key==='jobs'?state.jobs.filter(j=>activeStates.has(j.status)&&!j.deleted_at).length:0;
    nav.append(el('a',{href:'#'+key,class:'nav-link'+(state.view===key?' active':''),'aria-current':state.view===key?'page':null},icon(ico),el('span',{class:'nav-label'},label),count?el('span',{class:'count'},count):null));
  }
  $('#list-nav').replaceChildren(...state.lists.map(list=>el('a',{href:'#list/'+list.id,class:'nav-link'+(state.view==='list'&&state.listId===list.id?' active':'')},el('i',{class:'list-dot'}),el('span',{class:'nav-label'},list.name),el('span',{class:'count'},list.count))));
  $('#settings-link').replaceChildren(icon('settings'),el('span',{class:'nav-label'},'설정 및 백업'));
  $('#settings-link').classList.toggle('active',state.view==='settings');
}
async function loadLists(){state.lists=(await api('/lists')).lists;renderNav();}
async function newList(){const input=el('input',{placeholder:'예: 읽고 싶은 글',maxlength:60});dialog('새 목록',field('목록 이름',input),[{label:'만들기',run:async d=>{const value=await api('/lists',{method:'POST',body:{name:input.value}});await loadLists();d.close();location.hash='#list/'+value.id;toast('목록을 만들었습니다.');}}]);input.focus();}
function addDialog() {
  const urls=el('textarea',{id:'add-urls',placeholder:'https://www.youtube.com/watch?v=…\nhttps://example.com/article',rows:4});
  const files=el('input',{type:'file',multiple:true,accept:'.txt,.srt,.vtt,.html,.htm','aria-label':'원문 파일 선택'});
  const mode=el('select',{id:'add-mode'},option('detail','상세 정리',true),option('brief','핵심 요약'));
  const lists=listPicker(state.view==='list'?[state.listId]:[]);
  const feedback=el('div',{'aria-live':'polite'});
  const drop=el('div',{class:'drop-zone'},el('span',{},'또는 원문·자막 파일을 가져오세요'),files,el('small',{class:'hint'},'TXT · SRT · VTT · HTML / 파일당 최대 12MB'));
  drop.addEventListener('dragover',e=>{e.preventDefault();drop.style.borderColor='#2563eb';});
  drop.addEventListener('dragleave',()=>drop.style.borderColor='');
  drop.addEventListener('drop',e=>{e.preventDefault();files.files=e.dataTransfer.files;drop.style.borderColor='';});
  const body=el('div',{},field('URL 한 개 또는 여러 개',urls,'주소마다 줄을 바꾸어 붙여 넣으세요. 유튜브와 웹페이지를 자동으로 구분합니다.'),drop,el('div',{style:'height:20px'}),field('정리 방식',mode),el('div',{class:'field'},el('label',{},'저장할 목록'),lists),el('p',{class:'hint'},'원문은 로컬에 저장되며, 요약할 때 선택한 AI 엔진으로 전송됩니다.'),feedback);
  dialog('새 자료 추가',body,[{label:'가져오기',run:async(d,b)=>{
    const entries=urls.value.split(/\r?\n/).map(s=>s.trim()).filter(Boolean);
    if(!entries.length&&!files.files.length)throw new Error('URL을 입력하거나 파일을 선택해 주세요.');
    b.textContent='대기열에 추가 중…';const all=[],rejected=[];
    if(entries.length){const r=await api('/items/urls',{method:'POST',body:{urls:entries,mode:mode.value,list_ids:lists.values()}});all.push(...r.results);rejected.push(...r.rejected);urls.value='';}
    if(files.files.length){const data=new FormData();[...files.files].forEach(f=>data.append('files',f));data.append('mode',mode.value);data.append('list_ids',JSON.stringify(lists.values()));const r=await api('/items/files',{method:'POST',body:data});all.push(...r.results);rejected.push(...r.rejected);files.value='';}
    const duplicates=all.filter(r=>r.duplicate),added=all.length-duplicates.length;
    b.textContent='가져오기';
    if(!duplicates.length&&!rejected.length){d.close();location.hash='#jobs';toast(added+'개 자료를 대기열에 추가했습니다.');await refresh();return;}
    feedback.replaceChildren(...(added?[el('p',{class:'inline-info'},added+'개 자료를 대기열에 추가했습니다. 작업 현황에서 확인할 수 있습니다.')]:[]));
    duplicates.forEach(item=>feedback.append(el('div',{class:'duplicate-row'},el('p',{},'이미 저장된 자료: '+item.title),
      button(item.in_trash?'복원하고 열기':'기존 항목 열기',()=>safely(async()=>{if(item.in_trash)await api('/items/bulk',{method:'POST',body:{ids:[item.id],action:'restore'}});d.close();location.hash='#item/'+item.id;})),
      item.in_trash?null:button('원문 갱신',()=>safely(async()=>{await api('/items/'+item.id+'/regenerate',{method:'POST',body:{mode:mode.value,refresh:true}});toast('원문을 다시 수집해 갱신합니다.');d.close();location.hash='#jobs';})) )));
    rejected.forEach(r=>feedback.append(el('p',{class:'inline-error'},r.input+'\n'+r.message)));
    await loadLists();
  }}]);urls.focus();
}
async function classify(ids) {
  const picker=listPicker();const action=el('select',{},option('lists_add','선택 목록에 추가'),option('lists_remove','선택 목록에서 제거'));
  dialog('목록 분류',el('div',{},el('p',{class:'hint'},ids.length+'개 자료의 분류를 변경합니다. 원문·결과 파일은 중복 저장하지 않습니다.'),field('변경 방식',action),picker),[{label:'적용',run:async d=>{if(!picker.values().length)throw new Error('목록을 선택해 주세요.');await api('/items/bulk',{method:'POST',body:{ids,action:action.value,list_ids:picker.values()}});d.close();await refresh();toast('목록 분류를 변경했습니다.');}}]);
}
async function bulkAction(action,ids=[...state.selected]) {
  if(!ids.length)return;
  if(action==='purge') {
    const data=state.items.filter(i=>ids.includes(i.id));const confirm=el('input',{type:'checkbox'});
    dialog('자료를 영구 삭제할까요?',el('div',{},el('p',{},ids.length+'개 자료의 원문, 이미지, 모든 PNG·PDF 결과, 메모, 작업 기록을 삭제합니다. 목록 자체와 다른 자료는 유지됩니다. 이 작업은 되돌릴 수 없습니다.'),el('ul',{},data.map(i=>el('li',{},i.title))),el('label',{class:'hint'},confirm,' 삭제 대상과 범위를 확인했습니다.')),[{label:'영구 삭제',class:'danger',run:async d=>{
      if(!confirm.checked)throw new Error('삭제 범위 확인에 체크해 주세요.');
      const result=await api('/items/bulk',{method:'POST',body:{ids,action,confirm:'DELETE'}});
      state.selected.clear();d.close();await refresh();
      toast(result.pending_cleanup?'자료는 삭제했습니다. 잠긴 파일은 작업 종료 또는 다음 실행에서 정리합니다. 데이터 폴더 권한도 확인해 주세요.':'선택한 자료와 파일을 영구 삭제했습니다.');
    }}]);return;
  }
  await api('/items/bulk',{method:'POST',body:{ids,action}});state.selected.clear();
  if(state.view==='item'&&action==='trash')location.hash='#library';else await refresh();
  toast(action==='restore'?'자료와 기존 목록 분류를 복원했습니다.':action==='trash'?'휴지통으로 이동했습니다.':'즐겨찾기에 추가했습니다.');
}
function bulkBar() {
  const ids=[...state.selected];const bar=el('div',{class:'bulk-bar',hidden:!ids.length},el('span',{},ids.length+'개 선택'));
  if(state.view==='trash')bar.append(button('복원',()=>safely(()=>bulkAction('restore'))),button('영구 삭제',()=>safely(()=>bulkAction('purge')),'danger'));
  else bar.append(button('목록 분류',()=>classify(ids)),button('즐겨찾기',()=>safely(()=>bulkAction('favorite'))),button('휴지통으로',()=>safely(()=>bulkAction('trash'))));
  return bar;
}
async function loadItems(){const params=new URLSearchParams({q:state.q,sort:state.sort,kind:state.kind});if(state.view==='list')params.set('list_id',state.listId);if(state.view==='favorite')params.set('favorite','true');if(state.view==='trash')params.set('trash','true');state.items=(await api('/items?'+params)).items;const valid=new Set(state.items.map(i=>i.id));state.selected=new Set([...state.selected].filter(id=>valid.has(id)));}
function rowsView() {
  const host=$('#rows-host');if(!host)return;
  const all=el('input',{type:'checkbox','aria-label':'자료 전체 선택',checked:state.items.length>0&&state.items.every(i=>state.selected.has(i.id)),onChange:e=>{state.selected=e.target.checked?new Set(state.items.map(i=>i.id)):new Set();rowsView();}});
  const tbody=el('tbody');
  state.items.forEach(item=>{
    const check=el('input',{type:'checkbox','aria-label':item.title+' 선택',checked:state.selected.has(item.id),onChange:e=>{if(e.target.checked)state.selected.add(item.id);else state.selected.delete(item.id);rowsView();}});
    const thumb=item.thumbnail?el('img',{class:'thumb',src:'/api/items/'+item.id+'/thumbnail',alt:'',loading:'lazy'}):el('div',{class:'type-placeholder'},icon(item.kind));
    const open=()=>{if(state.view==='trash')return safely(()=>bulkAction('restore',[item.id]));location.hash='#item/'+item.id;};
    const title=button(item.title,open,'item-title',null,{title:item.title});
    const meta=el('div',{class:'item-meta'},el('span',{},kinds[item.kind]),item.lists.length?el('span',{class:'item-list-name'},' / '+item.lists.map(l=>l.name).join(' · ')):null);
    const fav=button('',()=>safely(async()=>{await api('/items/'+item.id,{method:'PATCH',body:{favorite:!item.favorite}});await loadItems();rowsView();}),'icon-button favorite-button'+(item.favorite?' on':''),'star',{'aria-label':item.favorite?'즐겨찾기 해제':'즐겨찾기 추가'});
    tbody.append(el('tr',{class:state.selected.has(item.id)?'selected':''},el('td',{},check),el('td',{},el('div',{class:'title-cell'},thumb,el('div',{class:'title-info'},title,meta))),el('td',{},item.kind==='youtube'?'youtube.com':item.kind==='web'?new URL(item.url).hostname:'로컬 파일'),el('td',{},date(item.created_at)),el('td',{},status(item.status)),el('td',{},state.view==='trash'?button('복원',()=>safely(()=>bulkAction('restore',[item.id])),'quiet'):fav)));
  });
  const table=el('table',{class:'library-table'},el('thead',{},el('tr',{},el('th',{},all),el('th',{},'제목 / 목록'),el('th',{},'출처'),el('th',{},'저장일'),el('th',{},'처리 상태'),el('th',{},''))),tbody);
  const count=el('p',{class:'library-count'},'총 ',el('strong',{},state.items.length),'개의 자료');
  host.replaceChildren(bulkBar(),count,state.items.length?el('div',{class:'table-wrap'},table):empty(state.q||state.kind?'검색 결과가 없습니다':state.view==='trash'?'휴지통이 비어 있습니다':'첫 번째 자료를 담아 보세요',state.view==='trash'?'삭제한 자료는 이곳에 보관됩니다. 복원하면 기존 목록 분류도 돌아옵니다.':state.q||state.kind?'검색어나 유형 필터를 바꾸어 보세요.':'읽고 싶은 유튜브와 웹페이지를 모으세요. 근거가 연결된 요약과 인포그래픽, PDF로 정리해 드립니다.',state.view==='trash'?null:button('새 자료 추가',addDialog,'primary','plus')));
}
async function libraryView() {
  const list=state.lists.find(l=>l.id===state.listId);
  const title={library:'전체 라이브러리',favorite:'즐겨찾기',trash:'휴지통',list:list?.name||'목록'}[state.view];
  const subtitle=state.view==='trash'?'원래 목록 정보를 유지한 채 보관합니다. 영구 삭제 전까지 복원할 수 있습니다.':'읽은 내용을, 다시 꺼내 쓸 수 있는 지식으로.';
  const actions=[];
  if(state.view==='list'&&list) {
    actions.push(button('이름 변경',()=>{const input=el('input',{value:list.name,maxlength:60});dialog('목록 이름 변경',field('이름',input),[{label:'저장',run:async d=>{await api('/lists/'+list.id,{method:'PATCH',body:{name:input.value}});d.close();await refresh();}}]);},'quiet'));
    actions.push(button('목록 삭제',()=>dialog('목록을 삭제할까요?',el('p',{},'“'+list.name+'” 목록의 분류만 삭제합니다. 자료와 원문·PDF는 라이브러리에 그대로 남습니다.'),[{label:'목록만 삭제',class:'danger',run:async d=>{await api('/lists/'+list.id,{method:'DELETE'});d.close();location.hash='#library';await loadLists();}}]),'quiet'));
  }
  if(state.view!=='trash')actions.push(button('새 자료 추가',addDialog,'primary','plus'));
  const search=el('input',{type:'search',placeholder:'제목, 메모, URL 검색',value:state.q,'aria-label':'라이브러리 검색'});
  let searchTimer;search.addEventListener('input',()=>{state.q=search.value;clearTimeout(searchTimer);searchTimer=setTimeout(()=>safely(async()=>{await loadItems();rowsView();}),220);});
  const sort=el('select',{'aria-label':'정렬'},option('latest','최신순',state.sort==='latest'),option('title','제목순',state.sort==='title'));
  sort.addEventListener('change',()=>safely(async()=>{state.sort=sort.value;await loadItems();rowsView();}));
  const kind=el('select',{'aria-label':'자료 유형'},option('','모든 유형',!state.kind),...Object.entries(kinds).map(([k,v])=>option(k,v,state.kind===k)));
  kind.addEventListener('change',()=>safely(async()=>{state.kind=kind.value;await loadItems();rowsView();}));
  $('#main').replaceChildren(heading(title,subtitle,actions),el('div',{class:'toolbar'},el('div',{class:'search'},icon('search'),search),kind,sort),el('div',{id:'rows-host'}));
  await loadItems();rowsView();
}
function progress(job) {
  const known=job.total>1;
  const box=el('div',{},el('div',{class:'progress-label'},status(job.status),el('span',{},known?job.done+' / '+job.total+' 단계 단위':job.status==='collecting'?'본문 확인 중':'')));
  if(known)box.append(el('div',{class:'progress-track'},el('div',{class:'progress-fill',style:'width:'+Math.min(100,Math.round(job.done/job.total*100))+'%'})));
  return box;
}
function jobsRows(){const host=$('#jobs-host');if(!host)return;host.replaceChildren();if(!state.jobs.length){host.append(empty('아직 작업이 없습니다','자료를 추가하면 수집·요약·출력 과정을 여기서 확인할 수 있습니다.',button('새 자료 추가',addDialog,'primary','plus'),'jobs'));return;}state.jobs.forEach(job=>{
  const title=job.deleted_at?el('p',{class:'job-title'},job.title+' · 휴지통'):button(job.title,()=>location.hash='#item/'+job.item_id,'item-title');
  const info=date(job.created_at)+(job.resume_count?' · 서버 중단 후 '+job.resume_count+'회 재개':'')+(job.cache_hits?' · 캐시 '+job.cache_hits+'개 재사용':'');
  const action=job.deleted_at?null:activeStates.has(job.status)?button('취소',()=>safely(async()=>{await api('/jobs/'+job.id+'/cancel',{method:'POST'});await refresh();}),'quiet'):['failed','partial','cancelled'].includes(job.status)?button('재시도',()=>safely(async()=>{await api('/jobs/'+job.id+'/retry',{method:'POST'});await refresh();}),'','refresh'):null;
  host.append(el('div',{class:'job-row'},el('div',{},title,el('span',{class:'job-info'},info),job.error_message?el('p',{class:'job-error'},job.error_message+' ['+job.error_code+']'):null),progress(job),action));
});}
function jobsView(){$('#main').replaceChildren(heading('작업 현황','완료한 단계와 분할 구간 수를 표시합니다. 창을 닫아도 작업은 서버에서 계속됩니다.',[button('새 자료 추가',addDialog,'primary','plus')]),el('div',{class:'job-list',id:'jobs-host'}));jobsRows();}
function mathText(text) {
  const span=el('span');let position=0;const regex=/\\\((.*?)\\\)|\\\[(.*?)\\\]/gs;let match;
  while((match=regex.exec(text))){span.append(document.createTextNode(text.slice(position,match.index)));const math=el('span');try{katex.render(match[1]||match[2],math,{displayMode:match[2]!==undefined,throwOnError:true,trust:false,maxExpand:1000,maxSize:10});}catch{math.textContent=match[0];}span.append(math);position=regex.lastIndex;}
  span.append(document.createTextNode(text.slice(position)));return span;
}
function evidenceLinks(item,source,refs) {
  return el('div',{class:'evidence-links'},refs.map(ref=>button(ref,()=>{state.tab='source';renderTab();const row=document.getElementById('segment-'+ref);if(row){row.classList.add('highlight');row.scrollIntoView({behavior:'smooth',block:'center'});}})));
}
function summaryItem(item,source,value){return el('div',{class:'summary-item'},el('span',{class:'item-kind'},kindLabels[value.kind]||'핵심'),el('p',{},mathText(value.text)),evidenceLinks(item,source,value.sources));}
function reportSection(item,source,section,number,depth=0) {
  const host=el('section',{class:'report-topic'},el('h'+Math.min(2+depth,5),{},number+' '+section.heading),
    el('div',{class:'report-intro'},el('p',{},mathText(section.overview.text)),evidenceLinks(item,source,section.overview.sources)));
  function entry(value) {
    const node=el('div',{class:'report-entry'});
    if(value.narrative)node.append(summaryItem(item,source,{...value.narrative,kind:value.item?.kind||'argument'}));
    else if(value.item)node.append(summaryItem(item,source,value.item));
    if(value.children)value.children.forEach((child,index)=>node.append(reportSection(item,source,child,number+'.'+(index+1),depth+2)));
    if(value.supporting?.length)node.append(el('div',{class:'report-support'},value.supporting.map(entry)));
    return node;
  }
  section.groups.forEach((group,index)=>host.append(el('h'+Math.min(3+depth,6),{},number+'.'+(index+1)+' '+group.heading),
    el('ol',{class:'report-arguments'},group.entries.map(value=>el('li',{},entry(value))))));
  return host;
}
function renderTab() {
  const data=state.detail;if(!data)return;const host=$('#tab-content');if(!host)return;
  const {item,source,summary}=data;document.querySelectorAll('.tabs button').forEach(b=>{b.classList.toggle('active',b.dataset.tab===state.tab);b.setAttribute('aria-selected',String(b.dataset.tab===state.tab));});host.replaceChildren();
  if(state.tab==='source') {
    if(!source){host.append(empty('원문을 확보하지 못했습니다','수집 오류를 확인하거나 TXT·SRT·VTT·HTML 파일로 가져와 주세요.',button('파일 가져오기',addDialog),'file'));return;}
    const meta=el('div',{class:'source-header'},el('strong',{},source.title),el('br'),source.url?el('a',{href:externalHref(source.url),target:'_blank',rel:'noopener noreferrer'},source.url):source.filename||'로컬 파일',el('br'),'수집 '+date(source.collected_at)+' · 언어 '+(source.language||'미상')+' · 작성자 '+(source.author||'미상')+(source.published_at?' · 게시일 '+source.published_at:''));
    const column=el('div',{class:'reading-column'},meta);
    source.segments.forEach(segment=>{
      const label=el('div',{class:'segment-id'},segment.id);
      if(segment.start!==undefined){const time=Math.floor(segment.start/60)+':'+String(Math.floor(segment.start%60)).padStart(2,'0');label.append(source.url&&source.kind==='youtube'?el('a',{href:externalHref(source.url+'&t='+Math.floor(segment.start)+'s'),target:'_blank',rel:'noopener noreferrer'},time+' ↗'):el('span',{},time));}
      column.append(el('div',{class:'source-segment',id:'segment-'+segment.id},label,el('p',{},segment.text)));
    });host.append(column);return;
  }
  if(!summary){host.append(empty(activeStates.has(item.status)?'정리하고 있습니다':'아직 요약 결과가 없습니다',activeStates.has(item.status)?'원문 수집과 요약·출력이 끝나면 자동으로 표시됩니다.':'위 오류 안내를 확인하고 엔진을 설정하거나 작업을 다시 시도해 주세요.',button('설정 열기',()=>location.hash='#settings'),'jobs'));return;}
  if(state.tab==='infographic') {host.append(el('p',{class:'hint'},'전체 주제의 핵심과 주요 관계를 함께 보여줍니다. 상세 설명과 근거는 요약 탭에서 확인하세요.'),el('img',{class:'output-image',src:'/api/items/'+item.id+'/download/png?v='+encodeURIComponent(item.result_path),alt:summary.title+' 인포그래픽'}));return;}
  if(state.tab==='pdf') {host.append(el('p',{class:'hint'},'첫 페이지는 인포그래픽, 이후는 상세 요약과 근거입니다. 미리보기가 지원되지 않으면 PDF를 다운로드해 주세요.'),el('iframe',{class:'pdf-frame',src:'/api/items/'+item.id+'/preview/pdf?v='+encodeURIComponent(item.result_path),title:'자료 PDF 미리보기'}));return;}
  const column=el('div',{class:'reading-column'});
  if(summary.partial)column.append(el('p',{class:'inline-error'},'부분 완료 · '+summary.failed_chunks+'개 구간 미처리. 빠진 구간: '+summary.missing_segments.join(', ')));
  if(summary.verification==='test-double')column.append(el('p',{class:'inline-error'},'검증용 AI 테스트 대역으로 만든 결과입니다. 실제 AI 요약이 아닙니다.'));
  if(summary.report?.version!=='chansum-report-3')column.append(el('p',{class:'inline-info'},'이 자료는 이전 방식으로 정리한 결과입니다. 위의 재생성에서 상세 정리를 선택하면 새 인포그래픽 요약과 설명문을 만듭니다. AI 이용량이 발생할 수 있습니다.'));
  column.append(el('figure',{class:'summary-visual'},el('figcaption',{},el('strong',{},'한눈에 보는 인포그래픽 요약'),button('크게 보기',()=>{state.tab='infographic';renderTab();},'quiet')),el('img',{src:'/api/items/'+item.id+'/download/png?v='+encodeURIComponent(item.result_path),alt:summary.title+' 전체 주제 인포그래픽 요약'})));
  column.append(el('div',{class:'overview'},mathText(summary.message.text),evidenceLinks(item,source,summary.message.sources)));
  if(summary.report) {
    const toc=el('nav',{class:'report-toc','aria-label':'보고서 목차'},el('h2',{},'목차'));
    summary.report.sections.forEach((section,index)=>toc.append(button((index+1)+'. '+section.heading,()=>document.getElementById('report-topic-'+index)?.scrollIntoView({behavior:'smooth',block:'start'}),'toc-link')));
    column.append(toc);
    summary.report.sections.forEach((section,index)=>{const node=reportSection(item,source,section,String(index+1));node.id='report-topic-'+index;column.append(node);});
  } else summary.sections.forEach(section=>column.append(el('section',{class:'summary-section'},el('h2',{},section.heading),section.items.map(value=>summaryItem(item,source,value)))));
  column.append(el('p',{class:'hint'},'요약 엔진: '+summary.engine+' · 모델: '+summary.model+' · 처리 '+summary.processed_chunks+'/'+summary.chunk_count+'구간 · '+summary.prompt_version));host.append(column);
}
async function detailView(id,sourceRef=null) {
  const data=await api('/items/'+id);state.detail=data;const {item,summary,jobs}=data;
  const main=$('#main');const nav=el('div',{class:'breadcrumb'},el('a',{href:'#library'},'라이브러리'),el('span',{},'/'),el('span',{},kinds[item.kind]));
  const title=el('div',{class:'detail-heading'},el('h1',{},item.title),el('div',{class:'detail-metadata'},el('span',{},kinds[item.kind]),el('span',{},'저장 '+date(item.created_at)),status(item.status),item.url?el('a',{href:externalHref(item.url),target:'_blank',rel:'noopener noreferrer'},'원본 열기 ↗'):null));
  const actions=el('div',{class:'detail-actions'});
  for(const [format,label] of [['png','PNG 다운로드'],['pdf','PDF 다운로드'],['svg','SVG 원본']])actions.append(el('a',{class:'download',href:data.downloads.includes(format)?'/api/items/'+id+'/download/'+format:null,'aria-disabled':String(!data.downloads.includes(format)),style:!data.downloads.includes(format)?'opacity:.4;pointer-events:none':null},icon('download'),label));
  actions.append(button('제목 변경',()=>{const input=el('input',{value:item.title,maxlength:250});dialog('제목 변경',field('제목',input),[{label:'저장',run:async d=>{await api('/items/'+id,{method:'PATCH',body:{title:input.value}});d.close();await detailView(id);}}]);},'','edit'));
  actions.append(button(item.favorite?'즐겨찾기 해제':'즐겨찾기',()=>safely(async()=>{await api('/items/'+id,{method:'PATCH',body:{favorite:!item.favorite}});await detailView(id);}),'','star'));
  actions.append(button('목록 분류',()=>classify([id]),'','folder'));
  actions.append(button('재생성',()=>{
    const mode=el('select',{},option('brief','핵심 요약',summary?.options.mode==='brief'),option('detail','상세 정리',summary?.options.mode==='detail'));
    const refresh=el('input',{type:'checkbox'});
    dialog('결과 재생성',el('div',{},field('정리 방식',mode),el('label',{class:'hint'},refresh,' 원문도 다시 수집 (파일은 저장된 입력 재사용)'),el('p',{class:'hint'},'옵션·원문·모델이 같으면 캐시를 재사용합니다. 새 결과 생성에 실패하면 이전에 성공한 결과는 그대로 보존합니다.')),[{label:'재생성',run:async d=>{await api('/items/'+id+'/regenerate',{method:'POST',body:{mode:mode.value,refresh:refresh.checked}});d.close();await detailView(id);}}]);
  },'','refresh',{disabled:activeStates.has(item.status)}));
  actions.append(button('휴지통으로',()=>safely(()=>bulkAction('trash',[id])),'quiet','trash'));
  const job=jobs[0];const jobBox=el('div',{id:'detail-job',class:'job-state'});
  if(job&&activeStates.has(job.status))jobBox.append(progress(job),el('p',{class:'hint'},job.resume_count?'서버 중단 후 저장된 단계에서 재개했습니다.':'탭을 닫거나 새로고침해도 서버에서 계속 처리합니다.'));
  if(item.error_message){jobBox.append(el('p',{class:'inline-error'},item.error_message+(item.result_path?'\n이전에 성공한 결과를 아래에 표시합니다.':'')),el('div',{class:'error-actions'},button('재시도',()=>safely(async()=>{await api('/jobs/'+job.id+'/retry',{method:'POST'});await detailView(id);}),'','refresh'),button('설정 확인',()=>location.hash='#settings'),button('파일 가져오기',addDialog)));}
  const tabs=el('div',{class:'tabs',role:'tablist','aria-label':'자료 결과'},[['summary','요약'],['infographic','인포그래픽'],['pdf','PDF'],['source','원문']].map(([key,label])=>button(label,()=>{state.tab=key;renderTab();},'',null,{role:'tab','data-tab':key,'aria-selected':String(state.tab===key)})));
  const note=el('textarea',{id:'item-note',placeholder:'이 자료에 대한 생각이나 기억할 내용을 남겨 보세요.',value:item.note,'aria-label':'자료 메모'});
  let noteTimer;async function saveNote(){await api('/items/'+id,{method:'PATCH',body:{note:note.value}});}
  note.addEventListener('input',()=>{clearTimeout(noteTimer);noteTimer=setTimeout(()=>safely(saveNote),600);});
  main.replaceChildren(nav,title,actions,jobBox,tabs,el('div',{id:'tab-content',class:'tab-body',role:'tabpanel'}),el('section',{class:'notes'},el('h2',{},'나의 메모'),note,button('메모 저장',()=>safely(async()=>{await saveNote();toast('메모를 저장했습니다.');}))));
  if(sourceRef)state.tab='source';renderTab();if(sourceRef)setTimeout(()=>{const row=document.getElementById('segment-'+sourceRef);if(row){row.classList.add('highlight');row.scrollIntoView({block:'center'});}},50);
}
async function settingsView() {
  const data=await api('/settings'),current=data.settings;
  const engine=el('select',{id:'engine'},option('codex','Codex CLI · ChatGPT 로그인',current.engine==='codex'),option('openai','OpenAI 호환 API',current.engine==='openai'),option('ollama','Ollama · 로컬 모델',current.engine==='ollama'));
  const model=el('input',{id:'model',value:current.model,placeholder:'Codex는 비워 두면 CLI 기본 모델 사용'});
  const endpoint=el('input',{id:'endpoint',value:current.base_url,placeholder:'https://api.openai.com/v1'});
  const key=el('input',{id:'api-key',type:'password',autocomplete:'new-password',placeholder:data.api_key_present?'키가 저장되어 있습니다. 변경할 때만 입력하세요.':'API 키 입력 (브라우저에 저장하지 않음)'});
  const clear=el('input',{type:'checkbox'});
  const limit=el('input',{id:'chunk-chars',type:'number',min:1000,max:40000,value:current.engine==='ollama'?Math.min(current.chunk_chars,4000):current.chunk_chars});
  const timeout=el('input',{id:'ai-timeout',type:'number',min:20,max:600,value:current.timeout});
  const fallback=el('input',{type:'checkbox',checked:current.youtube_fallback});
  const result=el('div',{class:'validation-result',role:'status'});
  engine.addEventListener('change',()=>{if(engine.value==='ollama'){endpoint.value='http://127.0.0.1:11434';limit.value=Math.min(Number(limit.value),4000);model.placeholder='예: qwen3:8b · 32K 문맥을 지원하는 설치 모델';}else if(engine.value==='openai'){endpoint.value='https://api.openai.com/v1';model.placeholder='사용 가능한 API 모델 이름';}else model.placeholder='비워 두면 CLI 기본 모델 사용';});
  async function save(){await api('/settings',{method:'PUT',body:{engine:engine.value,model:model.value,base_url:endpoint.value,api_key:key.value||null,clear_api_key:clear.checked,chunk_chars:Number(limit.value),timeout:Number(timeout.value),youtube_fallback:fallback.checked}});key.value='';clear.checked=false;}
  const ai=el('section',{class:'setting-section'},el('h2',{},'요약 엔진'),el('p',{class:'inline-info'},data.engine_status.message),el('p',{class:'hint'},'구간별 요약 후 보고서 구성에도 AI를 호출합니다. 긴 자료는 여러 번 호출하며 선택한 서비스의 이용량이 발생할 수 있습니다. 열람·다운로드는 저장된 결과를 사용합니다.'),field('연결 방식',engine),field('모델',model,'실제 사용 가능한 모델 이름을 입력하세요. 모델·프롬프트·원문·옵션별로 요약을 캐시합니다.'),field('API 또는 Ollama 서버 주소',endpoint,'Codex CLI에서는 이 주소와 API 키를 사용하지 않습니다.'),field('API 키',key,'키는 서버의 별도 설정 폴더에 보관하며 DB·백업·로그·프런트엔드 코드에 포함하지 않습니다.'),el('label',{class:'hint'},clear,' 저장된 API 키 지우기'),el('div',{style:'height:22px'}),el('div',{class:'form-row'},field('분할 원문 한도 (문자)',limit,'요약 프롬프트·JSON 공간은 별도로 필요합니다.'),field('AI 응답 제한 (초)',timeout)),el('label',{class:'hint'},fallback,' 필요할 때 yt-dlp로 유튜브 자막 보완 수집'),el('div',{style:'height:22px'}),el('div',{class:'setting-buttons'},button('설정 저장',()=>safely(async()=>{await save();toast('설정을 저장했습니다.');}),'primary'),button('실제 연결 테스트',async e=>{const b=e.currentTarget;b.disabled=true;result.textContent='실제 AI를 호출하고 있습니다. 선택한 서비스의 이용량이 발생할 수 있습니다.';try{await save();const response=await api('/engine/test',{method:'POST'});result.className='validation-result success';result.textContent=response.message;}catch(error){result.className='validation-result error';result.textContent=error.message;}finally{b.disabled=false;}}),button('Codex 로그인',()=>safely(async()=>{const response=await api('/engine/login',{method:'POST'});toast(response.message);}))),result);
  const dataSection=el('section',{class:'setting-section'},el('h2',{},'로컬 데이터'),el('p',{},'코드와 사용자 데이터는 별도 위치에 보관합니다. 앱을 업데이트해도 이 폴더를 유지하면 라이브러리가 남습니다.'),el('div',{class:'path-box'},data.data_dir),el('p',{},'비밀키 설정 폴더 (백업 제외)'),el('div',{class:'path-box'},data.config_dir),el('p',{class:'hint'},'저장 위치를 바꾸려면 서버를 종료하고 데이터 폴더를 옮긴 뒤 CHANSUM_DATA_DIR을 지정하세요. 앱이 실행 중일 때 DB 파일만 따로 옮기지 마세요.'));
  if(data.pending_cleanup)dataSection.append(el('p',{class:'inline-error'},data.pending_cleanup+'개 자료의 잠긴 파일이 삭제 대기 중입니다. 파일을 사용하는 프로그램을 닫은 뒤 앱을 다시 실행해 정리해 주세요.'));
  const restoreFile=el('input',{type:'file',accept:'.zip','aria-label':'복원할 Chansum 백업'});
  const backupSection=el('section',{class:'setting-section'},el('h2',{},'백업 및 복원'),el('p',{},'DB·목록·메모·원문·이미지·모든 결과물을 ZIP으로 묶습니다. 비밀키와 AI 캐시는 제외합니다. 처리 중인 작업을 완료하거나 취소한 뒤 진행하세요.'),button('백업 다운로드',async e=>{const b=e.currentTarget;b.disabled=true;try{const blob=await api('/backup',{method:'POST',blob:true});saveBlob(blob,'Chansum-backup-'+new Date().toISOString().slice(0,10)+'.zip');toast('백업을 만들었습니다.');}catch(error){toast(error.message,true);}finally{b.disabled=false;}},'','download'),el('div',{style:'height:25px'}),field('백업에서 복원',restoreFile,'최대 512MB. 현재 자료 전체를 백업 내용으로 교체합니다. 비밀키 설정은 바꾸지 않습니다.'),button('선택한 백업 복원',()=>{
    const file=restoreFile.files[0];if(!file){toast('복원할 ZIP 파일을 선택해 주세요.',true);return;}
    const confirm=el('input',{type:'checkbox'});
    dialog('라이브러리 전체를 교체할까요?',el('div',{},el('p',{},file.name+'의 DB·원문·결과물로 현재 라이브러리를 교체합니다. 복원 전 데이터는 별도 폴더에 보존합니다. 비밀키는 복원하지 않습니다.'),el('label',{class:'hint'},confirm,' 전체 교체 범위를 확인했습니다.')),[{label:'복원',run:async d=>{if(!confirm.checked)throw new Error('복원 범위 확인에 체크해 주세요.');const form=new FormData();form.append('file',file);form.append('confirm','RESTORE');const response=await api('/restore',{method:'POST',body:form});d.close();toast(response.message);await refresh();}}]);
  },'danger'));
  backupSection.append(el('p',{class:'hint'},'복원할 때 이 PC의 AI 연결 설정과 비밀키는 유지합니다. 백업의 서버 주소로 자동 변경하지 않습니다.'));
  $('#main').replaceChildren(heading('설정 및 백업','AI 연결과 이 PC에 저장되는 데이터를 관리합니다.'),ai,dataSection,backupSection);
}
let routing=0;
async function route() {
  const sequence=++routing;const parts=location.hash.replace(/^#/,'').split('/');state.view=parts[0]||'library';state.listId=state.view==='list'?parts[1]||'':'';state.selected.clear();
  renderNav();
  try{if(state.view==='jobs')jobsView();else if(state.view==='settings')await settingsView();else if(state.view==='item'){state.tab=parts[2]==='source'?'source':'summary';await detailView(parts[1],parts[2]==='source'?parts[3]:null);}else {if(!['library','list','favorite','trash'].includes(state.view))state.view='library';await libraryView();}}
  catch(e){if(sequence===routing)$('#main').replaceChildren(empty('자료를 불러오지 못했습니다',e.message,button('다시 시도',()=>route()),'refresh'));}
}
async function refresh() {await loadLists();state.jobs=(await api('/jobs')).jobs;renderNav();if(state.view==='jobs')jobsRows();else if(state.view==='list')await libraryView();else if(['library','favorite','trash'].includes(state.view)){await loadItems();rowsView();}else if(state.view==='item'&&state.detail)await detailView(state.detail.item.id);else if(state.view==='settings')await settingsView();}
let polling=false;
async function poll() {
  if(polling)return;polling=true;
  try{
    const old=JSON.stringify(state.jobs.map(j=>[j.id,j.status,j.done]));state.jobs=(await api('/jobs')).jobs;
    $('#connection-status').textContent='로컬 연결됨';
    if(old!==JSON.stringify(state.jobs.map(j=>[j.id,j.status,j.done]))){await loadLists();renderNav();if(state.view==='jobs')jobsRows();else if(['library','list','favorite','trash'].includes(state.view)){await loadItems();rowsView();}else if(state.view==='item'&&state.detail){const current=state.jobs.find(j=>j.item_id===state.detail.item.id);if(current){if(!activeStates.has(current.status)&&document.activeElement?.id!=='item-note')await detailView(current.item_id);else if(activeStates.has(current.status)){$('#detail-job')?.replaceChildren(progress(current),el('p',{class:'hint'},'서버에서 계속 처리하고 있습니다.'));}}}}
    if(state.view==='item'&&state.detail&&document.activeElement?.id!=='item-note'){
      const current=state.jobs.find(job=>job.item_id===state.detail.item.id);
      if(current&&!activeStates.has(current.status)&&state.detail.item.status!==current.status)await detailView(current.item_id);
    }
  }catch{$('#connection-status').textContent='서버 연결 끊김 · 실행 창을 확인하세요';}finally{polling=false;}
}
$('#new-list').addEventListener('click',()=>safely(newList));
window.addEventListener('hashchange',()=>route());
(async()=>{try{const health=await api('/health');$('#test-banner').hidden=!health.test_mode;await loadLists();state.jobs=(await api('/jobs')).jobs;await route();$('#connection-status').textContent='로컬 연결됨';}catch(e){toast(e.message,true);}setInterval(poll,1800);})();
