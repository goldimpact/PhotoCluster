/* One source of truth for settings help and the request's optional rules. */
(()=>{
  const ids={mirror:'ruleMirror',perspective:'rulePerspective',warp:'ruleWarp'};
  const labels={mirror:I18n.t('镜像版本'),perspective:I18n.t('透视变化'),warp:I18n.t('轻度扭曲校正')};
  const $=id=>document.getElementById(id);
  const descriptions={
    strict:I18n.t('快速近重复：比较感知指纹及画面结构，适合压缩、缩小和 90° / 180° 旋转后的副本。速度优先，任意角度或局部变形可能漏检。'),
    strong:I18n.t('增强近重复：在快速匹配之外增加局部特征和几何对齐，查找任意角度旋转、缩放及拉伸后的高度近似副本；比快速模式开销更高。'),
    relaxed:I18n.t('宽松近重复：使用增强模式的匹配流程，放宽画面差异容忍度，覆盖更多细微变化；更容易混入内容不同的文件，请仔细核对。'),
    variants:I18n.t('找同一画面的改图（同源画面变体）：例如同一张表情包的倒置、加字、裁剪或变形版本。按下方规则扩展识别；同一角色的不同重绘不一定共享原画面。'),
    subject:I18n.t('自动发现主体（实验）：独立的本地 DINOv2 模型比较整幅画面与局部区域，尝试聚集外观相近的角色或物体。无需选择样例，图片、GIF、视频均参与。它仍可能漏掉跨画风重绘，或混入不同身份，不是已验证的角色身份识别器。'),
  };
  const contentDescriptions={
    '0.84':I18n.t('相近场景：按本地视觉模型归类图片、动画和视频中的相近画面，允许不同片段；不要求来自同一原图。'),
    '0.77':I18n.t('更宽 · 相近内容与画风：允许较大的画面差异，也更容易混入不同主体。这只是放宽画面相似门槛，不是同一角色或物体的身份识别。'),
    '0.90':I18n.t('更严 · 高度相近画面：提高本地模型的内容相似门槛，分组更保守，但仍不等于同源或重复文件。'),
  };
  function rules(){return Object.fromEntries(Object.entries(ids).map(([key,id])=>[key,$(id).checked]));}
  function ruleText(value){return Object.keys(ids).filter(k=>value?.[k]).map(k=>labels[k]).join(I18n.language==='en'?', ':'、')||I18n.t('仅基础同源识别');}
  function render(){
    const mode=$('mode').value;
    $('contentThresholdLabel').hidden=mode!=='content';$('variantRules').hidden=mode!=='variants';
    $('subjectThresholdLabel').hidden=mode!=='subject';$('subjectModelHelp').hidden=mode!=='subject';
    $('subjectEngineLabel').hidden=mode!=='subject';
    const anime=$('subjectEngine').value==='anime';
    $('subjectModelDescription').textContent=anime
      ?I18n.t('CCIP 约 150 MB，面向单角色动漫画面训练，使用上游 OpenRAIL 模型许可。首次安装下载公共权重；照片不上传，分析在本机运行。')
      :I18n.t('DINOv2 约 24 MB，用于通用外观相似，不是角色身份模型。首次安装下载公共权重；照片不上传。');
    $('scanHelp').textContent=(mode==='content'?contentDescriptions[$('contentThreshold').value]:descriptions[mode])||I18n.t('请选择识别方式。');
    if(mode==='subject'&&anime)$('scanHelp').textContent=I18n.t('动漫角色（CCIP，实验）：按专门训练的角色身份特征比较发型、脸部和服装等外观线索，允许姿态、构图和画风变化；不要求颜色完全一致。无需样例，图片、GIF 和视频抽样帧参与。适合单角色画面，多人同框、动物吉祥物及极端恶搞可能识别不好。均衡档采用上游发布门槛，不代表在你的图库中已验证准确率。');
    if(mode==='content')$('scanHelp').textContent+=I18n.t(' 当前模型比较整幅画面，背景与画风也会影响分组；无法可靠聚齐同一角色的二创、重绘和恶搞图。');
    if(mode==='subject')$('scanHelp').textContent+=({'0.65':I18n.t(' 当前门槛更宽：容忍更多外观变化，也会增加误分组。'),'0.72':I18n.t(' 当前为均衡门槛：建议先检查结果，再调整。'),'0.80':I18n.t(' 当前门槛更严：减少误分组，也可能把同一主体分散。')}[$('subjectThreshold').value]||'');
    if(mode==='variants')$('scanHelp').textContent+=I18n.t(' 当前扩展：')+ruleText(rules())+(I18n.language==='en'?'.':'。');
    if(['strong','strict','relaxed'].includes(mode))$('scanHelp').textContent+=I18n.t(' 动画使用严格的时间轴抽样验证；非完全相同的视频需使用同源或语义模式。');
    $('scanStrategyHelp').textContent=$('scanStrategy').value==='force'
      ?I18n.t('扫描方式：强制全量重算，重新读取所选范围的原文件并提取特征，耗时较长；按当前识别方式和规则分类，不修改手机文件。')
      :I18n.t('扫描方式：增量更新，先同步目录，复用未变化的特征和兼容的比较结果。改变规则会按新组合重新归类，无须强制全量重算。');
  }
  try{const saved=JSON.parse(localStorage.getItem('photocluster.variantRules')||'null');for(const [k,id] of Object.entries(ids))if(typeof saved?.[k]==='boolean')$(id).checked=saved[k];}catch{}
  for(const id of ['mode','contentThreshold','subjectThreshold','subjectEngine','scanStrategy'])$(id).addEventListener('change',render);
  for(const id of Object.values(ids))$(id).addEventListener('change',()=>{try{localStorage.setItem('photocluster.variantRules',JSON.stringify(rules()));}catch{}render();});
  function subjectThreshold(){
    const preset=$('subjectThreshold').value;
    return $('subjectEngine').value==='anime'?({'0.65':.78,'0.72':1-.17847511429108218,'0.80':.85}[preset]??1-.17847511429108218):Number(preset);
  }
  window.ScanOptions={rules,ruleText,render,subjectThreshold,setBusy(busy){$('variantRules').disabled=busy;}};
  render();
})();
