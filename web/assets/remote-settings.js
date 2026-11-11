const remoteSettingsReady = (async () => {
  const $ = id => document.getElementById(id);
  const L = value => typeof window !== 'undefined' && window.QCi18n ? window.QCi18n.text(value) : value;
  const phases = {disabled: '已停用', checking: '检查中', ready: '已就绪 · 可启用', configuring: '配置中', starting: '连接器启动中 · 等待连接', connected: '隧道已连接', paused: '等待手动连接', error: '发生错误'};
  const active = () => ['checking', 'configuring'].includes(state?.phase);
  let state = null, busy = false, dirty = false, timer;

  function controls() {
    const locked = busy || active() || !!state?.enabled;
    for (const id of ['hostname', 'allowed-emails', 'api-token', 'save']) $(id).disabled = locked || !state;
    const configured = state?.hostname && state?.allowed_emails?.length && state?.api_token_saved;
    $('check').disabled = locked || dirty || !configured;
    $('enable').disabled = busy || active() || dirty || !configured || (state?.enabled && !state.can_resume);
    $('enable').textContent = L(state?.can_resume ? '启动连接' : '启用');
    $('tunnel-auto-start').disabled = $('tunnel-auto-save').disabled = busy || active() || !state;
    $('disable').disabled = busy || active() || !state?.enabled;
    $('refresh').disabled = busy;
  }

  function poll() {
    clearTimeout(timer);
    if (active() || state?.enabled) timer = setTimeout(() => load(false), active() || state?.phase === 'starting' ? 1500 : 15000);
  }

  function render(data, populate) {
    state = data;
    if (populate) $('tunnel-auto-start').checked = state.auto_start !== false;
    $('phase').textContent = L(phases[state.phase] || '未知状态');
    $('message').textContent = L(state.message || '服务器未提供状态说明');
    $('token-state').textContent = L(state.api_token_saved ? 'API Token 已保存；留空保留，填写可替换。' : '尚未保存 API Token。');
    $('details').textContent = [
      state.zone_name && 'Zone: ' + state.zone_name,
      state.account_name && 'Account: ' + state.account_name,
      L(state.cloudflared_available ? 'cloudflared 已安装' : 'cloudflared 未安装；启用前需在服务器安装'),
      L(state.local_only ? '隧道连接本机回环地址' : '尚未启用隧道监听保护'),
      state.lan_url && L('内网入口：') + state.lan_url,
    ].filter(Boolean).join(' · ');
    const host = String(state.hostname || '');
    const validHost = host.length <= 253 && host.includes('.') && /[a-z]/i.test(host.split('.').at(-1)) &&
      host.split('.').every(label => /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/i.test(label));
    const safeURL = validHost && (state.public_url === 'https://' + host || state.public_url === 'https://' + host + '/');
    $('public-link').hidden = !safeURL;
    $('public-link').removeAttribute('href');
    $('public-link').textContent = safeURL ? state.public_url : '';
    if (safeURL) $('public-link').setAttribute('href', state.public_url);
    if (populate) {
      $('hostname').value = state.hostname || '';
      $('allowed-emails').value = (state.allowed_emails || []).join('\n');
      $('api-token').value = '';
      dirty = false;
    }
    controls();
    poll();
  }

  async function request(body) {
    const options = {cache: 'no-store', headers: {}};
    if (body) Object.assign(options, {method: 'POST', headers: {...options.headers, 'Content-Type': 'application/json'}, body: JSON.stringify(body)});
    const response = await SiteAuth.fetch('/api/remote-access', options);
    let data;
    try { data = await response.json(); }
    catch { throw new Error('服务器返回了无法读取的状态，请刷新重试。'); }
    if (!response.ok) throw new Error(response.status === 401 ? '请登录后重试。' : String(data.error || data.message || '请求失败（HTTP ' + response.status + '）'));
    return data;
  }

  async function load(populate) {
    if (busy) return;
    clearTimeout(timer);
    busy = true;
    controls();
    try {
      render(await request(), populate);
      $('feedback').textContent = dirty ? '有未保存的修改；请先保存再检查或启用。' : '';
    } catch (error) {
      $('phase').textContent = '状态未知';
      $('feedback').textContent = '读取状态失败：' + (error.message || '请检查连接后刷新。');
      if (!$('public-link').hidden) $('feedback').textContent += ' 可从上方公网地址重试；已配置的内网入口也会保留。';
      poll();
    } finally { busy = false; controls(); }
  }

  async function action(name) {
    if (busy || active()) return;
    if (name === 'disable' && !await SiteAuth.confirm('停用将中断此公网地址的访问，包括当前通过公网打开的页面。确认停用？')) return;
    busy = true;
    clearTimeout(timer);
    controls();
    $('feedback').textContent = '正在提交…';
    const body = {action: name};
    if (name === 'auto_start') body.enabled = $('tunnel-auto-start').checked;
    if (name === 'save') Object.assign(body, {
      hostname: $('hostname').value.trim(),
      allowed_emails: $('allowed-emails').value.split(/[\s,;，；]+/).filter(Boolean),
      api_token: $('api-token').value.trim(),
    });
    try {
      render(await request(body), name === 'save');
      $('feedback').textContent = L(name === 'save' ? '已保存；保存不会启用远程访问。' :
        name === 'auto_start' ? '启动设置已保存。' : '');
    } catch (error) {
      $('feedback').textContent = error instanceof TypeError ? '请求失败，请检查连接后刷新状态。' : error.message;
      poll();
    } finally { busy = false; controls(); }
  }

  $('remote-form').addEventListener('submit', event => { event.preventDefault(); return action('save'); });
  $('change-password').addEventListener('click', async () => {
    try { await SiteAuth.changePassword(); $('password-feedback').textContent = '密码已保存，可以在内网和公网使用。'; await load(!dirty); }
    catch (error) { $('password-feedback').textContent = error.message; }
  });
  for (const name of ['check', 'enable', 'disable']) $(name).addEventListener('click', () => action(name));
  $('refresh').addEventListener('click', () => load(!dirty));
  $('tunnel-auto-save').addEventListener('click', () => action('auto_start'));
  for (const id of ['hostname', 'allowed-emails', 'api-token']) $(id).addEventListener('input', () => {
    dirty = true;
    $('feedback').textContent = '有未保存的修改；请先保存再检查或启用。';
    controls();
  });
  await load(true);
})();
