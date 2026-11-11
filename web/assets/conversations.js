let conversationRequest = 0, messageRequest = 0;
let conversationMessages = [], messageBefore = 0, messageHasMore = false;

function renderMessages() {
  const container = $('msgs');
  const cards = conversationMessages.map(message => {
    const card = document.createElement('article');
    card.className = 'message ' + (message.role === 'user' ? 'user' : 'assistant');
    const header = document.createElement('div');
    header.className = 'message-header';
    const role = document.createElement('strong');
    role.textContent = message.role === 'user' ? '用户' : '助手';
    const timestamp = document.createElement('time');
    const date = new Date(typeof message.timestamp === 'number' ? message.timestamp * 1000 : message.timestamp);
    timestamp.textContent = message.timestamp && !Number.isNaN(date.getTime())
      ? date.toLocaleString('zh-CN', {hour12: false}) : '';
    header.append(role, timestamp);
    const body = document.createElement('div');
    body.className = 'message-body';
    body.textContent = message.text;
    card.append(header, body);
    return card;
  });
  container.replaceChildren(...cards);
  if (!cards.length) container.textContent = '暂无可显示的用户与助手消息';
}

function selectConv() {
  const selected = convs[$('conv').value];
  globalThis.ConversationQuestions?.clear();
  syncModelOpts(selected);
  $('convtitle').textContent = selected?.title || '选择对话查看记录';
  conversationMessages = [];
  messageBefore = 0;
  messageHasMore = false;
  renderMessages();
  return showMsgs();
}

async function loadConvs() {
  const request = ++conversationRequest;
  globalThis.ConversationQuestions?.clear();
  ++messageRequest;
  convs = [];
  $('conv').replaceChildren();
  $('convtitle').textContent = '选择对话查看记录';
  conversationMessages = [];
  messageHasMore = false;
  renderMessages();
  $('oldermsgs').hidden = true;
  $('refreshmsgs').disabled = true;
  $('msgstatus').textContent = '正在读取对话列表…';
  try {
    const response = await fetch('/api/conversations?source=' + encodeURIComponent($('src').value) + '&limit=100');
    if (!response.ok) throw new Error('HTTP ' + response.status);
    const data = await response.json();
    if (request !== conversationRequest) return;
    if (!Array.isArray(data)) throw new Error('对话列表格式不正确');
    convs = data;
    $('conv').replaceChildren(...convs.map((conversation, index) => {
      const option = document.createElement('option');
      option.value = String(index);
      option.textContent = '[' + conversation.source + '] ' + conversation.title.replace(/\s+/g, ' ')
        + ' · ' + fmt(conversation.updated_at);
      return option;
    }));
    await selectConv();
  } catch (error) {
    if (request === conversationRequest) $('msgstatus').textContent = '读取列表失败：' + error.message;
  }
}

async function showMsgs(earlier = false) {
  const selected = convs[$('conv').value];
  const request = ++messageRequest;
  if (!selected) {
    $('msgstatus').textContent = '暂无本机对话';
    $('refreshmsgs').disabled = true;
    $('oldermsgs').hidden = true;
    return;
  }
  if (earlier && !messageHasMore) return;
  const params = new URLSearchParams({source: selected.source, id: selected.id, page: '1', limit: '50'});
  if (earlier) params.set('before', String(messageBefore));
  const container = $('msgs');
  $('msgstatus').textContent = earlier ? '正在加载更早消息…' : '正在读取对话…';
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
    conversationMessages = earlier ? [...page.messages, ...conversationMessages] : page.messages;
    messageBefore = page.next_before;
    messageHasMore = page.has_more;
    renderMessages();
    if (!earlier) globalThis.ConversationQuestions?.load(selected);
    container.scrollTop = earlier ? oldTop + container.scrollHeight - oldHeight : container.scrollHeight;
    $('msgstatus').textContent = legacy
      ? '已加载 ' + conversationMessages.length + ' 条消息（旧版服务仅提供最近记录，重启服务后可翻阅完整历史）'
      : '已加载 ' + conversationMessages.length + ' / ' + page.total + ' 条消息';
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
