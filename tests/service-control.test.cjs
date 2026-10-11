const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {JSDOM}=require('jsdom');
async function harness(managed=true,legacy=false){
  const dom=new JSDOM('<header></header><aside></aside><main><section class="scan-panel"></section><section class="results"></section></main>',{url:'http://localhost',runScripts:'outside-only'});
  const w=dom.window;w.localStorage.setItem('photocluster.language','en');let timer,offline=false;const requests=[];
  w.setInterval=fn=>{timer=fn;return 1;};w.clearInterval=()=>{};w.AbortSignal=AbortSignal;
  w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};w.HTMLDialogElement.prototype.close=function(){this.open=false;};
  w.fetch=async(url,options)=>{requests.push({url,options});if(offline)throw Error('offline');
    if(legacy&&url==='/api/runtime')return {ok:false,status:404};
    if(legacy&&url==='/api/status')return {ok:true,json:async()=>({running:false})};
    return {ok:true,json:async()=>({application:'PhotoCluster',instance:'test',managed,token:'token'})};};
  for(const file of ['locales/en.js','i18n.js','service-control.js'])vm.runInContext(fs.readFileSync('web/'+file,'utf8'),dom.getInternalVMContext());
  await new Promise(setImmediate);
  return {w,requests,close:()=>w.close(),offline:()=>offline=true,poll:()=>timer()};
}
test('exit is explicitly confirmed, authenticated and freezes operations only after acceptance',async()=>{
  const h=await harness();try{
    const $=id=>h.w.document.getElementById(id);
    assert.match($('serviceState').textContent,/running/);
    $('exitService').click();assert.equal($('exitDialog').open,true);
    $('cancelExit').click();assert.ok(h.requests.every(r=>!r.options?.method));
    $('exitService').click();await $('confirmExit').onclick();
    assert.equal(h.requests.at(-1).options.headers['X-PhotoCluster-Token'],'token');
    assert.equal(h.w.document.querySelector('.results').inert,true);
    h.offline();await h.poll();assert.match($('serviceState').textContent,/Exit requested/);
  }finally{h.close();}
});
test('unmanaged instance and unexpected disconnect do not claim successful exit',async()=>{
  const h=await harness(false);try{
    assert.equal(h.w.document.getElementById('exitService').disabled,true);
    assert.match(h.w.document.getElementById('serviceHint').textContent,/Ctrl\+C/);
    h.offline();await h.poll();assert.match(h.w.document.getElementById('serviceState').textContent,/Cannot connect/);
  }finally{h.close();}
});

test('legacy backend explains why exit is unavailable and never submits shutdown',async()=>{
  const h=await harness(false,true);try{
    const $=id=>h.w.document.getElementById(id);
    assert.match($('serviceState').textContent,/older service/);
    assert.match($('serviceHint').textContent,/does not upgrade/);
    assert.match($('exitService').textContent,/in-app exit unavailable/);
    assert.equal($('exitService').disabled,true);
    assert.ok(h.requests.every(r=>!r.options?.method));
  }finally{h.close();}
});
