/* Real observations at 500ms; animation interpolates only between known points. */
(()=>{
  const WINDOW=60000,RATE_WINDOW=2000,DELAY=500,STALE=3000;
  class SpeedHistory {
    constructor(){this.reset(null,null);}
    reset(job,phase){this.job=job;this.phase=phase;this.readings=[];this.points=[];this.rate=null;this.time=0;this.active=false;this.gap=false;}
    snapshot(now,wall){
      return {version:1,wall,job:this.job,phase:this.phase,active:this.active,rate:this.rate,
        time:this.time-now,readings:this.readings.map(p=>({...p,time:p.time-now})),
        points:this.points.map(p=>({...p,time:p.time-now}))};
    }
    restore(saved,now,wall){
      if(!saved||saved.version!==1||!Number.isFinite(saved.wall)||wall<saved.wall||wall-saved.wall>WINDOW||
        typeof saved.job!=='number'||!Number.isFinite(saved.job)||typeof saved.phase!=='string'||
        typeof saved.active!=='boolean'||!Number.isFinite(saved.time)||saved.time>0||
        !(saved.rate===null||Number.isFinite(saved.rate)&&saved.rate>=0)||
        !Array.isArray(saved.points)||saved.points.length>512||!Array.isArray(saved.readings)||saved.readings.length>512)return false;
      const validTime=p=>p&&Number.isFinite(p.time)&&p.time<=0;
      if(!saved.points.every(p=>validTime(p)&&(p.rate===null||Number.isFinite(p.rate)&&p.rate>=0))||
        !saved.readings.every(p=>validTime(p)&&Number.isFinite(p.done)&&p.done>=0&&Number.isFinite(p.cached)&&Number.isFinite(p.reused)))return false;
      const ordered=items=>items.every((p,i)=>!i||p.time>=items[i-1].time);
      if(!ordered(saved.points)||!ordered(saved.readings))return false;
      const shift=now-(wall-saved.wall);
      this.reset(saved.job,saved.phase);this.active=saved.active;this.rate=saved.rate;this.time=saved.time+shift;
      this.points=saved.points.map(p=>({...p,time:p.time+shift})).filter(p=>p.time>=now-WINDOW-DELAY);
      this.readings=saved.readings.map(p=>({...p,time:p.time+shift}));
      return true;
    }
    update(status,time){
      if(!status.running){
        if(status.started_at!==undefined&&status.started_at!==this.job)this.reset(null,null);
        this.active=false;return this.rate;
      }
      const job=status.started_at??'unknown',phase=status.phase;
      if(job!==this.job||phase!==this.phase)this.reset(job,phase);
      this.active=true;this.time=time;
      if(!Number.isFinite(status.done)||!(status.total>0)||phase==='refresh'){this.rate=null;return null;}
      const last=this.readings.at(-1);
      if(last&&time<=last.time)return this.rate;
      this.gap=!!last&&(time-last.time>STALE||status.done<last.done);
      if(this.gap){this.readings=[];this.points.push({time,rate:null});}
      this.readings.push({time,done:status.done,cached:status.cached||0,reused:status.reused_pairs||0});
      while(this.readings.length>2&&this.readings[1].time<=time-RATE_WINDOW)this.readings.shift();
      const first=this.readings[0],seconds=(time-first.time)/1000;
      this.rate=seconds>0?(status.done-first.done)/seconds:null;
      if(this.rate!==null)this.points.push({time,rate:this.rate,cached:!!status.reused_matches||(status.reused_pairs||0)>first.reused||(status.cached||0)>first.cached});
      this.points=this.points.filter(p=>p.time>=time-WINDOW-DELAY);
      return this.rate;
    }
  }
  function displayPoints(points,end){
    const result=[];
    for(let i=0;i<points.length;i++){
      const p=points[i];
      if(p.time<=end){if(p.time>=end-WINDOW)result.push(p);continue;}
      const before=points[i-1];
      if(before&&before.rate!==null&&p.rate!==null&&before.time<end)result.push({time:end,rate:before.rate+(p.rate-before.rate)*(end-before.time)/(p.time-before.time)});
      break;
    }
    return result;
  }
  window.SpeedHistory=SpeedHistory;window.SpeedDisplayPoints=displayPoints;
  const anchor=document.getElementById('currentPath');if(!anchor)return;
  anchor.insertAdjacentHTML('afterend',I18n.html`<section class="speed-chart" aria-label="处理速度趋势"><div class="speed-heading"><strong id="speedPhase">处理速度 · 等待任务</strong><span id="speedValue">等待采样</span></div><div class="speed-plot" id="speedPlot"><span id="speedMax" class="speed-scale">个/秒</span><svg id="speedSvg" viewBox="0 0 600 132" role="img" tabindex="0" aria-label="最近 60 秒速度曲线，可用左右方向键查看采样"><path id="speedGrid" class="speed-grid"/><path id="speedLine" class="speed-line" d=""/><circle id="speedDot" r="3" visibility="hidden"/><line id="speedCursor" class="speed-cursor" y1="20" y2="120" visibility="hidden"/></svg><span class="speed-zero">0</span></div><div class="speed-axis"><span>60 秒前</span><span id="speedRight">现在</span></div><p id="speedHint">开始分类后显示速度趋势</p><p id="speedSample" class="speed-sample" aria-live="off"></p></section>`);
  const $=id=>document.getElementById(id),history=new SpeedHistory();
  const storageKey='photocluster.speedHistory';let pendingRestore=null;
  try{pendingRestore=JSON.parse(sessionStorage.getItem(storageKey)||'null');sessionStorage.removeItem(storageKey);}catch{}
  const names={refresh:I18n.t('同步目录'),scan:I18n.t('读取与提取特征'),cluster:I18n.t('准备分类'),embedding:I18n.t('内容特征'),content_match:I18n.t('内容匹配'),variant_features:I18n.t('同源特征'),variant_match:I18n.t('几何验证'),subject_embedding:I18n.t('主体区域特征'),subject_match:I18n.t('主体匹配'),model_install:I18n.t('下载模型')};
  const motion=window.matchMedia('(prefers-reduced-motion: reduce)');
  let width=600,maximum=1,frame=null,lastFrame=null,viewTime=0,broken=false,selected=null,pointer=null;
  const number=n=>n.toLocaleString(I18n.locale,{maximumFractionDigits:1});
  function samples(){return history.points.filter(p=>p.rate!==null&&p.time<=viewTime&&p.time>=viewTime-WINDOW);}
  function inspect(){
    const list=samples();let point=null;
    const target=pointer===null?selected:viewTime-WINDOW+pointer*WINDOW;
    if(target!==null)for(const p of list)if(!point||Math.abs(p.time-target)<Math.abs(point.time-target))point=p;
    $('speedCursor').setAttribute('visibility',point?'visible':'hidden');
    if(!point){$('speedSample').textContent='';return;}
    const age=Math.max(0,(viewTime-point.time)/1000);
    $('speedSample').textContent=I18n.msg`${number(age)} 秒前：${number(point.rate)} 个/秒${point.cached?I18n.t(' · 含缓存复用'):''}`;
    const x=width*(1-(viewTime-point.time)/WINDOW);
    $('speedCursor').setAttribute('x1',x);$('speedCursor').setAttribute('x2',x);
  }
  function render(now){
    viewTime=history.active&&!broken&&!motion.matches?Math.min(now-DELAY,history.time):history.time;
    const points=displayPoints(history.points,viewTime);
    const target=Math.max(1,...history.points.filter(p=>p.rate!==null).map(p=>p.rate))*1.1;
    const dt=lastFrame===null?1000:Math.max(0,Math.min(100,now-lastFrame));lastFrame=now;
    maximum=motion.matches?target:maximum+(target-maximum)*(1-Math.exp(-dt/140));
    const scale=Math.max(maximum,...points.filter(p=>p.rate!==null).map(p=>p.rate*1.01));
    let path='',pen=false;
    for(const p of points){if(p.rate===null){pen=false;continue;}const x=width*(1-(viewTime-p.time)/WINDOW),y=120-100*p.rate/scale;path+=`${pen?'L':'M'}${x.toFixed(2)},${y.toFixed(2)} `;pen=true;}
    $('speedLine').setAttribute('d',path);
    const last=points.at(-1);$('speedDot').setAttribute('visibility',last&&last.rate!==null?'visible':'hidden');
    if(last&&last.rate!==null){$('speedDot').setAttribute('cx',width*(1-(viewTime-last.time)/WINDOW));$('speedDot').setAttribute('cy',120-100*last.rate/scale);}
    $('speedMax').textContent=number(scale)+I18n.t(' 个/秒');inspect();
  }
  function stop(){if(frame!==null){cancelAnimationFrame(frame);frame=null;}}
  function animate(now){
    frame=null;
    if(document.hidden||!history.active||motion.matches||broken)return;
    if(now-history.time>STALE){broken=true;$('speedHint').textContent=I18n.t('进度暂未更新，保留最后记录');return;}
    render(now);frame=requestAnimationFrame(animate);
  }
  function start(){if(frame===null&&history.active&&!motion.matches&&!document.hidden&&!broken)frame=requestAnimationFrame(animate);}
  function resize(){width=Math.max(1,$('speedPlot').getBoundingClientRect().width||600);$('speedSvg').setAttribute('viewBox',`0 0 ${width} 132`);$('speedGrid').setAttribute('d',`M0 20H${width} M0 70H${width} M0 120H${width}`);render(performance.now());}
  function update(status){
    if(pendingRestore){
      if(status.started_at===pendingRestore.job&&(!status.running||status.phase===pendingRestore.phase)){
        if(history.restore(pendingRestore,performance.now(),Date.now()))maximum=Math.max(1,...history.points.map(p=>p.rate||0))*1.1;
      }
      pendingRestore=null;
    }
    const phase=history.phase,job=history.job;
    history.update(status,performance.now());broken=false;
    if(phase!==history.phase||job!==history.job){maximum=1;lastFrame=null;selected=null;pointer=null;}
    const label=names[history.phase]||I18n.t('处理速度');
    $('speedPhase').textContent=`${label} · ${status.running?I18n.t('最近 60 秒'):history.points.length?I18n.t('最后阶段'):I18n.t('等待任务')}`;
    $('speedValue').textContent=history.rate===null?I18n.t('等待采样'):I18n.msg`${number(history.rate)} 个/秒${status.running?'':I18n.t(' · 最后采样')}`;
    $('speedRight').textContent=status.running?I18n.t('现在'):I18n.t('最后采样');
    $('speedHint').textContent=status.running
      ?status.phase==='refresh'?I18n.t('正在同步目录…'):history.gap?I18n.t('恢复进度采样，缺口期间无数据')
      :I18n.msg`悬停或触摸曲线查看速度${status.reused_pairs||status.reused_matches||status.phase==='scan'&&status.cached?I18n.t(' · 含缓存复用'):''}`
      :history.points.length?I18n.t('任务已结束或停止 · 保留最后阶段曲线'):I18n.t('开始分类后显示速度趋势');
    $('speedSvg').setAttribute('aria-label',I18n.msg`${label}，最近 60 秒，${history.rate===null?I18n.t('等待采样'):number(history.rate)+I18n.t(' 个/秒')}。左右方向键查看历史。`);
    render(performance.now());if(status.running)start();else stop();return status.running?history.rate:null;
  }
  $('speedSvg').addEventListener('pointermove',e=>{const r=$('speedSvg').getBoundingClientRect();pointer=Math.max(0,Math.min(1,(e.clientX-r.left)/r.width));inspect();});
  $('speedSvg').addEventListener('pointerleave',()=>{pointer=null;inspect();});
  $('speedSvg').addEventListener('keydown',e=>{
    if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();pointer=null;
    const list=samples();if(!list.length)return;let index=list.findIndex(p=>p.time===selected);if(index<0)index=list.length-1;
    index=e.key==='Home'?0:e.key==='End'?list.length-1:Math.max(0,Math.min(list.length-1,index+(e.key==='ArrowLeft'?-1:1)));
    selected=list[index].time;inspect();
  });
  $('speedSvg').addEventListener('blur',()=>{selected=null;inspect();});
  document.addEventListener('visibilitychange',()=>{if(document.hidden)stop();else {render(performance.now());start();}});
  motion.addEventListener('change',()=>{stop();render(performance.now());start();});
  window.addEventListener('pagehide',stop);
  new ResizeObserver(resize).observe($('speedPlot'));resize();
  window.SpeedChart={update,saveForReload(){
    try{sessionStorage.setItem(storageKey,JSON.stringify(history.snapshot(performance.now(),Date.now())));}catch{}
  },unavailable(){broken=true;stop();$('speedHint').textContent=I18n.t('暂时无法获取进度 · 保留最后记录');}};
})();
