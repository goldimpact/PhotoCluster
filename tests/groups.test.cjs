// DOM state tests; these do not assert visual browser layout.
const test=require('node:test'),assert=require('node:assert/strict');
const vm=require('node:vm'),fs=require('node:fs');
function harness(initialStatus={running:false,phase:'idle'}){
  const nodes=new Map(),scrolls=[],requests=[];
  const node=id=>{if(!nodes.has(id))nodes.set(id,{id,value:'',hidden:false,innerHTML:'',textContent:'',events:{},dataset:{},
    addEventListener(n,f){this.events[n]=f;},querySelectorAll(){return [];},querySelector(s){return node(id+s);},
    scrollIntoView(){scrolls.push(id);},get parentElement(){return node(id+'parent');}});return nodes.get(id);};
  for(const [id,value] of Object.entries({photoSort:'reference',filterKind:'all',groupSort:'count'}))node(id).value=value;
  const photos=Array.from({length:205},(_,i)=>({key:String(i),path:`/a/${i}.jpg`,album:'/a',modified:i,size:10,width:20,height:20,sharpness:10,score:0,reason:'unmatched'}));
  const state={status:initialStatus,groupTotal:0,resultMode:'variants'};
  const context={document:{getElementById:node},window:{scrollY:980,scrollTo:v=>scrolls.push(v.top),openPhotoViewer:(items,key)=>{context.viewer={items,key};}},
    setInterval(){},setTimeout,clearTimeout,console,fetch:async url=>{
      requests.push(url);const u=new URL(url,'http://local');let data;
      if(u.pathname==='/api/devices')data=[];
      else if(u.pathname==='/api/albums')data={serial:'s',count:205,albums:[]};
      else if(u.pathname==='/api/status')data=state.status;
      else if(u.pathname==='/api/errors')data=[];
      else if(u.pathname==='/api/groups')data={groups:[],total:state.groupTotal,summary:{groups:state.groupTotal,grouped_photos:0,scanned:205,ungrouped:205,mode:state.resultMode,finished_at:1},ungrouped:{count:205,covers:photos.slice(0,3),available:true}};
      else if(u.pathname==='/api/groups/0'){
        const page=Number(u.searchParams.get('page')||0),sort=u.searchParams.get('sort');
        const sorted=sort==='newest'?[...photos].reverse():photos;
        data={id:0,kind:'ungrouped',total:205,page,reference_key:null,photos:page?sorted.slice((page-1)*100,page*100):sorted};
      }else throw Error(url);
      return {ok:true,json:async()=>data};
    }};
  vm.createContext(context);vm.runInContext(fs.readFileSync("web/i18n.js","utf8"),context);vm.runInContext(fs.readFileSync('web/scan-options.js','utf8'),context);vm.runInContext(fs.readFileSync('web/app.js','utf8'),context);
  return {context,node,scrolls,requests,state,run:code=>vm.runInContext(code,context)};
}
const tick=()=>new Promise(setImmediate);
test('older subject policy clearly requests incremental reclassification',async()=>{
  const h=harness();await tick();
  h.run("resultSummary.recognition_outdated=true;renderResultStatus()");
  assert.match(h.node('resultStatus').textContent,/旧版主体判定结果/);
  assert.match(h.node('resultStatus').textContent,/增量更新即可/);
  h.run("scanState.running=true;renderResultStatus()");
  assert.match(h.node('resultStatus').textContent,/不是本轮实时分组/);
  assert.match(h.node('resultStatus').textContent,/旧版主体判定结果/);
});
test('unmatched folder pages, selects only the page, sorts globally and restores list scroll',async()=>{
  const h=harness();await tick();
  assert.match(h.node('ungroupedFolder').innerHTML,/205/);
  await h.run('openGroup(0)');
  assert.match(h.node('groupPhotos').innerHTML,/不代表绝对唯一/);
  assert.doesNotMatch(h.node('groupPhotos').innerHTML,/NaN/);
  h.node('pickAll').onclick();assert.equal(h.run('picked.size'),100);
  await h.run('detailNavigate(3)');assert.equal(h.run('picked.size'),0);
  h.node('pickAll').onclick();assert.equal(h.run('picked.size'),5);
  h.node('photoSort').value='newest';await h.node('photoSort').onchange();
  assert.equal(h.run('currentGroup.photos[0].key'),'204');
  assert.equal(h.run('detailPage'),1);
  h.node('groupPhotos').onclick({target:{closest:()=>({dataset:{previewKey:'204'}})}});await tick();
  assert.equal(h.context.viewer.items.length,205); // viewer still loops the whole folder
  h.node('backGroups').onclick();assert.equal(h.scrolls.at(-1),980);
  assert.equal(h.node('ungroupedFolder').hidden,false);
});

test('back control targets the results section, follows layout changes and respects reduced motion',()=>{
  const code=fs.readFileSync('web/enhancements.js','utf8');
  const fragment=code.slice(code.indexOf("  const top=byId('backTop')"),code.indexOf("  byId('syncInfo')"));
  const button={};const events={};let scroll,anchor=700,reduced=true,onResize;
  const context={byId:()=>button,window:{scrollY:0,addEventListener:(name,fn)=>events[name]=fn,matchMedia:()=>({matches:reduced}),scrollTo:v=>scroll=v},
    document:{querySelector:()=>({getBoundingClientRect:()=>({top:anchor-context.window.scrollY})})},
    ResizeObserver:class{constructor(fn){onResize=fn;}observe(){}}};
  vm.runInNewContext(fragment,context);assert.equal(button.hidden,true);
  context.window.scrollY=900;events.scroll();assert.equal(button.hidden,true);
  context.window.scrollY=1400;events.scroll();assert.equal(button.hidden,false);
  button.onclick();assert.equal(scroll.top,684);assert.equal(scroll.behavior,'instant');
  anchor=1100;onResize();assert.equal(button.hidden,true);
  context.window.scrollY=2000;events.resize();assert.equal(button.hidden,false);
  reduced=false;button.onclick();assert.equal(scroll.top,1084);assert.equal(scroll.behavior,'smooth');
  context.window.scrollY=1084;events.scroll();assert.equal(button.hidden,true);
});

test('running scan labels saved groups and stopped/error states never imply new results',async()=>{
  const h=harness();await tick();
  h.state.status={running:true,phase:'variant_match',started_at:2};await h.run('poll()');
  assert.match(h.node('resultStatus').textContent,/上次结果/);
  assert.match(h.node('resultStatus').textContent,/不是本轮实时分组/);
  assert.match(h.node('groupCount').parentElement.querySelector('span').textContent,/上次结果/);
  for(const phase of ['stopped','error']){
    h.state.status={running:false,phase,started_at:2};await h.run('poll()');
    assert.match(h.node('resultStatus').textContent,/没有生成新的完整分组/);
  }
  h.state.status={running:false,phase:'done',started_at:3};await h.run('poll()');
  assert.match(h.node('resultStatus').textContent,/最近一次已完成/);
  assert.equal(h.node('groupCount').parentElement.querySelector('span').textContent,'相似媒体组');
});

test('opening the app during a scan fetches and identifies previous results',async()=>{
  const h=harness({running:true,phase:'variant_match',started_at:2});await tick();
  assert.ok(h.requests.some(url=>url.startsWith('/api/groups?')));
  assert.match(h.node('resultStatus').textContent,/上次结果/);
  h.run('resultSummary=null;renderResultStatus()');
  assert.match(h.node('resultStatus').textContent,/尚无已完成的结果/);
});

test('classification completion returns page 27 to page 1 even when both modes have 54 pages',async()=>{
  const h=harness({running:false,phase:'done',started_at:1});await tick();
  h.state.groupTotal=1080;
  h.run('page=27');await h.run('loadGroups()');
  assert.match(h.node('pageInfo').textContent,/27 \/ 54/);
  h.state.status={running:true,phase:'variant_match',started_at:2};await h.run('poll()');
  assert.equal(h.run('page'),27); // These are still the previous scan's groups.
  h.state.resultMode='content';h.state.status={running:false,phase:'done',started_at:2};
  const before=h.requests.length;await h.run('poll()');
  const query=h.requests.slice(before).find(url=>url.startsWith('/api/groups?'));
  assert.equal(new URL(query,'http://local').searchParams.get('page'),'1');
  assert.match(h.node('pageInfo').textContent,/1 \/ 54/);
  assert.equal(h.node('pageInput').value,1);assert.equal(h.node('previous').disabled,true);
  h.run('page=27');await h.run('loadGroups()');await h.run('poll()');
  assert.equal(h.run('page'),27); // Ordinary polling must not keep sending users back.
});

test('fast cached completion between polls also resets group detail and selections',async()=>{
  const h=harness({running:false,phase:'done',started_at:1});await tick();
  h.state.groupTotal=1080;h.run('page=27');await h.run('loadGroups()');
  await h.run('openGroup(0)');await h.run('detailNavigate(3)');h.node('pickAll').onclick();
  assert.equal(h.run('picked.size'),5);
  h.state.status={running:false,phase:'done',started_at:2,reused_matches:true};await h.run('poll()');
  assert.equal(h.run('page'),1);assert.equal(h.run('currentGroup'),null);
  assert.equal(h.run('detailPage'),1);assert.equal(h.run('picked.size'),0);
  assert.equal(h.node('groupBrowser').hidden,true);assert.equal(h.node('pagination').hidden,false);
});

test('stopped or failed classification preserves the previous result page',async()=>{
  for(const phase of ['stopped','error']){
    const h=harness({running:false,phase:'done',started_at:1});await tick();
    h.state.groupTotal=1080;h.run('page=27');await h.run('loadGroups()');
    h.state.status={running:true,phase:'variant_match',started_at:2};await h.run('poll()');
    h.state.status={running:false,phase,started_at:2};await h.run('poll()');
    assert.equal(h.run('page'),27);assert.match(h.node('pageInfo').textContent,/27 \/ 54/);
  }
});
