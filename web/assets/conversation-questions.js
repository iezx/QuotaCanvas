(() => {
  let requestNumber = 0;
  const container = () => document.getElementById('conversation-questions');
  const T = (zh, en) => window.QCi18n?.t ? window.QCi18n.t(zh, en) : zh;

  function clear() {
    ++requestNumber;
    const root = container();
    if (root) { root.replaceChildren(); root.hidden = true; }
  }

  function renderRequest(request, selected, generation) {
    const form = document.createElement('form');
    form.className = 'message assistant';
    const heading = document.createElement('strong');
    heading.textContent = T('助手提问', 'Assistant question');
    form.append(heading);
    const readers = [];
    for (const [index, question] of request.questions.entries()) {
      const field = document.createElement('fieldset');
      field.className = 'card grp';
      const legend = document.createElement('legend');
      legend.textContent = question.header || T('问题', 'Question');
      const prompt = document.createElement('p');
      prompt.className = 'message-body';
      prompt.textContent = question.question;
      field.append(legend, prompt);
      const options = question.options || [], choices = [];
      const input = document.createElement(question.isSecret ? 'input' : 'textarea');
      if (question.isSecret) { input.type = 'password'; input.autocomplete = 'off'; }
      input.setAttribute('aria-label', question.question);
      input.setAttribute('style', 'width:100%;box-sizing:border-box;margin-top:8px');
      input.maxLength = 40000;
      input.placeholder = T('填写答案', 'Enter your answer');
      input.hidden = options.length > 0;
      const addOption = (label, description, other = false) => {
        const wrapper = document.createElement('label');
        wrapper.className = 'row';
        const radio = document.createElement('input');
        radio.type = 'radio';
        radio.name = 'question-' + index;
        radio.value = label;
        const text = document.createElement('span');
        text.textContent = label + (description ? ' · ' + description : '');
        radio.onchange = () => { input.hidden = !other; };
        wrapper.append(radio, text);
        field.append(wrapper);
        choices.push({radio, other});
      };
      for (const option of options) addOption(option.label, option.description);
      if (options.length && question.isOther) addOption(T('其他（填写答案）', 'Other (enter your answer)'), '', true);
      field.append(input);
      form.append(field);
      readers.push(() => {
        const choice = choices.find(value => value.radio.checked);
        const value = !options.length || choice?.other ? input.value.trim() : choice?.radio.value;
        if (!value) throw new Error(T('请回答所有问题后提交', 'Answer every question before submitting'));
        return [question.id, {answers: [value]}];
      });
    }
    const submit = document.createElement('button');
    submit.className = 'btn';
    submit.type = 'submit';
    submit.textContent = T('提交答案', 'Submit answers');
    const status = document.createElement('p');
    status.className = 'sub';
    status.setAttribute('role', 'status');
    form.append(submit, status);
    form.onsubmit = async event => {
      event.preventDefault();
      if (submit.disabled || generation !== requestNumber) return;
      try {
        const answers = Object.fromEntries(readers.map(read => read()));
        submit.disabled = true;
        status.textContent = T('正在提交答案…', 'Submitting answers…');
        const response = await fetch('/api/conversation/questions', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({source: selected.source, conv_id: selected.id, request_id: request.request_id, answers}),
        });
        const data = await response.json();
        if (!response.ok || !data.answered) throw new Error(data.error || 'HTTP ' + response.status);
        if (generation !== requestNumber) return;
        status.textContent = T('答案已提交，刷新对话查看后续回复', 'Answers submitted. Refresh the conversation to see the reply.');
        for (const field of form.children) if (field.tagName.toLowerCase() === 'fieldset') field.disabled = true;
      } catch (error) {
        if (generation !== requestNumber) return;
        status.textContent = T('提交失败：', 'Could not submit: ') + error.message;
        submit.disabled = false;
      }
    };
    return form;
  }

  async function load(selected) {
    clear();
    const generation = requestNumber, root = container();
    if (!root || selected?.source !== 'codex') return;
    try {
      const response = await fetch('/api/conversation/questions?source=codex&id=' + encodeURIComponent(selected.id));
      const data = await response.json();
      if (generation !== requestNumber) return;
      if (!response.ok) throw new Error(data.error || 'HTTP ' + response.status);
      if (!Array.isArray(data.requests)) throw new Error(T('问题数据格式不正确', 'Invalid question response'));
      root.replaceChildren(...data.requests.map(request => renderRequest(request, selected, generation)));
      root.hidden = !data.requests.length;
    } catch (error) {
      if (generation !== requestNumber) return;
      root.textContent = T('读取待回答问题失败：', 'Could not read pending questions: ') + error.message;
      root.hidden = false;
    }
  }

  window.ConversationQuestions = {load, clear};
})();
