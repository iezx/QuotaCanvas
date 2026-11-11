(async () => {
  const T=window.QCi18n.t,$=id=>document.getElementById(id);
  const publicLabel=document.createElement('label');
  publicLabel.innerHTML=`<input id="public-overview" type="checkbox" style="width:auto"> ${T('首页免密码访问','View overview without a password')}`;
  const publicNote=document.createElement('p');publicNote.className='sub';
  publicNote.textContent=T('默认关闭。开启后可直接查看首页用量、当前任务及未隐藏的邮箱；设置、对话和操作仍需登录。已有 Cloudflare Access 验证继续生效。','Off by default. Enables direct viewing of overview usage, current tasks and any unhidden email. Settings, conversations and actions still require sign-in. Existing Cloudflare Access checks remain in effect.');
  $('save-display').before(publicLabel,publicNote);
  const sources=[['codex','OpenAI Codex'],['agy','Antigravity (AGY)'],['cc','Claude Code']];
  const card=document.createElement('section');card.className='card';
  card.innerHTML=`<h2>${T('订阅日期','Subscription dates')}</h2><p class="sub">${T('可手动设置各订阅的起止日期，用于首页显示及订阅周期统计。取消手动设置后恢复自动读取；不会修改服务商的真实订阅。','Set subscription dates for the overview and subscription-period statistics. Turn off manual dates to restore detected data. Provider subscriptions are unchanged.')}</p>
    ${sources.map(([source,name])=>`<div><label><input id="sub-${source}-manual" type="checkbox" style="width:auto"> ${name} · ${T('手动设置','Manual dates')}</label><div class="row" style="margin-top:0"><label style="flex:1;margin-top:0">${T('开始日期','Start date')}<input id="sub-${source}-start" type="date" disabled></label><label style="flex:1;margin-top:0">${T('到期日期（可留空，不含当天）','Expiry date (optional, date excluded)')}<input id="sub-${source}-end" type="date" disabled></label></div></div>`).join('')}
    <button id="save-subscriptions" class="btn" type="button" disabled>${T('保存订阅日期','Save subscription dates')}</button><p id="subscription-feedback" class="sub" role="status"></p>`;
  $('save-display').closest('section').after(card);
  for(const [source] of sources)$(`sub-${source}-manual`).onchange=()=>{for(const field of ['start','end'])$(`sub-${source}-${field}`).disabled=!$(`sub-${source}-manual`).checked};
  async function request(body){const response=await SiteAuth.fetch('/api/settings',body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});const data=await response.json();if(!response.ok)throw new Error(data.error||'HTTP '+response.status);return data}
  try{const value=await request();$('hide-email').checked=value.hide_email;$('public-overview').checked=value.public_overview===true;
    for(const [source] of sources){const dates=value.subscriptions?.[source];$(`sub-${source}-manual`).checked=!!dates;for(const field of ['start','end']){$(`sub-${source}-${field}`).value=dates?.[field]||'';$(`sub-${source}-${field}`).disabled=!dates}}
    $('save-display').disabled=false;$('save-subscriptions').disabled=false}catch(error){$('display-feedback').textContent=error.message}
  $('save-display').onclick=async()=>{try{await request({hide_email:$('hide-email').checked,public_overview:$('public-overview').checked});$('display-feedback').textContent=T('已保存。重新打开首页即可生效。','Saved. Reopen the overview to apply.')}catch(error){$('display-feedback').textContent=error.message}};
  $('save-subscriptions').onclick=async()=>{try{const subscriptions={};for(const [source] of sources)if($(`sub-${source}-manual`).checked)subscriptions[source]={start:$(`sub-${source}-start`).value,end:$(`sub-${source}-end`).value};await request({subscriptions});$('subscription-feedback').textContent=T('订阅日期已保存。重新打开首页即可生效。','Subscription dates saved. Reopen the overview to apply.')}catch(error){$('subscription-feedback').textContent=error.message}};
})();
