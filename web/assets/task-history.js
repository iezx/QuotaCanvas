(() => {
  const card=document.getElementById('task-history-card'),T=window.QCi18n.t;
  function element(tag,text,className='') {const node=document.createElement(tag);node.textContent=text;node.className=className;return node;}
  const heading=element('h2',T('任务输出记录','Task output history'));heading.id='task-history-heading';
  const note=element('p',T('后台自动记录任务结束时的输出。平均速度 = 输出 tokens（含推理）÷ 整个任务耗时，包含等待与工具执行时间；不是模型逐 token 生成速度。仅保留最近 500 条，不保存对话正文。开始时间或完整输出缺失时显示不可用。','Tasks are recorded automatically in the background when they finish. Average speed = output tokens (including reasoning) / total task duration, including waits and tools. This is not streaming generation speed. Keeps the latest 500 records without conversation content. Missing start times or incomplete usage show as unavailable.'),'sub');
  const refresh=element('button',T('刷新记录','Refresh history'),'btn');refresh.type='button';
  const feedback=element('p','','sub');feedback.setAttribute('role','status');
  const content=element('div','','quota-log-table');card.append(heading,note,refresh,feedback,content);
  const unavailable=()=>T('不可用','Unavailable');
  const stamp=value=>value?new Date(value*1000).toLocaleString(window.QCi18n.english?'en-US':'zh-CN'):unavailable();
  function render(rows) {
    content.replaceChildren();
    if(!rows.length){content.append(element('p',T('暂无已结束任务。','No finished tasks yet.'),'sub'));return;}
    const table=document.createElement('table'),head=document.createElement('thead'),titles=document.createElement('tr');
    for(const title of [T('结束时间','Finished'),T('任务 / 状态','Task / status'),T('模型','Model'),T('输出 tokens','Output tokens'),T('任务耗时','Task duration'),T('平均速度','Average speed')]){const cell=element('th',title);cell.scope='col';titles.append(cell);}
    head.append(titles);table.append(head);const body=document.createElement('tbody');
    const sources={codex:'Codex',agy:'Antigravity',cc:'Claude Code',dsh:'DeepSeek Harness'};
    for(const row of rows){const line=document.createElement('tr');
      const status=row.status==='stopped'?T('已停止','Stopped'):T('已完成','Completed');
      const duration=typeof row.duration_seconds==='number'?row.duration_seconds.toFixed(1)+' s':unavailable();
      const rate=typeof row.average_tokens_per_second==='number'?row.average_tokens_per_second.toFixed(2)+' tok/s':unavailable();
      for(const value of [stamp(row.completed_at),(sources[row.source]||row.source)+' #'+row.id.slice(-8)+' · '+status,row.model||T('日志未提供模型','Model not reported'),row.output_tokens.toLocaleString(),duration,rate])line.append(element('td',value));
      body.append(line);
    }
    table.append(body);content.append(table);
  }
  async function load(){refresh.disabled=true;feedback.textContent=T('正在读取记录…','Loading history…');
    try{const response=await SiteAuth.fetch('/api/activity/history',{cache:'no-store'}),data=await response.json();if(!response.ok)throw Error(data.error||'HTTP '+response.status);if(!Array.isArray(data.tasks))throw Error(T('记录格式不正确','Invalid history response'));render(data.tasks);feedback.textContent=T('保留最近 500 条记录，重启后继续保留。','Keeps the latest 500 records across restarts.');}
    catch(error){feedback.textContent=T('读取失败：','Could not load: ')+error.message;}finally{refresh.disabled=false;}}
  refresh.onclick=load;load();
})();
