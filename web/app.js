const $=id=>document.getElementById(id);
let albums=[], selected=new Set(), page=1, total=0, lastResult='', wasRunning=false;
let currentGroup=null, picked=new Set(), pendingPlan=null, operationBusy=false;
let displayedPhotos=[], referenceKey=null, albumSerial=null;
let pollBusy=false;
let syncBusy=false,reviewItems=[];
let detailPage=1,groupScroll=0;
let scanState={},resultSummary=null,resultsLoaded=false;
function renderResultStatus(){
  const previous=!!resultSummary,when=previous?dateText(resultSummary.finished_at):'';
  const running=!!scanState.running;
  const interrupted=!running&&['stopped','error'].includes(scanState.phase);
  $('resultStatus').textContent=running
    ?previous?I18n.msg`本轮分类进行中。下方显示上次结果（完成于 ${when}），不是本轮实时分组；本轮完整结束后自动替换。扫描期间不能删除或移动文件。`:I18n.t('本轮分类进行中，尚无已完成的结果；全部处理结束后才会显示本轮分组。')
    :interrupted?previous?I18n.msg`本轮${scanState.phase==='error'?I18n.t('失败'):I18n.t('已停止')}，没有生成新的完整分组。下方仍是上次结果（完成于 ${when}）。`:I18n.msg`本轮${scanState.phase==='error'?I18n.t('失败'):I18n.t('已停止')}，尚无已完成的分类结果。`
    :previous?I18n.msg`下方为最近一次已完成的分类结果（${when}），不是实时分类。`:I18n.t('尚无已完成的分类结果。');
  $('resultStatus').dataset.state=running||interrupted?'previous':'saved';
  $('groupCount').parentElement.querySelector('span').textContent=running||interrupted?I18n.t('上次结果 · 相似媒体组'):I18n.t('相似媒体组');
}
function showScanState(state){scanState=state;wasRunning=!!state.running;window.SpeedChart?.update(state);renderResultStatus();updatePicks();}
const photoTime=p=>p.taken||p.modified||0;
const dateText=t=>t?new Date(t*1000).toLocaleString(I18n.locale):I18n.t('日期未知');
const fmt=n=>new Intl.NumberFormat(I18n.locale).format(n);
const bytes=n=>n>=1024**3?(n/1024**3).toFixed(2)+' GB':n>=1024**2?(n/1024**2).toFixed(1)+' MB':(n/1024).toFixed(1)+' KB';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function api(path,body){const r=await fetch('/api/'+path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const data=I18n.api(await r.json());if(!r.ok)throw Error(data.detail||I18n.t('请求失败'));return data;}
function notice(e){$('notice').hidden=false;$('notice').textContent=e.message||e;}
async function action(fn){try{$('notice').hidden=true;await fn();}catch(e){notice(e);}}
async function loadAlbums(){const data=await api('albums');const restored=window.LanguageSettings?.selection;if(restored?.serial===data.serial){selected=new Set(restored.paths);albumSerial=data.serial;}if(window.LanguageSettings)window.LanguageSettings.selection=null;const oldSelection=selected;const previousFilter=window.LanguageSettings?.filterAlbum||$('filterAlbum').value;albums=data.albums;selected=albumSerial===data.serial?new Set(albums.filter(a=>oldSelection.has(a.path)).map(a=>a.path)):new Set(albums.map(a=>a.path));albumSerial=data.serial;if(window.LanguageSettings)window.LanguageSettings.filterAlbum='';$('photoCount').textContent=fmt(data.count);$('albumCount').textContent=I18n.msg`${albums.length} 个相册 · ${bytes(albums.reduce((s,a)=>s+a.size,0))}`;$('syncInfo').textContent=data.refreshed_at?I18n.msg`上次同步：${dateText(data.refreshed_at)} · 新增/变化 ${data.changes?.added||0} · 移除/变化 ${data.changes?.removed||0}`:I18n.t('目录尚未同步');renderAlbums();$('filterAlbum').innerHTML=I18n.html('<option value="">全部相册</option>')+albums.map(a=>`<option value="${esc(a.path)}">${esc(a.name)} (${a.count})</option>`).join('');if(albums.some(a=>a.path===previousFilter))$('filterAlbum').value=previousFilter;}
function renderAlbums(){$('albumList').innerHTML=albums.map((a,i)=>I18n.html`<label class="album" title="${esc(a.path)} · 已缓存 ${a.cached} 个"><input type="checkbox" data-index="${i}" ${selected.has(a.path)?'checked':''}><span class="folder">▱</span><span class="name">${esc(a.name||a.path)}</span><span class="count">${fmt(a.count)}</span></label>`).join('')||I18n.html('<p class="muted">暂无相册，请刷新。</p>');}
$('albumList').addEventListener('change',e=>{const a=albums[Number(e.target.dataset.index)];if(a){e.target.checked?selected.add(a.path):selected.delete(a.path);$('scanTarget').value='selected';}});
$('selectAll').onclick=()=>{selected=new Set(albums.map(a=>a.path));$('scanTarget').value='selected';renderAlbums();};$('selectNone').onclick=()=>{selected.clear();$('scanTarget').value='selected';renderAlbums();};
async function loadDevices(){const previous=$('device').value;const devices=await api('devices');$('device').innerHTML=devices.map(d=>`<option value="${esc(d.serial)}" ${d.state!=='device'?'disabled':''}>${esc(d.description.match(/model:(\S+)/)?.[1]||d.serial)} · ${esc(d.state)}</option>`).join('')||I18n.html('<option value="">未发现 ADB 设备</option>');if(devices.some(d=>d.serial===previous&&d.state==='device'))$('device').value=previous;}
$('refresh').onclick=()=>action(async()=>{
  if(syncBusy)return;syncBusy=true;$('refresh').disabled=true;$('refresh').textContent=I18n.t('同步中…');$('scan').disabled=true;
  $('syncFeedback').hidden=false;$('syncSpinner').hidden=false;$('syncMessage').textContent=I18n.t('正在连接手机、读取图片与视频目录…');const start=Date.now();
  const timer=setInterval(()=>{$('syncElapsed').textContent=I18n.msg`已等待 ${Math.floor((Date.now()-start)/1000)} 秒`;},250);
  const statusTimer=setInterval(()=>api('sync-status').then(s=>{if(syncBusy&&s.running)$('syncMessage').textContent=s.message;}).catch(()=>{}),800);
  try{await loadDevices();if(!$('device').value)throw Error(I18n.t('请连接手机并允许 USB 调试'));const data=await api('refresh',{serial:$('device').value});await loadAlbums();backGroups();await loadGroups();$('syncMessage').textContent=I18n.msg`同步完成：${data.count} 个媒体文件，${data.albums.length} 个相册；新增/变化 ${data.changes?.added||0}，移除/变化 ${data.changes?.removed||0}`;}
  catch(e){$('syncMessage').textContent=I18n.t('同步失败：')+e.message;throw e;}
  finally{clearInterval(timer);clearInterval(statusTimer);syncBusy=false;$('syncSpinner').hidden=true;$('syncElapsed').textContent=I18n.msg`耗时 ${((Date.now()-start)/1000).toFixed(1)} 秒`;$('refresh').textContent=I18n.t('↻ 同步目录');$('refresh').disabled=false;$('scan').disabled=wasRunning;}
});
$('device').onchange=()=>{$('refresh').click();};
$('scan').onclick=()=>action(async()=>{const state=await api('scan',{albums:[...selected],mode:$('mode').value,scope:$('scope').value,force:$('scanStrategy').value==='force',all_albums:$('scanTarget').value==='all',serial:$('device').value||null,threshold:$('mode').value==='subject'?window.ScanOptions.subjectThreshold():Number($('contentThreshold').value),...($('mode').value==='subject'?{subject_engine:'auto'}:{}),...($('mode').value==='variants'?{rules:window.ScanOptions.rules()}:{})});showScanState(state);await poll();});
$('stop').onclick=()=>action(async()=>{const d=await api('stop',{});$('statusText').textContent=d.message;});
async function poll(){if(pollBusy||window.ServiceControl?.stopping)return;pollBusy=true;try{
  const s=await api('status');
  scanState=s;renderResultStatus();
  $('scan').disabled=s.running||syncBusy;$('refresh').disabled=s.running||syncBusy;$('stop').hidden=!s.running;
  $('scope').disabled=s.running;$('mode').disabled=s.running;$('statusText').textContent=s.message;
  for(const id of ['scanStrategy','scanTarget','device','contentThreshold','subjectThreshold'])$(id).disabled=s.running||syncBusy;
  for(const id of ['cachePreview','installSubjectModel'])if($(id))$(id).disabled=s.running||syncBusy;
  window.ScanOptions.setBusy(s.running||syncBusy);
  const recentRate=window.SpeedChart?.update(s);
  const speed=s.running&&recentRate!=null?I18n.msg` · ${recentRate.toFixed(1)} 个/秒（近期）`:'';
  const eta=s.running&&s.eta_seconds&&!(s.phase==='variant_match'&&s.reused_pairs)?I18n.msg` · 预计剩余 ${Math.ceil(s.eta_seconds/60)} 分钟`:'';
  const timing=!s.running&&s.elapsed_seconds!==undefined?I18n.msg` · 总耗时 ${s.elapsed_seconds} 秒`:'';
  const pairInfo=s.phase==='variant_match'?I18n.msg` · 已复用 ${fmt(s.reused_pairs||0)} 对验证`:'';
  $('progressText').textContent=s.total?I18n.msg`${fmt(s.done)} / ${fmt(s.total)}${speed}${eta}${timing}${pairInfo} · 跳过/失败 ${s.errors}`:'';
  if(s.phase==='model_install')$('progressText').textContent=I18n.msg`已下载 ${bytes(s.downloaded_bytes||0)}`;
  $('progress').value=s.total?s.done/s.total*100:0;$('currentPath').textContent=s.phase==='scan'?(s.current||''):'';
  if(s.running&&!resultsLoaded)await loadGroups();
  if(!s.running){const marker=JSON.stringify([s.phase,s.done,s.started_at]);if(wasRunning||marker!==lastResult){
    // A completed scan replaces the result set, even when it reused cached matches
    // or finished between polls. Previous-result browsing keeps its page on stop/error.
    if(s.phase==='done'){page=1;backGroups();}else if(wasRunning)backGroups();
    await loadAlbums();await loadGroups();
    reviewItems=await api('errors');renderReview();
    lastResult=marker;
  }}
  wasRunning=s.running;updatePicks();
}catch(e){window.SpeedChart?.unavailable();notice(e);}finally{pollBusy=false;}}
async function loadGroups(){
  const data=await api(`groups?page=${page}&album=${encodeURIComponent($('filterAlbum').value)}&kind=${$('filterKind').value}&sort=${$('groupSort').value}&q=${encodeURIComponent($('search').value)}`);total=data.total;
  resultSummary=data.summary;resultsLoaded=true;renderResultStatus();
  if(page>Math.max(1,Math.ceil(total/20))){page=Math.max(1,Math.ceil(total/20));return loadGroups();}
  if(!data.summary){$('ungroupedFolder').innerHTML='';$('groupCount').textContent='—';$('groupPhotoCount').textContent=I18n.t('等待分类');$('potential').textContent='—';$('groups').innerHTML=I18n.html('<div class="empty">选择真实相册，开始分类。</div>');backGroups();}
  if(data.summary){
    const s=data.summary;
    const u=data.ungrouped;
    $('ungroupedFolder').innerHTML=u?.available?I18n.html`<button class="virtual-folder" data-group="0"><div class="folder-cover">${u.covers.map(p=>I18n.html`<img loading="lazy" src="/api/thumb/${p.key}" alt="未归组媒体预览">`).join('')}</div><div class="folder-title">▱ 未归组媒体</div><div class="folder-meta">当前筛选 ${fmt(u.count)} 个 · 本次扫描共 ${fmt(s.ungrouped||0)} 个</div><div class="folder-meta">本次范围和模式下未找到匹配 · 查看并管理 →</div></button>`:I18n.html('<p class="muted">重新分类后可查看未归组媒体，已有特征会复用。</p>');
    $('ungroupedFolder').hidden=!!currentGroup;
    $('groupCount').textContent=fmt(s.groups);
    $('groupPhotoCount').textContent=I18n.msg`涉及 ${fmt(s.grouped_photos)} 个媒体文件 · 成功分析 ${fmt(s.scanned)} 个`;
    $('potential').textContent=['content','variants','subject'].includes(s.mode)?I18n.t('不作为删重依据'):bytes(s.potential_bytes);
    $('potential').parentElement.querySelector('span').textContent=['content','variants','subject'].includes(s.mode)?I18n.t('画面相似建议'):I18n.t('候选重复体积');
    $('potential').parentElement.querySelector('small').textContent=['content','variants','subject'].includes(s.mode)?I18n.t('相似画面可能保留不同内容，请人工比较'):I18n.t('每组仅保留参考图的估算，需人工确认');
    $('resultMeta').textContent=I18n.msg`结果完成于：${new Date(s.finished_at*1000).toLocaleString(I18n.locale)} · ${s.scope==='all'?I18n.t('跨相册'):I18n.t('相册内')} · ${{strict:I18n.t('快速模式'),strong:I18n.t('增强模式'),relaxed:I18n.t('宽松模式'),subject:I18n.t('自动主体组（实验）'),content:I18n.t('跨格式内容相似'),variants:I18n.t('同源画面变体')}[s.mode]}${s.total_seconds!==undefined?I18n.t(' · 该次耗时 ')+s.total_seconds+I18n.t(' 秒'):''} · ${s.mode==='content'?I18n.t('内容相似不等于重复，请自行比较'):I18n.t('虚拟文件夹不改变手机目录')}`;
    if(s.stale)$('resultMeta').textContent+=I18n.t(' · 手机目录已有变化，请重新分类');
    if(s.mode==='variants')$('resultMeta').textContent+=I18n.t(' · 本次规则：')+(s.rules?window.ScanOptions.ruleText(s.rules):I18n.t('旧版完整规则（含扭曲校正）'));
    if(s.mode==='subject'&&s.subject_engine!=='auto')$('resultMeta').textContent+=I18n.t(' · 旧版主体结果，可重新分类更新');
    $('groups').className='folder-grid';
    $('groups').innerHTML=data.groups.map(g=>I18n.html`<button class="virtual-folder" data-group="${g.id}"><div class="folder-cover">${g.photos.slice(0,3).map(p=>I18n.html`<img loading="lazy" src="/api/thumb/${p.key}" alt="分类预览">`).join('')}</div><div class="folder-title">▰ ${g.kind==='subject'?I18n.t('主体组'):g.kind==='content'?I18n.t('内容组'):g.kind==='variants'?I18n.t('同源画面组'):I18n.t('相似组')} ${String(g.id).padStart(3,'0')}${g.photos.some(p=>p.media_type==='video')?I18n.t(' · 视频'):g.photos.some(p=>p.animated)?I18n.t(' · 动画'):''}</div><div class="folder-meta">${g.photos.length} 个文件 · ${new Set(g.photos.map(p=>p.album)).size} 个来源目录</div><div class="folder-meta">最新：${esc(dateText(Math.max(...g.photos.map(photoTime))))}</div><div class="folder-meta">${['content','variants','subject'].includes(g.kind)?I18n.t('总大小 ')+bytes(g.photos.reduce((n,p)=>n+p.size,0)):I18n.t('候选体积 ')+bytes(g.potential_bytes)} <span>查看 →</span></div></button>`).join('')||I18n.html('<div class="empty"><h3>当前筛选下没有相似组</h3><p>可调整筛选或选择内容相似模式。</p></div>');
  }
  $('filteredCount').textContent=I18n.msg`${total} 个虚拟文件夹`;$('pageInfo').textContent=I18n.msg`第 ${page} / ${Math.max(1,Math.ceil(total/20))} 页`;$('previous').disabled=page<=1;$('next').disabled=page*20>=total;
  $('firstPage').disabled=page<=1;$('lastPage').disabled=page*20>=total;$('pageInput').max=Math.max(1,Math.ceil(total/20));$('pageInput').value=page;
  if(currentGroup){try{await openGroup(currentGroup.id);}catch(e){backGroups();}}
}
function backGroups(){const wasOpen=!!currentGroup;currentGroup=null;picked.clear();detailPage=1;$('groupBrowser').hidden=true;$('groups').hidden=false;$('ungroupedFolder').hidden=!$('ungroupedFolder').innerHTML;$('pagination').hidden=false;if(wasOpen)window.scrollTo({top:groupScroll,behavior:'instant'});}
async function openGroup(id){
  const opening=!currentGroup||currentGroup.id!==id;
  if(opening){detailPage=1;groupScroll=window.scrollY;}
  currentGroup=await api(`groups/${id}?page=${detailPage}&sort=${$('photoSort').value}&album=${encodeURIComponent($('filterAlbum').value)}&kind=${$('filterKind').value}&q=${encodeURIComponent($('search').value)}`);detailPage=currentGroup.page;picked=new Set([...picked].filter(key=>currentGroup.photos.some(p=>p.key===key)));
  $('ungroupedFolder').hidden=true;
  $('groups').hidden=true;$('pagination').hidden=true;$('groupBrowser').hidden=false;
  $('openGroupTitle').textContent=I18n.msg`${id===0?I18n.t('未归组媒体'):currentGroup.kind==='variants'?I18n.t('同源画面组 ')+id:I18n.t('相似组 ')+id} · ${currentGroup.total} 个媒体文件`;
  $('moveTarget').innerHTML=I18n.html('<option value="">选择手机真实目录…</option>')+albums.map(a=>`<option value="${esc(a.path)}">${esc(a.path)}</option>`).join('');
  referenceKey=currentGroup.reference_key;
  const pages=Math.max(1,Math.ceil(currentGroup.total/100));
  $('detailPagination').hidden=pages<=1;
  $('detailPrevious').disabled=detailPage<=1;$('detailNext').disabled=detailPage>=pages;
  $('detailPageInfo').textContent=I18n.msg`第 ${detailPage} / ${pages} 页 · 每页最多 100 个`;
  $('detailPageInput').value=detailPage;$('detailPageInput').max=pages;
  renderPhotos();
  updatePicks();
  if(opening)$('groupBrowser').scrollIntoView({block:'start'});
}
function renderPhotos(){
  displayedPhotos=[...currentGroup.photos];
  $('groupPhotos').innerHTML=displayedPhotos.map(p=>I18n.html`<div class="photo ${p.key===referenceKey?'reference':''}"><label class="pick-photo"><input type="checkbox" data-key="${p.key}" ${picked.has(p.key)?'checked':''}> 选择 ${p.media_type==='video'?I18n.t(' · 视频'):p.animated?I18n.t(' · 动画'):''}</label><button class="image-open" data-preview-key="${p.key}"><img loading="lazy" src="/api/thumb/${p.key}" alt="${esc(p.path.split('/').pop())}"></button><div class="photo-body"><div class="filename">${esc(p.path.split('/').pop())}</div><div class="real-path">${esc(p.album)}</div><div class="photo-info">${p.width} × ${p.height} · ${bytes(p.size)}<br>${p.taken?I18n.t('拍摄'):I18n.t('修改')}：${esc(dateText(photoTime(p)))}<br>${p.animated||p.media_type==='video'?I18n.msg`${(p.duration_ms/1000).toFixed(2)} 秒 · ${p.partial?I18n.t('部分恢复画面'):I18n.t('关键帧分析')}`:I18n.msg`清晰度参考 ${Math.round(p.sharpness)}`}</div><div class="score">${currentGroup.kind==='ungrouped'?I18n.t('未找到匹配（不代表绝对唯一）'):p.key===referenceKey?(['content','variants','subject'].includes(currentGroup.kind)?I18n.t('画面参考（请自行决定保留）'):I18n.t('保留参考 · 请自行决定')):p.score===1?I18n.t('文件完全相同'):I18n.msg`${['content','subject','character'].includes(p.relation)?I18n.t('模型内容分数'):I18n.t('相似度')} ${(p.score*100).toFixed(1)}% · 待确认`}</div><div class="photo-info">${esc(p.reason)}${p.warning?'<br>'+esc(p.warning):''}</div></div></div>`).join('');
}
$('photoSort').onchange=()=>action(async()=>{if(currentGroup){detailPage=1;picked.clear();await openGroup(currentGroup.id);}});
async function detailNavigate(target){const pages=Math.max(1,Math.ceil(currentGroup.total/100));if(!Number.isInteger(target)||target<1||target>pages)throw Error(I18n.msg`请输入 1 到 ${pages} 的页码`);detailPage=target;picked.clear();await openGroup(currentGroup.id);$('groupBrowser').scrollIntoView({block:'start'});}
$('detailPrevious').onclick=()=>action(()=>detailNavigate(detailPage-1));
$('detailNext').onclick=()=>action(()=>detailNavigate(detailPage+1));
$('detailJump').onclick=()=>action(()=>detailNavigate(Number($('detailPageInput').value)));
$('detailPageInput').onkeydown=e=>{if(e.key==='Enter')$('detailJump').click();};
function updatePicks(){
  $('pickedCount').textContent=I18n.msg`已选 ${picked.size} 个`;
  for(const id of ['deletePicked','movePicked'])$(id).disabled=!picked.size||wasRunning||operationBusy;
  $('comparePicked').disabled=picked.size!==2;
}
function renderReview(){
  $('errorPanel').hidden=!reviewItems.length;
  $('errors').innerHTML=reviewItems.map(p=>I18n.html`<article class="photo"><button class="image-open" data-review-key="${esc(p.key||'')}"><img src="/api/thumb/${esc(p.key||'missing')}" alt="待检查媒体预览" loading="lazy"></button><div class="photo-body"><div class="filename">${esc(p.path.split('/').pop())}</div><div class="real-path">${esc(p.path)}</div><p class="photo-info">${p.analyzed?I18n.t('已恢复画面并参与分析'):I18n.t('保留文件记录，可尝试查看原文件')}<br>${esc(p.error)}</p><button class="secondary" data-review-key="${esc(p.key||'')}">查看原文件</button></div></article>`).join('');
}
$('errors').onclick=e=>{const target=e.target.closest('[data-review-key]');if(target&&target.dataset.reviewKey)window.openPhotoViewer(reviewItems,target.dataset.reviewKey);};
$('backGroups').onclick=backGroups;
$('groups').onclick=e=>{const card=e.target.closest('[data-group]');if(card)action(async()=>{picked.clear();await openGroup(Number(card.dataset.group));});};
$('ungroupedFolder').onclick=$('groups').onclick;
$('groupPhotos').addEventListener('change',e=>{if(e.target.dataset.key){e.target.checked?picked.add(e.target.dataset.key):picked.delete(e.target.dataset.key);updatePicks();}});
$('groupPhotos').onclick=e=>{const button=e.target.closest('[data-preview-key]');if(button)action(async()=>{let photos=displayedPhotos;if(currentGroup.total>100){const id=currentGroup.id;const data=await api(`groups/${id}?sort=${$('photoSort').value}&album=${encodeURIComponent($('filterAlbum').value)}&kind=${$('filterKind').value}&q=${encodeURIComponent($('search').value)}`);if(currentGroup?.id!==id)return;photos=data.photos;}window.openPhotoViewer(photos,button.dataset.previewKey);});};
$('pickAll').onclick=()=>{picked=new Set(currentGroup.photos.map(p=>p.key));for(const box of $('groupPhotos').querySelectorAll('input'))box.checked=true;updatePicks();};
$('clearPicks').onclick=()=>{picked.clear();for(const box of $('groupPhotos').querySelectorAll('input'))box.checked=false;updatePicks();};
async function prepareOperation(kind){
  if(kind==='move'&&!$('moveTarget').value)throw Error(I18n.t('请选择手机上真实存在的目标目录'));
  pendingPlan=await api('operations/preview',{keys:[...picked],action:kind,target:kind==='move'?$('moveTarget').value:null});
  $('operationTitle').textContent=kind==='delete'?I18n.msg`删除手机上的 ${pendingPlan.items.length} 个原文件`:I18n.msg`移动手机上的 ${pendingPlan.items.length} 个媒体文件`;
  $('operationExplanation').textContent=kind==='delete'?I18n.t('这些文件将从手机原路径永久删除，不进入回收站。请核对下列文件。'):I18n.t('文件将移动到选定的手机真实目录。同名文件不会覆盖，虚拟相似组仍然只是程序中的展示。');
  $('operationPaths').textContent=pendingPlan.items.map(p=>p.source+(p.destination?'\n  → '+p.destination:'')).join('\n\n');
  $('confirmOperation').textContent=kind==='delete'?I18n.t('确认永久删除'):I18n.t('确认移动');$('operationDialog').showModal();
}
$('deletePicked').onclick=()=>action(()=>prepareOperation('delete'));
$('movePicked').onclick=()=>action(()=>prepareOperation('move'));
$('cancelOperation').onclick=()=>{$('operationDialog').close();pendingPlan=null;};
$('confirmOperation').onclick=()=>action(async()=>{
  if(!pendingPlan||operationBusy)return;
  operationBusy=true;$('confirmOperation').disabled=true;$('cancelOperation').disabled=true;
  try{
    const result=await api('operations/execute',{token:pendingPlan.token});
    $('operationDialog').close();pendingPlan=null;picked.clear();
    await loadAlbums();await loadGroups();
    notice(I18n.msg`成功 ${result.succeeded} / ${result.results.length} 个。`+result.results.filter(r=>r.error||r.warnings?.length).map(r=>`\n${r.source}: ${r.error||r.warnings.join('; ')}`).join(''));
  }finally{operationBusy=false;$('confirmOperation').disabled=false;$('cancelOperation').disabled=false;updatePicks();}
});
for(const id of ['filterAlbum','filterKind','groupSort'])$(id).onchange=()=>action(async()=>{backGroups();page=1;await loadGroups();});
let searchTimer;$('search').oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>action(async()=>{backGroups();page=1;await loadGroups();}),250);};
$('previous').onclick=()=>action(async()=>{page--;await loadGroups();});$('next').onclick=()=>action(async()=>{page++;await loadGroups();});
$('firstPage').onclick=()=>action(async()=>{page=1;await loadGroups();});$('lastPage').onclick=()=>action(async()=>{page=Math.max(1,Math.ceil(total/20));await loadGroups();});
$('jumpPage').onclick=()=>action(async()=>{const target=Number($('pageInput').value),max=Math.max(1,Math.ceil(total/20));if(!Number.isInteger(target)||target<1||target>max)throw Error(I18n.msg`请输入 1 到 ${max} 的页码`);page=target;await loadGroups();});
$('pageInput').onkeydown=e=>{if(e.key==='Enter')$('jumpPage').click();};
action(async()=>{await loadDevices();await loadAlbums();await poll();});
let lastPollAt=0;
setInterval(()=>{const now=Date.now();if(!document.hidden&&now-lastPollAt>=(wasRunning?500:2000)){lastPollAt=now;poll();}},250);
