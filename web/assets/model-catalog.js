(() => {
  const $=id=>document.getElementById(id),T=window.QCi18n.t;
  let models=[];window.QCModelCatalog={codex:models};
  function describe(){const source=convs[$('conv').value]?.source||'codex';$('command-help').textContent=T('点击／命令，或在输入框输入 / 选择当前 Agent 支持的命令。','Click / Commands, or type / in the message box to choose a command for the selected Agent.');const model=($('model').value?models.find(m=>(m.model||m.id)===$('model').value):models.find(m=>m.isDefault));const allowed=(model?.supportedReasoningEfforts||[]).map(x=>x.reasoningEffort);
    for(const option of $('effort').options)option.hidden=!!option.value&&((source==='codex'&&allowed.length>0&&!allowed.includes(option.value))||(source==='agy'&&!['low','medium','high','xhigh','max'].includes(option.value)));
    if($('effort').selectedOptions[0]?.hidden)$('effort').value='';
    $('model-description').textContent=model?`${model.description||''}${allowed.length?' · '+T('可选强度：','Available efforts: ')+allowed.join(', '):''}`:'';
  }
  $('model').addEventListener('change',describe);$('conv').addEventListener('change',()=>setTimeout(describe,0));$('src').addEventListener('change',()=>setTimeout(describe,0));new MutationObserver(describe).observe($('model'),{childList:true});describe();
  window.QCModelCatalogReady=(async()=>{try{const response=await SiteAuth.fetch('/api/models');if(!response.ok)return;const data=await response.json();models=data.data||[];window.QCModelCatalog.codex=models;document.dispatchEvent(new Event('qc-model-catalog'));const ids=models.map(m=>m.model||m.id).filter(Boolean);if(ids.length)MODELS_BY_SRC.codex=ids;syncModelOpts(convs[$('conv').value]);describe()}catch{}})();
})();
