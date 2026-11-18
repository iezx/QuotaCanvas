(() => {
  const $=id=>document.getElementById(id),T=window.QCi18n.t;
  window.QCModelCatalog={codex:[],agy:[],cc:[]};
  function describe(){const source=convs[$('conv').value]?.source||($('src').value==='all'?'codex':$('src').value);$('command-help').textContent=T('点击／命令，或在输入框输入 / 选择当前 Agent 支持的命令。','Click / Commands, or type / in the message box to choose a command for the selected Agent.');
    const catalog=window.QCModelCatalog[source]||[];
    const model=($('model').value?catalog.find(m=>(m.model||m.id)===$('model').value):catalog.find(m=>m.isDefault));
    const allowed=(model?.supportedReasoningEfforts||[]).map(x=>x.reasoningEffort);
    for(const option of $('effort').options)option.hidden=!!option.value&&((source==='codex'&&allowed.length>0&&!allowed.includes(option.value))||(source==='agy'&&!['low','medium','high','xhigh','max'].includes(option.value)));
    if($('effort').selectedOptions[0]?.hidden)$('effort').value='';
    $('model-description').textContent=model?`${model.description||''}${allowed.length?' · '+T('可选强度：','Available efforts: ')+allowed.join(', '):''}`:'';
  }
  $('model').addEventListener('change',describe);$('conv').addEventListener('change',()=>setTimeout(describe,0));$('src').addEventListener('change',()=>setTimeout(describe,0));new MutationObserver(describe).observe($('model'),{childList:true});describe();
  async function loadCatalog(source,url){
    try{const response=await SiteAuth.fetch(url);if(!response.ok)return;const data=await response.json();const items=data.data||[];
      if(!items.length)return;window.QCModelCatalog[source]=items;const ids=items.map(m=>m.model||m.id).filter(Boolean);
      if(ids.length){const fallback=MODELS_BY_SRC[source]||[];MODELS_BY_SRC[source]=[...new Set([...ids,...fallback])]}
      document.dispatchEvent(new Event('qc-model-catalog'));syncModelOpts(convs[$('conv').value]);describe();
    }catch{}
  }
  window.QCModelCatalogReady=Promise.all([loadCatalog('codex','/api/models'),loadCatalog('agy','/api/models?source=agy')]);
})();
