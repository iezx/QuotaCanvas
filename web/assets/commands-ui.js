(() => {
  const T=window.QCi18n.t,$=id=>document.getElementById(id),prompt=$('prompt');
  const toolbar=document.createElement('div');toolbar.className='row command-toolbar';
  toolbar.innerHTML=`<button class="btn" id="command-menu-toggle" type="button" aria-expanded="false" aria-controls="command-panel">／ ${T('命令','Commands')}</button><span class="sub">${T('输入 / 查看当前 Agent 的可用命令；选中后点击发送执行。','Type / to see commands for the selected Agent; choose one, then send.')}</span>`;
  const panel=document.createElement('div');panel.id='command-panel';panel.className='command-panel';panel.hidden=true;
  const result=document.createElement('div');result.id='command-result';result.className='command-result';result.hidden=true;result.setAttribute('role','status');
  prompt.closest('.row').before(toolbar,panel);prompt.closest('.row').after(result);
  let commands=[],source='',request=0;
  const cache=new Map(),activeSource=()=>convs[$('conv').value]?.source||($('src').value==='all'?'codex':$('src').value);
  const syntax=value=>window.QCi18n.english?value.replace('<目标>','<objective>').replace('<名称>','<name>').replace('<任务>','<task>'):value;
  function toggle(open){panel.hidden=!open;$('command-menu-toggle').setAttribute('aria-expanded',String(open));if(open)render()}
  function render(){const query=prompt.value.trim(),filter=/^\/[^\s]*$/.test(query)?query:'';const values=commands.filter(entry=>!filter||entry.command.startsWith(filter));
    panel.replaceChildren(...values.map(entry=>{const button=document.createElement('button');button.type='button';button.className='command-choice';button.disabled=entry.enabled===false;const code=document.createElement('code');code.textContent=syntax(entry.command);const description=document.createElement('span');description.textContent=entry[window.QCi18n.english?'description_en':'description_zh'];button.append(code,description);button.onclick=()=>{prompt.value=entry.insert;toggle(false);prompt.focus();prompt.setSelectionRange(prompt.value.length,prompt.value.length)};return button}));
    if(!values.length)panel.textContent=T('没有匹配命令。输入 /help 查看列表。','No matching commands. Use /help to show the list.');
  }
  async function load(){const selected=activeSource(),token=++request;source=selected;
    try{if(!cache.has(selected))cache.set(selected,SiteAuth.fetch('/api/commands?source='+encodeURIComponent(selected)).then(async response=>{const data=await response.json();if(!response.ok)throw Error(data.error||'HTTP '+response.status);return data.commands}).catch(error=>{cache.delete(selected);throw error}));const value=await cache.get(selected);if(token!==request)return;commands=value;if(!panel.hidden)render()}
    catch(error){if(token===request){commands=[];panel.textContent=T('读取命令失败：','Could not load commands: ')+error.message}}
  }
  function output(label,value){result.hidden=false;const heading=document.createElement('strong');heading.textContent=label;const pre=document.createElement('pre'),code=document.createElement('code');code.textContent=typeof value==='string'?value:JSON.stringify(value,null,2);pre.append(code);result.replaceChildren(heading,pre)}
  async function selectThread(thread){if(!thread?.id)return;const selected=convs[$('conv').value];const conversation={id:thread.id,source:'codex',title:thread.name||thread.preview||T('分支对话','Forked conversation'),cwd:thread.cwd||selected?.cwd,model:selected?.model||'',updated_at:thread.updatedAt||Math.floor(Date.now()/1000)};
    $('src').value='codex';await loadConvs();let index=convs.findIndex(c=>c.id===conversation.id);if(index<0){convs.unshift(conversation);index=0;const option=document.createElement('option');option.value='0';option.textContent=conversation.title;for(const old of $('conv').options)old.value=String(Number(old.value)+1);$('conv').prepend(option)}$('conv').value=String(index);await selectConv();load();
  }
  async function handleClient(text){const parts=text.trim().split(/\s+/),name=parts.shift(),argument=parts.join(' ');
    if(name==='/help'){prompt.value='';await load();toggle(true);return true}
    if(name==='/new'||name==='/clear'){$('new-conversation').click();if(argument)$('new-prompt').value=argument;return true}
    if(name==='/model'){
      if(argument){if(!/^[A-Za-z0-9][A-Za-z0-9._:/-]{0,119}$/.test(argument))throw Error(T('模型 ID 无效','Invalid model ID'));
        if(Array.from($('model').options).some(option=>option.value===argument))$('model').value=argument;else{$('model').value='__custom__';$('cmodel').value=argument}$('model').dispatchEvent(new Event('change'));output('/model',T('后续发送将使用：','Subsequent messages will use: ')+argument)}
      else{$('model').focus();try{$('model').showPicker()}catch{}output('/model',T('请在模型选择框中选择。','Choose a model in the model picker.'))}return true;
    }
    if(name==='/effort'){
      if(argument){const option=Array.from($('effort').options).find(option=>option.value===argument.toLowerCase()&&!option.hidden);if(!option)throw Error(T('当前模型不支持该思考强度。','This effort is not supported by the selected model.'));$('effort').value=option.value;output('/effort',T('后续发送的思考强度：','Reasoning effort for subsequent messages: ')+option.value)}
      else{$('effort').focus();try{$('effort').showPicker()}catch{}output('/effort',T('请在思考强度选择框中选择。','Choose an effort in the reasoning picker.'))}return true;
    }
    return false;
  }
  $('command-menu-toggle').onclick=()=>toggle(panel.hidden);
  prompt.addEventListener('input',()=>{if(/^\/[^\n]*$/.test(prompt.value.trim()))toggle(true);else toggle(false)});
  prompt.addEventListener('keydown',event=>{if(event.key==='Escape')toggle(false);if(event.key==='ArrowDown'&&!panel.hidden){event.preventDefault();panel.querySelector('button')?.focus()}});
  $('conv').addEventListener('change',load);$('src').addEventListener('change',load);new MutationObserver(()=>{if(source!==activeSource())load()}).observe($('model'),{childList:true});
  window.QCCommands={handleClient,output,async completed(command,value){output(T('命令结果：','Command result: ')+command,value);if(command.trim()==='/fork'&&value.thread)await selectThread(value.thread);if(command.trim().startsWith('/rename ')){const selected=convs[$('conv').value];if(selected){selected.title=command.trim().slice(8).trim();$('conv').selectedOptions[0].textContent='['+selected.source+'] '+selected.title;$('convtitle').textContent=selected.title}}},load};
  load();
})();
