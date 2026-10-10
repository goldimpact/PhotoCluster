/* Language changes reload the view, never the background service or scan. */
(()=>{
  const settings=['scanTarget','scope','mode','scanStrategy','contentThreshold','filterKind','groupSort','photoSort','search'];
  const key='photocluster.languageView';
  window.LanguageSettings={selection:null,filterAlbum:''};
  try{
    const saved=JSON.parse(sessionStorage.getItem(key)||'null');sessionStorage.removeItem(key);
    if(saved){for(const id of settings)if(typeof saved[id]==='string')document.getElementById(id).value=saved[id];
      window.LanguageSettings.selection=saved.selection;window.LanguageSettings.filterAlbum=saved.filterAlbum||'';}
  }catch{}
  const label=document.createElement('label');label.className='language-control';
  label.innerHTML='<span>语言 / Language</span><select id="language" aria-label="语言 / Language"><option value="zh">中文</option><option value="en">English</option></select>';
  document.querySelector('header').append(label);
  const select=document.getElementById('language');select.value=I18n.language;
  select.onchange=()=>{
    const saved=Object.fromEntries(settings.map(id=>[id,document.getElementById(id).value]));
    saved.selection={serial:albumSerial,paths:[...selected]};saved.filterAlbum=document.getElementById('filterAlbum').value;
    try{sessionStorage.setItem(key,JSON.stringify(saved));}catch{}
    // Closing these first releases originals and video leases immediately.
    for(const id of ['preview','compareDialog','operationDialog']){const dialog=document.getElementById(id);if(dialog?.open)dialog.close();}
    I18n.setLanguage(select.value);location.reload();
  };
})();
