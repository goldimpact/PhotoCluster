const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),acorn=require('acorn');
const {JSDOM}=require('jsdom');
const scripts=['web/locales/en.js','web/locales/api-en.js','web/i18n.js'];
function translator(language='en'){
  const context={window:{},localStorage:{getItem:()=>language,setItem(){}}};vm.createContext(context);
  for(const file of scripts)vm.runInContext(fs.readFileSync(file,'utf8'),context);
  return vm.runInContext('I18n',context);
}
test('translation substitutes once and never translates filenames, paths or identifiers',()=>{
  const i=translator();
  assert.equal(i.msg`已选 ${3} 个`,'3 selected');
  const name='文件完全相同 {1} <b>$&</b>';
  assert.equal(i.msg`${name} 个相册 · ${'1 MB'}`,`${name} albums · 1 MB`);
  const data={path:'文件完全相同',album:'确认移动',key:'已停止',reason:'文件完全相同',message:'同步完成：20 个媒体文件',warnings:['目标已存在同名文件，不会覆盖']};
  const localized=i.api(data);
  assert.equal(localized.path,data.path);assert.equal(localized.album,data.album);assert.equal(localized.key,data.key);
  assert.equal(localized.reason,'Identical files');assert.equal(localized.message,'Sync complete: 20 media files');
  assert.equal(data.reason,'文件完全相同');
  assert.equal(i.serverText('媒体已在目标相册内：/storage/确认移动.jpg'),'Media is already in the destination album: /storage/确认移动.jpg');
  assert.equal(i.html`<div title="分类预览">${name}</div><button>查看原文件</button>`,`<div title="Group preview">${name}</div><button>View original</button>`);
  i.setLanguage('zh');assert.equal(i.msg`已选 ${3} 个`,'已选 3 个');assert.equal(i.locale,'zh-CN');
});

test('launcher language overrides stale browser preference once, then in-page choice wins',()=>{
  const dom=new JSDOM('<html><body></body></html>',{url:'http://localhost:8765/?lang=zh&keep=1#view',runScripts:'outside-only'});
  const w=dom.window;w.localStorage.setItem('photocluster.language','en');
  try{
    vm.runInContext(fs.readFileSync('web/i18n.js','utf8'),dom.getInternalVMContext());
    assert.equal(vm.runInContext('I18n.language',dom.getInternalVMContext()),'zh');
    assert.equal(w.localStorage.getItem('photocluster.language'),'zh');
    assert.equal(w.location.search,'?keep=1');assert.equal(w.location.hash,'#view');
    vm.runInContext("I18n.setLanguage('en')",dom.getInternalVMContext());
    assert.equal(w.localStorage.getItem('photocluster.language'),'en');
    assert.equal(new URL(w.location.href).searchParams.has('lang'),false);
  }finally{w.close();}
});
test('every explicit UI translation has English copy with identical placeholders',()=>{
  const context={window:{}};vm.runInNewContext(fs.readFileSync(scripts[0],'utf8'),context);
  const dictionary=context.window.PhotoClusterEnglish,keys=new Set(),han=/[\u3400-\u9fff]/;
  function html(source){for(const part of source.split(/(<[^>]*>)/g)){
    if(part.startsWith('<')){for(const m of part.matchAll(/(?:title|aria-label|placeholder|alt)="([^"]*)"/g))if(han.test(m[1]))keys.add(m[1]);}
    else if(han.test(part))keys.add(part.trim());
  }}
  function walk(n){if(!n||typeof n!=='object')return;
    if(n.type==='CallExpression'&&n.callee.object?.name==='I18n'&&['t','html'].includes(n.callee.property?.name)&&n.arguments[0]?.type==='Literal'){
      const value=n.arguments[0].value;if(n.callee.property.name==='html')html(value);else keys.add(value);
    }
    if(n.type==='TaggedTemplateExpression'&&n.tag.object?.name==='I18n'){
      const key=n.quasi.quasis.map((q,i)=>q.value.cooked+(i<n.quasi.expressions.length?`{${i}}`:'')).join('');
      if(n.tag.property.name==='html')html(key);else if(n.tag.property.name==='msg')keys.add(key);
    }
    for(const value of Object.values(n)){if(Array.isArray(value))value.forEach(walk);else if(value&&typeof value==='object')walk(value);}
  }
  for(const file of fs.readdirSync('web').filter(x=>x.endsWith('.js')))walk(acorn.parse(fs.readFileSync('web/'+file,'utf8'),{ecmaVersion:'latest'}));
  const dom=new JSDOM(fs.readFileSync('web/index.html','utf8'));dom.window.document.querySelectorAll('script').forEach(el=>el.remove());html(dom.window.document.documentElement.outerHTML);dom.window.close();
  for(const key of keys)assert.ok(dictionary[key],`Missing translation: ${key}`);
  const placeholders=s=>[...s.matchAll(/\{\d+\}/g)].map(m=>m[0]).sort();
  for(const [source,target] of Object.entries(dictionary))assert.deepEqual(placeholders(source),placeholders(target),source);
});

async function app(language='en',saved=null){
  const dom=new JSDOM(fs.readFileSync('web/index.html','utf8'),{url:'http://localhost:8765',runScripts:'outside-only'}),w=dom.window;
  w.eval=code=>vm.runInContext(code,dom.getInternalVMContext());
  w.localStorage.setItem('photocluster.language',language);
  if(saved)w.sessionStorage.setItem('photocluster.languageView',JSON.stringify(saved));
  w.matchMedia=()=>({matches:true,addEventListener(){}});w.ResizeObserver=class{observe(){}};
  w.scrollTo=()=>{};w.HTMLElement.prototype.scrollIntoView=()=>{};
  w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};w.HTMLDialogElement.prototype.close=function(){this.open=false;this.dispatchEvent(new w.Event('close'));};
  w.HTMLMediaElement.prototype.pause=w.HTMLMediaElement.prototype.load=()=>{};
  const photos=[0,1].map(i=>({key:String(i),path:`/storage/emulated/0/相似媒体组/${i?'确认移动':'文件完全相同'}.jpg`,album:'/storage/emulated/0/相似媒体组',size:100,modified:1700000000,width:640,height:480,sharpness:5,score:i?.9:1,reason:'视觉相似，需人工确认'}));
  const group={id:1,kind:'variants',photos,total:2,page:1,reference_key:'0'};
  const state={running:true,phase:'variant_match',message:'验证同源画面与几何变换',done:5,total:10,errors:0,started_at:1};
  const requests=[];
  w.fetch=async(path,options)=>{requests.push({path,options});let data;const url=new URL(path,w.location);
    if(url.pathname==='/api/runtime')data={application:'PhotoCluster',instance:'test',managed:true,stopping:false,token:'test-only'};
    else if(url.pathname==='/api/devices')data=[{serial:'test-device',state:'device',description:'model:Test'}];
    else if(url.pathname==='/api/albums')data={serial:'test-device',count:2,albums:[{path:photos[0].album,name:'相似媒体组',count:2,size:200,cached:2}]};
    else if(url.pathname==='/api/status')data=state;
    else if(url.pathname==='/api/groups')data={groups:[group],total:1,summary:{mode:'variants',groups:1,grouped_photos:2,scanned:2,finished_at:1,scope:'all'},ungrouped:{available:true,count:0,covers:[]}};
    else if(url.pathname==='/api/groups/1')data=group;
    else if(url.pathname==='/api/errors')data=[];
    else if(url.pathname==='/api/subject-model')data={installed:true};
    else if(url.pathname==='/api/cache')data={location:'test-cache',categories:Object.fromEntries(['results','analysis','library','models'].map(k=>[k,{bytes:1024,files:1}]))};
    else if(url.pathname==='/api/cache/preview')data={token:'cache-test-only',scope:JSON.parse(options.body).scope,bytes:1024,files:1};
    else if(url.pathname==='/api/cache/clear')data={failed:0,usage:{location:'test-cache',categories:Object.fromEntries(['results','analysis','library','models'].map(k=>[k,{bytes:0,files:0}]))}};
    else if(url.pathname==='/api/scan')data=state;
    else if(url.pathname==='/api/hardware')data={cpu_physical:4,cpu_logical:8,memory_gb:16,workers:4,accelerator:{backend:'cpu'},sift:'CPU 并行'};
    else if(url.pathname==='/api/operations/preview')data={token:'test-only',items:photos.map(p=>({source:p.path}))};
    else throw Error('Unexpected request: '+path);
    return {ok:true,json:async()=>data};
  };
  for(const script of w.document.querySelectorAll('script'))w.eval(script.src?fs.readFileSync('web/'+new URL(script.src).pathname.slice(1),'utf8'):script.textContent);
  await new Promise(setImmediate);return {dom,w,photos,state,requests};
}
test('English page renders settings, progress, groups and permanent deletion confirmation without changing paths',async()=>{
  const h=await app();try{
    const d=h.w.document;
    assert.equal(d.documentElement.lang,'en');assert.equal(d.getElementById('language').value,'en');
    assert.match(d.getElementById('statusText').textContent,/Verifying shared scenes/);
    assert.match(d.getElementById('scanHelp').textContent,/Same-source variants/);
    assert.match(d.getElementById('hardwareInfo').textContent,/Parallel CPU/);
    assert.match(d.getElementById('resultStatus').textContent,/previous completed scan/);
    assert.equal(d.querySelector('.album .name').textContent,'相似媒体组');
    await h.w.eval('openGroup(1)');assert.match(d.getElementById('groupPhotos').textContent,/文件完全相同.jpg/);
    assert.match(d.getElementById('groupPhotos').textContent,/Visually similar; manual review required/);
    h.state.running=false;h.state.phase='done';await h.w.eval('poll()');
    h.w.eval("picked=new Set(['0','1'])");await h.w.eval("prepareOperation('delete')");
    assert.match(d.getElementById('operationExplanation').textContent,/permanently deleted/);
    assert.equal(d.getElementById('confirmOperation').textContent,'Confirm permanent deletion');
    assert.equal(d.getElementById('operationPaths').textContent,h.photos.map(p=>p.path).join('\n\n'));
    assert.ok(h.requests.every(r=>!r.path.includes('/execute')&&!r.path.includes('/scan')));
    // Apart from language labels and user-owned paths, static English UI has no Chinese.
    for(const el of d.querySelectorAll('.album,.filename,.real-path,#operationPaths,#language,.language-control,#filterAlbum,#moveTarget'))el.remove();
    d.querySelectorAll('script').forEach(el=>el.remove());
    assert.doesNotMatch(d.body.textContent,/[\u3400-\u9fff]/);
  }finally{await new Promise(setImmediate);h.dom.window.close();}
});

test('cache UI previews scope in both languages and clears only after confirmation',async()=>{
  for(const lang of ['zh','en']){
    const h=await app(lang);try{
      const d=h.w.document;h.state.running=false;h.state.phase='idle';await h.w.eval('poll()');
      await d.getElementById('cacheRefresh').onclick();assert.match(d.getElementById('cacheUsage').textContent,/KB/);
      d.getElementById('cacheScope').value='analysis';await d.getElementById('cachePreview').onclick();
      assert.equal(d.getElementById('cacheDialog').open,true);
      assert.match(d.getElementById('cacheExplanation').textContent,lang==='zh'?/重新读取媒体/:/reread media/);
      assert.ok(!h.requests.some(r=>r.path.endsWith('/clear')));
      d.getElementById('cacheCancel').onclick();await d.getElementById('cacheConfirm').onclick();
      assert.ok(!h.requests.some(r=>r.path.endsWith('/clear')));
      await d.getElementById('cachePreview').onclick();await d.getElementById('cacheConfirm').onclick();
      const clear=h.requests.filter(r=>r.path.endsWith('/clear'));assert.equal(clear.length,1);
      assert.deepEqual(JSON.parse(clear[0].options.body),{token:'cache-test-only'});
      assert.ok(!h.requests.some(r=>r.path.includes('operations/')));
    }finally{await new Promise(setImmediate);h.dom.window.close();}
  }
});

test('automatic subject mode sends its own threshold without examples and preserves language settings',async()=>{
  const h=await app('en',{mode:'subject',subjectThreshold:'0.65'});try{
    const d=h.w.document;h.state.running=false;h.state.phase='idle';await h.w.eval('poll()');
    assert.equal(d.getElementById('mode').value,'subject');assert.equal(d.getElementById('subjectThresholdLabel').hidden,false);
    assert.equal(d.getElementById('contentThresholdLabel').hidden,true);
    assert.match(d.getElementById('scanHelp').textContent,/DINOv2/);
    await d.getElementById('scan').onclick();
    const request=h.requests.find(r=>r.path==='/api/scan'),body=JSON.parse(request.options.body);
    assert.equal(body.mode,'subject');assert.equal(body.threshold,.65);assert.equal(body.examples,undefined);
  }finally{await new Promise(setImmediate);h.dom.window.close();}
});
test('language reload restores scope, mode, filters and album selections without starting a scan',async()=>{
  const h=await app('zh',{mode:'content',scope:'album',scanTarget:'selected',contentThreshold:'0.77',groupSort:'oldest',search:'我的照片',selection:{serial:'test-device',paths:[]}});
  try{const d=h.w.document;assert.equal(d.documentElement.lang,'zh-CN');assert.equal(d.getElementById('scope').value,'album');
    assert.match(d.getElementById('scanHelp').textContent,/相近内容与画风/);
    assert.equal(d.querySelector('.album input').checked,false);assert.equal(d.getElementById('search').value,'我的照片');
    assert.equal(h.w.sessionStorage.getItem('photocluster.languageView'),null);
    assert.ok(h.requests.every(r=>!r.options?.method));
  }finally{await new Promise(setImmediate);h.dom.window.close();}
});
