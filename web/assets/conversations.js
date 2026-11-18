let conversationRequest = 0, messageRequest = 0;
let conversationMessages = [], messageBefore = 0, messageHasMore = false, messageTotal = 0, messageLegacy = false;
let activeConvKey = '', autoRefreshTimer = null, autoRefreshUntil = 0;
const PIN_STORAGE_KEY = 'quotacanvas.pinned_conversations';
const DRAFT_STORAGE_KEY = 'quotacanvas.prompt_drafts';
const T = (zh, en) => globalThis.QCi18n?.t ? globalThis.QCi18n.t(zh, en) : zh;

function storageGet(key, fallback) {
  try {
    const raw = globalThis.localStorage?.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
}

function storageSet(key, value) {
  try { globalThis.localStorage?.setItem(key, JSON.stringify(value)); } catch {}
}

function convKey(c) { return c ? `${c.source}:${c.id}` : ''; }
function loadPins() { return new Set(storageGet(PIN_STORAGE_KEY, [])); }
function isPinned(c) { return !!c && loadPins().has(convKey(c)); }

function syncPinButton(c) {
  const btn = $('pinconv');
  if (!btn) return;
  const pinned = isPinned(c);
  btn.textContent = pinned ? T('★ 已置顶', '★ Pinned') : T('☆ 置顶', '☆ Pin');
  btn.disabled = !c;
}

function togglePin() {
  const c = convs[$('conv')?.value];
  if (!c) return;
  const pins = loadPins(), key = convKey(c);
  if (pins.has(key)) pins.delete(key); else pins.add(key);
  storageSet(PIN_STORAGE_KEY, [...pins]);
  renderConvOptions(key);
  syncPinButton(c);
}

function updatePromptCount() {
  const el = $('promptlen'), prompt = $('prompt');
  if (!el || !prompt) return;
  const len = prompt.value.length;
  el.textContent = globalThis.QCi18n?.english
    ? `${len} chars · Ctrl/Cmd + Enter to send`
    : `${len} 字 · Ctrl/Cmd + Enter 立即发送`;
}

function saveCurrentDraft(key = activeConvKey) {
  const prompt = $('prompt');
  if (!key || !prompt) return;
  const drafts = storageGet(DRAFT_STORAGE_KEY, {});
  const val = prompt.value;
  if (val.trim()) drafts[key] = val;
  else delete drafts[key];
  const keys = Object.keys(drafts);
  if (keys.length > 50) delete drafts[keys[0]];
  storageSet(DRAFT_STORAGE_KEY, drafts);
}

function loadDraftFor(c) {
  const prompt = $('prompt');
  if (!prompt) return;
  const drafts = storageGet(DRAFT_STORAGE_KEY, {});
  const key = convKey(c);
  prompt.value = (key && drafts[key]) || '';
  updatePromptCount();
}

function clearDraft(c) {
  const key = convKey(c);
  if (!key) return;
  const drafts = storageGet(DRAFT_STORAGE_KEY, {});
  delete drafts[key];
  storageSet(DRAFT_STORAGE_KEY, drafts);
}

async function copyPlainText(text, label) {
  try {
    await globalThis.navigator?.clipboard?.writeText(String(text ?? ''));
    if ($('msgstatus')) $('msgstatus').textContent = label || T('已复制到剪贴板', 'Copied to clipboard');
  } catch {
    if ($('msgstatus')) $('msgstatus').textContent = T('当前环境不支持自动复制', 'Clipboard unavailable');
  }
}

function formatTok(n) {
  const num = Number(n || 0);
  if (!num) return '';
  if (num >= 1e6) return (num / 1e6).toFixed(1) + 'M tok';
  if (num >= 1e3) return (num / 1e3).toFixed(1) + 'k tok';
  return num + ' tok';
}

function renderConvMeta(c) {
  const meta = $('convmeta');
  if (!meta) return;
  if (!c) { meta.replaceChildren(); meta.hidden = true; return; }
  meta.hidden = false;
  const pills = [];
  const makePill = (text, title, onClick) => {
    const el = document.createElement(onClick ? 'button' : 'span');
    el.className = 'meta-pill';
    if (onClick) { el.type = 'button'; el.onclick = onClick; }
    if (title) el.title = title;
    el.textContent = text;
    pills.push(el);
  };
  makePill((c.source_name || c.source).toUpperCase());
  if (c.model) makePill(T('模型: ', 'Model: ') + c.model);
  if (c.cwd) makePill('📁 ' + c.cwd, T('点击复制工作目录', 'Click to copy working directory'), () => copyPlainText(c.cwd, T('已复制工作目录', 'Copied working directory')));
  makePill('ID: ' + String(c.id).slice(0, 12), T('点击复制完整对话 ID: ', 'Click to copy full ID: ') + c.id, () => copyPlainText(c.id, T('已复制对话 ID', 'Copied conversation ID')));
  const loadedTokens = conversationMessages.reduce((s, m) => s + Number(m.tokens || 0), 0);
  const tokValue = loadedTokens || Number(c.tokens_used || 0);
  if (tokValue) makePill(formatTok(tokValue));
  if (c.updated_at) makePill(T('更新: ', 'Updated: ') + fmt(c.updated_at));
  meta.replaceChildren(...pills);
}

function populateCwdHistory() {
  const list = $('cwd-list');
  if (!list) return;
  const seen = new Set(), options = [];
  for (const c of convs) {
    if (!c?.cwd || seen.has(c.cwd)) continue;
    seen.add(c.cwd);
    const opt = document.createElement('option');
    opt.value = c.cwd;
    options.push(opt);
  }
  list.replaceChildren(...options);
}

function formatMessageTime(ts) {
  if (!ts) return '';
  const date = new Date(typeof ts === 'number' ? ts * 1000 : ts);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleString(globalThis.QCi18n?.english ? 'en-US' : 'zh-CN', {hour12: false});
}

function updateMessageStatus() {
  const statusEl = $('msgstatus');
  if (!statusEl) return;
  if (messageLegacy) {
    statusEl.textContent = '已加载 ' + conversationMessages.length + ' 条消息（旧版服务仅提供最近记录，重启服务后可翻阅完整历史）';
    return;
  }
  const query = ($('msgsearch')?.value || '').trim().toLowerCase();
  const roleFilter = $('msgrole')?.value || 'all';
  const totalShown = filteredMessages().length;
  if (query || roleFilter !== 'all') {
    statusEl.textContent = globalThis.QCi18n?.english
      ? `Showing ${totalShown} matching of ${conversationMessages.length} loaded (${messageTotal} total)`
      : `当前筛选 ${totalShown} 条 · 已加载 ${conversationMessages.length} / ${messageTotal} 条消息`;
    return;
  }
  statusEl.textContent = '已加载 ' + conversationMessages.length + ' / ' + messageTotal + ' 条消息';
}

function filteredMessages() {
  const query = ($('msgsearch')?.value || '').trim().toLowerCase();
  const roleFilter = $('msgrole')?.value || 'all';
  return conversationMessages.filter(m => {
    if (roleFilter === 'user' && m.role !== 'user') return false;
    if (roleFilter === 'assistant' && m.role !== 'assistant') return false;
    if (roleFilter === 'tools' && (!Array.isArray(m.tools) || !m.tools.length)) return false;
    if (!query) return true;
    const hay = (String(m.text || '') + ' ' + String(m.model || '') + ' ' + (Array.isArray(m.tools) ? m.tools.join(' ') : '')).toLowerCase();
    return hay.includes(query);
  });
}

function renderMessages() {
  const container = $('msgs');
  const visible = filteredMessages();
  const cards = visible.map(message => {
    const card = document.createElement('article');
    card.className = 'message ' + (message.role === 'user' ? 'user' : 'assistant');
    const header = document.createElement('div');
    header.className = 'message-header';
    const left = document.createElement('div');
    left.className = 'message-meta';
    const role = document.createElement('strong');
    role.textContent = message.role === 'user' ? T('用户', 'User') : T('助手', 'Assistant');
    const timestamp = document.createElement('time');
    timestamp.textContent = formatMessageTime(message.timestamp);
    left.append(role, timestamp);
    if (message.model) {
      const mTag = document.createElement('span');
      mTag.className = 'tag';
      mTag.textContent = message.model;
      left.append(mTag);
    }
    if (message.tokens) {
      const tTag = document.createElement('span');
      tTag.className = 'tag';
      tTag.textContent = formatTok(message.tokens);
      left.append(tTag);
    }
    if (Array.isArray(message.tools) && message.tools.length) {
      const toolTag = document.createElement('span');
      toolTag.className = 'tag';
      toolTag.textContent = '🔧 ' + message.tools.slice(0, 6).join(', ') + (message.tools.length > 6 ? ` +${message.tools.length - 6}` : '');
      left.append(toolTag);
    }
    const actions = document.createElement('div');
    actions.className = 'message-actions';
    const copyBtn = document.createElement('button');
    copyBtn.type = 'button';
    copyBtn.className = 'msg-btn';
    copyBtn.textContent = T('复制', 'Copy');
    copyBtn.onclick = () => copyPlainText(message.text, T('已复制该条消息', 'Message copied'));
    const quoteBtn = document.createElement('button');
    quoteBtn.type = 'button';
    quoteBtn.className = 'msg-btn';
    quoteBtn.textContent = T('引用', 'Quote');
    quoteBtn.onclick = () => {
      const prompt = $('prompt');
      if (!prompt) return;
      const snippet = String(message.text || '').trim().slice(0, 400).split('\n').map(l => '> ' + l).join('\n');
      prompt.value = (prompt.value ? prompt.value.trimEnd() + '\n\n' : '') + snippet + '\n\n';
      updatePromptCount();
      saveCurrentDraft();
      prompt.focus();
    };
    actions.append(copyBtn, quoteBtn);
    header.append(left, actions);
    const body = document.createElement('div');
    body.className = 'message-body';
    body.textContent = message.text;
    card.append(header, body);
    return card;
  });
  container.replaceChildren(...cards);
  if (!cards.length) {
    container.textContent = conversationMessages.length
      ? T('没有匹配当前筛选条件的消息', 'No messages match the current filter')
      : T('暂无可显示的用户与助手消息', 'No user or assistant messages');
  }
  if (conversationMessages.length) updateMessageStatus();
  renderConvMeta(convs[$('conv')?.value]);
}

function scrollMsgs(toBottom = true) {
  const container = $('msgs');
  if (!container) return;
  container.scrollTop = toBottom ? container.scrollHeight : 0;
}

function buildMarkdownTranscript() {
  const c = convs[$('conv')?.value];
  const header = [
    '# ' + (c?.title || 'Conversation'),
    '',
    c ? `- Source: ${c.source}\n- ID: ${c.id}\n- CWD: ${c.cwd || '-'}\n- Model: ${c.model || '-'}` : '',
    '',
  ].join('\n');
  const body = conversationMessages.map(m => {
    const role = m.role === 'user' ? 'User' : 'Assistant';
    const meta = [formatMessageTime(m.timestamp), m.model, m.tokens ? formatTok(m.tokens) : ''].filter(Boolean).join(' · ');
    return `## ${role}${meta ? ` (${meta})` : ''}\n\n${m.text}\n`;
  }).join('\n---\n\n');
  return header + body;
}

function copyConversation() {
  if (!conversationMessages.length) return;
  copyPlainText(buildMarkdownTranscript(), T('已复制完整对话 Markdown', 'Copied full conversation Markdown'));
}

function exportConversation() {
  if (!conversationMessages.length || typeof globalThis.Blob !== 'function') return;
  const c = convs[$('conv')?.value];
  const blob = new globalThis.Blob([buildMarkdownTranscript()], {type: 'text/markdown;charset=utf-8'});
  const url = globalThis.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `conversation-${c?.source || 'log'}-${String(c?.id || 'export').slice(0, 16)}.md`;
  a.click();
  setTimeout(() => globalThis.URL.revokeObjectURL(url), 1500);
}

function renderConvOptions(preferredKey = '') {
  const select = $('conv');
  if (!select) return;
  const filter = ($('convfilter')?.value || '').trim().toLowerCase();
  const pins = loadPins();
  const prevKey = preferredKey || convKey(convs[select.value]);
  const indices = convs.map((_, i) => i).filter(i => {
    if (!filter) return true;
    const c = convs[i];
    const hay = `${c.source} ${c.id} ${c.title || ''} ${c.cwd || ''} ${c.model || ''}`.toLowerCase();
    return hay.includes(filter);
  });
  indices.sort((a, b) => {
    const pa = pins.has(convKey(convs[a])) ? 1 : 0;
    const pb = pins.has(convKey(convs[b])) ? 1 : 0;
    return pb - pa || (Number(convs[b]?.updated_at || 0) - Number(convs[a]?.updated_at || 0)) || a - b;
  });
  const options = indices.map(index => {
    const conversation = convs[index];
    const option = document.createElement('option');
    option.value = String(index);
    const pinPrefix = pins.has(convKey(conversation)) ? '★ ' : '';
    option.textContent = pinPrefix + '[' + conversation.source + '] ' + String(conversation.title || '').replace(/\s+/g, ' ')
      + ' · ' + fmt(conversation.updated_at);
    return option;
  });
  select.replaceChildren(...options);
  if (prevKey) {
    const match = indices.find(i => convKey(convs[i]) === prevKey);
    if (match !== undefined) select.value = String(match);
  }
}

function syncAutoRefresh() {
  if (autoRefreshTimer) { clearInterval(autoRefreshTimer); autoRefreshTimer = null; }
  if (!$('msgauto')?.checked) return;
  autoRefreshTimer = setInterval(() => {
    if (autoRefreshUntil && Date.now() > autoRefreshUntil) {
      if ($('msgauto')) $('msgauto').checked = false;
      autoRefreshUntil = 0;
      clearInterval(autoRefreshTimer);
      autoRefreshTimer = null;
      return;
    }
    if (convs[$('conv')?.value]) showMsgs(false, true);
  }, 5000);
}

function enableAutoRefreshBrief() {
  if (!$('msgauto')) return;
  $('msgauto').checked = true;
  autoRefreshUntil = Date.now() + 90000;
  syncAutoRefresh();
}

function selectConv() {
  if (activeConvKey) saveCurrentDraft(activeConvKey);
  const selected = convs[$('conv').value];
  activeConvKey = convKey(selected);
  globalThis.ConversationQuestions?.clear();
  syncModelOpts(selected);
  syncPinButton(selected);
  if ($('ccwd')) {
    $('ccwd').value = '';
    $('ccwd').placeholder = selected?.cwd || T('默认跟随对话工作目录', 'Default: conversation CWD');
  }
  loadDraftFor(selected);
  $('convtitle').textContent = selected?.title || '选择对话查看记录';
  conversationMessages = [];
  messageBefore = 0;
  messageHasMore = false;
  messageTotal = 0;
  messageLegacy = false;
  renderMessages();
  return showMsgs();
}

async function loadConvs() {
  const request = ++conversationRequest;
  globalThis.ConversationQuestions?.clear();
  ++messageRequest;
  const previousKey = activeConvKey || convKey(convs[$('conv')?.value]);
  convs = [];
  $('conv').replaceChildren();
  $('convtitle').textContent = '选择对话查看记录';
  conversationMessages = [];
  messageHasMore = false;
  messageTotal = 0;
  messageLegacy = false;
  renderMessages();
  syncPinButton(null);
  $('oldermsgs').hidden = true;
  $('refreshmsgs').disabled = true;
  $('msgstatus').textContent = '正在读取对话列表…';
  try {
    const subFlag = $('subthreads')?.checked ? '&sub=1' : '';
    const response = await fetch('/api/conversations?source=' + encodeURIComponent($('src').value) + '&limit=150' + subFlag);
    if (!response.ok) throw new Error('HTTP ' + response.status);
    const data = await response.json();
    if (request !== conversationRequest) return;
    if (!Array.isArray(data)) throw new Error('对话列表格式不正确');
    convs = data;
    populateCwdHistory();
    renderConvOptions(previousKey);
    await selectConv();
  } catch (error) {
    if (request === conversationRequest) $('msgstatus').textContent = '读取列表失败：' + error.message;
  }
}

async function showMsgs(earlier = false, quiet = false) {
  const selected = convs[$('conv').value];
  const request = ++messageRequest;
  if (!selected) {
    $('msgstatus').textContent = '暂无本机对话';
    $('refreshmsgs').disabled = true;
    $('oldermsgs').hidden = true;
    renderConvMeta(null);
    return;
  }
  if (earlier && !messageHasMore) return;
  const params = new URLSearchParams({source: selected.source, id: selected.id, page: '1', limit: '50'});
  if (earlier) params.set('before', String(messageBefore));
  const container = $('msgs');
  if (!quiet) $('msgstatus').textContent = earlier ? '正在加载更早消息…' : '正在读取对话…';
  $('refreshmsgs').disabled = true;
  $('oldermsgs').disabled = true;
  try {
    const response = await fetch('/api/conversation?' + params);
    if (!response.ok) throw new Error('HTTP ' + response.status);
    const data = await response.json();
    if (request !== messageRequest) return;
    const legacy = Array.isArray(data);
    const page = legacy ? {messages: data, total: data.length, next_before: 0, has_more: false} : data;
    if (!page || !Array.isArray(page.messages)) throw new Error('对话数据格式不正确');
    const oldHeight = container.scrollHeight, oldTop = container.scrollTop;
    const atBottom = (oldHeight - oldTop - (container.clientHeight || 0)) < 80;
    conversationMessages = earlier ? [...page.messages, ...conversationMessages] : page.messages;
    messageBefore = page.next_before;
    messageHasMore = page.has_more;
    messageTotal = page.total;
    messageLegacy = legacy;
    renderMessages();
    if (!earlier && !quiet) globalThis.ConversationQuestions?.load(selected);
    if (earlier) container.scrollTop = oldTop + container.scrollHeight - oldHeight;
    else if (!quiet || atBottom) container.scrollTop = container.scrollHeight;
    updateMessageStatus();
    $('oldermsgs').hidden = !messageHasMore;
  } catch (error) {
    if (request === messageRequest) $('msgstatus').textContent = '读取对话失败：' + error.message;
  } finally {
    if (request === messageRequest) {
      $('refreshmsgs').disabled = false;
      $('oldermsgs').disabled = false;
    }
  }
}
