const SiteAuth = (() => {
  const originalFetch = window.fetch.bind(window);
  const $ = id => document.getElementById(id);
  let pending = null, dismissed = false, legacyToken = '';
  try { legacyToken = localStorage.tok || ''; } catch {}
  const loginDialog = document.createElement('dialog');
  loginDialog.id = 'site-login';
  loginDialog.className = 'site-dialog';
  loginDialog.setAttribute('aria-labelledby', 'auth-title');
  loginDialog.innerHTML = `<form id="auth-form"><h2 id="auth-title">登录</h2>
    <p id="auth-hint" class="hint"></p><p><a id="auth-setup-link" hidden>前往公网入口验证邮箱</a></p>
    <div id="auth-current-row" hidden><label for="auth-current">当前密码</label><input id="auth-current" type="password" autocomplete="current-password" maxlength="256"></div>
    <label id="auth-password-label" for="auth-password">密码</label><input id="auth-password" type="password" autocomplete="current-password" required maxlength="256">
    <div id="auth-repeat-row" hidden><label for="auth-repeat">再次输入新密码</label><input id="auth-repeat" type="password" autocomplete="new-password" maxlength="256"></div>
    <p id="auth-error" class="error" role="status" aria-live="polite"></p>
    <div class="dialog-actions"><button id="auth-cancel" type="button">取消</button><button id="auth-submit" class="primary" type="submit">登录</button></div></form>`;
  const confirmDialog = document.createElement('dialog');
  confirmDialog.id = 'site-confirm';
  confirmDialog.className = 'site-dialog';
  confirmDialog.setAttribute('aria-labelledby', 'confirm-title');
  confirmDialog.innerHTML = `<h2 id="confirm-title">确认操作</h2><p id="confirm-text"></p><div class="dialog-actions"><button id="confirm-no" type="button">取消</button><button id="confirm-yes" class="primary" type="button">确认</button></div>`;
  document.body.append(loginDialog, confirmDialog);

  async function request(url, body) {
    const options = {credentials: 'same-origin', cache: 'no-store', headers: {'X-UI-Language': window.QCi18n?.english ? 'en' : 'zh'}};
    if (legacyToken) options.headers['X-Token'] = legacyToken;
    if (body) Object.assign(options, {method: 'POST', headers: {...options.headers, 'Content-Type': 'application/json'}, body: JSON.stringify(body)});
    const response = await originalFetch(url, options);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '登录服务暂时不可用，请重试');
    return data;
  }

  function buttons(authenticated) {
    const fallback = $('login-fallback');
    if (fallback) fallback.hidden = authenticated;
    for (const button of document.querySelectorAll('[data-auth-login]')) {
      button.textContent = authenticated ? '退出登录' : '登录';
      button.onclick = async () => {
        try {
          if (authenticated) await logout();
          else await login();
          window.location.reload();
        } catch {}
      };
    }
  }

  function clearSecrets() {
    for (const id of ['auth-password', 'auth-repeat', 'auth-current']) $(id).value = '';
  }

  function login(change = false) {
    dismissed = false;
    if (pending) return pending;
    pending = (async () => {
      let state = await request('/api/auth/status');
      if (state.configured && state.authenticated && !change) { buttons(true); return true; }
      let mode = state.configured ? (change ? 'change' : 'login') : (state.can_setup ? 'setup' : 'bootstrap');
      return new Promise((resolve, reject) => {
        let finished = false;
        const render = () => {
          clearSecrets();
          $('auth-error').textContent = '';
          $('auth-title').textContent = {login: '登录面板', setup: '设置登录密码', change: '修改登录密码', bootstrap: '首次设置验证'}[mode];
          $('auth-submit').textContent = {login: '登录', setup: '设置并登录', change: '保存密码', bootstrap: '验证令牌'}[mode];
          $('auth-password-label').textContent = mode === 'bootstrap' ? '已有访问令牌' : mode === 'login' ? '密码' : '新密码';
          $('auth-password').autocomplete = mode === 'login' ? 'current-password' : 'new-password';
          $('auth-repeat-row').hidden = !['setup', 'change'].includes(mode);
          $('auth-current-row').hidden = mode !== 'change';
          $('auth-hint').textContent = mode === 'bootstrap'
            ? '首次设置密码，请先从公网域名通过 Cloudflare 邮箱验证；也可使用已有访问令牌完成首次验证。'
            : mode === 'setup' ? (state.access_email ? '邮箱已验证：' + state.access_email + '。' : '') + '设置一个 10–256 个字符的密码，之后可在内网和公网登录。'
            : mode === 'change' ? '修改后，其他浏览器需要使用新密码重新登录。' : '输入你设置的面板密码。';
          $('auth-setup-link').hidden = mode !== 'bootstrap' || !state.setup_url;
          if (state.setup_url) $('auth-setup-link').setAttribute('href', state.setup_url + '/settings.html');
        };
        const finish = error => {
          if (finished) return;
          finished = true;
          clearSecrets();
          loginDialog.close();
          $('auth-form').onsubmit = null;
          if (error) { dismissed = true; reject(error); }
          else { buttons(true); resolve(true); }
        };
        $('auth-cancel').onclick = () => finish(new Error('已取消登录，请点击页面上的「登录」继续'));
        loginDialog.oncancel = event => { event.preventDefault(); $('auth-cancel').onclick(); };
        $('auth-form').onsubmit = async event => {
          event.preventDefault();
          $('auth-submit').disabled = true;
          $('auth-cancel').disabled = true;
          try {
            const password = $('auth-password').value;
            if (mode === 'bootstrap') {
              legacyToken = password.trim();
              state = await request('/api/auth/status');
              if (!state.can_setup && !state.authenticated) { legacyToken = ''; throw new Error('访问令牌无效'); }
              mode = state.configured ? 'login' : 'setup';
              render();
              return;
            }
            if (mode !== 'login' && password !== $('auth-repeat').value) throw new Error('两次输入的新密码不一致');
            await request('/api/auth/' + (mode === 'change' ? 'password' : mode), {password, ...(mode === 'change' ? {current_password: $('auth-current').value} : {})});
            legacyToken = '';
            try { localStorage.removeItem('tok'); } catch {}
            finish();
          } catch (error) {
            $('auth-error').textContent = error.message || '登录失败，请重试';
            $('auth-password').value = '';
            $('auth-password').focus();
          } finally {
            $('auth-submit').disabled = false;
            $('auth-cancel').disabled = false;
          }
        };
        render();
        loginDialog.showModal();
        $('auth-password').focus();
      });
    })().finally(() => { pending = null; });
    return pending;
  }

  async function authenticatedFetch(url, options = {}) {
    const init = {...options, credentials: 'same-origin', headers: {...options.headers, 'X-UI-Language': window.QCi18n?.english ? 'en' : 'zh'}};
    if (legacyToken) init.headers['X-Token'] = legacyToken;
    let response = await originalFetch(url, init);
    if (response.status === 401) {
      if (dismissed) throw new Error('尚未登录，请点击页面上的「登录」继续');
      await login();
      delete init.headers['X-Token'];
      if (legacyToken) init.headers['X-Token'] = legacyToken;
      response = await originalFetch(url, init);
    }
    return response;
  }

  async function logout() {
    await request('/api/auth/logout', {});
    legacyToken = '';
    try { localStorage.removeItem('tok'); } catch {}
    dismissed = true;
    buttons(false);
  }

  let confirmation = null;
  function confirmAction(text) {
    if (confirmation) return Promise.resolve(false);
    $('confirm-text').textContent = text;
    confirmation = new Promise(resolve => {
      const finish = value => { confirmDialog.close(); confirmation = null; resolve(value); };
      $('confirm-no').onclick = () => finish(false);
      $('confirm-yes').onclick = () => finish(true);
      confirmDialog.oncancel = event => { event.preventDefault(); finish(false); };
      confirmDialog.showModal();
      $('confirm-no').focus();
    });
    return confirmation;
  }

  const ready = request('/api/auth/status').then(state => { buttons(state.authenticated); return state; }).catch(() => { buttons(false); return null; });
  return {fetch: authenticatedFetch, login, logout, changePassword: () => login(true), confirm: confirmAction, ready};
})();
