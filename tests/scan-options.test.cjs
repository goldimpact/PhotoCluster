const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function harness(saved){
  const nodes=new Map();
  function $(id){if(!nodes.has(id))nodes.set(id,{id,value:'',checked:false,events:{},addEventListener(n,fn){this.events[n]=fn;}});return nodes.get(id);}
  $('mode').value='variants';$('scanStrategy').value='incremental';$('contentThreshold').value='0.84';$('ruleMirror').checked=$('rulePerspective').checked=true;
  const stored={value:saved?JSON.stringify(saved):null};
  const context={document:{getElementById:$},window:{},localStorage:{getItem:()=>stored.value,setItem:(k,v)=>stored.value=v}};
  vm.runInNewContext(fs.readFileSync("web/i18n.js","utf8")+"\n"+fs.readFileSync('web/scan-options.js','utf8'),context);
  const change=(id,value)=>{if(typeof value==='boolean')$(id).checked=value;else $(id).value=value;$(id).events.change();};
  return {$,change,api:context.window.ScanOptions,stored};
}
test('all five modes have their own help; strategy changes never overwrite it',()=>{
  const h=harness(),seen=new Set();
  for(const mode of ['variants','strict','strong','relaxed','content']){
    h.change('mode',mode);const text=h.$('scanHelp').textContent;seen.add(text);
    h.change('scanStrategy','force');assert.equal(h.$('scanHelp').textContent,text);
    assert.match(h.$('scanStrategyHelp').textContent,/强制全量重算/);
    h.change('scanStrategy','incremental');assert.equal(h.$('scanHelp').textContent,text);
    assert.equal(h.$('variantRules').hidden,mode!=='variants');
    assert.equal(h.$('contentThresholdLabel').hidden,mode!=='content');
  }
  assert.equal(seen.size,5);
});
test('content threshold explains each choice immediately',()=>{
  const h=harness();h.change('mode','content');
  for(const [v,text] of [['0.77','相似角色与风格'],['0.90','高度相近画面'],['0.84','相近场景']]){
    h.change('contentThreshold',v);assert.ok(h.$('scanHelp').textContent.includes(text));
  }
});
test('rules default warp off, persist, remain selected across modes, and disable during scan',()=>{
  const h=harness();assert.equal(h.api.rules().warp,false);
  h.change('ruleWarp',true);h.change('rulePerspective',false);
  assert.match(h.$('scanHelp').textContent,/轻度扭曲校正/);
  h.change('mode','content');h.change('mode','variants');assert.equal(h.api.rules().warp,true);
  h.api.setBusy(true);assert.equal(h.$('variantRules').disabled,true);
  h.api.setBusy(false);assert.equal(h.$('variantRules').disabled,false);
  const restored=harness(JSON.parse(h.stored.value));assert.equal(restored.api.rules().warp,true);assert.equal(restored.api.rules().perspective,false);
  assert.equal(h.api.ruleText({mirror:false,perspective:false,warp:false}),'仅基础同源识别');
});
