const securitySettingsReady = (async () => {
  const T = window.QCi18n.t, $ = id => document.getElementById(id);
  const card = $('security-card');
  if (!card) return;
  card.innerHTML = `<h2 id="security-heading">${T('登录保护与 IP 记录', 'Login protection and IP audit')}</h2>
    <p class="sub">${T('同一 IP 在统计窗口内达到失败次数上限后暂时封禁；正确登录会清除该 IP 的失败计数。保护设置、封禁及最近 500 条记录保存在服务器，重启后仍有效。', 'An IP is temporarily blocked after reaching the failed-attempt limit within the time window. A successful login clears its failures. Settings, blocks, and the latest 500 audit records are saved on the server and survive restarts.')}</p>
    <form id="security-form"><div class="row security-fields">
      <label for="security-max-failures">${T('失败次数上限', 'Failed-attempt limit')}<input id="security-max-failures" type="number" min="1" max="100" step="1" required disabled></label>
      <label for="security-window-seconds">${T('统计窗口（秒）', 'Time window (seconds)')}<input id="security-window-seconds" type="number" min="10" max="86400" step="1" required disabled></label>
      <label for="security-block-seconds">${T('封禁时长（秒）', 'Block duration (seconds)')}<input id="security-block-seconds" type="number" min="10" max="86400" step="1" required disabled></label>
    </div><div class="row"><button id="security-save" class="btn" type="submit" disabled>${T('保存登录保护', 'Save login protection')}</button><button id="security-refresh" class="btn" type="button">${T('刷新记录', 'Refresh records')}</button></div></form>
    <p id="security-feedback" class="sub" role="status" aria-live="polite"></p>
    <p class="sub">${T('默认：15 分钟内失败 8 次，封禁 15 分钟。分散到多个 IP 的猜测也受全局保护：60 秒内失败 120 次后冷却 5 秒，受限重试不会延长冷却。已登录的会话仍可管理设置。记录不包含密码或访问令牌。', 'Default: 8 failures in 15 minutes block an IP for 15 minutes. A global guard also limits distributed guessing: 120 failures in 60 seconds trigger a 5-second cooldown; rejected retries do not extend it. Existing sessions can still manage settings. Records contain no passwords or access tokens.')}</p>
    <h3>${T('当前封禁的 IP', 'Blocked IP addresses')}</h3><p id="security-summary" class="sub" role="status"></p>
    <div class="security-table"><table><thead><tr><th scope="col">IP</th><th scope="col">${T('失败次数', 'Failures')}</th><th scope="col">${T('解除时间', 'Block expires')}</th><th scope="col">${T('操作', 'Action')}</th></tr></thead><tbody id="security-blocked"></tbody></table></div>
    <h3>${T('登录与管理记录', 'Login and administration audit')}</h3><p id="security-audit-summary" class="sub"></p>
    <div class="security-table security-audit-table"><table><thead><tr><th scope="col">${T('时间', 'Time')}</th><th scope="col">${T('事件', 'Event')}</th><th scope="col">IP</th><th scope="col">${T('详情', 'Details')}</th></tr></thead><tbody id="security-audit"></tbody></table></div>`;

  const fields = ['max-failures', 'window-seconds', 'block-seconds'];
  const events = {
    login_success: T('登录成功', 'Login succeeded'), login_failure: T('密码错误', 'Incorrect password'),
    login_blocked: T('登录已受限', 'Login rejected'), ip_blocked: T('IP 已封禁', 'IP blocked'),
    ip_unblocked: T('管理员解除封禁', 'IP unblocked by administrator'), policy_updated: T('保护设置已修改', 'Protection settings changed'),
    block_expired: T('封禁已到期', 'Block expired'), global_blocked: T('全局登录冷却', 'Global login cooldown'),
  };
  const reasons = {ip: T('IP 封禁', 'IP block'), global: T('全局冷却', 'Global cooldown'),
    capacity: T('封禁记录已满', 'Block capacity reached'), policy: T('保护设置', 'Protection settings')};
  let state = null, busy = false, dirty = false, unblockButtons = [];

  function controls() {
    for (const field of fields) $('security-' + field).disabled = busy || !state;
    $('security-save').disabled = busy || !state;
    $('security-refresh').disabled = busy;
    for (const button of unblockButtons) button.disabled = busy;
  }

  function date(stamp) {
    const value = new Date(Number(stamp) * 1000);
    return Number.isFinite(value.getTime()) ? value.toLocaleString(window.QCi18n.english ? 'en-US' : 'zh-CN') : T('未知', 'Unknown');
  }

  function cell(row, value) {
    const td = document.createElement('td');
    td.textContent = String(value);
    row.append(td);
    return td;
  }

  function render(data, populate) {
    state = data;
    if (populate) {
      for (const field of fields) $('security-' + field).value = state.policy[field.replaceAll('-', '_')];
      dirty = false;
    }
    $('security-blocked').replaceChildren();
    unblockButtons = [];
    const blocked = state.blocked || [];
    $('security-summary').textContent = blocked.length
      ? T(`当前封禁 ${blocked.length} 个 IP。到期后自动解除，也可手动解除。`, `${blocked.length} IP address(es) blocked. Blocks expire automatically or can be removed below.`)
      : T('当前没有封禁的 IP。', 'No IP addresses are currently blocked.');
    if (state.global?.blocked_until > Date.now() / 1000) $('security-summary').textContent += ' ' + T('全局冷却至：', 'Global cooldown until: ') + date(state.global.blocked_until);
    for (const entry of blocked) {
      const row = document.createElement('tr');
      cell(row, entry.ip);
      cell(row, entry.failed_attempts);
      cell(row, date(entry.blocked_until));
      const actions = cell(row, ''), button = document.createElement('button');
      button.type = 'button'; button.className = 'btn';
      button.textContent = T('解除封禁', 'Unblock');
      button.setAttribute('aria-label', T(`解除 ${entry.ip} 的封禁`, `Unblock ${entry.ip}`));
      button.addEventListener('click', () => unblock(entry.ip));
      actions.append(button); unblockButtons.push(button);
      $('security-blocked').append(row);
    }
    $('security-audit').replaceChildren();
    const audit = state.audit || [];
    $('security-audit-summary').textContent = audit.length
      ? T(`最近 ${audit.length} 条记录，按时间倒序；最多保留 500 条。`, `Latest ${audit.length} records, newest first; up to 500 are retained.`)
      : T('暂无记录。', 'No records yet.');
    for (const entry of audit) {
      const row = document.createElement('tr'), details = [];
      cell(row, date(entry.time));
      cell(row, events[entry.event] || T('未知事件', 'Unknown event'));
      cell(row, entry.ip);
      if (entry.target_ip) details.push(T('目标 IP：', 'Target IP: ') + entry.target_ip);
      if (entry.reason) details.push(reasons[entry.reason] || T('登录保护', 'Login protection'));
      if (entry.blocked_until) details.push(T('解除时间：', 'Expires: ') + date(entry.blocked_until));
      if (entry.policy) details.push(T('次数 / 窗口秒数 / 封禁秒数：', 'Limit / window seconds / block seconds: ') + [entry.policy.max_failures, entry.policy.window_seconds, entry.policy.block_seconds].join(' / '));
      cell(row, details.join(' · '));
      $('security-audit').append(row);
    }
    controls();
  }

  async function request(body) {
    const options = {cache: 'no-store'};
    if (body) Object.assign(options, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
    const response = await SiteAuth.fetch('/api/security', options);
    let data;
    try { data = await response.json(); }
    catch { throw new Error(T('无法读取服务器返回的记录，请刷新重试。', 'Unable to read the server response. Refresh and try again.')); }
    if (!response.ok) throw new Error(data.error || T('请求失败（HTTP ', 'Request failed (HTTP ') + response.status + ')');
    return data;
  }

  async function load() {
    if (busy) return;
    busy = true; controls();
    try {
      render(await request(), !dirty);
      $('security-feedback').textContent = dirty ? T('有未保存的保护设置。', 'Protection settings have unsaved changes.') : '';
    } catch (error) { $('security-feedback').textContent = T('读取失败：', 'Unable to load: ') + error.message; }
    finally { busy = false; controls(); }
  }

  async function save(event) {
    event.preventDefault();
    if (busy || !state) return;
    busy = true; controls();
    try {
      const body = {action: 'configure'};
      for (const field of fields) body[field.replaceAll('-', '_')] = Number($('security-' + field).value);
      render(await request(body), true);
      $('security-feedback').textContent = T('登录保护已保存。已有封禁保留原解除时间。', 'Login protection saved. Existing blocks keep their expiry times.');
    } catch (error) { $('security-feedback').textContent = error.message; }
    finally { busy = false; controls(); }
  }

  async function unblock(ip) {
    if (busy || !state) return;
    busy = true; controls();
    try {
      if (!await SiteAuth.confirm(T(`解除 ${ip} 的封禁并清除其失败计数？`, `Unblock ${ip} and clear its failed attempts?`))) return;
      render(await request({action: 'unblock', ip}), false);
      $('security-feedback').textContent = T(`${ip} 已解除封禁。`, `${ip} unblocked.`);
    } catch (error) { $('security-feedback').textContent = error.message; }
    finally { busy = false; controls(); }
  }

  $('security-form').addEventListener('submit', save);
  $('security-refresh').addEventListener('click', load);
  for (const field of fields) $('security-' + field).addEventListener('input', () => {
    dirty = true;
    $('security-feedback').textContent = T('有未保存的保护设置。', 'Protection settings have unsaved changes.');
  });
  await load();
})();
