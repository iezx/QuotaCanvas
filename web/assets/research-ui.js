(() => {
  const T=window.QCi18n.t;
  const dialog=document.createElement('dialog');dialog.className='site-dialog research-dialog';dialog.id='research-dialog';
  dialog.innerHTML=`<header class="research-head"><h2>${T('查价 Agent 对话','Price research conversation')}</h2><button id="research-close" type="button">${T('关闭','Close')}</button></header>
    <label for="research-history-select">${T('查价记录（最近 10 次）','Research history (last 10 runs)')}</label><select id="research-history-select"></select>
    <p id="research-meta" class="hint"></p><p id="research-progress" class="hint" role="status"></p><div id="research-messages" class="research-messages" role="region" aria-label="${T('查价对话记录','Research conversation messages')}"></div>`;
  document.body.append(dialog);
  const $=id=>document.getElementById(id),names={codex:'Codex',agy:'Antigravity',cc:'Claude Code'};
  const statuses={running:T('正在执行','Running'),completed:T('已完成','Completed'),failed:T('失败','Failed'),interrupted:T('已中断','Interrupted')};
  let selected='',revision=-1,requestId=0,timer,retryDelay=2000;
  const fmt=value=>new Date(value*1000).toLocaleString(window.QCi18n.english?'en-US':'zh-CN');
  async function load(id=selected){
    clearTimeout(timer);const request=++requestId;
    try{const response=await SiteAuth.fetch('/api/pricing/research'+(id?'?id='+encodeURIComponent(id):''));const data=await response.json();if(!response.ok)throw Object.assign(Error(data.error||'HTTP '+response.status),{status:response.status});retryDelay=2000;if(request!==requestId||!dialog.open)return;
      $('research-history-select').replaceChildren(...data.runs.map(run=>{const option=document.createElement('option');option.value=run.id;option.textContent=`${fmt(run.started_at)} · ${names[run.agent]||run.agent} · ${statuses[run.status]||run.status}`;return option}));
      const run=data.run;if(!run){selected='';$('research-meta').textContent=T('尚无记录。新执行一次查价后即可查看对话。','No records yet. Start a new research run to record its conversation.');$('research-messages').replaceChildren();$('research-progress').textContent='';return}
      $('research-history-select').value=run.id;
      if(selected!==run.id){selected=run.id;revision=-1}
      $('research-meta').textContent=`${names[run.agent]||run.agent} · ${run.model||T('Agent 默认模型','Agent default model')} · ${fmt(run.started_at)}`;
      $('research-progress').textContent=(statuses[run.status]||run.status)+(run.error?' · '+run.error:'')+(run.truncated?' · '+T('较长内容已截断','Long content was truncated'):'');
      if(revision!==run.revision){const list=$('research-messages'),follow=list.scrollTop+list.clientHeight>=list.scrollHeight-80;revision=run.revision;
        list.replaceChildren(...run.messages.map(message=>{const card=document.createElement('article');card.className='research-message';const head=document.createElement('strong');head.textContent=(message.role==='user'?T('用户提示词','User prompt'):T('助手','Assistant'))+' · '+fmt(message.timestamp);const body=document.createElement('div');body.className='message-body';body.textContent=message.text;card.append(head,body);return card}));
        if(follow)list.scrollTop=list.scrollHeight;
      }
      if(run.status==='running')timer=setTimeout(()=>load(selected),2000);
    }catch(error){if(request===requestId&&dialog.open){$('research-progress').textContent=T('读取失败，正在重试：','Could not load; retrying: ')+error.message;if(!error.status||error.status>=500){timer=setTimeout(()=>load(selected),retryDelay);retryDelay=Math.min(30000,retryDelay*2)}}}
  }
  $('research-close').onclick=()=>dialog.close();dialog.addEventListener('close',()=>{clearTimeout(timer);requestId++});
  $('research-history-select').onchange=()=>{revision=-1;load($('research-history-select').value)};
  window.QCResearch={open(id=''){selected=id;revision=-1;$('research-meta').textContent=T('正在读取…','Loading…');$('research-progress').textContent='';$('research-messages').replaceChildren();if(!dialog.open)dialog.showModal();load(id)}};
})();
