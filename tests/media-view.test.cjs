const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync('web/media-view.js','utf8').split('\n(()=>{')[0];
function harness(){
  const requests=[],intervals=new Set();
  const context={window:{},DOMException,URL:{},setInterval(fn){intervals.add(fn);return fn;},clearInterval(fn){intervals.delete(fn);},fetch:(url,options)=>new Promise(resolve=>requests.push({url,options,resolve}))};
  vm.runInNewContext(fs.readFileSync("web/i18n.js","utf8")+"\n"+source,context);return {context,requests,intervals,load:context.window.MediaView.load};
}
test('video token arriving after close is released',async()=>{
  const h=harness(),controller=new AbortController();const promise=h.load({key:'v',media_type:'video'},controller.signal);controller.abort();
  h.requests[0].resolve({ok:true,json:async()=>({token:'t',url:'/api/video-stream/t'})});
  await assert.rejects(promise,e=>e.name==='AbortError');assert.equal(h.requests[1].url,'/api/video-release/t');assert.equal(h.intervals.size,0);
});
test('active video lease has keepalive and releases on close',async()=>{
  const h=harness();const promise=h.load({key:'v',media_type:'video'},new AbortController().signal);
  h.requests[0].resolve({ok:true,json:async()=>({token:'t',url:'/api/video-stream/t'})});const r=await promise;
  assert.equal(r.video,true);assert.equal(h.intervals.size,1);r.release();assert.equal(h.intervals.size,0);assert.equal(h.requests[1].url,'/api/video-release/t');
});
