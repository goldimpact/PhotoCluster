/* Visible controls: labels and dedicated status, rather than hover prose. */
(()=>{
  const byId=id=>document.getElementById(id);
  byId('mode').insertAdjacentHTML('afterbegin',I18n.html('<option value="variants">找同一画面的改图 · 旋转 / 加字 / 变形</option><option value="content">按画面内容归类 · 相近场景 / 画风</option>'));byId('mode').value='variants';
  byId('mode').closest('label').firstChild.textContent=I18n.t('识别方式');
  document.querySelector('header h1').textContent=I18n.t('把相近的画面，放在一起。');
  document.querySelector('footer').textContent=I18n.t('支持手机媒体库中的本地图片、GIF 和视频。内容相似是视觉模型的归类建议，不等于重复；损坏或只能部分恢复的媒体保留在待检查卡片中。');
  byId('mode').closest('label').insertAdjacentHTML('afterend',I18n.html('<label id="contentThresholdLabel">内容相似程度<select id="contentThreshold"><option value="0.84">相近场景（推荐）</option><option value="0.77">更宽 · 相近内容与画风</option><option value="0.90">更严 · 高度相近画面</option></select></label>'));
  byId('contentThresholdLabel').hidden=true;
  byId('scanHelp').setAttribute('aria-live','polite');
  byId('scanHelp').insertAdjacentHTML('beforebegin',I18n.html(`<details class="scan-guide" id="recognitionGuide"><summary>这些识别方式有什么区别？能按同一个角色分类吗？</summary><ul><li><strong>找副本：</strong>例如原图与压缩图。快速优先速度；增强增加旋转、拉伸对齐；宽松允许更多细微差异。这三种都是近重复识别。</li><li><strong>找同一画面的改图：</strong>例如一张表情包被倒置、加字、裁剪或变形。仍需要共享原画面；同一角色重新画了一张，通常不属于这种关系。</li><li><strong>按画面内容归类：</strong>例如不同图片或视频片段中的相近场景、构图与画风。可以跨原图来源，但画面相近不代表主体相同。</li></ul><p>尚不支持可靠的主体身份归类：同一角色的表情包、二创与恶搞图可能分散，不同角色也可能因画风相近而混在一起。选择“更宽”不会开启角色识别。</p><p>“同一个角色 / 同一辆车”与“都是猫 / 都是汽车”是不同的分类目标，现有模式没有分别识别这两种关系。所有方式均在本机分析，分类不会移动手机文件。</p></details>`));
  byId('scanHelp').insertAdjacentHTML('afterend',I18n.html`<fieldset id="variantRules" class="variant-rules"><legend>同源识别规则 · 可多选</legend><p class="rule-base">基础识别始终开启：旋转 / 倒置、缩放 / 拉伸、裁剪和加字等局部变化。图片、GIF 与视频均参与；动态媒体按抽样关键帧比较。</p><div class="rule-grid"><label><input id="ruleMirror" type="checkbox" checked><span><strong>镜像版本</strong><small>额外比较左右翻转画面；增加特征匹配开销。</small></span></label><label><input id="rulePerspective" type="checkbox" checked><span><strong>透视变化 <em>额外开销</em></strong><small>例如斜拍、梯形变化；关闭后使用旋转、缩放、拉伸等仿射对齐。</small></span></label><label><input id="ruleWarp" type="checkbox"><span><strong>轻度扭曲校正 <em class="cost-high">高开销 · 按需开启</em></strong><small>基础对齐失败后再尝试局部变形。关闭可省去这一步，也可能漏掉扭曲版本。</small></span></label></div><p class="rule-note">标注的是额外计算开销，不是固定耗时承诺。修改设置后需点击“同步并分类”，已有结果不会自动变化。</p></fieldset><p id="scanStrategyHelp" class="scan-help" aria-live="polite"></p>`);
  byId('groups').insertAdjacentHTML('beforebegin','<div id="ungroupedFolder" class="folder-grid" hidden></div>');
  document.querySelector('.results-heading').insertAdjacentHTML('afterend',I18n.html('<p id="resultStatus" class="result-status" role="status" aria-live="polite">正在读取已保存的分类结果…</p>'));
  byId('groupPhotos').insertAdjacentHTML('afterend',I18n.html('<div id="detailPagination" class="pagination" hidden><button id="detailPrevious" class="secondary">上一页</button><span id="detailPageInfo"></span><button id="detailNext" class="secondary">下一页</button><label>跳至 <input id="detailPageInput" type="number" min="1" step="1" value="1" aria-label="组内目标页码"> 页</label><button id="detailJump" class="secondary">跳转</button></div>'));
  byId('pickAll').textContent=I18n.t('全选本页（最多 100 个）');
  byId('groupBrowser').querySelector('p').textContent=I18n.t('这些是虚拟文件夹，不支持新增文件。可查看原文件、并排对比，以及删除或移动到手机真实目录。未归组仅表示本次范围和模式下未找到匹配。');
  document.body.insertAdjacentHTML('beforeend',I18n.html('<button id="backTop" class="back-top secondary" aria-label="回到相似分类文件夹区域顶部" hidden>↑ 回到分类区</button>'));
  const top=byId('backTop');
  const results=document.querySelector('.results');
  // Measure at use time: help, progress and translated copy can move the section.
  const resultTop=()=>Math.max(0,window.scrollY+results.getBoundingClientRect().top-16);
  const updateTop=()=>{top.hidden=window.scrollY<resultTop()+400;};
  window.addEventListener('scroll',updateTop,{passive:true});
  window.addEventListener('resize',updateTop);
  if(typeof ResizeObserver!=='undefined')new ResizeObserver(updateTop).observe(document.querySelector('main'));
  updateTop();
  top.onclick=()=>window.scrollTo({top:resultTop(),behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});
  byId('syncInfo').insertAdjacentHTML('afterend','<div id="syncFeedback" class="sync-feedback" role="status" aria-live="polite" hidden><span id="syncSpinner" class="spinner"></span><span id="syncMessage"></span><span id="syncElapsed"></span></div>');
  const sort=byId('groupSort'),label=document.createElement('label');label.className='group-sort-label';label.textContent=I18n.t('分组排序 ');sort.before(label);label.append(sort);sort.querySelector('[value="size"]').textContent=I18n.t('体积最大');
  byId('filterKind').insertAdjacentHTML('beforeend',I18n.html('<option value="video">包含视频的组</option>'));
  byId('pagination').insertAdjacentHTML('afterbegin',I18n.html('<button id="firstPage" class="secondary">首页</button>'));
  byId('pagination').insertAdjacentHTML('beforeend',I18n.html('<button id="lastPage" class="secondary">末页</button><label>跳至 <input id="pageInput" type="number" min="1" step="1" value="1" aria-label="目标页码"> 页</label><button id="jumpPage" class="secondary">跳转</button>'));
  byId('errorPanel').querySelector('summary').textContent=I18n.t('待检查媒体（包含无法完整解码的文件）');
  byId('errors').replaceWith(Object.assign(document.createElement('div'),{id:'errors',className:'detail-photos'}));
  byId('clearPicks').insertAdjacentHTML('afterend',I18n.html('<button id="comparePicked" class="secondary">并排对比（选 2 个）</button>'));
  const viewport=byId('previewViewport'),stage=document.createElement('div');stage.id='imageStage';viewport.prepend(stage);stage.append(byId('previewImage'));
  stage.insertAdjacentHTML('afterend','<video id="previewVideo" controls playsinline hidden></video>');
  const compare=document.createElement('dialog');compare.id='compareDialog';compare.setAttribute('aria-label',I18n.t('媒体并排对比'));
  compare.innerHTML=I18n.html('<div class="viewer-toolbar"><strong>并排对比 · 图片 / 动画 / 视频</strong><button id="closeCompare" class="secondary">关闭 ×</button></div><div id="comparePanels" class="compare-panels"></div>');
  document.body.append(compare);
  // Repeated cards are self-evident. Only dedicated action controls keep help.
  const clean=()=>document.querySelectorAll('.virtual-folder[title],.image-open[title],.folder-meta[title],.pick-photo[title]').forEach(el=>el.removeAttribute('title'));
  new MutationObserver(clean).observe(byId('groups'),{childList:true,subtree:true});
  new MutationObserver(clean).observe(byId('groupPhotos'),{childList:true,subtree:true});
})();
