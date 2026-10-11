/* Cache actions require a visible scope preview and a second explicit click. */
(()=>{
  document.querySelector('.scan-panel').insertAdjacentHTML('beforeend',I18n.html(`<details id="cacheSettings" class="scan-guide"><summary>本地缓存 · 占用、用途与清理</summary><p>缓存保存在电脑上：缩略图与关键帧用于预览，特征用于比较，分组结果用于快速恢复。换分类规则可复用兼容特征；换模型或预处理版本会重新计算对应特征和分组。旧文件留在磁盘上不代表仍被使用。</p><p>强制全量重算只重算所选媒体，不负责释放所有旧缓存。下方清理只作用于当前服务实例，不清理其他系统实例；手机原文件、已下载模型、启动设置和操作日志均保留。</p><button id="cacheRefresh" class="secondary">查看 / 刷新缓存占用</button><div id="cacheUsage" role="status"></div><p id="cacheLocation" class="real-path"></p><label>清理范围<select id="cacheScope"><option value="results">仅分组结果 · 保留特征与预览</option><option value="analysis">分析缓存与分组 · 下次重新读取手机媒体</option><option value="all">全部媒体库缓存 · 同时忘记目录列表</option></select></label><button id="cachePreview" class="secondary">预览清理范围</button><p id="cacheFeedback" role="status"></p></details><dialog id="cacheDialog"><h2>确认清理本机缓存</h2><p id="cacheExplanation"></p><p>不会删除或移动手机文件。模型、启动设置和操作日志保留。</p><div class="dialog-actions"><button id="cacheCancel" class="secondary">取消</button><button id="cacheConfirm" class="danger">确认清理缓存</button></div></dialog>`));
  let plan=null,busy=false;
  const labels={results:I18n.t('分组结果'),analysis:I18n.t('缩略图、关键帧与分析特征'),library:I18n.t('媒体目录与特征索引'),models:I18n.t('已下载模型（保留）')};
  const effects={results:I18n.t('清空虚拟分组和已保存的匹配结果。下次分类复用兼容的特征与预览。'),analysis:I18n.t('清空虚拟分组、缩略图、关键帧、模型特征和匹配缓存。保留目录列表；下次分类需要连接手机重新读取媒体。'),all:I18n.t('清空所有媒体分析缓存、分组与目录列表。下次使用需要重新同步手机目录并分析。')};
  function render(data){
    $('cacheUsage').textContent=Object.entries(labels).map(([k,v])=>`${v}: ${bytes(data.categories[k].bytes)} (${fmt(data.categories[k].files)})`).join(' · ');
    $('cacheLocation').textContent=data.location;
    if(data.busy)$('cacheFeedback').textContent=I18n.t('正在扫描、同步或安装模型，结束后才能清理缓存。');
  }
  async function refresh(){render(await api('cache'));}
  $('cacheRefresh').onclick=()=>action(refresh);
  $('cacheSettings').addEventListener('toggle',()=>{if($('cacheSettings').open)action(refresh);});
  $('cachePreview').onclick=()=>action(async()=>{
    if(busy)return;
    plan=await api('cache/preview',{scope:$('cacheScope').value});
    $('cacheExplanation').textContent=effects[plan.scope]+' '+I18n.msg`当前涉及 ${fmt(plan.files)} 个缓存文件，约 ${bytes(plan.bytes)}。`;
    $('cacheDialog').showModal();
  });
  $('cacheCancel').onclick=()=>{$('cacheDialog').close();plan=null;};
  $('cacheDialog').addEventListener('close',()=>{plan=null;});
  $('cacheConfirm').onclick=()=>action(async()=>{
    if(!plan||busy)return;
    busy=true;$('cacheConfirm').disabled=true;
    $('cacheFeedback').textContent=I18n.t('正在清理本机缓存…');
    try{
      const result=await api('cache/clear',{token:plan.token});
      $('cacheDialog').close();render(result.usage);
      $('cacheFeedback').textContent=result.failed?I18n.msg`${result.failed} 个缓存文件暂时无法删除；可稍后重试。`:I18n.t('缓存已清理。手机文件未改变。');
      page=1;backGroups();await loadAlbums();await loadGroups();reviewItems=await api('errors');renderReview();await poll();
    }finally{busy=false;$('cacheConfirm').disabled=false;}
  });
  $('installSubjectModel').onclick=()=>action(async()=>{
    const info=await api('subject-model?engine=auto');
    if(info.installed){$('subjectModelStatus').textContent=info.perceptual?I18n.t('主体识别资源已就绪 · 已启用感知复核'):I18n.t('主体识别资源已就绪 · 基础核验');return;}
    showScanState(await api('subject-model/install',{engine:'auto'}));
    $('subjectModelStatus').textContent=I18n.t('正在下载公共模型；可在进度区查看状态。');
  });
  api('subject-model?engine=auto').then(info=>{
    if(info.installed)$('subjectModelStatus').textContent=info.perceptual?I18n.t('主体识别资源已就绪 · 已启用感知复核'):I18n.t('主体识别资源已就绪 · 基础核验');
  }).catch(()=>{});
})();
