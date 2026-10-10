const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function harness(dom=false,reduced=false){
  const nodes=new Map();let html='';const node=id=>{if(!nodes.has(id))nodes.set(id,{value:0,events:{},attrs:{},hidden:false,textContent:'',insertAdjacentHTML(where,text){html+=text;},setAttribute(k,v){this.attrs[k]=v;},removeAttribute(k){delete this.attrs[k];},addEventListener(k,fn){this.events[k]=fn;},getBoundingClientRect(){return {left:0,width:600};}});return nodes.get(id);};
  let now=0,next=0;const frames=new Map(),events={};
  const context={window:{matchMedia:()=>({matches:reduced,addEventListener(){}}),addEventListener(){}},document:{hidden:false,getElementById:id=>dom?node(id):null,addEventListener:(k,f)=>events[k]=f},performance:{now:()=>now},ResizeObserver:class{observe(){}},requestAnimationFrame:fn=>{frames.set(++next,fn);return next;},cancelAnimationFrame:id=>frames.delete(id)};
  vm.runInNewContext(fs.readFileSync("web/i18n.js","utf8")+"\n"+fs.readFileSync('web/speed-chart.js','utf8'),context);
  return {History:context.window.SpeedHistory,display:context.window.SpeedDisplayPoints,chart:context.window.SpeedChart,node,time:value=>now=value,frames,html:()=>html,document:context.document,events,frame(time){now=time;const pending=[...frames.values()];frames.clear();pending.forEach(fn=>fn(time));}};
}
const status=(done,extra={})=>({running:true,phase:'variant_match',started_at:1,total:1000,done,...extra});
test('recent rate uses observed progress, shows zero, and ignores reported average',()=>{
  const h=new (harness().History)();
  assert.equal(h.update(status(100,{rate:900}),0),null);
  assert.equal(h.update(status(120,{rate:900}),2000),10);
  assert.equal(h.update(status(120),4000),0);
  assert.equal(h.update(status(120),6000),0);
  assert.equal(h.update(status(120),8000),0);
  assert.equal(h.points.at(-1).rate,0);
});
test('phase/job changes and counter reset never connect unrelated samples',()=>{
  const h=new (harness().History)();h.update(status(0),0);h.update(status(20),2000);
  assert.equal(h.update(status(300,{phase:'embedding'}),4000),null);assert.equal(h.points.length,0);
  h.update(status(320,{phase:'embedding'}),6000);
  assert.equal(h.update(status(0,{started_at:2}),8000),null);
  h.update(status(10,{started_at:2}),10000);
  assert.equal(h.update(status(1,{started_at:2}),12000),null);assert.equal(h.points.at(-1).rate,null);
});
test('long polling gaps break curve; history bounded to 60 seconds; stop freezes',()=>{
  const h=new (harness().History)();h.update(status(0),0);h.update(status(10),2000);
  assert.equal(h.update(status(90),20000),null);assert.equal(h.gap,true);
  h.update(status(100),22000);assert.equal(h.rate,5);
  for(let t=24000;t<=100000;t+=2000)h.update(status(100+t/1000),t);
  assert.ok(h.points.every(p=>p.time>=40000));assert.ok(h.points.length<=31);
  const before=JSON.stringify(h.points);h.update({running:false,phase:'done'},120000);
  assert.equal(JSON.stringify(h.points),before);assert.equal(h.time,100000);
});
test('cache increments marked and refresh has no invented throughput',()=>{
  const h=new (harness().History)();h.update(status(0),0);
  h.update(status(10,{reused_pairs:50}),2000);assert.equal(h.points.at(-1).cached,true);
  h.update(status(0,{phase:'refresh',total:0}),4000);assert.equal(h.rate,null);assert.equal(h.points.length,0);
});
test('unscaled HTML labels, no slider, pointer and keyboard inspection, terminal record',()=>{
  const h=harness(true,true);h.chart.update(status(0));h.time(2000);h.chart.update(status(20,{reused_pairs:30}));
  assert.doesNotMatch(h.html(),/type="range"|<text|preserveAspectRatio="none"/);
  assert.match(h.html(),/<span id="speedMax"/);
  assert.match(h.node('speedLine').attrs.d,/M/);assert.match(h.node('speedValue').textContent,/10/);
  assert.match(h.node('speedHint').textContent,/缓存复用/);
  h.node('speedSvg').events.pointermove({clientX:600});assert.match(h.node('speedSample').textContent,/10 个\/秒/);
  h.node('speedSvg').events.keydown({key:'End',preventDefault(){}});assert.match(h.node('speedSample').textContent,/10/);
  h.chart.update({running:false,phase:'stopped'});assert.match(h.node('speedValue').textContent,/最后采样/);
  h.chart.unavailable();assert.match(h.node('speedHint').textContent,/无法获取/);
});

test('animation advances between network samples but never extrapolates a new speed',()=>{
  const h=harness(true);h.chart.update(status(0));h.time(500);h.chart.update(status(5));h.time(1000);h.chart.update(status(15));
  h.frame(1100);const a=h.node('speedLine').attrs.d;h.frame(1250);const b=h.node('speedLine').attrs.d;assert.notEqual(a,b);
  const points=[{time:500,rate:10},{time:1000,rate:20}];
  assert.equal(h.display(points,750).at(-1).rate,15);
  assert.equal(h.display(points,1400).at(-1).time,1000);
  assert.equal(h.display([{time:500,rate:10},{time:750,rate:null},{time:1000,rate:20}],900).at(-1).rate,null);
  h.frame(4500);assert.equal(h.frames.size,0);assert.match(h.node('speedHint').textContent,/暂未更新/);
});

test('hidden tab, stopped job, disconnected poll and reduced motion stop animation',()=>{
  const h=harness(true);h.chart.update(status(0));assert.equal(h.frames.size,1);
  h.document.hidden=true;h.events.visibilitychange();assert.equal(h.frames.size,0);
  h.document.hidden=false;h.events.visibilitychange();assert.equal(h.frames.size,1);
  h.chart.unavailable();assert.equal(h.frames.size,0);
  h.time(500);h.chart.update(status(5));assert.equal(h.frames.size,1);
  h.chart.update({running:false,phase:'done'});assert.equal(h.frames.size,0);
  const reduced=harness(true,true);reduced.chart.update(status(0));assert.equal(reduced.frames.size,0);
});
