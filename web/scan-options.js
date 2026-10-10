/* One source of truth for settings help and the request's optional rules. */
(()=>{
  const ids={mirror:'ruleMirror',perspective:'rulePerspective',warp:'ruleWarp'};
  const labels={mirror:I18n.t('镜像版本'),perspective:I18n.t('透视变化'),warp:I18n.t('轻度扭曲校正')};
  const $=id=>document.getElementById(id);
  const descriptions={
    strict:I18n.t('快速近重复：比较感知指纹及画面结构，适合压缩、缩小和 90° / 180° 旋转后的副本。速度优先，任意角度或局部变形可能漏检。'),
    strong:I18n.t('增强近重复：在快速匹配之外增加局部特征和几何对齐，查找任意角度旋转、缩放及拉伸后的高度近似副本；比快速模式开销更高。'),
    relaxed:I18n.t('宽松近重复：使用增强模式的匹配流程，放宽画面差异容忍度，覆盖更多细微变化；更容易混入内容不同的文件，请仔细核对。'),
    variants:I18n.t('同源画面变体：查找同一画面的改动版本，按下方勾选规则扩展识别。它依赖共同画面，不会仅因属于同一角色或风格就归组。'),
  };
  const contentDescriptions={
    '0.84':I18n.t('相近场景：按本地视觉模型归类图片、动画和视频中的相近画面，允许不同片段；不要求来自同一原图。'),
    '0.77':I18n.t('更宽 · 相似角色与风格：允许较大的画面差异，可能将同类角色或类似画风归组；误归组风险更高。'),
    '0.90':I18n.t('更严 · 高度相近画面：提高本地模型的内容相似门槛，分组更保守，但仍不等于同源或重复文件。'),
  };
  function rules(){return Object.fromEntries(Object.entries(ids).map(([key,id])=>[key,$(id).checked]));}
  function ruleText(value){return Object.keys(ids).filter(k=>value?.[k]).map(k=>labels[k]).join(I18n.language==='en'?', ':'、')||I18n.t('仅基础同源识别');}
  function render(){
    const mode=$('mode').value;
    $('contentThresholdLabel').hidden=mode!=='content';$('variantRules').hidden=mode!=='variants';
    $('scanHelp').textContent=(mode==='content'?contentDescriptions[$('contentThreshold').value]:descriptions[mode])||I18n.t('请选择识别方式。');
    if(mode==='variants')$('scanHelp').textContent+=I18n.t(' 当前扩展：')+ruleText(rules())+(I18n.language==='en'?'.':'。');
    if(['strong','strict','relaxed'].includes(mode))$('scanHelp').textContent+=I18n.t(' 动画使用严格的时间轴抽样验证；非完全相同的视频需使用同源或语义模式。');
    $('scanStrategyHelp').textContent=$('scanStrategy').value==='force'
      ?I18n.t('扫描方式：强制全量重算，重新读取所选范围的原文件并提取特征，耗时较长；按当前识别方式和规则分类，不修改手机文件。')
      :I18n.t('扫描方式：增量更新，先同步目录，复用未变化的特征和兼容的比较结果。改变规则会按新组合重新归类，无须强制全量重算。');
  }
  try{const saved=JSON.parse(localStorage.getItem('photocluster.variantRules')||'null');for(const [k,id] of Object.entries(ids))if(typeof saved?.[k]==='boolean')$(id).checked=saved[k];}catch{}
  for(const id of ['mode','contentThreshold','scanStrategy'])$(id).addEventListener('change',render);
  for(const id of Object.values(ids))$(id).addEventListener('change',()=>{try{localStorage.setItem('photocluster.variantRules',JSON.stringify(rules()));}catch{}render();});
  window.ScanOptions={rules,ruleText,render,setBusy(busy){$('variantRules').disabled=busy;}};
  render();
})();
