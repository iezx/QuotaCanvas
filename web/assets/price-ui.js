(() => {
  const box=document.getElementById('price'),T=window.QCi18n.t;
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let latest=null,selectedModel=null,researchAgent=null,researchModel=null,refreshResearch=null,modelRequest=0;
  async function request(body){const options=body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{};
    const response=await SiteAuth.fetch('/api/pricing',options),data=await response.json();if(!response.ok)throw new Error(data.error||'HTTP '+response.status);return data;}
  async function load(){try{latest=await request();render()}catch(error){box.textContent=T('读取价格失败：','Could not load prices: ')+error.message}}
  function render(){
    const data=latest,models=data.models||{},proposals=data.proposals||[],schedule=data.schedule||{},ids=[...new Set([...Object.keys(models),...(data.observed_models||[])])].sort();
    const fields=[['price-in','in',T('输入','Input')],['price-cr','cache_read',T('缓存读','Cache read')],
      ['price-cw','cache_write',T('缓存写','Cache write')],['price-out','out',T('输出','Output')]];
    researchAgent??=schedule.agent||'codex';researchModel??=schedule.model||'';
    box.innerHTML=`<div class="price-layout"><section class="card"><h3 style="margin-top:0">${T('自动获取模型与 API 价格','Research models and API prices')}</h3>
      <div class="row"><label for="research-agent">Agent <select id="research-agent">${[['codex','Codex'],['agy','Antigravity (AGY)'],['cc','Claude Code']].map(([id,label])=>`<option value="${id}" ${data.agents?.[id]?.installed===false?'disabled':''}>${label}${data.agents?.[id]?.installed===false?' · '+T('未安装','Not installed'):''}</option>`).join('')}</select></label>
      <label for="research-model">${T('查价使用的模型','Model used for research')} <input id="research-model" list="research-model-list" placeholder="${T('留空使用 Agent 默认模型','Blank for agent default')}"></label><datalist id="research-model-list"></datalist></div>
      <p class="sub" id="research-model-status" role="status"></p>
      <div class="row"><button type="button" class="btn" id="research" ${data.running?'disabled':''}>${data.running?T('正在获取…','Researching…'):T('调用本机 Agent 获取最新资料','Research latest data with local agent')}</button><button type="button" class="btn" id="view-research">${T('查看查价对话','View research conversation')}</button><span class="sub" id="price-last-checked">${data.last_checked?T('上次检查：','Last checked: ')+esc(new Date(data.last_checked*1000).toLocaleString()):T('尚未检查','Not checked yet')}</span></div>
      <p class="sub">${T('查询模型名称、能力说明和 API 价格，结果附来源，确认后应用。定时检查不会自动覆盖手动价格。','Research model names, capabilities, and API prices with source links. Review and apply suggestions; scheduled checks never overwrite manual prices.')}</p>
      <div class="row"><label class="check-label"><input id="price-auto" type="checkbox" ${schedule.enabled?'checked':''}> ${T('定时获取建议','Schedule research')}</label><input id="price-hours" aria-label="${T('检查间隔（小时）','Check interval (hours)')}" type="number" min="24" max="720" value="${esc(schedule.interval_hours||168)}" style="width:80px"><span class="sub">${T('小时一次','hours between checks')}</span><button class="btn" id="price-schedule" type="button">${T('保存更新设置','Save schedule')}</button></div>
      <details class="price-import"><summary>${T('用其他 AI 查价并导入','Research with another AI and import')}</summary>
        <p class="sub">${T('复制提示词给 AI。可加上要查询的模型 ID 和供应商。把返回的 JSON 粘贴到下方，导入后在待确认建议中应用。','Copy the prompt into your AI. Add the model IDs and providers to research. Paste the resulting JSON below, then apply the suggestions you approve.')}</p>
        <label>${T('查价提示词','Research prompt')} <textarea id="price-prompt" rows="3" readonly>${esc(data.research_prompt||'')}</textarea></label>
        <button type="button" class="btn" id="price-copy">${T('复制提示词','Copy prompt')}</button>
        <label>${T('AI 返回的 JSON','JSON from the AI')} <textarea id="price-import-json" rows="4" spellcheck="false"></textarea></label>
        <button type="button" class="btn" id="price-import">${T('导入为待确认建议','Import as suggestions')}</button>
      </details>
      <p class="sub" id="price-status" role="status">${esc(data.last_error||'')}</p>
      </section><section class="card"><h3>${T('手动调整 API 标价（USD / 1M tokens）','Edit API prices (USD / 1M tokens)')}</h3>
      <p class="sub">${T('输入或选择模型，调整下列四项价格并保存。价格用于重算 API 等价费用。','Enter or choose a model, edit the four prices, and save. Prices recalculate API-equivalent estimates.')}</p>
      <div class="row"><label class="model-field">${T('模型','Model')}
        <select id="price-model-choice"><option value="">${T('请选择模型','Select a model')}</option>
        ${ids.map(id=>`<option value="${esc(id)}">${esc(id)}${Object.hasOwn(models,id)?'':' · '+T('待定价','Unpriced')}</option>`).join('')}
        <option value="@new">${T('添加自定义模型 ID','Add a custom model ID')}</option></select></label></div>
      <label class="model-field" id="price-custom" hidden>${T('自定义模型 ID','Custom model ID')} <input id="price-model" maxlength="120" spellcheck="false"></label>
      <div class="price-fields">
      ${fields.map(([id,key,label])=>`<label>${label} <input id="${id}" type="number" min="0" max="1000000" step="any"></label>`).join('')}
      </div><div class="price-actions"><button class="btn" id="price-save" type="button">${T('保存价格','Save price')}</button><p id="price-source" class="sub"></p></div>
      <p id="price-edit-status" class="sub" role="status"></p>
      </section><section class="card"><h3>${T('待确认建议','Suggestions to review')} <span id="price-proposal-count">(${proposals.length})</span></h3><div id="proposals"></div>
      </section><section class="card"><details><summary>${T('查看全部 API 标价','View all API prices')} (${Object.keys(models).length})</summary><div class="table-wrap"><table><tr><th>${T('模型','Model')}<th>${T('输入','Input')}<th>${T('缓存读','Cache read')}<th>${T('缓存写','Cache write')}<th>${T('输出','Output')}</tr>${Object.entries(models).map(([model,p])=>`<tr><td>${esc(model)}<td>${esc(p.in)}<td>${esc(p.cache_read)}<td>${esc(p.cache_write)}<td>${esc(p.out)}`).join('')}</table></div></details>
      <p class="sub">${T('内置价格可能过期。等价估算不代表订阅账单；查询建议也需核对来源和价格适用条件。','Built-in prices may be outdated. Estimates are not subscription bills; verify source links and pricing conditions before applying suggestions.')}</p></section></div>`;
    const $=id=>document.getElementById(id);
    const choice=$('price-model-choice'), custom=$('price-model');
    const modelId=()=>choice.value==='@new'?custom.value.trim():choice.value;
    function fill(){
      const model=modelId(), p=Object.hasOwn(models,model)?models[model]:null, meta=data.metadata?.[model];
      $('price-custom').hidden=choice.value!=='@new';
      $('price-save').disabled=!model;
      for(const [id,key] of fields)$(id).value=p?p[key]:'';
      const source=$('price-source');source.replaceChildren();if(!meta)return;
      source.append(document.createTextNode(T('更新时间：','Updated: ')+new Date(meta.updated_at*1000).toLocaleString()+' · '));
      if(meta.source==='manual')source.append(document.createTextNode(T('手动设置','Manual price')));
      else try{const url=new URL(meta.source);if(url.protocol==='https:'){const link=document.createElement('a');link.href=url.href;link.textContent=T('查看来源','View source');link.target='_blank';link.rel='noopener noreferrer';source.append(link)}}catch{}
    }
    choice.value=selectedModel && ids.includes(selectedModel) ? selectedModel : '';
    choice.onchange=()=>{selectedModel=choice.value;custom.value='';$('price-edit-status').textContent='';fill();if(!$('price-custom').hidden)custom.focus()};
    custom.oninput=()=>{$('price-save').disabled=!modelId()};
    fill();
    async function action(body,message,status='price-status'){
      try{const result=await request(body);await load();if(result.research_id)window.QCResearch.open(result.research_id);if(message)$(status).textContent=message}
      catch(error){if($(status))$(status).textContent=T('操作失败：','Action failed: ')+error.message}
    }
    $('research-agent').value=researchAgent;$('research-model').value=researchModel;
    async function modelChoices(){
      const source=$('research-agent').value,list=$('research-model-list'),status=$('research-model-status'),request=++modelRequest;
      const current=()=>request===modelRequest&&$('research-model-list')===list&&$('research-agent').value===source;
      list.replaceChildren();status.textContent=T('正在读取该 Agent 的模型列表…','Loading this agent’s model list…');
      try{
        const response=await SiteAuth.fetch('/api/models?source='+encodeURIComponent(source),{cache:'no-store'});
        if(!response.ok)throw new Error('HTTP '+response.status);
        const value=await response.json(),choices=[...new Set((value.data||[]).map(m=>m.model||m.id).filter(id=>typeof id==='string'&&id))];
        if(!choices.length)throw new Error('No available models');
        if(!current())return;
        list.replaceChildren(...choices.map(id=>{const option=document.createElement('option');option.value=id;return option}));
        status.textContent=T('可选择该 Agent 提供的模型，也可输入自定义模型 ID。','Choose a model offered by this agent or enter a custom model ID.');
      }catch{
        if(current())status.textContent=T('模型列表不可用，可留空使用 Agent 默认模型，或输入自定义模型 ID。','Model list unavailable. Leave blank for the agent default or enter a custom model ID.');
      }
    }
    $('research-agent').onchange=()=>{researchAgent=$('research-agent').value;researchModel='';$('research-model').value='';modelChoices()};
    $('research-model').oninput=()=>{researchModel=$('research-model').value.trim()};modelChoices();
    const options=()=>({agent:$('research-agent').value,research_model:$('research-model').value.trim()});
    $('view-research').onclick=()=>window.QCResearch.open();
    $('research').onclick=()=>action({action:'research',...options()});
    $('price-schedule').onclick=()=>action({action:'schedule',enabled:$('price-auto').checked,interval_hours:+$('price-hours').value,...options()},T('更新设置已保存','Schedule saved'));
    $('price-copy').onclick=async()=>{
      const prompt=$('price-prompt');prompt.focus();prompt.select();
      try{await navigator.clipboard.writeText(prompt.value);$('price-status').textContent=T('提示词已复制。','Prompt copied.')}
      catch{$('price-status').textContent=T('已选中提示词，可手动复制。','Prompt selected. Copy it with your browser or keyboard.')}
    };
    $('price-import').onclick=()=>{
      let data;
      try{data=JSON.parse($('price-import-json').value.trim().replace(/^\x60\x60\x60(?:json)?\s*|\s*\x60\x60\x60$/gi,''))}
      catch{$('price-status').textContent=T('请输入有效的 JSON。','Enter valid JSON.');return}
      return action({action:'import',models:data?.models},T('已导入。点击「应用建议」后生效。','Imported. Apply a suggestion to use its prices.'));
    };
    $('price-save').onclick=async()=>{
      const model=modelId(), values=fields.map(([id,key])=>[key,$(id).value]);
      if(!model || fields.some(([id])=>!$(id).value||!$(id).checkValidity())){
        $('price-edit-status').textContent=T('请填写模型 ID 和四项有效价格，不收费的项目填 0。','Enter a model ID and all four valid prices. Use 0 for free operations.');
        return;
      }
      selectedModel=model;
      $('price-save').disabled=true;
      await action({action:'save',model,prices:Object.fromEntries(values)},T('价格已保存，正在重算费用。','Price saved. Recalculating estimates.'),'price-edit-status');
      if($('price-model-choice')===choice)$('price-save').disabled=!modelId();
    };
    function renderProposals(entries){$('proposals').replaceChildren();$('price-proposal-count').textContent='('+entries.length+')';
    if(!entries.length)$('proposals').textContent=T('暂无建议','No suggestions');
    for(const p of entries){const card=document.createElement('article');card.className='qb';const title=document.createElement('strong');title.textContent=p.model;const info=document.createElement('p');info.className='sub';info.textContent=`Input ${p.in} · Cache read ${p.cache_read} · Cache write ${p.cache_write} · Output ${p.out} — ${p.description}`;
      const link=document.createElement('a');link.href=p.source;link.textContent=T('查看来源','View source');link.target='_blank';link.rel='noopener noreferrer';const button=document.createElement('button');button.className='btn';button.type='button';button.textContent=T('应用建议','Apply suggestion');button.onclick=()=>action({action:'apply',model:p.model});
      const dismiss=document.createElement('button');dismiss.className='btn';dismiss.type='button';dismiss.textContent=T('不应用',"Don't apply");dismiss.onclick=()=>action({action:'dismiss',model:p.model},T('建议已移除，现有价格保持不变。','Suggestion removed. Current prices are unchanged.'));
      card.append(title,info,link,document.createTextNode(' '),button,document.createTextNode(' '),dismiss);$('proposals').append(card);}
    }
    renderProposals(proposals);
    refreshResearch=next=>{$('research').disabled=next.running;$('research').textContent=next.running?T('正在获取…','Researching…'):T('调用本机 Agent 获取最新资料','Research latest data with local agent');$('price-status').textContent=next.last_error||T('查价完成，请核对待确认建议。','Research completed. Review the suggestions.');if(next.last_checked)$('price-last-checked').textContent=T('上次检查：','Last checked: ')+new Date(next.last_checked*1000).toLocaleString();renderProposals(next.proposals||[])};

  }
  load();setInterval(async()=>{if(!latest?.running)return;try{const next=await request();const finished=latest.running&&!next.running;latest=next;if(finished)refreshResearch?.(next)}catch{}},5000);
})();
