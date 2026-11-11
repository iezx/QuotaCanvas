// QuotaCanvas first-party overview. Rebuild with npm ci and python3 build_web.py.
import * as React from "react";
import * as jsxRuntime from "react/jsx-runtime";
import { createRoot } from "react-dom/client";
var Uu = 52, Wu = 864e5, Gu = [`周一`, `周二`, `周三`, `周四`, `周五`, `周六`, `周日`], Ku = { cost: `费用`, tok: `Tokens`, req: `请求` }, qu = [0, 22, 45, 70, 100], Ju = [{ name: `《战争与和平》`, tokens: 73e4 }, { name: `《悲惨世界》`, tokens: 735e3 }, { name: `《基督山伯爵》`, tokens: 595e3 }, { name: `《堂吉诃德》`, tokens: 555e3 }, { name: `《安娜·卡列尼娜》`, tokens: 455e3 }, { name: `《卡拉马佐夫兄弟》`, tokens: 455e3 }, { name: `《米德尔马契》`, tokens: 41e4 }, { name: `《尤利西斯》`, tokens: 345e3 }, { name: `《白鲸》`, tokens: 275e3 }, { name: `《罪与罚》`, tokens: 265e3 }, { name: `《简·爱》`, tokens: 24e4 }, { name: `《远大前程》`, tokens: 24e4 }, { name: `《双城记》`, tokens: 175e3 }, { name: `《傲慢与偏见》`, tokens: 165e3 }], Yu = [{ name: `《泰坦尼克号》`, minutes: 195 }, { name: `《指环王：王者归来》`, minutes: 201 }, { name: `《教父》`, minutes: 175 }, { name: `《教父2》`, minutes: 200 }, { name: `《肖申克的救赎》`, minutes: 142 }, { name: `《阿甘正传》`, minutes: 142 }, { name: `《星际穿越》`, minutes: 169 }, { name: `《盗梦空间》`, minutes: 148 }, { name: `《阿凡达》`, minutes: 162 }, { name: `《辛德勒的名单》`, minutes: 195 }, { name: `《阿拉伯的劳伦斯》`, minutes: 222 }, { name: `《七武士》`, minutes: 207 }, { name: `《美国往事》`, minutes: 229 }, { name: `《宾虚》`, minutes: 212 }, { name: `《乱世佳人》`, minutes: 221 }, { name: `《公民凯恩》`, minutes: 119 }, { name: `《绿里奇迹》`, minutes: 189 }, { name: `《角斗士》`, minutes: 155 }, { name: `《勇敢的心》`, minutes: 177 }, { name: `《黑暗骑士》`, minutes: 152 }, { name: `《2001太空漫游》`, minutes: 139 }, { name: `《现代启示录》`, minutes: 147 }, { name: `《低俗小说》`, minutes: 154 }, { name: `《霸王别姬》`, minutes: 171 }, { name: `《与狼共舞》`, minutes: 181 }, { name: `《千与千寻》`, minutes: 124 }, { name: `《卡萨布兰卡》`, minutes: 102 }], Q = (e) => e[Math.floor(Math.random() * e.length)], $ = Q(Ju), Xu = Q(Yu), Zu = (e) => new Date(e).toISOString().slice(0, 10), Qu = (e) => Date.parse(e + `T00:00:00Z`), $u = (e, t) => e?.[t], ed = (e, t) => `color-mix(in oklch, ${e} ${t}%, var(--background))`;
function QCtext(value) {
  return window.QCi18n.text(value);
}
function td(e) {
  if (window.QCi18n.english) return e == null ? `—` : Intl.NumberFormat(`en-US`, { notation: `compact`, maximumFractionDigits: 2 }).format(e);
  if (e == null) return `—`;
  for (let [t, n] of [[`亿`, 1e8], [`万`, 1e4]]) {
    let r = e / n;
    if (r >= 1) return String(Number(r.toFixed(r < 10 ? 2 : +(r < 100)))) + t;
  }
  return Math.round(e).toLocaleString(`en-US`);
}
var nd = (e) => e == null ? `—` : `$` + e.toLocaleString(`en-US`, { minimumFractionDigits: 2, maximumFractionDigits: 2 }), rd = (e) => e == null ? `—` : Math.round(e).toLocaleString(`en-US`), id = (e, t) => e === `cost` ? nd(t) : e === `tok` ? td(t) : rd(t), ad = (e) => window.QCi18n.english ? e : `${+e.slice(0, 4)}年${+e.slice(5, 7)}月${+e.slice(8)}日`, od = (e) => window.QCi18n.english ? `${Math.floor(e / 36e5)}h ${Math.round(e % 36e5 / 6e4)}m` : `${Math.floor(e / 36e5)} 小时 ${Math.round(e % 36e5 / 6e4)} 分`;
function sd(e, t, n) {
  let r = $u(e, t);
  return r ? r[n] : void 0;
}
function fmtResetTime(ts) {
  if (!ts) return `—`;
  let now = Date.now() / 1e3, diff = Math.floor(ts - now), d = new Date(ts * 1e3), pad = (n) => String(n).padStart(2, `0`), dtStr = `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  if (window.QCi18n.english) {
    if (diff <= 0) return `Reset (${dtStr})`;
    let days2 = Math.floor(diff / 86400), hours = Math.floor(diff % 86400 / 3600), minutes = Math.floor(diff % 3600 / 60);
    return `Resets in ${days2 ? days2 + `d ` : ``}${hours}h ${minutes}m (${dtStr})`;
  }
  if (diff <= 0) return `已重置 (${dtStr})`;
  let days = Math.floor(diff / 86400), rem = diff % 86400, hrs = Math.floor(rem / 3600), mins = Math.floor(rem % 3600 / 60);
  if (days > 0) return `${days}天${hrs}小时后重置 (${dtStr})`;
  if (hrs > 0) return `${hrs}小时${mins}分后重置 (${dtStr})`;
  return `${mins}分钟后重置 (${dtStr})`;
}
function useStats() {
  let [e, t] = (0, React.useState)(null), [loading, setLoading] = (0, React.useState)(false);
  let load = (force = false) => {
    setLoading(true);
    let url = force ? `/api/refresh` : `/api/stats.json`;
    fetch(url, { cache: `no-store` }).then((r) => r.ok ? r.json() : Promise.reject(r.status)).then((d) => {
      t(d);
      setLoading(false);
    }).catch(() => setLoading(false));
  };
  (0, React.useEffect)(() => {
    load(false);
    let r = setInterval(() => load(false), 6e4);
    return () => clearInterval(r);
  }, []);
  return { stats: e, loading, reload: () => load(true) };
}
function useStoredValue(e, t) {
  let [n, r] = (0, React.useState)(() => {
    try {
      return localStorage.getItem(e) ?? t;
    } catch {
      return t;
    }
  });
  return [n, (t2) => {
    r(t2);
    try {
      localStorage.setItem(e, t2);
    } catch {
    }
  }];
}
function AnimatedTokens({ value: e }) {
  let [t, n] = (0, React.useState)(0), r = (0, React.useRef)(0);
  return (0, React.useEffect)(() => {
    let t2 = r.current;
    if (t2 === e || matchMedia(`(prefers-reduced-motion: reduce)`).matches) {
      r.current = e, n(e);
      return;
    }
    let i = performance.now(), a = requestAnimationFrame(function o(s) {
      let c = Math.min((s - i) / 600, 1);
      r.current = t2 + (e - t2) * (1 - (1 - c) ** 3), n(Math.round(r.current)), c < 1 && (a = requestAnimationFrame(o));
    });
    return () => cancelAnimationFrame(a);
  }, [e]), (0, jsxRuntime.jsx)(`span`, { className: `font-mono text-2xl font-medium tracking-tight tabular-nums`, "aria-label": `Tokens 总数 ${rd(e)}`, children: rd(t) });
}
function Brand() {
  return jsxRuntime.jsxs('h1', {className: 'qc-brand', children: ['QuotaCanvas', jsxRuntime.jsx('span', {className: 'qc-version', children: 'v0.0.1'})]});
}
function Overview() {
  let { stats: e, loading, reload } = useStats(), [t, n] = useStoredValue(`ai-usage.metric`, `tok`), [r, i] = useStoredValue(`ai-usage.source`, `all`);
  if (!e) return jsxRuntime.jsxs('main', {className: 'mx-auto max-w-[1360px] px-4 pt-4 sm:px-12 sm:pt-8', children: [jsxRuntime.jsx(Brand, {}), jsxRuntime.jsx('p', {className: 'mt-12 text-sm text-muted-foreground', children: QCtext('加载中…')})]});
  let a = Object.keys(e.sources), o = t in Ku ? t : `tok`, s = r === `all` || a.includes(r) ? r : `all`, c = s === `all` ? a : [s];
  let totalTok = e.days.reduce((acc, d) => acc + c.reduce((s2, src) => s2 + ($u(d, src)?.tok ?? 0), 0), 0);
  let totalCost = e.days.reduce((acc, d) => acc + c.reduce((s2, src) => s2 + ($u(d, src)?.cost ?? 0), 0), 0);
  let genTime = e.generated ? new Date(e.generated).toLocaleTimeString(`zh-CN`, { hour12: false }) : `—`;
  return (0, jsxRuntime.jsxs)(`div`, { className: `mx-auto max-w-[1360px] px-4 pt-4 pb-12 sm:px-12 sm:pt-8 sm:pb-16`, children: [
    (0, jsxRuntime.jsxs)(`header`, { className: `mb-6 flex flex-wrap items-center justify-between gap-4`, children: [
      (0, jsxRuntime.jsxs)(`div`, { className: `flex flex-wrap items-baseline gap-4`, children: [
        jsxRuntime.jsx(Brand, {}),
        (0, jsxRuntime.jsx)(AnimatedTokens, { value: totalTok }),
        (0, jsxRuntime.jsxs)(`span`, { className: `font-mono text-sm text-muted-foreground tabular-nums`, children: [`≈ API `, nd(totalCost)] })
      ] }),
      (0, jsxRuntime.jsxs)(`div`, { className: `flex flex-wrap items-center gap-3 text-xs text-muted-foreground`, children: [
        (0, jsxRuntime.jsx)(`button`, { type: `button`, onClick: () => {
          try {
            localStorage.setItem(`quotacanvas.language`, window.QCi18n.english ? `zh` : `en`);
          } catch {
          }
          location.reload();
        }, className: `inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs text-muted-foreground hover:bg-muted hover:text-foreground`, children: window.QCi18n.english ? `中文` : `English` }),
        (0, jsxRuntime.jsx)(`a`, { href: `/live.html`, className: `inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs text-muted-foreground hover:bg-muted hover:text-foreground`, title: `额度预计 · 对话与定时发送 · API 标价`, children: `额度预计 · 对话定时 →` }),
        (0, jsxRuntime.jsx)(`a`, { href: `/pricing.html`, className: `inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs text-muted-foreground hover:bg-muted hover:text-foreground`, children: QCtext(`模型与价格`) }),
        (0, jsxRuntime.jsx)(`a`, { href: `/settings.html`, className: `inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs text-muted-foreground hover:bg-muted hover:text-foreground`, title: `Cloudflare Tunnel + Access 远程访问设置`, children: `设置` }),
        (0, jsxRuntime.jsxs)(`button`, { type: `button`, onClick: reload, className: `inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs text-muted-foreground hover:bg-muted hover:text-foreground`, title: `点击立即重新扫描日志并刷新`, children: [
          (0, jsxRuntime.jsx)(`span`, { className: `size-1.5 rounded-full`, style: { background: loading ? `#d4a72c` : `#10a37f` } }),
          loading ? `刷新中…` : `每分钟自动更新 · ${genTime}`
        ] }),
        a.length > 1 && (0, jsxRuntime.jsx)(SourceFilter, { sources: e.sources, value: s, onChange: i })
      ] })
    ] }),
    jsxRuntime.jsx(TaskOutput, { srcs: c, sources: e.sources }),
    (0, jsxRuntime.jsx)(md, { stats: e, srcs: c }),
    (0, jsxRuntime.jsx)(Qd, { stats: e, srcs: c }),
    (0, jsxRuntime.jsx)(SrcTotals, { stats: e }),
    (0, jsxRuntime.jsx)(xd, { stats: e, srcs: c }),
    (0, jsxRuntime.jsx)(Ed, { stats: e, srcs: c }),
    (0, jsxRuntime.jsx)(`div`, { className: `my-16 h-px bg-muted` }),
    (0, jsxRuntime.jsx)(Dd, { stats: e, metric: o, onMetric: n, srcs: c })
  ] });
}
function TaskOutput({ srcs, sources }) {
  const [activity, setActivity] = React.useState(null), [failed, setFailed] = React.useState(false);
  const text = (zh, en) => window.QCi18n.english ? en : zh;
  React.useEffect(() => {
    let stopped = false, timer;
    const controller = new AbortController();
    async function load() {
      try {
        if (!document.hidden) {
          const response = await fetch('/api/activity', {cache: 'no-store', signal: controller.signal});
          if (!response.ok) throw Error(response.status);
          const data = await response.json();
          if (!Array.isArray(data.tasks)) throw Error('Invalid activity data');
          if (!stopped) { setActivity(data); setFailed(false); }
        }
      } catch {
        if (!stopped) setFailed(true);
      } finally {
        if (!stopped) timer = setTimeout(load, 1000);
      }
    }
    load();
    return () => { stopped = true; clearTimeout(timer); controller.abort(); };
  }, []);
  const tasks = (activity?.tasks || []).filter(task => srcs.includes(task.source));
  const states = {running: text('进行中', 'Running'), waiting: text('等待新输出', 'Waiting for output'), completed: text('已完成', 'Completed'), stopped: text('已停止', 'Stopped')};
  return jsxRuntime.jsxs('section', {className: 'mb-8 rounded-[10px] border p-4', 'aria-label': text('当前任务输出', 'Current task output'), children: [
    jsxRuntime.jsxs('div', {className: 'mb-3 flex flex-wrap items-center justify-between gap-2', children: [
      jsxRuntime.jsx('h2', {className: 'text-sm font-semibold', children: text('当前任务输出', 'Current task output')}),
      jsxRuntime.jsx('span', {className: 'text-[11px] text-muted-foreground', children: text('近 30 秒平均 · 每秒刷新', '30-second average · refreshes every second')})
    ]}),
    failed || !activity || !tasks.length ? jsxRuntime.jsx('p', {className: 'text-xs text-muted-foreground', children: failed ? text('读取失败，正在重试…', 'Could not load activity. Retrying…') : !activity ? text('加载中…', 'Loading…') : text('暂无近期任务', 'No recent tasks')}) :
      jsxRuntime.jsx('div', {className: 'flex flex-col gap-3', children: tasks.map(task => jsxRuntime.jsxs('div', {className: 'flex flex-wrap items-center justify-between gap-x-6 gap-y-2 border-b border-muted pb-3 last:border-0', children: [
        jsxRuntime.jsxs('div', {className: 'flex min-w-0 flex-wrap items-center gap-2 text-xs', children: [
          jsxRuntime.jsx('span', {className: 'size-1.5 rounded-full', style: {background: task.status === 'running' ? sources[task.source]?.color || '#10a37f' : '#999'}}),
          jsxRuntime.jsx('span', {className: 'font-medium', children: sources[task.source]?.name || task.source}),
          jsxRuntime.jsx('span', {className: 'font-mono text-muted-foreground', children: task.model || '—'}),
          jsxRuntime.jsx('span', {className: 'font-mono text-muted-foreground', children: '#' + task.id.slice(-8)}),
          jsxRuntime.jsx('span', {className: 'text-muted-foreground', children: states[task.status] || '—'})
        ]}),
        jsxRuntime.jsxs('div', {className: 'flex items-baseline gap-4 tabular-nums', children: [
          jsxRuntime.jsxs('span', {className: 'font-mono text-lg font-medium', children: [task.tokens_per_second.toFixed(1), jsxRuntime.jsx('span', {className: 'ml-1 text-xs font-normal text-muted-foreground', children: 'tok/s'})]}),
          jsxRuntime.jsx('span', {className: 'text-xs text-muted-foreground', children: text('已记录输出 ', 'Recorded output ') + td(task.output_tokens) + ' tokens'})
        ]})
      ]}, task.source + task.id))}),
    jsxRuntime.jsx('p', {className: 'mt-3 text-[11px] text-muted-foreground', children: text('仅统计输出 tokens（含推理），不含输入与缓存。日志在响应结束后更新，包含任务等待时间，并非模型逐 token 的生成速度。', 'Output tokens only (including reasoning); input and cache tokens are excluded. Logs update after each response. The average includes task wait time and is not the model’s streaming generation speed.')})
  ]});
}
function SrcTotals({ stats: e }) {
  let rows = Object.keys(e.sources).map((src) => {
    let t = { tok: 0, in: 0, cr: 0, cw: 0, out: 0, req: 0, cost: 0 };
    for (let d of e.days) {
      let x = d[src];
      if (x) {
        t.tok += x.tok;
        t.in += x.in ?? 0;
        t.cr += x.cr ?? 0;
        t.cw += x.cw ?? 0;
        t.out += x.out ?? 0;
        t.req += x.req ?? 0;
        t.cost += x.cost ?? 0;
      }
    }
    return { src, ...t };
  });
  let cl = { tok: 0, cost: 0, by: {} };
  for (let m of e.summary.models) {
    if (/claude/i.test(m[0])) {
      cl.tok += m[1];
      cl.cost += m[3] ?? 0;
      cl.by[m[2]] = (cl.by[m[2]] ?? 0) + m[1];
    }
  }
  let cell = (label, value, sub, color) => (0, jsxRuntime.jsx)(bd, { label, value, sub, color });
  return (0, jsxRuntime.jsx)(Pd, { title: `各来源 Token 消耗`, className: `mt-12`, children: (0, jsxRuntime.jsxs)(`div`, { className: Nd, children: [
    ...rows.map((r) => (0, jsxRuntime.jsxs)(`div`, { className: `flex flex-col gap-4 rounded-[10px] border p-4`, children: [
      (0, jsxRuntime.jsxs)(`div`, { className: `flex items-center gap-2 pb-2 border-b`, children: [(0, jsxRuntime.jsx)(`span`, { className: `size-2 rounded-full`, style: { background: e.sources[r.src].color } }), (0, jsxRuntime.jsx)(`span`, { className: `text-sm font-semibold`, children: e.sources[r.src].name }), (0, jsxRuntime.jsxs)(`span`, { className: `ml-auto font-mono text-xs text-muted-foreground`, children: [`≈ API `, nd(r.cost)] })] }),
      (0, jsxRuntime.jsxs)(`div`, { className: `grid grid-cols-2 gap-x-8 gap-y-10 sm:grid-cols-3`, children: [
        cell(`总 Tokens`, td(r.tok), `${r.req.toLocaleString()} 次请求`, e.sources[r.src].color),
        cell(`输入 + 输出`, td(r.in + r.out), `输入 ${td(r.in)} · 输出 ${td(r.out)}`),
        cell(`缓存读取`, td(r.cr), `命中 ${(r.cr / Math.max(r.in + r.cr + r.cw, 1) * 100).toFixed(1)}%`)
      ] })
    ] }, r.src)),
    (0, jsxRuntime.jsxs)(`div`, { className: `flex flex-col gap-4 rounded-[10px] border p-4`, children: [
      (0, jsxRuntime.jsxs)(`div`, { className: `flex items-center gap-2 pb-2 border-b`, children: [(0, jsxRuntime.jsx)(`span`, { className: `size-2 rounded-full`, style: { background: `#d97757` } }), (0, jsxRuntime.jsx)(`span`, { className: `text-sm font-semibold`, children: `Claude 系列模型（所有来源合计）` }), (0, jsxRuntime.jsxs)(`span`, { className: `ml-auto font-mono text-xs text-muted-foreground`, children: [`≈ API `, nd(cl.cost)] })] }),
      (0, jsxRuntime.jsxs)(`div`, { className: `grid grid-cols-2 gap-x-8 gap-y-10 sm:grid-cols-3`, children: [
        cell(`Claude Tokens`, td(cl.tok), Object.entries(cl.by).map(([k, v]) => `${(e.sources[k] || { name: k }).name} ${td(v)}`).join(` · `) || `暂无用量`, `#d97757`)
      ] })
    ] })
  ] }) });
}
function QuotaBar({ label, usedPct, subLeft, subRight, costText, color, warn }) {
  let pct = Math.min(Math.max(usedPct ?? 0, 0), 100), barColor = pct >= 100 ? `#da7756` : warn ? `#d4a72c` : color;
  return (0, jsxRuntime.jsxs)(`div`, { className: `flex flex-col gap-1.5 py-2.5 border-b border-muted last:border-0`, children: [
    (0, jsxRuntime.jsxs)(`div`, { className: `flex items-center justify-between gap-2 text-xs`, children: [
      (0, jsxRuntime.jsx)(`span`, { className: `font-medium`, children: label }),
      (0, jsxRuntime.jsx)(`span`, { className: `font-mono tabular-nums text-muted-foreground`, children: QCtext(subRight) })
    ] }),
    (0, jsxRuntime.jsx)(`div`, { className: `h-2 w-full overflow-hidden rounded-full bg-muted`, children: (0, jsxRuntime.jsx)(`div`, { className: `h-full rounded-full transition-all`, style: { width: `${Math.max(pct, pct > 0 ? 2 : 0)}%`, background: barColor } }) }),
    (0, jsxRuntime.jsxs)(`div`, { className: `flex flex-wrap items-center justify-between gap-2 text-[11px] text-muted-foreground/80 tabular-nums`, children: [
      (0, jsxRuntime.jsx)(`span`, { children: QCtext(subLeft) }),
      (0, jsxRuntime.jsx)(`span`, { className: `font-medium text-foreground/80`, children: usedPct != null ? QCtext(`已用 ${pct.toFixed(1)}% · 剩余 ${(100 - pct).toFixed(1)}%`) : QCtext(`正常可用`) })
    ] }),
    costText && (0, jsxRuntime.jsxs)(`div`, { className: `flex items-center justify-between gap-2 rounded-md bg-muted/40 px-2 py-1 font-mono text-[11px] text-muted-foreground tabular-nums`, children: [
      (0, jsxRuntime.jsx)(`span`, { children: `API 额度折算与预测` }),
      (0, jsxRuntime.jsx)(`span`, { className: `text-foreground/90`, children: QCtext(costText) })
    ] })
  ] });
}
function Qd({ stats: e, srcs: t }) {
  let q = e.quotas;
  if (!q) return null;
  let showCodex = t.includes(`codex`) && q.codex, showAgy = t.includes(`agy`) && q.agy, showCc = t.includes(`cc`) && q.cc;
  if (!showCodex && !showAgy && !showCc) return null;
  let qc = q.codex, qa = q.agy;
  return (0, jsxRuntime.jsx)(Pd, { title: `实时使用额度与 API 价值预测 (Codex · Antigravity · Claude)`, className: `mt-12`, right: (0, jsxRuntime.jsx)(`span`, { className: `text-[11px] text-muted-foreground/70`, children: `数据源: 官方实时额度接口 + 本地日志 API 等价折算` }), children: (0, jsxRuntime.jsxs)(`div`, { className: Nd, children: [
    showCodex && (0, jsxRuntime.jsxs)(`div`, { className: `flex flex-col gap-2 rounded-[10px] border p-4`, children: [
      (0, jsxRuntime.jsxs)(`div`, { className: `flex flex-wrap items-center justify-between gap-2 pb-2 border-b`, children: [
        (0, jsxRuntime.jsxs)(`div`, { className: `flex items-center gap-2`, children: [
          (0, jsxRuntime.jsx)(`span`, { className: `size-2 rounded-full`, style: { background: e.sources.codex?.color ?? `#10a37f` } }),
          (0, jsxRuntime.jsx)(`span`, { className: `text-sm font-semibold`, children: `OpenAI Codex` }),
          (0, jsxRuntime.jsx)(`span`, { className: `rounded-md border bg-muted/50 px-2 py-0.5 font-mono text-[11px] text-muted-foreground`, children: (qc.plan_type || `plus`).toUpperCase() })
        ] }),
        (0, jsxRuntime.jsxs)(`span`, { className: `font-mono text-xs text-muted-foreground`, children: [qc.email || `本地账号`, ` · 默认 `, qc.default_model || `gpt-6-sol`] })
      ] }),
      ...[`primary`, `secondary`].filter((k) => qc[k]).map((k) => (0, jsxRuntime.jsx)(QuotaBar, {
        label: qc[k].label || `窗口额度 (${k === `primary` ? `Primary` : `Secondary`} Window)`,
        usedPct: qc[k].used_percent,
        subLeft: qc[k].forecast_text || (qc[k].is_reset ? `窗口已重置 (上次峰值 ${qc[k].raw_used_percent}%)` : ``),
        subRight: fmtResetTime(qc[k].resets_at),
        costText: qc[k].cost_text,
        color: e.sources.codex?.color ?? `#10a37f`,
        warn: (qc[k].used_percent ?? 0) >= 80
      }, k)),
      !qc.primary && !qc.secondary && (0, jsxRuntime.jsx)(`div`, { className: `py-2 text-xs text-muted-foreground`, children: `暂无额度窗口数据` }),
      (0, jsxRuntime.jsxs)(`div`, { className: `mt-1 flex flex-wrap items-center justify-between gap-2 text-[11px] text-muted-foreground tabular-nums`, children: [
        (0, jsxRuntime.jsxs)(`span`, { children: [`近 5h 累计: `, td(qc.window_5h?.tokens ?? 0), ` tokens`] }),
        (0, jsxRuntime.jsxs)(`span`, { children: [`订阅周期: `, qc.subscription_start || `—`, ` ~ `, qc.subscription_until || `—`] })
      ] })
    ] }),
    showAgy && (0, jsxRuntime.jsxs)(`div`, { className: `flex flex-col gap-2 rounded-[10px] border p-4`, children: [
      (0, jsxRuntime.jsxs)(`div`, { className: `flex flex-wrap items-center justify-between gap-2 pb-2 border-b`, children: [
        (0, jsxRuntime.jsxs)(`div`, { className: `flex items-center gap-2`, children: [
          (0, jsxRuntime.jsx)(`span`, { className: `size-2 rounded-full`, style: { background: e.sources.agy?.color ?? `#8b5cf6` } }),
          (0, jsxRuntime.jsx)(`span`, { className: `text-sm font-semibold`, children: `Antigravity (AGY)` }),
          (0, jsxRuntime.jsx)(`span`, { className: `rounded-md border bg-muted/50 px-2 py-0.5 font-mono text-[11px] text-muted-foreground`, children: qa.active_model || `Gemini 4 Argon` })
        ] }),
        (0, jsxRuntime.jsx)(`span`, { className: `font-mono text-xs text-muted-foreground`, children: qa.email || `本地账号` })
      ] }),
      qa.live ? (qa.live.groups || []).map((g) => (0, jsxRuntime.jsxs)(`div`, { className: `flex flex-col`, children: [
        (0, jsxRuntime.jsx)(`div`, { className: `pt-2 text-xs font-semibold`, children: g.name }),
        (0, jsxRuntime.jsx)(`div`, { className: `text-[11px] text-muted-foreground/70`, children: g.description }),
        ...g.buckets.map((b) => (0, jsxRuntime.jsx)(QuotaBar, { label: b.name.replace(` Remaining`, ``), usedPct: b.used_percent, subLeft: b.forecast_text || ``, subRight: fmtResetTime(b.resets_at), costText: b.cost_text, color: e.sources.agy?.color ?? `#8b5cf6`, warn: (b.used_percent ?? 0) >= 80 }, b.bucket_id))
      ] }, g.name)) : null,
      qa.live ? (0, jsxRuntime.jsxs)(`details`, { className: `text-[11px] text-muted-foreground`, children: [(0, jsxRuntime.jsxs)(`summary`, { className: `cursor-pointer py-1`, children: [`全部模型剩余额度 (`, qa.live.models.length, `)`] }), (0, jsxRuntime.jsx)(`div`, { className: `grid grid-cols-1 gap-x-6 sm:grid-cols-2`, children: qa.live.models.map((m) => (0, jsxRuntime.jsxs)(`div`, { className: `flex justify-between py-0.5 tabular-nums`, children: [(0, jsxRuntime.jsx)(`span`, { children: m.name }), (0, jsxRuntime.jsxs)(`span`, { children: [m.remaining_percent, `%`] })] }, m.model_id)) })] }) : null,
      qa.live ? null : (qa.models || []).map((mb) => {
        let isEx = mb.status === `exhausted`;
        let pct = isEx ? 100 : Math.min(100, Math.round((mb.window_5h_tokens || 0) / 25e6 * 100));
        return (0, jsxRuntime.jsx)(QuotaBar, {
          label: `${mb.model_name}${mb.is_current ? ` [当前模型]` : ``}`,
          usedPct: isEx ? 100 : pct,
          subLeft: `近 5h: ${td(mb.window_5h_tokens)} tokens (${rd(mb.window_5h_requests)} 次) · ≈ ${nd(mb.window_5h_cost)}`,
          subRight: isEx ? `额度冷却 · ${fmtResetTime(mb.resets_at)}` : mb.resets_at ? fmtResetTime(mb.resets_at) : `额度充足 (Available)`,
          color: e.sources.agy?.color ?? `#8b5cf6`,
          warn: isEx
        }, mb.model_id);
      }),
      (0, jsxRuntime.jsxs)(`div`, { className: `mt-1 flex flex-wrap items-center justify-between gap-2 text-[11px] text-muted-foreground tabular-nums`, children: [
        (0, jsxRuntime.jsxs)(`span`, { children: [`近 5h 合计: `, td(qa.window_5h?.tokens ?? 0), ` tokens (`, nd(qa.window_5h?.cost ?? 0), `)`] }),
        (0, jsxRuntime.jsxs)(`span`, { children: [`近 24h 合计: `, td(qa.window_24h?.tokens ?? 0), ` tokens (`, nd(qa.window_24h?.cost ?? 0), `)`] })
      ] }),
      qa.subscription_manual && (0, jsxRuntime.jsx)(`span`, { className: `text-[11px] text-muted-foreground`, children: QCtext(`订阅周期: `) + qa.subscription_start + ` ~ ` + (qa.subscription_until || `—`) })
    ] }),
    showCc && (0, jsxRuntime.jsxs)(`div`, { className: `flex flex-col gap-2 rounded-[10px] border p-4`, children: [
      (0, jsxRuntime.jsxs)(`div`, { className: `flex flex-wrap items-center justify-between gap-2 pb-2 border-b`, children: [
        (0, jsxRuntime.jsxs)(`div`, { className: `flex items-center gap-2`, children: [(0, jsxRuntime.jsx)(`span`, { className: `size-2 rounded-full`, style: { background: e.sources.cc?.color ?? `#d97757` } }), (0, jsxRuntime.jsx)(`span`, { className: `text-sm font-semibold`, children: `Claude Code` }), (0, jsxRuntime.jsx)(`span`, { className: `rounded-md border bg-muted/50 px-2 py-0.5 font-mono text-[11px] text-muted-foreground`, children: (q.cc.plan || `—`).toUpperCase() })] }),
        (0, jsxRuntime.jsx)(`span`, { className: `font-mono text-xs text-muted-foreground`, children: q.cc.error ? `额度接口: ${q.cc.error.slice(0, 40)}` : `官方实时` })
      ] }),
      ...(q.cc.buckets || []).map((b) => (0, jsxRuntime.jsx)(QuotaBar, { label: b.name, usedPct: b.used_percent, subLeft: b.forecast_text || ``, subRight: fmtResetTime(b.resets_at), costText: b.cost_text, color: e.sources.cc?.color ?? `#d97757`, warn: (b.used_percent ?? 0) >= 80 }, b.bucket_id)),
      q.cc.subscription_manual && (0, jsxRuntime.jsx)(`span`, { className: `text-[11px] text-muted-foreground`, children: QCtext(`订阅周期: `) + q.cc.subscription_start + ` ~ ` + (q.cc.subscription_until || `—`) })
    ] })
  ] }) });
}
function SourceFilter({ sources, value, onChange }) {
  return jsxRuntime.jsx("select", {
    "aria-label": QCtext("来源"),
    className: "w-44 rounded-md border bg-background px-2.5 py-1 text-xs text-foreground",
    value,
    onChange: (event) => onChange(event.target.value),
    children: [
      jsxRuntime.jsx("option", { value: "all", children: QCtext("全部来源") }, "all"),
      ...Object.entries(sources).map(([key, source]) => jsxRuntime.jsx("option", { value: key, children: source.name }, key))
    ]
  });
}
function MetricPicker({ label, value, onChange, items }) {
  return jsxRuntime.jsx("div", {
    role: "group",
    "aria-label": QCtext(label),
    className: "flex flex-wrap items-center gap-4",
    children: items.map((item) => jsxRuntime.jsx("button", {
      type: "button",
      "aria-pressed": value === item.value,
      onClick: () => onChange(item.value),
      className: "h-8 text-xs text-muted-foreground hover:text-foreground aria-pressed:text-foreground",
      children: QCtext(item.label)
    }, item.value))
  });
}
function md({ stats: e, srcs: t }) {
  let [n, r] = (0, React.useState)(null), i = (0, React.useRef)(null);
  (0, React.useEffect)(() => {
    i.current && (i.current.scrollLeft = i.current.scrollWidth);
  }, []);
  let a = (0, React.useMemo)(() => new Map(e.days.map((e2) => [e2.d, e2])), [e]), o = Qu(e.today), s = o - (new Date(o).getUTCDay() + 6) % 7 * Wu - 357 * Wu, c = e.sources[t[0]]?.color ?? `#10a37f`, l = (0, React.useMemo)(() => {
    let n2 = Array.from({ length: 364 }, (e2, n3) => {
      let r3 = Zu(s + n3 * Wu), i3 = a.get(r3), c2 = 0, l3 = false, u3 = -1, d3 = null;
      for (let e3 of t) {
        let t2 = $u(i3, e3);
        t2 && (l3 = true, c2 += t2.tok, t2.tok > u3 && (u3 = t2.tok, d3 = e3));
      }
      return { date: r3, d: i3, total: c2, has: l3, src: d3, future: s + n3 * Wu > o };
    }), r2 = n2.map((e2) => e2.total).filter((e2) => e2 > 0).sort((e2, t2) => e2 - t2), i2 = (e2) => r2[Math.min(r2.length - 1, Math.floor(e2 * r2.length))] ?? 0, [l2, u2, d2] = [i2(0.25), i2(0.5), i2(0.75)];
    return n2.map((t2) => {
      let n3 = t2.total <= 0 ? 0 : t2.total <= l2 ? 1 : t2.total <= u2 ? 2 : t2.total <= d2 ? 3 : 4, r3 = t2.src ? e.sources[t2.src].color : c, i3 = t2.future ? `transparent` : n3 === 0 ? `var(--muted)` : ed(r3, qu[n3]);
      return { ...t2, bg: i3 };
    });
  }, [e, t.join(), s]), u = n !== null && !l[n].future ? l[n] : null, d = Array.from({ length: Uu }, (e2, t2) => {
    let n2 = new Date(s + t2 * 7 * Wu).getUTCMonth();
    return n2 !== (t2 ? new Date(s + (t2 - 1) * 7 * Wu).getUTCMonth() : -1) && t2 < 51 ? `${n2 + 1}月` : ``;
  });
  return (0, jsxRuntime.jsxs)(`section`, { "aria-label": `每日用量`, children: [(0, jsxRuntime.jsx)(`div`, { ref: i, className: `overflow-x-auto min-[900px]:overflow-visible`, children: (0, jsxRuntime.jsxs)(`div`, { className: `flex min-w-[820px] flex-col gap-2 min-[900px]:min-w-0`, children: [(0, jsxRuntime.jsx)(`div`, { className: `grid h-3.5 grid-cols-[repeat(52,minmax(0,1fr))] gap-1 text-[11px] text-muted-foreground/70`, children: d.map((e2, t2) => (0, jsxRuntime.jsx)(`span`, { className: `whitespace-nowrap`, children: e2 }, t2)) }), (0, jsxRuntime.jsxs)(`div`, { className: `relative`, onMouseLeave: () => r(null), children: [(0, jsxRuntime.jsx)(`div`, { className: `grid grid-flow-col grid-cols-[repeat(52,minmax(0,1fr))] grid-rows-[repeat(7,auto)] gap-1`, children: l.map((e2, t2) => (0, jsxRuntime.jsx)(`button`, { type: `button`, disabled: e2.future, "aria-label": `${e2.date} ${e2.has ? td(e2.total) : `无记录`}`, onMouseEnter: () => r(t2), onFocus: () => r(t2), onClick: () => r(t2), className: `block aspect-square w-full rounded-[3px] outline-none focus-visible:ring-2 focus-visible:ring-foreground`, style: { background: e2.bg, boxShadow: n === t2 ? `0 0 0 2px var(--foreground)` : void 0 } }, e2.date)) }), u && (0, jsxRuntime.jsx)(hd, { stats: e, srcs: t, cell: u, index: n })] }), (0, jsxRuntime.jsxs)(`div`, { className: `mt-1 flex items-center justify-end gap-1 text-[11px] text-muted-foreground/70`, children: [(0, jsxRuntime.jsx)(`span`, { className: `mr-1`, children: `Less` }), qu.map((e2, t2) => (0, jsxRuntime.jsx)(`span`, { className: `size-2.5 rounded-[2px]`, style: { background: t2 ? ed(c, e2) : `var(--muted)` } }, t2)), (0, jsxRuntime.jsx)(`span`, { className: `ml-1`, children: `More` })] })] }) }), u && (0, jsxRuntime.jsx)(hd, { stats: e, srcs: t, cell: u, index: n, mobile: true })] });
}
function hd(e) {
  let { stats: t, srcs: n, index: r, cell: i, mobile: a } = e, { d: o } = i, s = Math.floor(r / 7), c = r % 7, l = s < 6 ? `-12%` : s > 45 ? `-88%` : `-50%`, u = n.flatMap((e2) => {
    let t2 = $u(o, e2);
    return t2 ? [{ s: e2, p: t2 }] : [];
  }), d = u.filter((e2) => e2.p.in != null), f = (e2) => d.reduce((t2, n2) => t2 + (n2.p[e2] ?? 0), 0), p = o?.q === `legacy` ? `按天存档 · 无请求数` : o?.q === `est` ? `stats-cache 估算` : ``, m = (o?.m ?? []).filter((e2) => n.includes(e2[2])).slice(0, 3), h = /* @__PURE__ */ new Map();
  for (let [e2, t2, r2] of o?.t ?? []) n.includes(r2) && h.set(e2, (h.get(e2) ?? 0) + t2);
  let g = [...h].sort((e2, t2) => t2[1] - e2[1]).slice(0, 3).map((e2) => e2[0]).join(` · `);
  return (0, jsxRuntime.jsxs)(`div`, { className: `pointer-events-none absolute z-50 flex w-80 flex-col gap-2.5 rounded-[10px] border bg-popover p-3.5 text-xs text-popover-foreground shadow-[0_12px_32px_-12px_rgb(0_0_0/0.25)] max-[899px]:static max-[899px]:mt-3 max-[899px]:w-auto max-[899px]:transform-none! ${a ? `min-[900px]:hidden` : `max-[899px]:hidden`}`, style: { left: `${(s + 0.5) / Uu * 100}%`, top: `${(c + 1) / 7 * 100}%`, transform: `translate(${l}, 10px)` }, children: [(0, jsxRuntime.jsxs)(`div`, { className: `flex items-baseline justify-between gap-2`, children: [(0, jsxRuntime.jsx)(`span`, { className: `text-[13px] font-semibold`, children: ad(i.date) }), (0, jsxRuntime.jsx)(`span`, { className: `text-muted-foreground`, children: Gu[c] })] }), (0, jsxRuntime.jsxs)(`div`, { className: `flex items-baseline gap-2`, children: [(0, jsxRuntime.jsx)(`span`, { className: `font-mono text-[22px] font-medium tracking-tight`, children: i.has ? td(i.total) : `无记录` }), i.has && (0, jsxRuntime.jsx)(`span`, { className: `text-muted-foreground`, children: `Tokens` })] }), p && (0, jsxRuntime.jsx)(`span`, { className: `self-start rounded-md border bg-muted/50 px-2 py-0.5 text-[11px] text-muted-foreground`, children: p }), u.length > 0 && (0, jsxRuntime.jsxs)(`div`, { className: `flex flex-col gap-1.5 border-t border-muted pt-2.5 tabular-nums`, children: [(0, jsxRuntime.jsxs)(`div`, { className: `grid grid-cols-[minmax(0,1fr)_56px_56px_40px] gap-2 text-[11px] text-muted-foreground`, children: [(0, jsxRuntime.jsx)(`span`, { children: `来源` }), (0, jsxRuntime.jsx)(`span`, { className: `text-right`, children: `费用` }), (0, jsxRuntime.jsx)(`span`, { className: `text-right`, children: `Tokens` }), (0, jsxRuntime.jsx)(`span`, { className: `text-right`, children: `请求` })] }), u.map(({ s: e2, p: n2 }) => (0, jsxRuntime.jsxs)(`div`, { className: `grid grid-cols-[minmax(0,1fr)_56px_56px_40px] items-center gap-2`, children: [(0, jsxRuntime.jsxs)(`span`, { className: `flex min-w-0 items-center gap-1.5`, children: [(0, jsxRuntime.jsx)(`span`, { className: `size-[7px] shrink-0 rounded-full`, style: { background: t.sources[e2].color } }), (0, jsxRuntime.jsx)(`span`, { className: `truncate`, children: t.sources[e2].name })] }), (0, jsxRuntime.jsx)(`span`, { className: `text-right`, children: nd(n2.cost) }), (0, jsxRuntime.jsx)(`span`, { className: `text-right`, children: td(n2.tok) }), (0, jsxRuntime.jsx)(`span`, { className: `text-right`, children: rd(n2.req) })] }, e2))] }), d.length > 0 && (0, jsxRuntime.jsx)(_d, { parts: gd.map(([e2, t2, n2]) => ({ label: e2, color: n2, value: f(t2) })) }), o && (0, jsxRuntime.jsxs)(`div`, { className: `flex flex-col gap-1 border-t border-muted pt-2.5 text-muted-foreground`, children: [m.map(([e2, t2]) => (0, jsxRuntime.jsxs)(`div`, { className: `flex justify-between gap-2`, children: [(0, jsxRuntime.jsx)(`span`, { className: `font-mono text-[11px]`, children: e2 }), (0, jsxRuntime.jsx)(`span`, { className: `tabular-nums`, children: td(t2) })] }, e2)), (0, jsxRuntime.jsxs)(`div`, { className: `flex justify-between gap-2`, children: [(0, jsxRuntime.jsx)(`span`, { children: `会话` }), (0, jsxRuntime.jsx)(`span`, { children: rd(u.reduce((e2, t2) => e2 + t2.p.ses, 0)) })] }), g && (0, jsxRuntime.jsxs)(`div`, { className: `flex justify-between gap-2`, children: [(0, jsxRuntime.jsx)(`span`, { children: `常用工具` }), (0, jsxRuntime.jsx)(`span`, { children: g })] })] })] });
}
var gd = [[`输入`, `in`, `#da7756`], [`输出`, `out`, `#7c5cd6`], [`缓存读`, `cr`, `#3aa17e`], [`缓存写`, `cw`, `#d4a72c`]];
function _d({ parts: e }) {
  let t = e.reduce((e2, t2) => e2 + t2.value, 0);
  return t <= 0 ? null : (0, jsxRuntime.jsxs)(`div`, { className: `flex flex-col gap-2`, children: [(0, jsxRuntime.jsx)(`div`, { className: `flex h-2 gap-px overflow-hidden bg-muted`, children: e.filter((e2) => e2.value > 0).map((e2) => (0, jsxRuntime.jsx)(`span`, { className: `h-full min-w-[3px]`, style: { flex: `${e2.value} 0 0`, background: e2.color } }, e2.label)) }), (0, jsxRuntime.jsx)(`div`, { className: `grid grid-cols-2 gap-x-3 gap-y-1 text-muted-foreground tabular-nums`, children: e.map((e2) => (0, jsxRuntime.jsxs)(`span`, { className: `flex items-center gap-1.5 whitespace-nowrap`, children: [(0, jsxRuntime.jsx)(`span`, { className: `size-[7px] shrink-0 rounded-full`, style: { background: e2.color } }), e2.label, ` `, td(e2.value), (0, jsxRuntime.jsx)(`span`, { className: `text-[11px] text-muted-foreground/70`, children: jd(e2.value / t) })] }, e2.label)) })] });
}
var vd = `#3b82f6`, yd = `grid grid-cols-2 gap-x-8 gap-y-10 sm:grid-cols-3 xl:grid-cols-5`;
function bd({ label: e, value: t, sub: n, color: r }) {
  return (0, jsxRuntime.jsxs)(`div`, { className: `flex min-w-0 flex-col items-center gap-2 text-center`, children: [(0, jsxRuntime.jsx)(`span`, { className: `max-w-full text-xs text-muted-foreground`, children: QCtext(e) }), (0, jsxRuntime.jsx)(`span`, { className: `text-[34px] leading-none font-medium tracking-[-0.035em] tabular-nums`, style: { color: r }, children: QCtext(t) }), (0, jsxRuntime.jsx)(`span`, { className: `max-w-full text-xs leading-snug text-muted-foreground/70`, children: QCtext(n) })] });
}
function xd({ stats: e, srcs: t }) {
  let sn = { codex: `Codex`, agy: `AGY`, cc: `Claude` }, n = e.days.filter((e2) => t.some((t2) => $u(e2, t2))), r = 0, i = 0, a = 0, o = 0, s = 0, c = 0, l = 0, u = null, d = {};
  for (let e2 of n) {
    let n2 = 0;
    for (let u2 of t) {
      let t2 = $u(e2, u2);
      t2 && (a += t2.ses, i += t2.tok, r += t2.cost ?? 0, n2 += t2.cost ?? 0, d[u2] = (d[u2] ?? 0) + (t2.cost ?? 0), t2.in != null && (o += t2.in + (t2.out ?? 0), s += t2.in, c += t2.cr ?? 0, l += t2.cw ?? 0));
    }
    (!u || n2 > u.cost) && (u = { d: e2.d, cost: n2 });
  }
  let f = n.map((e2) => e2.d), p = Math.max(f.length, 1), m = 0, h = 0, g = -1 / 0;
  for (let e2 of f) h = Qu(e2) - g === Wu ? h + 1 : 1, m = Math.max(m, h), g = Qu(e2);
  let _ = new Set(f), v = 0;
  for (let t2 = Qu(e.today); _.has(Zu(t2)); t2 -= Wu) v++;
  let y = Math.max(0, ...t.map((t2) => e.summary.longest_ms[t2] ?? 0)), b = s + c + l, x = [{ label: `API 折算费用`, value: nd(r), sub: t.length > 1 ? t.map((t2) => `${sn[t2] || e.sources[t2].name} ${nd(d[t2] ?? 0)}`).join(` · `) : `按官方 API 标价自动折算` }, { label: `Tokens`, value: td(i), sub: `平均每天 ${td(i / p)}` }, { label: `活跃天数`, value: String(f.length), sub: `始于 ${f[0] ?? `—`}` }, { label: `连续使用`, value: `${v} 天`, sub: `最长 ${m} 天` }, { label: `会话`, value: rd(a), sub: `平均每天 ${(a / p).toFixed(1)} 个` }], S = [{ label: `相当于${$.name}`, value: `${Math.round(o / $.tokens)} 本`, sub: `输入与输出共 ${td(o)} token` }, { label: `最长会话够看${Xu.name}`, value: `${(y / 6e4 / Xu.minutes).toFixed(1)} 遍`, sub: `持续 ${od(y)}` }, b ? { label: `缓存命中`, value: `${(c / b * 100).toFixed(1)}%`, sub: `只有 ${((1 - c / b) * 100).toFixed(1)}% 的输入没走缓存` } : { label: `缓存命中`, value: `—`, sub: `没有输入明细` }, { label: `最忙的一天`, value: u ? `${+u.d.slice(5, 7)}月${+u.d.slice(8)}日` : `—`, sub: `花掉 ${nd(u?.cost)}` }, { label: `日均费用`, value: nd(r / p), sub: `按 ${f.length} 个活跃日算` }];
  return (0, jsxRuntime.jsxs)(`section`, { "aria-label": `总览`, className: `mt-16 flex flex-col gap-12`, children: [(0, jsxRuntime.jsx)(`div`, { className: yd, children: x.map((e2) => (0, jsxRuntime.jsx)(bd, { ...e2 }, e2.label)) }), (0, jsxRuntime.jsx)(`div`, { className: yd, children: S.map((e2) => (0, jsxRuntime.jsx)(bd, { ...e2, color: vd }, e2.label)) })] });
}
function Sd(e, t) { let [n, r, i] = e.split(`-`).map(Number), a = new Date(Date.UTC(n, r - 1 + t + 1, 0)).getUTCDate(); return Date.UTC(n, r - 1 + t, Math.min(i, a)); }
function Cd(stats, srcs) {
  const plans = (stats.plans ?? []).filter((plan) => stats.sources[plan.source] && (!srcs || srcs.includes(plan.source))).sort((a, b) => a.from.localeCompare(b.from));
  const today = Qu(stats.today), days = new Map(stats.days.map((day) => [day.d, day])), periods = [];
  plans.forEach((plan, index) => {
    const next = plans.slice(index + 1).find((item) => item.source === plan.source);
    const expiry = Math.min(next ? Qu(next.from) : Infinity, plan.until ? Qu(plan.until) : Infinity);
    for (let month = 0; ; month++) {
      const from = Sd(plan.from, month);
      if (from > today || from >= expiry) break;
      const end = Math.min(Sd(plan.from, month + 1), expiry);
      let cost = 0;
      for (let day = from; day < end && day <= today; day += Wu) cost += $u(days.get(Zu(day)), plan.source)?.cost ?? 0;
      periods.push({ source: plan.source, name: plan.name ?? `订阅`, from, to: end - Wu, price: plan.price, cost, ongoing: end > today });
    }
  });
  return periods.sort((a, b) => a.from - b.from);
}
var wd= (e) => `×${e >= 10 ? Math.round(e) : e.toFixed(1)}`, Td = (e) => `${new Date(e).getUTCMonth() + 1}/${new Date(e).getUTCDate()}`;
function Ed({ stats: e, srcs }) {
  let t = Cd(e, srcs), n = (0, React.useRef)(null), r = (0, React.useRef)(null), [i, a] = (0, React.useState)(null);
  if ((0, React.useEffect)(() => {
    n.current && (n.current.scrollLeft = n.current.scrollWidth);
  }, [t.length]), !t.length) return null;
  let o = t.reduce((e2, t2) => e2 + t2.cost, 0), s = t.reduce((e2, t2) => e2 + t2.price, 0), c = t.slice(-12), l = Math.max(...c.map((e2) => Math.max(e2.cost, e2.price)), 1e-9), u = (e2) => e2 / l * 0.76, d = (e2) => `${u(e2) * 100}%`, f = (e2, t2) => {
    let n2 = t2.getBoundingClientRect(), i2 = r.current.getBoundingClientRect();
    a({ i: e2, x: n2.left + n2.width / 2 - i2.left, y: n2.top - i2.top + n2.height * (1 - u(c[e2].cost)) - 54 });
  }, p = i && c[i.i];
  return (0, jsxRuntime.jsxs)(`section`, { "aria-label": `订阅`, className: `mt-16 grid grid-cols-[minmax(0,1fr)] items-center gap-10 min-[900px]:grid-cols-[minmax(0,16rem)_minmax(0,1fr)]`, children: [(0, jsxRuntime.jsx)(bd, { label: `订阅回报`, value: wd(o / s), sub: `API 等价 ${nd(o)} · 已付 ${nd(s)}`, color: vd }), (0, jsxRuntime.jsxs)(`div`, { className: `flex flex-col gap-2`, children: [(0, jsxRuntime.jsxs)(`div`, { ref: r, className: `relative`, onMouseLeave: () => a(null), children: [(0, jsxRuntime.jsxs)(`div`, { ref: n, className: `overflow-x-auto`, children: [(0, jsxRuntime.jsx)(`div`, { className: `flex h-52 gap-2 border-b`, style: { minWidth: `${c.length * 4.25}rem` }, children: c.map((t2, n2) => (0, jsxRuntime.jsxs)(`div`, { onMouseEnter: (e2) => f(n2, e2.currentTarget), onClick: (e2) => f(n2, e2.currentTarget), className: `relative h-full min-w-15 flex-1 ${i?.i === n2 ? `bg-muted/60` : ``}`, children: [(0, jsxRuntime.jsx)(`div`, { className: `absolute bottom-0 left-1/2 w-[60%] max-w-10 -translate-x-1/2 rounded-t-[2px]`, style: { height: d(t2.cost), background: t2.ongoing ? `repeating-linear-gradient(135deg, ${e.sources[t2.source].color} 0 2px, transparent 2px 5px)` : e.sources[t2.source].color } }), (0, jsxRuntime.jsx)(`div`, { className: `absolute inset-x-0 border-t-2 border-dashed`, style: { bottom: d(t2.price), borderColor: vd } }), (0, jsxRuntime.jsxs)(`div`, { className: `absolute inset-x-0 flex flex-col items-center tabular-nums`, style: { bottom: `calc(${d(t2.cost)} + 6px)` }, children: [(0, jsxRuntime.jsx)(`span`, { className: `font-mono text-base font-medium`, children: wd(t2.cost / t2.price) }), (0, jsxRuntime.jsxs)(`span`, { className: `text-[11px] text-muted-foreground`, children: [`$`, Math.round(t2.cost).toLocaleString(`en-US`)] })] })] }, t2.from + t2.source)) }), (0, jsxRuntime.jsx)(`div`, { className: `mt-2 flex gap-2 text-[11px] text-muted-foreground/70`, style: { minWidth: `${c.length * 4.25}rem` }, children: c.map((e2) => (0, jsxRuntime.jsxs)(`span`, { className: `min-w-15 flex-1 text-center whitespace-nowrap`, children: [Td(e2.from), `–`, Td(e2.to), e2.ongoing && (0, jsxRuntime.jsx)(`span`, { className: `block`, children: `${e2.name} 进行中` })] }, e2.from + e2.source)) })] }), p && (0, jsxRuntime.jsxs)(`div`, { className: `pointer-events-none absolute z-50 flex w-52 flex-col gap-1.5 rounded-[10px] border bg-popover px-3 py-2.5 text-xs text-popover-foreground shadow-[0_12px_32px_-12px_rgb(0_0_0/0.25)]`, style: { left: `clamp(6rem, ${i.x}px, calc(100% - 6rem))`, top: i.y, transform: `translate(-50%, -100%)` }, children: [(0, jsxRuntime.jsxs)(`div`, { className: `flex justify-between gap-4`, children: [(0, jsxRuntime.jsxs)(`span`, { className: `font-semibold`, children: [p.name, p.ongoing && `（进行中）`] }), (0, jsxRuntime.jsxs)(`span`, { className: `text-muted-foreground`, children: [Td(p.from), `–`, Td(p.to)] })] }), (0, jsxRuntime.jsx)(`span`, { className: `font-mono text-base font-medium`, children: wd(p.cost / p.price) }), (0, jsxRuntime.jsxs)(`div`, { className: `flex justify-between gap-4 tabular-nums`, children: [(0, jsxRuntime.jsx)(`span`, { children: `API 等价` }), (0, jsxRuntime.jsx)(`span`, { children: nd(p.cost) })] }), (0, jsxRuntime.jsxs)(`div`, { className: `flex justify-between gap-4 tabular-nums`, children: [(0, jsxRuntime.jsx)(`span`, { children: `订阅` }), (0, jsxRuntime.jsx)(`span`, { children: nd(p.price) })] })] })] }), (0, jsxRuntime.jsxs)(`div`, { className: `mt-1 flex items-center justify-end gap-2 text-[11px] text-muted-foreground/70`, children: [(0, jsxRuntime.jsx)(`span`, { className: `w-5 border-t-2 border-dashed`, style: { borderColor: vd } }), [...new Set(c.map((e2) => `${e2.name} $${e2.price}/月`))].join(` · `)] })] })] });
}
function Dd({ stats: e, metric: t, onMetric: n, srcs: r }) {
  let [modelSort, setModelSort] = useStoredValue(`ai-usage.model-sort`, `tok`), costSort = modelSort === `cost`;
  let i = e.summary.models.filter((e2) => r.includes(e2[2])).sort((a2, b) => costSort ? (b[3] ?? 0) - (a2[3] ?? 0) : b[1] - a2[1]), a = i.reduce((total, m) => total + (costSort ? m[3] ?? 0 : m[1]), 0), o = (() => {
    let top = new Set(i.slice(0, Md).map((x) => x[0] + x[2]));
    for (let sc of r) {
      i.filter((x) => x[2] === sc).slice(0, 4).forEach((x) => top.add(x[0] + x[2]));
    }
    return i.filter((x) => top.has(x[0] + x[2]));
  })().map(([t2, n2, r2, mCost]) => ({ key: t2 + r2, label: t2 === `unknown` ? (window.QCi18n?.text(`日志未提供模型`) ?? `日志未提供模型`) : t2, title: e.sources[r2]?.name ? `${e.sources[r2].name} · ${t2}` : t2, value: costSort ? mCost ?? 0 : n2, text: td(n2), note: mCost != null ? `${nd(mCost)} · ${jd((costSort ? mCost : n2) / Math.max(a, 1e-9))}` : (window.QCi18n?.text(`待定价`) ?? `待定价`), color: e.sources[r2]?.color })), s = /* @__PURE__ */ new Map();
  for (let [t2, n2, i2] of e.summary.tools) r.includes(i2) && s.set(t2, (s.get(t2) ?? 0) + n2);
  let c = [...s].sort((e2, t2) => t2[1] - e2[1]), l = c.reduce((e2, t2) => e2 + t2[1], 0), u = c.slice(0, Md).map(([e2, t2]) => ({ key: e2, label: e2, value: t2, text: rd(t2), note: jd(t2 / l) })), d = e.days[0] ? Qu(e.days[0].d) : Qu(e.today), f = new Map(e.days.map((e2) => [e2.d, e2])), p = [];
  for (let n2 = d; n2 <= Qu(e.today); n2 += Wu) {
    let e2 = Zu(n2), i2 = r.flatMap((n3) => {
      let r2 = sd(f.get(e2), n3, t);
      return r2 ? [[n3, r2]] : [];
    });
    p.push({ d: e2, parts: i2, sum: i2.reduce((e3, t2) => e3 + t2[1], 0) });
  }
  return (0, jsxRuntime.jsxs)(jsxRuntime.Fragment, { children: [(0, jsxRuntime.jsx)(Pd, { title: `每日${Ku[t]}`, right: (0, jsxRuntime.jsx)(MetricPicker, { label: `度量`, value: t, onChange: (e2) => n(e2), items: Object.keys(Ku).map((e2) => ({ value: e2, label: Ku[e2] })) }), children: (0, jsxRuntime.jsx)(Ad, { stats: e, metric: t, bars: p }) }), (0, jsxRuntime.jsxs)(`div`, { className: `mt-16 ${Nd}`, children: [(0, jsxRuntime.jsx)(`section`, { "aria-label": `模型`, children: (0, jsxRuntime.jsxs)(jsxRuntime.Fragment, { children: [(0, jsxRuntime.jsxs)(`label`, { className: `mb-2 flex items-center justify-end gap-2 text-xs text-muted-foreground`, children: [QCtext(`排序`), (0, jsxRuntime.jsxs)(`select`, { id: `model-sort`, "aria-label": QCtext(`模型排序`), className: `rounded-md border bg-background px-2 py-1 text-foreground`, value: costSort ? `cost` : `tok`, onChange: (event) => setModelSort(event.target.value), children: [(0, jsxRuntime.jsx)(`option`, { value: `tok`, children: QCtext(`按 Tokens 排序`) }), (0, jsxRuntime.jsx)(`option`, { value: `cost`, children: QCtext(`按费用排序`) })] })] }), (0, jsxRuntime.jsx)(Id, { items: o, head: [QCtext(`模型`), `Tokens`, QCtext(`费用 / 占比`)] })] }) }), (0, jsxRuntime.jsx)(`section`, { "aria-label": `工具`, children: (0, jsxRuntime.jsx)(Id, { items: u, head: [`工具`, `次数`, `占比`] }) })] })] });
}
function Od(e) {
  let t = 10 ** Math.floor(Math.log10(e));
  return [1, 2, 5, 10].map((e2) => e2 * t).find((t2) => t2 >= e);
}
function kd(e, t) {
  return e === `cost` ? `$` + t.toLocaleString(`en-US`) : e === `tok` ? td(t) : rd(t);
}
function Ad({ stats: e, metric: t, bars: n }) {
  let [r, i] = (0, React.useState)(null), a = Od(Math.max(...n.map((e2) => e2.sum), 1e-9) / 4), o = a * Math.ceil(Math.max(...n.map((e2) => e2.sum), a) / a), s = Array.from({ length: Math.round(o / a) + 1 }, (e2, t2) => t2 * a), c = r === null ? null : n[r];
  return (0, jsxRuntime.jsxs)(`div`, { className: `flex flex-col gap-2 pl-12`, children: [(0, jsxRuntime.jsxs)(`div`, { className: `relative h-60`, onMouseLeave: () => i(null), children: [s.map((e2) => (0, jsxRuntime.jsx)(`div`, { className: `absolute inset-x-0 border-t ${e2 ? `border-dashed border-border/70` : `border-border`}`, style: { bottom: `${e2 / o * 100}%` }, children: (0, jsxRuntime.jsx)(`span`, { className: `absolute -left-12 w-10 -translate-y-1/2 text-right text-[11px] text-muted-foreground/70 tabular-nums`, children: kd(t, e2) }) }, e2)), (0, jsxRuntime.jsx)(`div`, { className: `absolute inset-0 flex items-end gap-0.5`, children: n.map((t2, n2) => (0, jsxRuntime.jsx)(`div`, { onMouseEnter: () => i(n2), className: `flex h-full min-w-0 flex-1 flex-col-reverse rounded-t-[2px] ${r === n2 ? `bg-muted` : ``}`, children: t2.parts.map(([n3, r2], i2) => (0, jsxRuntime.jsx)(`div`, { style: { height: `${r2 / o * 100}%`, background: e.sources[n3].color, borderRadius: i2 === t2.parts.length - 1 ? `2px 2px 0 0` : 0 } }, n3)) }, t2.d)) }), c && (0, jsxRuntime.jsxs)(`div`, { className: `pointer-events-none absolute z-50 flex min-w-44 flex-col gap-1.5 rounded-[10px] border bg-popover px-3 py-2.5 text-xs text-popover-foreground shadow-[0_12px_32px_-12px_rgb(0_0_0/0.25)]`, style: { left: `${(r + 0.5) / n.length * 100}%`, bottom: `calc(${c.sum / o * 100}% + 8px)`, transform: `translateX(${r < n.length * 0.15 ? `-10%` : r > n.length * 0.85 ? `-90%` : `-50%`})` }, children: [(0, jsxRuntime.jsxs)(`div`, { className: `flex justify-between gap-4`, children: [(0, jsxRuntime.jsx)(`span`, { className: `font-semibold`, children: ad(c.d) }), (0, jsxRuntime.jsx)(`span`, { className: `text-muted-foreground`, children: Gu[(new Date(Qu(c.d)).getUTCDay() + 6) % 7] })] }), (0, jsxRuntime.jsx)(`span`, { className: `font-mono text-base font-medium`, children: c.sum ? id(t, c.sum) : `无记录` }), c.parts.length > 1 && c.parts.map(([n2, r2]) => (0, jsxRuntime.jsxs)(`div`, { className: `flex items-center justify-between gap-4 tabular-nums`, children: [(0, jsxRuntime.jsxs)(`span`, { className: `inline-flex items-center gap-1.5 whitespace-nowrap`, children: [(0, jsxRuntime.jsx)(`span`, { className: `size-[7px] shrink-0 rounded-full`, style: { background: e.sources[n2].color } }), e.sources[n2].name] }), (0, jsxRuntime.jsx)(`span`, { children: id(t, r2) })] }, n2))] })] }), (0, jsxRuntime.jsx)(`div`, { className: `flex h-3.5 gap-0.5 text-[11px] text-muted-foreground/70`, children: n.map((e2, t2) => (0, jsxRuntime.jsx)(`span`, { className: `min-w-0 flex-1 whitespace-nowrap`, children: e2.d.endsWith(`-01`) || t2 === 0 ? `${+e2.d.slice(5, 7)}月` : `` }, e2.d)) })] });
}
var jd = (e) => (e * 100 < 1 ? (e * 100).toFixed(1) : Math.round(e * 100)) + `%`, Md = 10, Nd = `grid grid-cols-1 gap-x-16 gap-y-12 min-[900px]:grid-cols-2`;
function Pd(e) {
  return (0, jsxRuntime.jsxs)(`section`, { "aria-label": e.title, className: e.className, children: [(0, jsxRuntime.jsxs)(`div`, { className: `mb-3 flex min-h-8 flex-wrap items-center justify-between gap-x-4`, children: [(0, jsxRuntime.jsx)(`h2`, { className: `text-xs font-medium text-muted-foreground`, children: e.title }), e.right] }), e.children] });
}
var Fd = `grid grid-cols-[minmax(0,1fr)_4.5rem_7.5rem] items-center gap-4 sm:grid-cols-[minmax(0,14rem)_minmax(0,1fr)_4.5rem_7.5rem]`;
function Id({ items: e, head: t }) {
  if (!e.length) return (0, jsxRuntime.jsx)(`p`, { className: `text-xs text-muted-foreground/70`, children: `暂无` });
  let n = Math.max(...e.map((e2) => e2.value), 1e-9);
  return (0, jsxRuntime.jsxs)(`div`, { className: `flex flex-col`, children: [t && (0, jsxRuntime.jsxs)(`div`, { className: `${Fd} h-8 border-b text-xs text-muted-foreground`, children: [(0, jsxRuntime.jsx)(`span`, { children: t[0] }), (0, jsxRuntime.jsx)(`span`, { className: `max-sm:hidden` }), (0, jsxRuntime.jsx)(`span`, { className: `text-right`, children: t[1] }), (0, jsxRuntime.jsx)(`span`, { className: `text-right`, children: t[2] })] }), e.map((e2) => (0, jsxRuntime.jsxs)(`div`, { title: e2.title, className: `${Fd} h-10 border-b border-muted text-[13px] last:border-0`, children: [(0, jsxRuntime.jsxs)(`span`, { className: `flex min-w-0 items-center gap-1.5 font-mono text-xs`, children: [e2.color && (0, jsxRuntime.jsx)(`span`, { className: `size-[7px] shrink-0 rounded-full`, style: { background: e2.color } }), (0, jsxRuntime.jsx)(`span`, { className: `truncate`, children: e2.label })] }), (0, jsxRuntime.jsx)(`div`, { className: `h-[3px] rounded-full max-sm:hidden`, style: { width: `${Math.max(e2.value / n * 100, 1)}%`, background: e2.color ?? `color-mix(in oklch, var(--foreground) 80%, transparent)` } }), (0, jsxRuntime.jsx)(`span`, { className: `text-right tabular-nums`, children: e2.text }), (0, jsxRuntime.jsx)(`span`, { className: `whitespace-nowrap text-right text-xs text-muted-foreground tabular-nums`, children: e2.note })] }, e2.key))] });
}
var Ld = matchMedia(`(prefers-color-scheme: dark)`), Rd = () => document.documentElement.classList.toggle(`dark`, Ld.matches);
Rd(), Ld.addEventListener(`change`, Rd), createRoot(document.getElementById(`root`)).render((0, jsxRuntime.jsx)(React.StrictMode, { children: (0, jsxRuntime.jsx)(Overview, {}) }));
