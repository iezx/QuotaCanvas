(() => {
  const box = document.getElementById('price'), T = window.QCi18n.t;
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const timestamp = value => new Date(value * 1000).toLocaleString();
  const safeHref = raw => {
    if (typeof raw !== 'string' || !raw) return null;
    try {
      const u = new URL(raw);
      return u.protocol === 'https:' ? u.href : null;
    } catch {
      return null;
    }
  };
  const fmtUsd = value => typeof value === 'number' && Number.isFinite(value)
    ? '$' + (value === 0 ? '0' : value.toFixed(8).replace(/\.?0+$/, ''))
    : '—';
  const nextCheck = schedule => schedule?.enabled && schedule.next_at
    ? T('下次检查：', 'Next check: ') + timestamp(schedule.next_at)
    : T('定时查价未开启', 'Scheduled research is off');
  const nextSourceCheck = schedule => {
    if (!schedule?.enabled) return T('定时检查已关闭', 'Scheduled check is off');
    if (schedule.next_at) return T('下次自动检查：', 'Next automatic check: ') + timestamp(schedule.next_at);
    return T('每 ', 'Every ') + (schedule.interval_hours || 1) + T(' 小时自动检查一次（首次运行或到期时触发）', ' hour(s) automatically (runs when due)');
  };
  const researchFeedback = data => data.last_error || (data.last_rejected
    ? T('已保留有效建议，跳过的无效或重复条目：', 'Valid suggestions saved. Invalid or duplicate entries skipped: ') + data.last_rejected
    : '');
  const translateSourceError = err => {
    if (!err) return '';
    if (err === 'API key required') return T('需要 API Key', 'API key required');
    return err;
  };
  const makeLink = (href, label) => {
    const clean = safeHref(href);
    if (!clean) return null;
    const a = document.createElement('a');
    a.href = clean;
    a.textContent = label;
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    return a;
  };
  const makeBadge = (text, cls = '') => {
    const span = document.createElement('span');
    span.className = cls ? 'badge ' + cls : 'badge';
    span.textContent = text;
    return span;
  };
  const sourceLabel = meta => {
    const src = meta?.source;
    if (!src) return T('内置', 'Built-in');
    if (src === 'manual') return T('手动', 'Manual');
    if (meta?.channel === 'openrouter' || src.startsWith('https://openrouter.ai/')) return 'OpenRouter';
    return T('来源链接', 'Linked');
  };

  let latest = null, selectedModel = null, researchAgent = null, researchModel = null, researchScope = null;
  let refreshResearch = null, refreshSourcesView = null, modelRequest = 0;
  let orFilter = null, orQuery = '', orShowVariants = false, orShowAll = false;
  let discProvider = 'all', discFilter = 'unpriced', discQuery = '', discShowAll = false;
  let allPricesOpen = false, importDetailsOpen = false;
  let sourceDraft = { dirty: false, enabled: {}, keys: {}, clearKey: {}, schedEnabled: true, hours: '1', autoSync: false };

  function syncSourceDraft(ps, force = false) {
    if (!ps || (sourceDraft.dirty && !force)) return;
    sourceDraft.dirty = false;
    sourceDraft.enabled = {};
    sourceDraft.keys = {};
    sourceDraft.clearKey = {};
    for (const sid of (ps.order || [])) {
      sourceDraft.enabled[sid] = Boolean(ps.sources?.[sid]?.enabled);
    }
    sourceDraft.schedEnabled = ps.schedule?.enabled !== false;
    sourceDraft.hours = String(ps.schedule?.interval_hours || 1);
    sourceDraft.autoSync = Boolean(ps.schedule?.auto_sync_openrouter);
  }

  async function request(body) {
    const options = body
      ? { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body) }
      : { cache: 'no-store' };
    const response = await SiteAuth.fetch('/api/pricing', options), data = await response.json();
    if (!response.ok) throw new Error(data.error || 'HTTP ' + response.status);
    return data;
  }

  async function load() {
    try {
      latest = await request();
      syncSourceDraft(latest?.provider_sources);
      render();
    } catch (error) {
      box.textContent = T('读取价格失败：', 'Could not load prices: ') + error.message;
    }
  }

  function renderSourceStatusHtml(src) {
    const status = src.status || 'never';
    const dotCls = status === 'ok' ? 'dot-ok' : status === 'needs_key' ? 'dot-warn' : status === 'error' ? 'dot-err' : '';
    const parts = [`<span class="dot ${dotCls}"></span>`];
    if (status === 'ok') {
      if (src.kind === 'quotes') {
        parts.push(`<span class="badge badge-ok">${esc(src.quoted_count ?? src.total_count ?? 0)} ${T('条报价', 'quotes')}</span>`);
        if (src.diff_count) parts.push(`<span class="badge badge-new">${esc(src.diff_count)} ${T('可更新', 'differ')}</span>`);
      } else {
        parts.push(`<span class="badge badge-ok">${esc(src.total_count || 0)} ${T('个模型', 'models')}</span>`);
        if (src.new_count) parts.push(`<span class="badge badge-new">+${esc(src.new_count)} ${T('新发现', 'new')}</span>`);
        if (src.unpriced_count) parts.push(`<span class="badge">${esc(src.unpriced_count)} ${T('未定价', 'unpriced')}</span>`);
      }
    } else if (status === 'needs_key') {
      parts.push(`<span class="badge badge-warn">${T('需要 API Key', 'API key needed')}</span>`);
    } else if (status === 'error') {
      parts.push(`<span class="badge badge-err" title="${esc(src.error)}">${T('检查失败', 'Check failed')}</span>`);
      if (src.error) parts.push(`<span>${esc(src.error.slice(0, 72))}${src.error.length > 72 ? '…' : ''}</span>`);
    } else {
      parts.push(`<span>${T('尚未检查', 'Not checked')}</span>`);
    }
    if (src.checked_at) parts.push(`<span>${esc(timestamp(src.checked_at))}</span>`);
    const docs = safeHref(src.docs_url);
    if (docs) parts.push(`<a href="${esc(docs)}" target="_blank" rel="noopener noreferrer">${T('官网定价', 'Docs')}</a>`);
    return parts.join('');
  }

  function renderProviderCardsHtml(ps) {
    if (!ps || typeof ps !== 'object') return '';
    const order = ps.order || [], sources = ps.sources || {}, sched = ps.schedule || {};
    const rowsHtml = order.map(sid => {
      const src = sources[sid] || { id: sid, name: sid };
      const checked = Object.hasOwn(sourceDraft.enabled, sid) ? sourceDraft.enabled[sid] : Boolean(src.enabled);
      const willClear = Boolean(sourceDraft.clearKey[sid]);
      const kindBadge = src.kind === 'quotes'
        ? T('可同步报价', 'Quotes')
        : T('新模型发现', 'Discovery');
      const placeholder = willClear
        ? T('保存或刷新时将清除已保存的 Key', 'Saved key will be cleared on save/refresh')
        : src.api_key_saved
          ? T('已保存 Key（留空保持不变）', 'Key saved (leave blank to keep)')
          : src.requires_key
            ? T('输入官方 API Key', 'Enter official API key')
            : T('可选 API Key（留空使用公开目录）', 'Optional API key (blank for public catalog)');
      const clearBtn = src.api_key_saved
        ? `<button type="button" class="btn btn-sm" id="src-clear-${esc(sid)}">${willClear ? T('撤销清除', 'Undo clear') : T('清除 Key', 'Clear key')}</button>`
        : '';
      return `<div class="source-row" id="src-row-${esc(sid)}">
        <label class="source-check"><input type="checkbox" id="src-enabled-${esc(sid)}" ${checked ? 'checked' : ''}><span>${esc(src.name)}</span><span class="badge">${esc(kindBadge)}</span></label>
        <div class="source-key-wrap"><input type="password" autocomplete="off" spellcheck="false" id="src-key-${esc(sid)}" placeholder="${esc(placeholder)}" ${willClear ? 'disabled' : ''}>${clearBtn}</div>
        <div class="source-meta" id="src-meta-${esc(sid)}">${renderSourceStatusHtml(src)}</div>
      </div>`;
    }).join('');

    const lastText = ps.running
      ? T('正在刷新模型来源…', 'Refreshing sources…')
      : ps.last_checked
        ? T('上次检查：', 'Last checked: ') + esc(timestamp(ps.last_checked))
        : T('尚未检查', 'Not checked yet');

    return `<section class="card" id="sources-card">
      <div class="card-head">
        <h3>${T('模型来源与定时检查', 'Model sources & scheduled checks')}</h3>
        <span class="sub" id="sources-last-checked">${lastText}</span>
      </div>
      <p class="sub">${T('勾选需要检查的来源。OpenRouter 提供可同步的 USD 渠道报价（API Key 可选）；Google Gemini、OpenAI、Anthropic、DeepSeek 使用各自官方 API Key 发现账号可见的新模型。默认每小时检查一次，定时同步不会覆盖手动设置的价格。', 'Select the sources to check. OpenRouter provides syncable USD channel quotes (API key optional). Google Gemini, OpenAI, Anthropic, and DeepSeek use your API key to discover account-visible models. Checks run hourly by default and never overwrite manual prices.')}</p>
      <div class="source-list">${rowsHtml}</div>
      <div class="row">
        <label class="check-label"><input type="checkbox" id="sources-auto" ${sourceDraft.schedEnabled ? 'checked' : ''}> ${T('定时检查已勾选来源', 'Check selected sources automatically')}</label>
        <label class="check-label">${T('每', 'Every')} <input type="number" id="sources-hours" min="1" max="720" value="${esc(sourceDraft.hours)}" aria-label="${T('来源检查间隔（小时）', 'Source check interval (hours)')}" style="width:74px"> ${T('小时', 'hours')}</label>
        <label class="check-label"><input type="checkbox" id="sources-auto-sync" ${sourceDraft.autoSync ? 'checked' : ''}> ${T('检查后自动同步 OpenRouter 已匹配非手动模型', 'Auto-sync matched non-manual OpenRouter quotes')}</label>
      </div>
      <div class="row">
        <button type="button" class="btn btn-primary" id="sources-refresh" ${ps.running ? 'disabled' : ''}>${ps.running ? T('正在刷新…', 'Refreshing…') : T('立即刷新已勾选来源', 'Refresh selected now')}</button>
        <button type="button" class="btn" id="sources-save">${T('保存来源与定时', 'Save sources & schedule')}</button>
        <span class="sub" id="sources-next-check">${esc(nextSourceCheck(sched))}</span>
      </div>
      <p class="sub" id="sources-status" role="status"></p>
    </section>
    <section class="card" id="openrouter-card">
      <div class="card-head">
        <h3>${T('OpenRouter 渠道报价（USD / 1M tokens）', 'OpenRouter channel quotes (USD / 1M tokens)')}</h3>
        <span class="sub" id="or-counts"></span>
      </div>
      <div class="toolbar">
        <div class="pill-group" id="or-filters"></div>
        <input type="search" id="or-search" placeholder="${T('搜索 OpenRouter 或本地模型…', 'Filter OpenRouter or local model…')}" value="${esc(orQuery)}" aria-label="${T('搜索 OpenRouter 模型', 'Filter OpenRouter models')}" style="min-width:220px;flex:1">
        <label class="check-label"><input type="checkbox" id="or-variants" ${orShowVariants ? 'checked' : ''}> ${T('包含 :batch / :free 等变体', 'Include :batch / :free variants')}</label>
        <button type="button" class="btn" id="or-sync-matched">${T('同步已匹配非手动模型', 'Sync matched non-manual')}</button>
      </div>
      <p class="sub" id="or-status" role="status"></p>
      <div class="price-scroll" id="or-body"></div>
    </section>
    <section class="card" id="unpriced-card">
      <div class="card-head">
        <h3>${T('未定价新模型 · OpenRouter 自动查价', 'Unpriced models · OpenRouter auto-lookup')}</h3>
        <span class="sub" id="unpriced-counts"></span>
      </div>
      <p class="sub">${T('系统探测到尚无本机价格记录的模型（来自本机使用日志或上方渠道发现）后，会自动向 OpenRouter 查询是否存在固定报价。', 'When new models without local prices are detected (from local usage logs or provider discovery), QuotaCanvas automatically checks OpenRouter for matching rates.')}</p>
      <div class="toolbar">
        <button type="button" class="btn" id="unpriced-lookup">${T('立即向 OpenRouter 查价', 'Query OpenRouter now')}</button>
        <button type="button" class="btn" id="unpriced-sync-all">${T('一键导入已匹配报价', 'Import all matched quotes')}</button>
      </div>
      <p class="sub" id="unpriced-status" role="status"></p>
      <div class="price-scroll" id="unpriced-body"></div>
    </section>
    <section class="card" id="discovery-card">
      <div class="card-head">
        <h3>${T('账号可见新模型发现', 'Account-visible model discovery')}</h3>
        <span class="sub" id="disc-counts"></span>
      </div>
      <div class="toolbar">
        <div class="pill-group" id="disc-providers"></div>
        <div class="pill-group" id="disc-filters"></div>
        <input type="search" id="disc-search" placeholder="${T('筛选发现的模型 ID…', 'Filter discovered model ID…')}" value="${esc(discQuery)}" aria-label="${T('筛选发现的模型', 'Filter discovered models')}" style="min-width:200px;flex:1">
      </div>
      <p class="sub" id="disc-status" role="status"></p>
      <div class="price-scroll" id="disc-body"></div>
    </section>`;
  }

  function render() {
    const data = latest, models = data.models || {}, proposals = data.proposals || [], schedule = data.schedule || {};
    const ids = [...new Set([...Object.keys(models), ...(data.observed_models || [])])].sort();
    const ps = data.provider_sources || null;
    const fields = [['price-in', 'in', T('输入', 'Input')], ['price-cr', 'cache_read', T('缓存读', 'Cache read')],
      ['price-cw', 'cache_write', T('缓存写', 'Cache write')], ['price-out', 'out', T('输出', 'Output')]];
    researchAgent ??= schedule.agent || 'codex';
    researchModel ??= schedule.model || '';
    researchScope ??= schedule.scope || 'all';

    box.innerHTML = `<div class="price-layout">${renderProviderCardsHtml(ps)}<section class="card"><h3 style="margin-top:0">${T('自动获取模型与 API 价格', 'Research models and API prices')}</h3>
      <div class="row"><label for="research-agent">Agent <select id="research-agent">${[['codex', 'Codex'], ['agy', 'Antigravity (AGY)'], ['cc', 'Claude Code']].map(([id, label]) => `<option value="${id}" ${data.agents?.[id]?.installed === false ? 'disabled' : ''}>${label}${data.agents?.[id]?.installed === false ? ' · ' + T('未安装', 'Not installed') : ''}</option>`).join('')}</select></label>
      <label for="research-model">${T('查价使用的模型', 'Model used for research')} <input id="research-model" list="research-model-list" placeholder="${T('留空使用 Agent 默认模型', 'Blank for agent default')}"></label><datalist id="research-model-list"></datalist>
      <label for="research-scope">${T('查价范围', 'Research scope')}
        <select id="research-scope"><option value="all">${T('全部供应商', 'All providers')}</option>
          <option value="google">Google Gemini</option><option value="openai">OpenAI</option>
          <option value="anthropic">Anthropic</option><option value="deepseek">DeepSeek</option>
        </select></label></div>
      <p class="sub" id="research-model-status" role="status"></p>
      <div class="row"><button type="button" class="btn" id="research" ${data.running ? 'disabled' : ''}>${data.running ? T('正在获取…', 'Researching…') : T('调用本机 Agent 获取最新资料', 'Research latest data with local agent')}</button><button type="button" class="btn" id="view-research">${T('查看查价对话', 'View research conversation')}</button><span class="sub" id="price-last-checked">${data.last_checked ? T('上次检查：', 'Last checked: ') + esc(timestamp(data.last_checked)) : T('尚未检查', 'Not checked yet')}</span></div>
      <p class="sub">${T('查询模型名称、能力说明和 API 价格，结果附来源，确认后应用。定时检查不会自动覆盖手动价格。', 'Research model names, capabilities, and API prices with source links. Review and apply suggestions; scheduled checks never overwrite manual prices.')}</p>
      <div class="row"><label class="check-label"><input id="price-auto" type="checkbox" ${schedule.enabled ? 'checked' : ''}> ${T('定时获取建议', 'Schedule research')}</label><input id="price-hours" aria-label="${T('检查间隔（小时）', 'Check interval (hours)')}" type="number" min="24" max="720" value="${esc(schedule.interval_hours || 168)}" style="width:80px"><span class="sub">${T('小时一次', 'hours between checks')}</span><button class="btn" id="price-schedule" type="button">${T('保存更新设置', 'Save schedule')}</button></div>
      <p class="sub" id="price-next-check">${esc(nextCheck(schedule))}</p>
      <details class="price-import" id="price-import-details" ${importDetailsOpen ? 'open' : ''}><summary>${T('用其他 AI 查价并导入', 'Research with another AI and import')}</summary>
        <p class="sub">${T('复制提示词给 AI。可加上要查询的模型 ID 和供应商。把返回的 JSON 粘贴到下方，导入后在待确认建议中应用。', 'Copy the prompt into your AI. Add the model IDs and providers to research. Paste the resulting JSON below, then apply the suggestions you approve.')}</p>
        <label>${T('查价提示词', 'Research prompt')} <textarea id="price-prompt" rows="3" readonly>${esc(data.research_prompt || '')}</textarea></label>
        <button type="button" class="btn" id="price-copy">${T('复制提示词', 'Copy prompt')}</button>
        <label>${T('AI 返回的 JSON', 'JSON from the AI')} <textarea id="price-import-json" rows="4" spellcheck="false"></textarea></label>
        <button type="button" class="btn" id="price-import">${T('导入为待确认建议', 'Import as suggestions')}</button>
      </details>
      <p class="sub" id="price-status" role="status">${esc(researchFeedback(data))}</p>
      </section><section class="card" id="price-edit-card"><h3>${T('手动调整 API 标价（USD / 1M tokens）', 'Edit API prices (USD / 1M tokens)')}</h3>
      <p class="sub">${T('输入或选择模型，调整下列四项价格并保存。价格用于重算 API 等价费用。', 'Enter or choose a model, edit the four prices, and save. Prices recalculate API-equivalent estimates.')}</p>
      <div class="row"><label class="model-field">${T('模型', 'Model')}
        <select id="price-model-choice"><option value="">${T('请选择模型', 'Select a model')}</option>
        ${ids.map(id => `<option value="${esc(id)}">${esc(id)}${Object.hasOwn(models, id) ? '' : ' · ' + T('待定价', 'Unpriced')}</option>`).join('')}
        <option value="@new">${T('添加自定义模型 ID', 'Add a custom model ID')}</option></select></label></div>
      <label class="model-field" id="price-custom" hidden>${T('自定义模型 ID', 'Custom model ID')} <input id="price-model" maxlength="120" spellcheck="false"></label>
      <div class="price-fields">
      ${fields.map(([id, key, label]) => `<label>${label} <input id="${id}" type="number" min="0" max="1000000" step="any"></label>`).join('')}
      </div><div class="price-actions"><button class="btn" id="price-save" type="button">${T('保存价格', 'Save price')}</button><p id="price-source" class="sub"></p></div>
      <p id="price-edit-status" class="sub" role="status"></p>
      </section><section class="card"><h3>${T('待确认建议', 'Suggestions to review')} <span id="price-proposal-count">(${proposals.length})</span></h3><div id="proposals"></div>
      </section><section class="card"><details id="price-all-details" ${allPricesOpen ? 'open' : ''}><summary>${T('查看全部 API 标价', 'View all API prices')} (${Object.keys(models).length})</summary><div class="table-wrap"><table><tr><th>${T('模型', 'Model')}<th>${T('输入', 'Input')}<th>${T('缓存读', 'Cache read')}<th>${T('缓存写', 'Cache write')}<th>${T('输出', 'Output')}<th>${T('来源', 'Source')}</tr>${Object.entries(models).map(([model, p]) => `<tr><td class="mono">${esc(model)}<td class="num">${esc(p.in)}<td class="num">${esc(p.cache_read)}<td class="num">${esc(p.cache_write)}<td class="num">${esc(p.out)}<td><span class="badge">${esc(sourceLabel(data.metadata?.[model]))}</span>`).join('')}</table></div></details>
      <p class="sub">${T('内置价格可能过期。等价估算不代表订阅账单；查询建议也需核对来源和价格适用条件。', 'Built-in prices may be outdated. Estimates are not subscription bills; verify source links and pricing conditions before applying suggestions.')}</p></section></div>`;

    const $ = id => document.getElementById(id);
    const choice = $('price-model-choice'), custom = $('price-model');
    const modelId = () => choice.value === '@new' ? custom.value.trim() : choice.value;

    function fill() {
      const model = modelId(), p = Object.hasOwn(models, model) ? models[model] : null;
      const meta = data.metadata?.[model], catalog = data.catalog?.[model];
      $('price-custom').hidden = choice.value !== '@new';
      $('price-save').disabled = !model;
      for (const [id, key] of fields) $(id).value = p ? p[key] : '';
      const source = $('price-source'); source.replaceChildren();
      if (meta?.updated_at) source.append(T('更新时间：', 'Updated: ') + timestamp(meta.updated_at) + ' · ');
      if (meta?.source === 'manual') source.append(T('手动设置', 'Manual price'));
      else if (meta || catalog) {
        if (!meta && catalog.verified_on) source.append(T('官方标价核对日期：', 'Official rates checked: ') + catalog.verified_on + ' · ');
        const link = makeLink((meta || catalog).source, meta?.channel === 'openrouter' ? 'OpenRouter' : T('查看来源', 'View source'));
        if (link) source.append(link);
      }
      if (!meta && catalog?.next_rate) {
        const rate = catalog.next_rate;
        source.append(' · ' + T('新价格生效日（UTC）：', 'New rates from (UTC): ') + rate.effective_from + ' · ' +
          fields.map(([, key, label]) => label + ' $' + rate[key]).join(' · '));
      }
    }

    choice.value = selectedModel && ids.includes(selectedModel) ? selectedModel : '';
    choice.onchange = () => {
      selectedModel = choice.value;
      custom.value = '';
      $('price-edit-status').textContent = '';
      fill();
      if (!$('price-custom').hidden) custom.focus?.();
    };
    custom.oninput = () => { $('price-save').disabled = !modelId(); };
    fill();

    function prefillManualPrice(targetId) {
      if (ids.includes(targetId)) {
        selectedModel = targetId;
        choice.value = targetId;
        custom.value = '';
      } else {
        selectedModel = '@new';
        choice.value = '@new';
        custom.value = targetId;
      }
      $('price-edit-status').textContent = '';
      fill();
      $('price-edit-card')?.scrollIntoView?.({ behavior: 'smooth', block: 'start' });
      $('price-in')?.focus?.();
    }

    if ($('price-all-details')) $('price-all-details').ontoggle = () => { allPricesOpen = Boolean($('price-all-details').open); };
    if ($('price-import-details')) $('price-import-details').ontoggle = () => { importDetailsOpen = Boolean($('price-import-details').open); };

    async function action(body, message, status = 'price-status', afterLoad = null) {
      const orScroll = $('or-body')?.scrollTop || 0;
      const discScroll = $('disc-body')?.scrollTop || 0;
      const unpricedScroll = $('unpriced-body')?.scrollTop || 0;
      const winY = typeof window.scrollY === 'number' ? window.scrollY : 0;
      try {
        const result = await request(body);
        if (afterLoad) afterLoad(result);
        if (result?.pricing && typeof result.pricing === 'object') {
          latest = result.pricing;
          syncSourceDraft(latest?.provider_sources);
          render();
        } else {
          await load();
        }
        if ($('or-body')) $('or-body').scrollTop = orScroll;
        if ($('disc-body')) $('disc-body').scrollTop = discScroll;
        if ($('unpriced-body')) $('unpriced-body').scrollTop = unpricedScroll;
        if (typeof window.scrollTo === 'function') window.scrollTo(0, winY);
        if (result.research_id) window.QCResearch.open(result.research_id);
        const text = typeof message === 'function' ? message(result) : message;
        if (text && $(status)) $(status).textContent = text;
        return result;
      } catch (error) {
        if ($(status)) $(status).textContent = T('操作失败：', 'Action failed: ') + error.message;
        return null;
      }
    }

    async function confirmOverwrite(label) {
      const msg = T('「', '"') + label + T('」当前是手动设置的价格，确定要用 OpenRouter 报价覆盖吗？', '" has a manual price override. Overwrite it with the OpenRouter quote?');
      if (typeof SiteAuth?.confirm === 'function') return SiteAuth.confirm(msg, { confirmText: T('覆盖手动价格', 'Overwrite') });
      return typeof confirm === 'function' ? confirm(msg) : false;
    }

    function bindAndRenderProviderSections(currentPs) {
      if (!currentPs || typeof currentPs !== 'object') return;
      const order = currentPs.order || [], sources = currentPs.sources || {};
      const orSrc = sources.openrouter || { models: [] };

      for (const sid of order) {
        const enabledEl = $('src-enabled-' + sid);
        const keyEl = $('src-key-' + sid);
        const clearEl = $('src-clear-' + sid);
        if (enabledEl) {
          enabledEl.onchange = () => {
            sourceDraft.dirty = true;
            sourceDraft.enabled[sid] = Boolean(enabledEl.checked);
          };
        }
        if (keyEl) {
          keyEl.value = sourceDraft.keys[sid] || '';
          keyEl.oninput = () => {
            sourceDraft.dirty = true;
            sourceDraft.keys[sid] = keyEl.value;
          };
        }
        if (clearEl) {
          clearEl.onclick = () => {
            sourceDraft.dirty = true;
            sourceDraft.clearKey[sid] = !sourceDraft.clearKey[sid];
            if (sourceDraft.clearKey[sid]) sourceDraft.keys[sid] = '';
            render();
          };
        }
      }

      if ($('sources-auto')) {
        $('sources-auto').onchange = () => {
          sourceDraft.dirty = true;
          sourceDraft.schedEnabled = Boolean($('sources-auto').checked);
        };
      }
      if ($('sources-hours')) {
        $('sources-hours').oninput = () => {
          sourceDraft.dirty = true;
          sourceDraft.hours = $('sources-hours').value;
        };
      }
      if ($('sources-auto-sync')) {
        $('sources-auto-sync').onchange = () => {
          sourceDraft.dirty = true;
          sourceDraft.autoSync = Boolean($('sources-auto-sync').checked);
        };
      }

      function buildSourcePayload() {
        const sourcesPatch = {};
        const selected = [];
        for (const sid of order) {
          const en = Boolean($('src-enabled-' + sid)?.checked);
          if (en) selected.push(sid);
          const patch = { enabled: en };
          if (sourceDraft.clearKey[sid]) {
            patch.clear_key = true;
          } else {
            const rawKey = $('src-key-' + sid)?.value?.trim();
            if (rawKey) patch.api_key = rawKey;
          }
          sourcesPatch[sid] = patch;
        }
        const hoursVal = Number($('sources-hours')?.value || 1);
        const schedulePatch = {
          enabled: Boolean($('sources-auto')?.checked),
          interval_hours: hoursVal,
          auto_sync_openrouter: Boolean($('sources-auto-sync')?.checked),
        };
        return { sourcesPatch, schedulePatch, selected };
      }

      if ($('sources-save')) {
        $('sources-save').onclick = () => {
          const { sourcesPatch, schedulePatch } = buildSourcePayload();
          if (!Number.isInteger(schedulePatch.interval_hours) || schedulePatch.interval_hours < 1 || schedulePatch.interval_hours > 720) {
            $('sources-status').textContent = T('检查间隔需为 1 到 720 之间的整数小时。', 'Check interval must be a whole number from 1 to 720 hours.');
            return;
          }
          action(
            { action: 'sources_save', sources: sourcesPatch, schedule: schedulePatch },
            T('来源设置与定时规则已保存。', 'Sources and schedule saved.'),
            'sources-status',
            res => syncSourceDraft(res.provider_sources, true),
          );
        };
      }

      if ($('sources-refresh')) {
        $('sources-refresh').onclick = async () => {
          const { sourcesPatch, schedulePatch, selected } = buildSourcePayload();
          if (!selected.length) {
            $('sources-status').textContent = T('请至少勾选一个来源后再刷新。', 'Select at least one source before refreshing.');
            return;
          }
          if (!Number.isInteger(schedulePatch.interval_hours) || schedulePatch.interval_hours < 1 || schedulePatch.interval_hours > 720) {
            $('sources-status').textContent = T('检查间隔需为 1 到 720 之间的整数小时。', 'Check interval must be a whole number from 1 to 720 hours.');
            return;
          }
          const btn = $('sources-refresh');
          btn.disabled = true;
          btn.textContent = T('正在刷新…', 'Refreshing…');
          $('sources-status').textContent = T('正在从已勾选来源拉取最新模型目录…', 'Fetching latest model catalogs from selected sources…');
          const res = await action(
            { action: 'sources_refresh', sources: sourcesPatch, schedule: schedulePatch, target_sources: selected },
            result => {
              const outcomes = result?.outcomes || {};
              const parts = selected.map(sid => {
                const name = sources[sid]?.name || sid;
                const out = outcomes[sid] || {};
                if (out.status === 'ok') return `${name}: ${T('成功', 'OK')} (${out.models?.length ?? 0})`;
                if (out.status === 'needs_key') return `${name}: ${T('缺少 API Key', 'Key needed')}`;
                return `${name}: ${T('失败', 'Error')} (${translateSourceError(out.error) || 'error'})`;
              });
              return parts.join(' · ');
            },
            'sources-status',
            result => syncSourceDraft(result.provider_sources, true),
          );
          if (!res && $('sources-refresh')) {
            $('sources-refresh').disabled = false;
            $('sources-refresh').textContent = T('立即刷新已勾选来源', 'Refresh selected now');
          }
        };
      }

      function renderOpenRouterTable(psNow) {
        const src = psNow.sources?.openrouter || { models: [] };
        const quotes = src.models || [];
        if (orFilter === null && quotes.length) {
          orFilter = src.matched_count ? 'matched' : src.quoted_count ? 'all' : 'matched';
        }
        const filterNow = orFilter || (src.matched_count ? 'matched' : src.quoted_count ? 'all' : 'matched');
        $('or-counts').textContent = quotes.length
          ? `${src.quoted_count || 0} ${T('条固定报价', 'quoted')} · ${src.matched_count || 0} ${T('个匹配本地模型', 'matched')} · ${src.diff_count || 0} ${T('条与当前价格不同', 'differ')}`
          : T('尚未拉取 OpenRouter 报价', 'OpenRouter quotes not fetched yet');

        const filterDefs = [
          ['matched', `${T('已匹配本地', 'Matched local')} (${src.matched_count || 0})`],
          ['diff', `${T('报价有差异', 'Price differs')} (${src.diff_count || 0})`],
          ['all', `${T('全部报价', 'All quotes')} (${src.quoted_count || 0})`],
          ['dynamic', `${T('动态路由', 'Dynamic')} (${src.dynamic_count || 0})`],
        ];
        const pillBox = $('or-filters');
        pillBox.replaceChildren(...filterDefs.map(([key, label]) => {
          const btn = document.createElement('button');
          btn.type = 'button';
          btn.className = filterNow === key ? 'pill active' : 'pill';
          btn.textContent = label;
          btn.onclick = () => { orFilter = key; orShowAll = false; renderOpenRouterTable(latest?.provider_sources || psNow); };
          return btn;
        }));

        const qLower = orQuery.trim().toLowerCase();
        const filtered = quotes.filter(q => {
          if (!orShowVariants && q.variant) return false;
          if (filterNow === 'matched' && !q.matched_model) return false;
          if (filterNow === 'diff' && !(q.matched_model && q.price_differs)) return false;
          if (filterNow === 'all' && !q.quote_available) return false;
          if (filterNow === 'dynamic' && q.quote_available) return false;
          if (qLower) {
            const hay = `${q.id} ${q.name || ''} ${q.matched_model || ''}`.toLowerCase();
            if (!hay.includes(qLower)) return false;
          }
          return true;
        });

        const syncableCount = quotes.filter(q => q.quote_available && !q.variant && q.matched_model && !q.is_manual).length;
        $('or-sync-matched').disabled = !syncableCount || Boolean(psNow.running);
        $('or-sync-matched').textContent = `${T('同步已匹配非手动模型', 'Sync matched non-manual')} (${syncableCount})`;
        $('or-sync-matched').onclick = () => action(
          { action: 'sync_matched' },
          res => {
            const s = res.sync || {};
            const n = v => Array.isArray(v) ? v.length : (v || 0);
            return T('同步完成：已更新 ', 'Sync complete: updated ') + n(s.synced)
              + T('，跳过手动 ', ', skipped manual ') + n(s.skipped_manual)
              + T('，无变化 ', ', unchanged ') + n(s.unchanged);
          },
          'or-status',
        );

        const body = $('or-body');
        if (!filtered.length) {
          const empty = document.createElement('p');
          empty.className = 'sub';
          empty.textContent = quotes.length
            ? T('当前筛选条件下没有匹配的 OpenRouter 报价。', 'No OpenRouter quotes match the current filters.')
            : T('勾选 OpenRouter 并点击「立即刷新已勾选来源」即可拉取最新渠道报价。', 'Check OpenRouter and click "Refresh selected now" to load channel quotes.');
          body.replaceChildren(empty);
          return;
        }

        const limit = orShowAll ? filtered.length : 150;
        const visible = filtered.slice(0, limit);
        const table = document.createElement('table');
        const head = document.createElement('tr');
        for (const col of [T('OpenRouter 模型', 'OpenRouter model'), T('本地模型', 'Local model'), T('输入', 'Input'), T('缓存读', 'Cache read'), T('缓存写', 'Cache write'), T('输出', 'Output'), T('操作', 'Action')]) {
          const th = document.createElement('th');
          th.textContent = col;
          head.append(th);
        }
        table.append(head);

        for (const q of visible) {
          const tr = document.createElement('tr');
          const idTd = document.createElement('td');
          const idSpan = document.createElement('div');
          idSpan.className = 'mono';
          idSpan.textContent = q.id;
          idTd.append(idSpan);
          if (q.name && q.name !== q.id) {
            const sub = document.createElement('div');
            sub.className = 'sub';
            sub.textContent = q.name;
            idTd.append(sub);
          }
          if (q.variant) idTd.append(makeBadge(':' + q.variant));
          const orLink = makeLink(q.source, 'OpenRouter');
          if (orLink) idTd.append(document.createTextNode(' '), orLink);

          const matchTd = document.createElement('td');
          if (q.matched_model) {
            const mSpan = document.createElement('div');
            mSpan.className = 'mono';
            mSpan.textContent = q.matched_model;
            matchTd.append(mSpan);
            if (q.is_manual) matchTd.append(makeBadge(T('手动保护', 'Manual'), 'badge-warn'));
            else if (q.price_differs) matchTd.append(makeBadge(T('有差异', 'Differs'), 'badge-new'));
            else matchTd.append(makeBadge(T('已一致', 'In sync'), 'badge-ok'));
          } else {
            matchTd.textContent = '—';
          }

          const numCells = [q.in, q.cache_read, q.cache_write, q.out].map(v => {
            const td = document.createElement('td');
            td.className = 'num';
            td.textContent = q.quote_available ? fmtUsd(v) : '—';
            return td;
          });

          const actTd = document.createElement('td');
          actTd.className = 'action-cell';
          const makeRowSyncBtn = (label, busyLabel, payload, msg, needsConfirm = false) => {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'btn btn-sm';
            btn.textContent = label;
            btn.onclick = async () => {
              if (needsConfirm && !await confirmOverwrite(q.matched_model)) return;
              btn.disabled = true;
              btn.textContent = busyLabel;
              await action(payload, msg, 'or-status', res => { if (res?.model) selectedModel = res.model; });
              if (btn.textContent !== label) { btn.disabled = false; btn.textContent = label; }
            };
            return btn;
          };
          if (!q.quote_available) {
            actTd.append(makeBadge(T('动态定价不可同步', 'Dynamic rate')));
          } else if (q.matched_model && q.is_manual) {
            actTd.append(makeRowSyncBtn(
              T('覆盖手动', 'Overwrite manual'),
              T('同步中…', 'Syncing…'),
              { action: 'sync_quote', quote_id: q.id, target_model: q.matched_model, overwrite_manual: true },
              T('已用 OpenRouter 报价更新 ', 'Updated with OpenRouter quote: ') + q.matched_model,
              true,
            ));
          } else if (q.matched_model) {
            actTd.append(makeRowSyncBtn(
              q.price_differs ? T('同步覆盖', 'Sync price') : T('重新同步', 'Re-sync'),
              T('同步中…', 'Syncing…'),
              { action: 'sync_quote', quote_id: q.id, target_model: q.matched_model },
              T('已同步报价到 ', 'Synced quote to ') + q.matched_model,
            ));
          } else {
            actTd.append(makeRowSyncBtn(
              T('导入该模型报价', 'Import quote'),
              T('导入中…', 'Importing…'),
              { action: 'sync_quote', quote_id: q.id },
              T('已导入渠道报价：', 'Imported channel quote: ') + q.id,
            ));
          }

          tr.append(idTd, matchTd, ...numCells, actTd);
          table.append(tr);
        }

        const nodes = [table];
        if (!orShowAll && filtered.length > limit) {
          const more = document.createElement('button');
          more.type = 'button';
          more.className = 'btn';
          more.textContent = T('显示全部 ', 'Show all ') + filtered.length + T(' 条', ' rows');
          more.onclick = () => { orShowAll = true; renderOpenRouterTable(latest?.provider_sources || psNow); };
          nodes.push(more);
        }
        body.replaceChildren(...nodes);
      }

      function renderDiscoveryTable(psNow) {
        const sourcesMap = psNow.sources || {};
        const discIds = (psNow.order || []).filter(sid => sourcesMap[sid]?.kind === 'discovery');
        const allItems = [];
        for (const sid of discIds) {
          const src = sourcesMap[sid] || {};
          for (const item of (src.models || [])) {
            allItems.push({ ...item, sourceId: sid, sourceName: src.name || sid });
          }
        }
        const totalDiscovered = allItems.filter(m => !m.dismissed).length;
        const totalUnpriced = allItems.filter(m => !m.dismissed && !m.in_catalog).length;
        const totalNew = allItems.filter(m => !m.dismissed && m.is_new_since_last).length;
        const totalDismissed = allItems.filter(m => m.dismissed).length;
        $('disc-counts').textContent = allItems.length
          ? `${totalDiscovered} ${T('个模型', 'models')} · ${totalUnpriced} ${T('个未定价', 'unpriced')} · ${totalNew} ${T('个新发现', 'new')}`
          : T('填入官方 API Key 并刷新后，将在此列出账号可见模型', 'Add provider API keys above and refresh to discover models');

        const providerBtns = [['all', T('全部四家', 'All 4')], ...discIds.map(sid => {
          const s = sourcesMap[sid] || {};
          return [sid, s.total_count ? `${s.name} (${s.unpriced_count ?? 0}/${s.total_count})` : (s.name || sid)];
        })];
        $('disc-providers').replaceChildren(...providerBtns.map(([key, label]) => {
          const btn = document.createElement('button');
          btn.type = 'button';
          btn.className = discProvider === key ? 'pill active' : 'pill';
          btn.textContent = label;
          btn.onclick = () => { discProvider = key; discShowAll = false; renderDiscoveryTable(latest?.provider_sources || psNow); };
          return btn;
        }));

        const filterDefs = [
          ['unpriced', `${T('未定价', 'Unpriced')} (${totalUnpriced})`],
          ['new', `${T('新发现', 'New')} (${totalNew})`],
          ['all', `${T('全部可见', 'All visible')} (${totalDiscovered})`],
          ['dismissed', `${T('已忽略', 'Dismissed')} (${totalDismissed})`],
        ];
        $('disc-filters').replaceChildren(...filterDefs.map(([key, label]) => {
          const btn = document.createElement('button');
          btn.type = 'button';
          btn.className = discFilter === key ? 'pill active' : 'pill';
          btn.textContent = label;
          btn.onclick = () => { discFilter = key; discShowAll = false; renderDiscoveryTable(latest?.provider_sources || psNow); };
          return btn;
        }));

        const qLower = discQuery.trim().toLowerCase();
        const filtered = allItems.filter(m => {
          if (discProvider !== 'all' && m.sourceId !== discProvider) return false;
          if (discFilter === 'dismissed') { if (!m.dismissed) return false; }
          else if (m.dismissed) return false;
          if (discFilter === 'unpriced' && m.in_catalog) return false;
          if (discFilter === 'new' && !m.is_new_since_last) return false;
          if (qLower) {
            const hay = `${m.sourceId} ${m.sourceName} ${m.id} ${m.display_name || ''} ${m.detail || ''}`.toLowerCase();
            if (!hay.includes(qLower)) return false;
          }
          return true;
        });

        const body = $('disc-body');
        if (!filtered.length) {
          const empty = document.createElement('p');
          empty.className = 'sub';
          empty.textContent = allItems.length
            ? T('当前筛选条件下没有发现的模型。', 'No discovered models match the current filters.')
            : T('Google Gemini、OpenAI、Anthropic 和 DeepSeek 的 /models 接口用于发现账号可用模型；勾选并保存各自 API Key 后点击刷新即可看到新模型列表。', 'Google Gemini, OpenAI, Anthropic, and DeepSeek /models APIs list account-visible models; enable them with your API keys and refresh to see new models.');
          body.replaceChildren(empty);
          return;
        }

        const limit = discShowAll ? filtered.length : 150;
        const visible = filtered.slice(0, limit);
        const table = document.createElement('table');
        const head = document.createElement('tr');
        for (const col of [T('来源', 'Provider'), T('模型 ID', 'Model ID'), T('参考报价 / 说明', 'Reference / Notes'), T('操作', 'Action')]) {
          const th = document.createElement('th');
          th.textContent = col;
          head.append(th);
        }
        table.append(head);

        for (const m of visible) {
          const tr = document.createElement('tr');
          const provTd = document.createElement('td');
          provTd.textContent = m.sourceName;

          const idTd = document.createElement('td');
          const idDiv = document.createElement('div');
          idDiv.className = 'mono';
          idDiv.textContent = m.id;
          idTd.append(idDiv);
          if (m.display_name && m.display_name !== m.id) {
            const nameDiv = document.createElement('div');
            nameDiv.className = 'sub';
            nameDiv.textContent = m.display_name;
            idTd.append(nameDiv);
          }
          if (m.is_new_since_last) idTd.append(makeBadge(T('新发现', 'New'), 'badge-new'), document.createTextNode(' '));
          if (m.observed) idTd.append(makeBadge(T('日志已出现', 'Observed'), 'badge-warn'), document.createTextNode(' '));
          if (m.in_catalog) idTd.append(makeBadge(T('已定价', 'Priced'), 'badge-ok'));

          const infoTd = document.createElement('td');
          if (m.openrouter_quote) {
            const q = m.openrouter_quote;
            const qText = document.createElement('div');
            qText.textContent = `OpenRouter: ${T('输入', 'In')} ${fmtUsd(q.in)} · ${T('输出', 'Out')} ${fmtUsd(q.out)}`;
            infoTd.append(qText);
          }
          if (m.detail) {
            const dText = document.createElement('div');
            dText.className = 'sub';
            dText.textContent = m.detail;
            infoTd.append(dText);
          }
          const srcLink = makeLink(m.source, T('官网说明', 'Provider docs'));
          if (srcLink) infoTd.append(srcLink);

          const actTd = document.createElement('td');
          actTd.className = 'action-cell';
          if (m.openrouter_quote) {
            const useOrBtn = document.createElement('button');
            useOrBtn.type = 'button';
            useOrBtn.className = 'btn btn-sm';
            useOrBtn.textContent = T('同步 OpenRouter 报价', 'Use OpenRouter quote');
            useOrBtn.onclick = () => action(
              { action: 'sync_quote', quote_id: m.openrouter_quote.id, target_model: m.id },
              T('已将 OpenRouter 报价同步给 ', 'Applied OpenRouter quote to ') + m.id,
              'disc-status',
            );
            actTd.append(useOrBtn);
          }
          const editBtn = document.createElement('button');
          editBtn.type = 'button';
          editBtn.className = 'btn btn-sm';
          editBtn.textContent = m.in_catalog ? T('调整价格', 'Edit price') : T('去定价', 'Set price');
          editBtn.onclick = () => prefillManualPrice(m.id);
          actTd.append(editBtn);

          const toggleBtn = document.createElement('button');
          toggleBtn.type = 'button';
          toggleBtn.className = 'btn btn-sm';
          toggleBtn.textContent = m.dismissed ? T('恢复', 'Restore') : T('忽略', 'Dismiss');
          toggleBtn.onclick = () => action(
            { action: m.dismissed ? 'restore_discovered' : 'dismiss_discovered', source: m.sourceId, model: m.id },
            m.dismissed ? T('已恢复显示：', 'Restored: ') + m.id : T('已忽略：', 'Dismissed: ') + m.id,
            'disc-status',
          );
          actTd.append(toggleBtn);

          tr.append(provTd, idTd, infoTd, actTd);
          table.append(tr);
        }

        const nodes = [table];
        if (!discShowAll && filtered.length > limit) {
          const more = document.createElement('button');
          more.type = 'button';
          more.className = 'btn';
          more.textContent = T('显示全部 ', 'Show all ') + filtered.length + T(' 条', ' rows');
          more.onclick = () => { discShowAll = true; renderDiscoveryTable(latest?.provider_sources || psNow); };
          nodes.push(more);
        }
        body.replaceChildren(...nodes);
      }

      if ($('or-search')) {
        $('or-search').oninput = () => { orQuery = $('or-search').value; orShowAll = false; renderOpenRouterTable(latest?.provider_sources || currentPs); };
      }
      if ($('or-variants')) {
        $('or-variants').onchange = () => { orShowVariants = Boolean($('or-variants').checked); orShowAll = false; renderOpenRouterTable(latest?.provider_sources || currentPs); };
      }
      if ($('disc-search')) {
        $('disc-search').oninput = () => { discQuery = $('disc-search').value; discShowAll = false; renderDiscoveryTable(latest?.provider_sources || currentPs); };
      }

      function renderUnpricedSection(psNow) {
        const items = psNow.unpriced_models || [], summary = psNow.unpriced_summary || {};
        if ($('unpriced-counts')) {
          $('unpriced-counts').textContent = items.length
            ? `${items.length} ${T('个未定价模型', 'unpriced')} · ${summary.matched || 0} ${T('个已在 OpenRouter 找到报价', 'matched on OpenRouter')}`
            : T('所有已探测模型均有价格记录', 'All detected models have prices');
        }
        if ($('unpriced-lookup')) {
          $('unpriced-lookup').disabled = Boolean(psNow.running);
          $('unpriced-lookup').onclick = () => action(
            { action: 'lookup_unpriced', force: true },
            res => T('查价完成：检测到 ', 'Lookup complete: ') + (res?.lookup?.unpriced_count ?? 0) + T(' 个未定价模型，OpenRouter 匹配到 ', ' unpriced model(s), OpenRouter matched ') + (res?.lookup?.matched?.length ?? 0) + T(' 个。', '.'),
            'unpriced-status',
          );
        }
        if ($('unpriced-sync-all')) {
          $('unpriced-sync-all').disabled = !(summary.matched > 0) || Boolean(psNow.running);
          $('unpriced-sync-all').onclick = () => action(
            { action: 'sync_matched', include_discovered: true },
            res => {
              const s = res.sync || {};
              const n = v => Array.isArray(v) ? v.length : (v || 0);
              return T('已导入未定价模型报价：更新 ', 'Imported unpriced matches: updated ') + n(s.synced) + T(' 个', '');
            },
            'unpriced-status',
          );
        }
        const body = $('unpriced-body');
        if (!body) return;
        if (!items.length) {
          const ok = document.createElement('p');
          ok.className = 'sub';
          ok.textContent = T('目前所有本地日志与已发现的模型都已有价格记录。', 'Every observed and discovered model currently has a local price record.');
          body.replaceChildren(ok);
          return;
        }
        const table = document.createElement('table');
        const head = document.createElement('tr');
        for (const col of [T('未定价模型', 'Unpriced model'), T('来源探测', 'Detected from'), T('OpenRouter 自动查价结果', 'OpenRouter lookup'), T('操作', 'Action')]) {
          const th = document.createElement('th');
          th.textContent = col;
          head.append(th);
        }
        table.append(head);
        for (const item of items.slice(0, 150)) {
          const tr = document.createElement('tr');
          const idTd = document.createElement('td');
          idTd.className = 'mono';
          idTd.textContent = item.id;
          const origTd = document.createElement('td');
          origTd.textContent = (item.sources || []).map(s => s === 'local' ? T('本机日志', 'Local log') : (psNow.sources?.[s]?.name || s)).join(' · ');
          const orTd = document.createElement('td');
          if (item.openrouter_quote) {
            const q = item.openrouter_quote;
            const line = document.createElement('div');
            line.textContent = `${q.id} · ${T('输入', 'In')} ${fmtUsd(q.in)} / ${T('输出', 'Out')} ${fmtUsd(q.out)}`;
            orTd.append(line);
          } else if (item.match_status === 'dynamic') {
            orTd.append(makeBadge(T('OpenRouter 为动态定价', 'Dynamic pricing on OpenRouter'), 'badge-warn'));
          } else if (item.checked) {
            orTd.append(makeBadge(T('OpenRouter 暂无对应固定报价', 'Not listed on OpenRouter')));
          } else {
            orTd.append(makeBadge(T('等待自动查询', 'Pending lookup')));
          }
          const actTd = document.createElement('td');
          actTd.className = 'action-cell';
          if (item.openrouter_quote) {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'btn btn-sm';
            btn.textContent = T('导入该模型报价', 'Import quote');
            btn.onclick = () => action(
              { action: 'sync_quote', quote_id: item.openrouter_quote.id, target_model: item.id },
              T('已导入渠道报价：', 'Imported channel quote: ') + item.id,
              'unpriced-status',
              res => { if (res?.model) selectedModel = res.model; },
            );
            actTd.append(btn);
          }
          const manualBtn = document.createElement('button');
          manualBtn.type = 'button';
          manualBtn.className = 'btn btn-sm';
          manualBtn.textContent = T('手动定价', 'Set price');
          manualBtn.onclick = () => prefillManualPrice(item.id);
          actTd.append(manualBtn);
          tr.append(idTd, origTd, orTd, actTd);
          table.append(tr);
        }
        body.replaceChildren(table);
      }

      renderOpenRouterTable(currentPs);
      renderUnpricedSection(currentPs);
      renderDiscoveryTable(currentPs);

      refreshSourcesView = next => {
        const nextPs = next?.provider_sources;
        if (!nextPs) return;
        const refreshBtn = $('sources-refresh');
        if (refreshBtn) {
          refreshBtn.disabled = Boolean(nextPs.running);
          refreshBtn.textContent = nextPs.running ? T('正在刷新…', 'Refreshing…') : T('立即刷新已勾选来源', 'Refresh selected now');
        }
        if ($('sources-last-checked')) {
          $('sources-last-checked').textContent = nextPs.running
            ? T('正在刷新模型来源…', 'Refreshing sources…')
            : nextPs.last_checked
              ? T('上次检查：', 'Last checked: ') + timestamp(nextPs.last_checked)
              : T('尚未检查', 'Not checked yet');
        }
        if ($('sources-next-check')) $('sources-next-check').textContent = nextSourceCheck(nextPs.schedule);
        for (const sid of (nextPs.order || [])) {
          const metaEl = $('src-meta-' + sid);
          if (metaEl && nextPs.sources?.[sid]) metaEl.innerHTML = renderSourceStatusHtml(nextPs.sources[sid]);
        }
        renderOpenRouterTable(nextPs);
        renderUnpricedSection(nextPs);
        renderDiscoveryTable(nextPs);
      };
    }

    bindAndRenderProviderSections(ps);

    $('research-agent').value = researchAgent;
    $('research-model').value = researchModel;
    $('research-scope').value = researchScope;
    $('research-scope').onchange = () => { researchScope = $('research-scope').value; };

    async function modelChoices() {
      const source = $('research-agent').value, list = $('research-model-list'), status = $('research-model-status'), reqId = ++modelRequest;
      const current = () => reqId === modelRequest && $('research-model-list') === list && $('research-agent').value === source;
      list.replaceChildren();
      status.textContent = T('正在读取该 Agent 的模型列表…', 'Loading this agent’s model list…');
      try {
        const response = await SiteAuth.fetch('/api/models?source=' + encodeURIComponent(source), { cache: 'no-store' });
        if (!response.ok) throw new Error('HTTP ' + response.status);
        const value = await response.json(), choices = [...new Set((value.data || []).map(m => m.model || m.id).filter(id => typeof id === 'string' && id))];
        if (!choices.length) throw new Error('No available models');
        if (!current()) return;
        list.replaceChildren(...choices.map(id => { const option = document.createElement('option'); option.value = id; return option; }));
        status.textContent = T('可选择该 Agent 提供的模型，也可输入自定义模型 ID。', 'Choose a model offered by this agent or enter a custom model ID.');
      } catch {
        if (current()) status.textContent = T('模型列表不可用，可留空使用 Agent 默认模型，或输入自定义模型 ID。', 'Model list unavailable. Leave blank for the agent default or enter a custom model ID.');
      }
    }

    $('research-agent').onchange = () => {
      researchAgent = $('research-agent').value;
      researchModel = '';
      $('research-model').value = '';
      modelChoices();
    };
    $('research-model').oninput = () => { researchModel = $('research-model').value.trim(); };
    modelChoices();

    const options = () => ({ agent: $('research-agent').value, research_model: $('research-model').value.trim(), scope: $('research-scope').value });
    $('view-research').onclick = () => window.QCResearch.open();
    $('research').onclick = () => action({ action: 'research', ...options() });
    $('price-schedule').onclick = () => action({ action: 'schedule', enabled: $('price-auto').checked, interval_hours: +$('price-hours').value, ...options() }, T('更新设置已保存', 'Schedule saved'));
    $('price-copy').onclick = async () => {
      const prompt = $('price-prompt'); prompt.focus?.(); prompt.select?.();
      try {
        await navigator.clipboard.writeText(prompt.value);
        $('price-status').textContent = T('提示词已复制。', 'Prompt copied.');
      } catch {
        $('price-status').textContent = T('已选中提示词，可手动复制。', 'Prompt selected. Copy it with your browser or keyboard.');
      }
    };
    $('price-import').onclick = () => {
      let parsed;
      try { parsed = JSON.parse($('price-import-json').value.trim().replace(/^\x60\x60\x60(?:json)?\s*|\s*\x60\x60\x60$/gi, '')); }
      catch { $('price-status').textContent = T('请输入有效的 JSON。', 'Enter valid JSON.'); return; }
      return action({ action: 'import', models: parsed?.models }, T('已导入。点击「应用建议」后生效。', 'Imported. Apply a suggestion to use its prices.'));
    };
    $('price-save').onclick = async () => {
      const model = modelId(), values = fields.map(([id, key]) => [key, $(id).value]);
      if (!model || fields.some(([id]) => !$(id).value || (typeof $(id).checkValidity === 'function' && !$(id).checkValidity()))) {
        $('price-edit-status').textContent = T('请填写模型 ID 和四项有效价格，不收费的项目填 0。', 'Enter a model ID and all four valid prices. Use 0 for free operations.');
        return;
      }
      selectedModel = model;
      $('price-save').disabled = true;
      await action({ action: 'save', model, prices: Object.fromEntries(values) }, T('价格已保存，正在重算费用。', 'Price saved. Recalculating estimates.'), 'price-edit-status');
      if ($('price-model-choice') === choice) $('price-save').disabled = !modelId();
    };

    function renderProposals(entries) {
      $('proposals').replaceChildren();
      $('price-proposal-count').textContent = '(' + entries.length + ')';
      if (!entries.length) $('proposals').textContent = T('暂无建议', 'No suggestions');
      for (const p of entries) {
        const card = document.createElement('article'); card.className = 'qb';
        const title = document.createElement('strong'); title.textContent = p.model;
        const info = document.createElement('p'); info.className = 'sub';
        info.textContent = `Input ${p.in} · Cache read ${p.cache_read} · Cache write ${p.cache_write} · Output ${p.out} — ${p.description}`;
        const link = makeLink(p.source, T('查看来源', 'View source'));
        const button = document.createElement('button'); button.className = 'btn'; button.type = 'button';
        button.textContent = T('应用建议', 'Apply suggestion');
        button.onclick = () => action({ action: 'apply', model: p.model });
        const dismiss = document.createElement('button'); dismiss.className = 'btn'; dismiss.type = 'button';
        dismiss.textContent = T('不应用', "Don't apply");
        dismiss.onclick = () => action({ action: 'dismiss', model: p.model }, T('建议已移除，现有价格保持不变。', 'Suggestion removed. Current prices are unchanged.'));
        card.append(title, info);
        if (link) card.append(link, document.createTextNode(' '));
        card.append(button, document.createTextNode(' '), dismiss);
        $('proposals').append(card);
      }
    }
    renderProposals(proposals);

    refreshResearch = next => {
      $('research').disabled = next.running;
      $('research').textContent = next.running ? T('正在获取…', 'Researching…') : T('调用本机 Agent 获取最新资料', 'Research latest data with local agent');
      $('price-status').textContent = researchFeedback(next) || (next.running ? '' : T('查价完成，请核对待确认建议。', 'Research completed. Review the suggestions.'));
      if (next.last_checked) $('price-last-checked').textContent = T('上次检查：', 'Last checked: ') + timestamp(next.last_checked);
      $('price-next-check').textContent = nextCheck(next.schedule);
      renderProposals(next.proposals || []);
    };
  }

  load();
  setInterval(async () => {
    if (!latest) return;
    const researchDue = latest.running || (latest.schedule?.enabled && latest.schedule.next_at * 1000 <= Date.now());
    const ps = latest.provider_sources;
    const sourcesDue = ps && (ps.running || (ps.unpriced_summary?.unchecked > 0) || (ps.schedule?.enabled && ps.schedule.next_at * 1000 <= Date.now()));
    if (!researchDue && !sourcesDue) return;
    const previous = latest;
    try {
      const next = await request();
      if (latest !== previous) return;
      latest = next;
      if (next.running !== previous.running || next.last_checked !== previous.last_checked ||
          next.schedule?.next_at !== previous.schedule?.next_at) {
        refreshResearch?.(next);
      }
      const prevPs = previous.provider_sources, nextPs = next.provider_sources;
      if (nextPs && (nextPs.running !== prevPs?.running || nextPs.last_checked !== prevPs?.last_checked ||
          nextPs.unpriced_summary?.last_lookup_at !== prevPs?.unpriced_summary?.last_lookup_at ||
          nextPs.schedule?.next_at !== prevPs?.schedule?.next_at)) {
        if (!sourceDraft.dirty) syncSourceDraft(nextPs);
        refreshSourcesView?.(next);
      }
    } catch {}
  }, 5000);
})();
