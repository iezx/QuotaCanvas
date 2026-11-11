(() => {
  const card = document.getElementById('quota-window-card'), T = window.QCi18n.t;
  const element = (tag, value, className = '') => {
    const node = document.createElement(tag); node.textContent = value; node.className = className; return node;
  };
  const heading = element('h2', T('额度耗尽记录', 'Quota exhaustion history')); heading.id = 'quota-window-heading';
  const note = element('p', T('仅记录服务运行时观测到的额度耗尽，离线期间可能遗漏。金额为可用日志的 USD API 等价估算，不是账单；缺失金额或模型显示不可用。已保存记录保留记录时的价格，不随之后改价重算。', 'Records exhaustion observed while the service is running; periods offline may be missing. Amounts are USD API-equivalent estimates from available logs, not bills. Missing amounts or models are unavailable. Saved records keep the prices used when recorded.'), 'sub');
  const refresh = element('button', T('刷新记录', 'Refresh history'), 'btn'); refresh.type = 'button';
  const feedback = element('p', '', 'sub'); feedback.setAttribute('role', 'status');
  const content = element('div', '', 'quota-log-table');
  card.append(heading, note, refresh, feedback, content);
  const unavailable = () => T('不可用', 'Unavailable');
  const money = value => typeof value === 'number' && Number.isFinite(value)
    ? new Intl.NumberFormat(window.QCi18n.english ? 'en-US' : 'zh-CN', {style: 'currency', currency: 'USD', maximumFractionDigits: 4}).format(value) : unavailable();
  const stamp = value => value ? new Date(value * 1000).toLocaleString(window.QCi18n.english ? 'en-US' : 'zh-CN') : unavailable();
  const duration = value => !value ? unavailable() : value % 1440 === 0 ? value / 1440 + T('天', 'd') : value % 60 === 0 ? value / 60 + T('小时', 'h') : value + T('分钟', 'm');
  function render(rows) {
    content.replaceChildren();
    if (!rows.length) { content.append(element('p', T('尚未观测到额度耗尽记录。', 'No quota exhaustion has been observed yet.'), 'sub')); return; }
    const table = document.createElement('table'), head = document.createElement('thead'), titles = document.createElement('tr');
    for (const title of [T('观测时间', 'Observed'), T('来源 / 窗口', 'Source / window'), T('重置时间', 'Reset time'), T('耗尽时 API 等价金额', 'API equivalent at exhaustion'), T('整窗额度估算', 'Full-window estimate'), T('使用的模型', 'Models used')]) {
      const cell = element('th', title); cell.scope = 'col'; titles.append(cell);
    }
    head.append(titles); table.append(head);
    const body = document.createElement('tbody'), sources = {codex: 'Codex', agy: 'Antigravity', cc: 'Claude Code'};
    for (const row of rows) {
      const line = document.createElement('tr');
      const bucket = row.bucket === 'primary' ? T('主要窗口', 'Primary window') : row.bucket === 'secondary' ? T('次要窗口', 'Secondary window') : row.bucket;
      for (const value of [stamp(row.observed_at), [sources[row.source] || row.source, row.group, bucket || row.label, duration(row.window_minutes)].filter(Boolean).join(' · '), stamp(row.resets_at), money(row.cost_used), money(row.cost_quota_total)]) line.append(element('td', value));
      const cell = document.createElement('td'), models = Array.isArray(row.models) ? row.models : [];
      if (!models.length) cell.textContent = unavailable();
      else {
        const details = document.createElement('details'); details.append(element('summary', models.length + T(' 个模型', ' models')));
        const list = document.createElement('ul');
        for (const model of models) list.append(element('li', model.model + ' · ' + money(model.cost) + ' · ' + (model.tokens ?? '—') + ' tokens · ' + (model.requests ?? '—') + T(' 次请求', ' requests')));
        details.append(list); cell.append(details);
      }
      line.append(cell); body.append(line);
    }
    table.append(body); content.append(table);
  }
  async function load() {
    refresh.disabled = true; feedback.textContent = T('正在读取记录…', 'Loading history…');
    try {
      const response = await SiteAuth.fetch('/api/quota-windows', {cache: 'no-store'}), data = await response.json();
      if (!response.ok) throw Error(data.error || 'HTTP ' + response.status);
      if (!Array.isArray(data.windows)) throw Error(T('记录格式不正确', 'Invalid history response'));
      render(data.windows); feedback.textContent = T('保留最近 500 条记录。', 'Keeps the latest 500 records.');
    } catch (error) { feedback.textContent = T('读取失败：', 'Could not load: ') + error.message; }
    finally { refresh.disabled = false; }
  }
  refresh.onclick = load;
  load();
})();
