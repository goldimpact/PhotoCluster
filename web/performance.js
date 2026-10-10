/* Hardware availability is distinct from the active classification stage. */
(()=>{
  const line=document.createElement('p');line.id='hardwareInfo';line.className='muted';
  line.setAttribute('role','status');document.querySelector('.scan-panel').append(line);
  fetch('/api/hardware').then(r=>{if(!r.ok)throw Error('hardware');return r.json().then(data=>I18n.api(data));}).then(h=>{
    const a=h.accelerator;
    line.textContent=I18n.msg`本地计算：${h.cpu_physical} 核 / ${h.cpu_logical} 线程 · ${h.memory_gb} GB 内存 · ${h.workers} 个并行任务。内容检索：${a.backend==='cuda'?I18n.t('CUDA 可用（')+a.device+'）':'CPU'}；同源分析：${h.sift}；模型推理：CPU INT8。`;
    if(a.backend!=='cuda')line.textContent+=I18n.t(' GPU 不可用时自动使用 CPU。');
  }).catch(()=>{line.textContent=I18n.t('本地计算状态暂时无法读取；不影响分类。');});
})();
