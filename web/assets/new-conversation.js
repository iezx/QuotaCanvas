(() => {
  const T=window.QCi18n.t,$=id=>document.getElementById(id);
  const dialog=document.createElement('dialog');dialog.className='site-dialog';dialog.id='new-conversation-dialog';
  dialog.innerHTML=`<form id="new-conversation-form"><h2>${T('新建本机对话','New local conversation')}</h2>
    <label for="new-source">${T('来源','Source')}</label><select id="new-source"><option value="codex">Codex</option><option value="agy">Antigravity</option><option value="cc">Claude Code</option></select>
    <label for="new-cwd">${T('项目目录（本机绝对路径）','Project directory (absolute local path)')}</label><input id="new-cwd" required autocomplete="off" placeholder="/path/to/project">
    <label for="new-model">${T('模型（留空使用默认）','Model (blank for default)')}</label><input id="new-model" list="new-model-list"><datalist id="new-model-list"></datalist>
    <label for="new-effort">${T('思考强度','Reasoning effort')}</label><select id="new-effort"><option value="">${T('默认','Default')}</option>${['low','medium','high','xhigh','max','ultra'].map(x=>`<option value="${x}">${x}</option>`).join('')}</select>
    <label for="new-prompt">${T('第一条消息','First message')}</label><textarea id="new-prompt" required rows="4" maxlength="40000" style="width:100%"></textarea>
    <p id="new-conversation-error" class="error" role="status"></p><div class="dialog-actions"><button id="new-conversation-cancel" type="button">${T('取消','Cancel')}</button><button class="primary" id="new-conversation-submit" type="submit">${T('创建并发送','Create and send')}</button></div></form>`;
  document.body.append(dialog);
  function syncEfforts(){const source=$('new-source').value,catalog=window.QCModelCatalog?.[source]||[],id=$('new-model').value.trim();const model=id?catalog.find(m=>(m.model||m.id)===id):catalog.find(m=>m.isDefault);
    const allowed=(model?.supportedReasoningEfforts||[]).map(x=>x.reasoningEffort);
    for(const option of $('new-effort').options)option.hidden=!!option.value&&((allowed.length&&!allowed.includes(option.value))||(source==='agy'&&!['low','medium','high','xhigh','max'].includes(option.value)));
    if($('new-effort').selectedOptions[0]?.hidden)$('new-effort').value='';
  }
  $('new-model').oninput=syncEfforts;$('new-model').onchange=syncEfforts;document.addEventListener('qc-model-catalog',syncEfforts);
  function modelChoices(){const list=$('new-model-list');list.replaceChildren(...(MODELS_BY_SRC[$('new-source').value]||[]).map(id=>{const option=document.createElement('option');option.value=id;return option}));syncEfforts()}
  $('new-conversation').onclick=()=>{const current=convs[$('conv').value];$('new-source').value=current?.source||($('src').value==='all'?'codex':$('src').value);$('new-cwd').value=current?.cwd||'';$('new-model').value=getSelModel();$('new-effort').value=$('effort').value;$('new-conversation-error').textContent='';modelChoices();dialog.showModal();$('new-cwd').focus()};
  $('new-source').onchange=()=>{$('new-model').value='';modelChoices()};
  $('new-conversation-cancel').onclick=()=>dialog.close();
  $('new-conversation-form').onsubmit=async event=>{event.preventDefault();$('new-conversation-submit').disabled=true;
    try{const chosenEffort=$('new-effort').value;if($('new-source').value==='codex')await window.QCModelCatalogReady;syncEfforts();if(chosenEffort&&$('new-effort').value!==chosenEffort)throw new Error(T('该模型不支持所选思考强度，请重新选择。','This model does not support that effort. Please choose again.'));const response=await SiteAuth.fetch('/api/conversations',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({source:$('new-source').value,cwd:$('new-cwd').value.trim(),model:$('new-model').value.trim(),effort:$('new-effort').value,prompt:$('new-prompt').value})});
      const result=await response.json();if(!response.ok)throw new Error(result.error||'HTTP '+response.status);
      dialog.close();$('new-prompt').value='';$('src').value=$('new-source').value;await loadConvs();
      if(result.conversation){let index=convs.findIndex(c=>c.id===result.conversation.id);if(index<0){convs.unshift(result.conversation);index=0;const option=document.createElement('option');option.value='0';option.textContent=result.conversation.title;for(const item of $('conv').options)item.value=String(Number(item.value)+1);$('conv').prepend(option)}$('conv').value=String(index);await selectConv();}
      else $('msgstatus').textContent=T('新对话已启动，首条回复生成后可刷新列表查看。','Conversation started. Refresh the list after the first reply arrives.');
    }catch(error){$('new-conversation-error').textContent=error.message}finally{$('new-conversation-submit').disabled=false}
  };
})();
