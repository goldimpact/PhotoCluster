/* The server acknowledges exit; loss of a connection alone is never called success. */
(()=>{
  const panel=document.createElement('section');panel.className='service-control';
  panel.innerHTML=I18n.html('<div><strong id="serviceState" role="status">正在连接本地服务…</strong><p id="serviceHint">关闭浏览器标签页不会退出程序。</p></div><button id="exitService" class="secondary" disabled>退出 PhotoCluster</button>');
  document.querySelector('header').after(panel);
  const dialog=document.createElement('dialog');dialog.id='exitDialog';
  dialog.innerHTML=I18n.html('<h2>退出 PhotoCluster？</h2><p>正在分类时会先停止并保存已完成的缓存；正在删除、移动或读取的文件会等待当前操作结束。退出不会删除缓存或手机文件。</p><div class="dialog-actions"><button id="cancelExit" class="secondary">取消</button><button id="confirmExit" class="primary">确认退出</button></div>');
  document.body.append(dialog);
  const $=id=>document.getElementById(id);
  let snapshot=null,busy=false,accepted=false,waiting=false;
  window.ServiceControl={get stopping(){return waiting;}};
  function freeze(){
    waiting=true;
    for(const id of ['preview','compareDialog','operationDialog']){const d=$(id);if(d?.open)d.close();}
    document.querySelector('main .scan-panel').inert=true;
    document.querySelector('main .results').inert=true;
    document.querySelector('aside').inert=true;
    window.SpeedChart?.unavailable();
    $('exitService').disabled=true;
  }
  async function refresh(){
    if(busy)return;busy=true;
    try{
      const r=await fetch('/api/runtime',{cache:'no-store',signal:AbortSignal.timeout(3000)});
      if(r.status===404){
        const legacy=await fetch('/api/status',{cache:'no-store',signal:AbortSignal.timeout(3000)});
        if(!legacy.ok)throw Error('unavailable');
        const status=await legacy.json();if(typeof status.running!=='boolean')throw Error('unavailable');
        $('serviceState').textContent=I18n.t('旧版服务正在运行');
        $('serviceHint').textContent=I18n.t('页面已更新，后台仍是旧版。双击 PhotoCluster.cmd，在控制窗口点击“切换到新版”，无需寻找原终端。');
        $('exitService').textContent=I18n.t('旧版服务不支持界面退出');
        $('exitService').disabled=true;return;
      }
      if(!r.ok)throw Error('unavailable');
      const next=await r.json();
      if(next.application!=='PhotoCluster')throw Error('unavailable');
      if(waiting&&snapshot&&next.instance!==snapshot.instance){location.reload();return;}
      snapshot=next;
      if(next.stopping){freeze();$('serviceState').textContent=I18n.t('正在退出，等待当前工作完成…');$('serviceHint').textContent=I18n.t('正在保存缓存和释放预览，请稍候。');}
      else{
        $('serviceState').textContent=next.managed?I18n.t('本地服务正在运行'):I18n.t('服务由外部命令管理');
        $('exitService').textContent=next.managed?I18n.t('退出 PhotoCluster'):I18n.t('请从原启动窗口退出');
        $('serviceHint').textContent=next.managed?I18n.t('关闭浏览器标签页不会退出程序。'):I18n.t('此服务由外部启动方式管理。可在 PhotoCluster 控制窗口点击“切换到新版”；命令行用户也可在原终端按 Ctrl+C。');
        $('exitService').disabled=!next.managed;
      }
    }catch{
      $('exitService').disabled=true;
      $('serviceState').textContent=waiting&&accepted?I18n.t('退出请求已接受，服务连接已断开'):I18n.t('无法连接本地服务');
      $('serviceHint').textContent=waiting&&accepted?I18n.t('可关闭此页面；启动窗口会在进程结束后显示“已停止”。再次使用请打开 PhotoCluster 启动器。'):I18n.t('请打开 PhotoCluster 启动器查看状态或启动服务，然后刷新页面。');
    }finally{busy=false;}
  }
  $('exitService').onclick=()=>dialog.showModal();
  $('cancelExit').onclick=()=>dialog.close();
  $('confirmExit').onclick=async()=>{
    if(!snapshot||waiting)return;
    $('confirmExit').disabled=true;
    try{
      const r=await fetch('/api/runtime/exit',{method:'POST',headers:{'X-PhotoCluster-Token':snapshot.token},signal:AbortSignal.timeout(5000)});
      if(!r.ok)throw Error('exit failed');
      accepted=true;freeze();dialog.close();
      $('serviceState').textContent=I18n.t('正在退出，等待当前工作完成…');
      $('serviceHint').textContent=I18n.t('正在保存缓存和释放预览，请稍候。');
    }catch{dialog.close();$('serviceHint').textContent=I18n.t('退出请求未确认，请检查启动器状态后重试。');}
    finally{$('confirmExit').disabled=false;}
  };
  refresh();const timer=setInterval(refresh,1500);
  window.addEventListener('pagehide',()=>clearInterval(timer));
})();
