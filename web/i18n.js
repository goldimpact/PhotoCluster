/* Explicit source translation: substitute values only AFTER translating copy.
 * No observers or replacements run over filenames, paths or server payloads. */
const I18n=(()=>{
  let language='zh';
  try{language=localStorage.getItem('photocluster.language')==='en'?'en':'zh';}catch{}
  const dictionary=()=>window.PhotoClusterEnglish||{};
  const t=key=>language==='en'?(dictionary()[key]??key):key;
  const substitute=(pattern,values)=>pattern.replace(/\{(\d+)\}/g,(token,index)=>index<values.length?String(values[index]):token);
  const pattern=strings=>strings.map((s,i)=>s+(i<strings.length-1?`{${i}}`:'')).join('');
  function textPart(source){const trimmed=source.trim();return trimmed?source.replace(trimmed,t(trimmed)):source;}
  function markup(source){
    return source.split(/(<[^>]*>)/g).map(part=>part.startsWith('<')
      ?part.replace(/((?:title|aria-label|placeholder|alt)=")([^"]*)(")/g,(_,a,b,c)=>a+t(b)+c)
      :textPart(part)).join('');
  }
  function html(strings,...values){return typeof strings==='string'?markup(strings):substitute(markup(pattern(strings)),values);}
  function msg(strings,...values){return substitute(t(pattern(strings)),values);}
  const apiFields=new Set(['message','detail','reason','warning','warnings','error','sift']);
  const escapeRE=s=>s.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
  const apiPatterns=Object.entries(window.PhotoClusterApiEnglish||{}).map(([source,target])=>({
    source,target,re:source.includes('{0}')?new RegExp('^'+source.split(/\{\d+\}/).map(escapeRE).join('([\\s\\S]*?)')+'$'):null
  }));
  function serverText(value){
    if(language!=='en'||typeof value!=='string')return value;
    if(Object.hasOwn(dictionary(),value))return t(value);
    for(const {source,target,re} of apiPatterns){if(value===source)return target;if(re){const match=value.match(re);if(match)return substitute(target,match.slice(1));}}
    return value; // External diagnostics are retained verbatim.
  }
  function api(value,field=''){
    if(typeof value==='string')return apiFields.has(field)?serverText(value):value;
    if(Array.isArray(value))return value.map(item=>api(item,field));
    if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).map(([k,v])=>[k,api(v,k)]));
    return value;
  }
  function localizeDocument(root=document){
    // Called once, synchronously, before application data is loaded.
    const walk=node=>{
      if(node.nodeType===3){node.nodeValue=textPart(node.nodeValue);return;}
      if(node.nodeType===1){
        if(['SCRIPT','STYLE'].includes(node.tagName))return;
        for(const name of ['title','aria-label','placeholder','alt'])if(node.hasAttribute(name))node.setAttribute(name,t(node.getAttribute(name)));
      }
      for(const child of node.childNodes||[])walk(child);
    };
    walk(root);root.documentElement?.setAttribute('lang',language==='en'?'en':'zh-CN');
  }
  return {t,msg,html,api,serverText,localizeDocument,get language(){return language;},get locale(){return language==='en'?'en-US':'zh-CN';},
    setLanguage(value){if(!['zh','en'].includes(value))return;language=value;try{localStorage.setItem('photocluster.language',value);}catch{}},
    format:(key,...values)=>substitute(t(key),values)};
})();
