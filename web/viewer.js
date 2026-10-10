/* Geometry is independent of the DOM so cursor-anchor behavior is testable. */
window.zoomGeometry=({width,height,viewWidth,viewHeight,oldScale,newScale,scrollX,scrollY,x,y})=>{
  const oldLeft=Math.max(0,(viewWidth-width*oldScale)/2),oldTop=Math.max(0,(viewHeight-height*oldScale)/2);
  const pointX=(scrollX+x-oldLeft)/oldScale,pointY=(scrollY+y-oldTop)/oldScale;
  const newWidth=width*newScale,newHeight=height*newScale;
  const left=Math.max(0,(viewWidth-newWidth)/2),top=Math.max(0,(viewHeight-newHeight)/2);
  return {width:newWidth,height:newHeight,left,top,
    scrollX:Math.max(0,Math.min(Math.max(0,newWidth-viewWidth),left+pointX*newScale-x)),
    scrollY:Math.max(0,Math.min(Math.max(0,newHeight-viewHeight),top+pointY*newScale-y))};
};
(()=>{
  let photos=[],index=0,controller=null,resource=null,generation=0,scale=null,ready=false,drag=null;
  const dialog=$('preview'),img=$('previewImage'),viewport=$('previewViewport'),stage=$('imageStage'),video=$('previewVideo');
  const actualScale=()=>scale||Math.min(1,viewport.clientWidth/Math.max(1,img.naturalWidth),viewport.clientHeight/Math.max(1,img.naturalHeight));
  function layout(value){const w=img.naturalWidth*value,h=img.naturalHeight*value;stage.style.width=Math.max(viewport.clientWidth,w)+'px';stage.style.height=Math.max(viewport.clientHeight,h)+'px';img.style.width=w+'px';img.style.height=h+'px';img.style.left=Math.max(0,(viewport.clientWidth-w)/2)+'px';img.style.top=Math.max(0,(viewport.clientHeight-h)/2)+'px';}
  function release(){generation++;controller?.abort();controller=null;img.onload=null;img.onerror=null;img.removeAttribute('src');video.pause();video.removeAttribute('src');video.load();resource?.release();resource=null;ready=false;drag=null;}
  function fit(){scale=null;layout(actualScale());viewport.scrollTo(0,0);$('zoomFit').textContent=I18n.t('适应窗口');}
  function zoom(value,x=viewport.clientWidth/2,y=viewport.clientHeight/2){if(!ready)return;const old=actualScale();scale=Math.max(.05,Math.min(12,value));
    const geometry=window.zoomGeometry({width:img.naturalWidth,height:img.naturalHeight,viewWidth:viewport.clientWidth,viewHeight:viewport.clientHeight,oldScale:old,newScale:scale,scrollX:viewport.scrollLeft,scrollY:viewport.scrollTop,x,y});
    layout(scale);viewport.scrollLeft=geometry.scrollX;viewport.scrollTop=geometry.scrollY;$('zoomFit').textContent=Math.round(scale*100)+I18n.t('% · 适应');
  }
  async function show(next){
    release();index=(next+photos.length)%photos.length;const run=generation,p=photos[index];scale=null;
    const isVideo=p.media_type==='video';video.hidden=true;stage.hidden=false;
    for(const id of ['zoomFit','zoomActual','zoomIn','zoomOut'])$(id).disabled=isVideo;
    $('previewPosition').textContent=`${index+1} / ${photos.length}${isVideo?I18n.t(' · 视频'):p.animated?I18n.t(' · 动画'):''}`;
    $('previewPath').textContent=p.path;$('previewMetadata').textContent=`${p.width||'?'} × ${p.height||'?'} · ${bytes(p.size)} · ${p.taken?I18n.t('拍摄'):I18n.t('修改')} ${dateText(photoTime(p))}${p.warning?' · '+p.warning:''}`;
    $('previewStatus').textContent=isVideo?I18n.t('正在从手机准备可拖动播放的视频…'):I18n.t('正在从手机读取原图…');img.onload=fit;img.src='/api/thumb/'+p.key;
    controller=new AbortController();
    try{
      const loaded=await MediaView.load(p,controller.signal);if(run!==generation||!dialog.open){loaded.release();return;}resource=loaded;
      if(loaded.video){stage.hidden=true;video.hidden=false;video.src=loaded.url;$('previewStatus').textContent=I18n.t('视频已就绪 · 可播放和拖动进度');video.onerror=()=>{$('previewStatus').textContent=I18n.t('浏览器无法播放此编码；可通过列表关键帧查看内容。');};}
      else {img.onload=()=>{if(run!==generation)return;ready=true;fit();$('previewStatus').textContent=loaded.converted?I18n.t('全分辨率兼容预览'):p.animated?I18n.t('手机原始动画 · 自动播放'):I18n.t('手机原图 · 滚轮以鼠标位置缩放');};img.onerror=()=>{if(run===generation)$('previewStatus').textContent=I18n.t('原文件无法完整解码，可返回列表查看已恢复画面。');};img.src=loaded.url;}
    }catch(error){if(error.name!=='AbortError'&&run===generation)$('previewStatus').textContent=I18n.t('读取失败：')+error.message+I18n.t('。保留已恢复的缩略图。');}
  }
  window.openPhotoViewer=(items,key)=>{photos=[...items];const start=photos.findIndex(p=>p.key===key);if(start<0)return;if(!dialog.open)dialog.showModal();show(start);};
  $('previewPrevious').onclick=()=>show(index-1);$('previewNext').onclick=()=>show(index+1);$('retryOriginal').onclick=()=>show(index);$('closePreview').onclick=()=>dialog.close();
  dialog.addEventListener('close',()=>{release();photos=[];});dialog.addEventListener('keydown',e=>{if(e.target===video)return;if(e.key==='ArrowLeft'){e.preventDefault();show(index-1);}if(e.key==='ArrowRight'){e.preventDefault();show(index+1);}});
  $('zoomFit').onclick=fit;$('zoomActual').onclick=()=>zoom(1);$('zoomIn').onclick=()=>zoom(actualScale()*1.25);$('zoomOut').onclick=()=>zoom(actualScale()/1.25);
  viewport.addEventListener('wheel',e=>{if(ready){e.preventDefault();const r=viewport.getBoundingClientRect();zoom(actualScale()*(e.deltaY<0?1.15:1/1.15),e.clientX-r.left,e.clientY-r.top);}},{passive:false});
  img.draggable=false;viewport.onpointerdown=e=>{if(ready&&scale){drag={x:e.clientX,y:e.clientY,left:viewport.scrollLeft,top:viewport.scrollTop};viewport.setPointerCapture(e.pointerId);}};
  viewport.onpointermove=e=>{if(drag){viewport.scrollLeft=drag.left+drag.x-e.clientX;viewport.scrollTop=drag.top+drag.y-e.clientY;}};viewport.onpointerup=viewport.onpointercancel=()=>{drag=null;};
  window.addEventListener('resize',()=>{if(dialog.open&&ready){if(scale)layout(scale);else fit();}});window.addEventListener('pagehide',release);
})();
