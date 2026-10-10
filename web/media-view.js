/* A shared lifecycle for image blobs and seekable video leases. */
window.MediaView={
  async load(photo,signal){
    if(photo.media_type==='video'){
      // A lease request may finish after cancellation; always collect and
      // release its token rather than aborting before its response arrives.
      const r=await fetch('/api/video/'+encodeURIComponent(photo.key),{method:'POST'});
      const data=I18n.api(await r.json());if(!r.ok)throw Error(data.detail||I18n.t('视频读取失败'));
      const release=()=>{fetch('/api/video-release/'+data.token,{method:'POST',keepalive:true}).catch(()=>{});};
      if(signal?.aborted){release();throw new DOMException('Aborted','AbortError');}
      const timer=setInterval(()=>fetch('/api/video-keepalive/'+data.token,{method:'POST'}).catch(()=>{}),60000);
      return {url:data.url,video:true,release(){clearInterval(timer);release();}};
    }
    const r=await fetch('/api/original/'+encodeURIComponent(photo.key),{signal,cache:'no-store'});
    if(!r.ok){const error=I18n.api(await r.json());throw Error(error.detail||I18n.t('原图读取失败'));}
    const url=URL.createObjectURL(await r.blob());
    return {url,video:false,converted:r.headers.get('X-Preview-Converted')==='1',release(){URL.revokeObjectURL(url);}};
  }
};
(()=>{
  let resources=[],controllers=[],generation=0;
  const dialog=$('compareDialog');
  function clear(){generation++;controllers.forEach(c=>c.abort());controllers=[];dialog.querySelectorAll('video').forEach(v=>{v.pause();v.removeAttribute('src');v.load();});resources.forEach(r=>r.release());resources=[];$('comparePanels').replaceChildren();}
  $('comparePicked').onclick=()=>action(async()=>{
    const photos=currentGroup.photos.filter(p=>picked.has(p.key));if(photos.length!==2)throw Error(I18n.t('请恰好选择两个媒体文件'));
    clear();const run=generation;dialog.showModal();
    await Promise.all(photos.map(async p=>{
      const panel=document.createElement('section');panel.innerHTML=I18n.html`<h3>${esc(p.path.split('/').pop())}</h3><img src="/api/thumb/${p.key}" alt="媒体预览"><video controls playsinline hidden></video><p role="status">正在读取…</p><small>${esc(p.path)}</small>`;$('comparePanels').append(panel);
      const controller=new AbortController();controllers.push(controller);
      try{const resource=await MediaView.load(p,controller.signal);if(run!==generation){resource.release();return;}resources.push(resource);
        const el=panel.querySelector(resource.video?'video':'img');panel.querySelector('img').hidden=resource.video;el.hidden=false;el.src=resource.url;panel.querySelector('p').textContent=resource.video?I18n.t('可播放、暂停和拖动进度'):I18n.t('原图已加载');
      }catch(e){if(run===generation&&e.name!=='AbortError')panel.querySelector('p').textContent=e.message;}
    }));
  });
  $('closeCompare').onclick=()=>dialog.close();dialog.addEventListener('close',clear);window.addEventListener('pagehide',clear);
})();
