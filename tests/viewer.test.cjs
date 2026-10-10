// Headless state-machine tests, not a replacement for real browser rendering.
const test=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
function harness(){
  const elements=new Map(),requests=[],revoked=[];let count=0;
  function $(id){
    if(!elements.has(id))elements.set(id,{id,style:{},events:{},open:false,naturalWidth:1000,naturalHeight:800,clientWidth:500,clientHeight:400,scrollLeft:0,scrollTop:0,
      addEventListener(name,fn){this.events[name]=fn;},removeAttribute(name){delete this[name];},scrollTo(){},setPointerCapture(){},
      pause(){},load(){},getBoundingClientRect(){return {left:0,top:0};},showModal(){this.open=true;},close(){this.open=false;this.events.close?.();}});
    return elements.get(id);
  }
  const context={$ ,bytes:n=>''+n,dateText:String,photoTime:p=>p.modified,AbortController,
    URL:{createObjectURL:()=>`blob:${++count}`,revokeObjectURL:u=>revoked.push(u)},
    window:{addEventListener(){}},fetch:(url,options)=>new Promise(resolve=>requests.push({url,options,resolve}))};
  context.MediaView={load:async(p,signal)=>{const r=await context.fetch('/api/original/'+p.key,{signal});if(!r.ok)throw Error((await r.json()).detail);await r.blob();if(signal.aborted)throw {name:'AbortError'};const url=context.URL.createObjectURL();return {url,release(){context.URL.revokeObjectURL(url);}};}};
  vm.runInNewContext(fs.readFileSync("web/i18n.js","utf8")+"\n"+fs.readFileSync('web/viewer.js','utf8'),context);
  return {context,$,requests,revoked};
}
const photos=[{key:'a',path:'/a',modified:1},{key:'b',path:'/b',modified:2},{key:'c',path:'/c',modified:3}];
const respond=r=>r.resolve({ok:true,headers:{get:()=>null},blob:async()=>({})});
const tick=()=>new Promise(setImmediate);
test('viewer wraps both ends, keyboard navigation, abort and close cleanup',async()=>{
  const h=harness();h.context.window.openPhotoViewer(photos,'c');
  assert.equal(h.requests[0].url,'/api/original/c');respond(h.requests[0]);await tick();
  h.$('previewImage').onload();assert.equal(h.$('previewImage').src,'blob:1');
  h.$('previewNext').onclick();assert.equal(h.requests[1].url,'/api/original/a');
  assert.deepEqual(h.revoked,['blob:1']);assert.equal(h.requests[0].options.signal.aborted,true);
  h.$('preview').events.keydown({key:'ArrowLeft',preventDefault(){}});
  assert.equal(h.requests[2].url,'/api/original/c');
  respond(h.requests[1]);await tick();assert.equal(h.$('previewImage').src,'/api/thumb/c');
  respond(h.requests[2]);await tick();assert.equal(h.$('previewImage').src,'blob:2');
  h.$('closePreview').onclick();assert.deepEqual(h.revoked,['blob:1','blob:2']);
  assert.equal(h.$('previewImage').src,undefined);
});
test('response arriving after close cannot recreate original image',async()=>{
  const h=harness();h.context.window.openPhotoViewer(photos,'a');h.$('preview').close();
  respond(h.requests[0]);await tick();assert.equal(h.$('previewImage').src,undefined);
});
test('single photo wraps to itself and read failure retains thumbnail',async()=>{
  const h=harness();h.context.window.openPhotoViewer([photos[0]],'a');
  h.requests[0].resolve({ok:false,json:async()=>({detail:'phone disconnected'})});
  await tick();assert.equal(h.$('previewImage').src,'/api/thumb/a');
  assert.match(h.$('previewStatus').textContent,/phone disconnected/);
  h.$('previewNext').onclick();assert.equal(h.requests[1].url,'/api/original/a');
});
test('zoom preserves the image coordinate under an off-center mouse',()=>{
  const h=harness();const g=h.context.window.zoomGeometry({width:1000,height:800,viewWidth:500,viewHeight:400,oldScale:1,newScale:2,scrollX:200,scrollY:150,x:100,y:80});
  assert.equal((g.scrollX+100)/2,300);assert.equal((g.scrollY+80)/2,230);
  const fitted=h.context.window.zoomGeometry({width:1000,height:800,viewWidth:500,viewHeight:400,oldScale:.5,newScale:1,scrollX:0,scrollY:0,x:375,y:250});
  assert.equal(fitted.scrollX+375,750);assert.equal(fitted.scrollY+250,500);
});
test('zooming out clamps scroll without negative offsets',()=>{
  const h=harness();const g=h.context.window.zoomGeometry({width:1000,height:800,viewWidth:500,viewHeight:400,oldScale:1,newScale:.25,scrollX:200,scrollY:100,x:450,y:350});
  assert.equal(g.scrollX,0);assert.equal(g.scrollY,0);assert.equal(g.left,125);
});
