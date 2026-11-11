(() => {
  let language = 'zh';
  try { language = localStorage.getItem('quotacanvas.language') || 'zh'; } catch {}
  const english = language === 'en';
  window.QCi18n = {english, t:(zh,en)=>english?en:zh};
  const dictionary = {
    '面板启动时自动连接隧道':'Connect tunnel when QuotaCanvas starts','保存启动设置':'Save startup settings',
    '适用于已启用的远程访问。关闭后，下次启动面板时需从本机或内网手动连接。':'Applies to enabled remote access. Turn off to require manual connection from this computer or your LAN after restart.',
    '等待手动连接':'Waiting for manual connection','启动连接':'Connect tunnel','启动设置已保存。':'Startup settings saved.',
    '已关闭开机自动连接；可在本机或内网手动启动':'Automatic startup is off. Connect manually from this computer or your LAN.',
    '日志未提供模型':'Model not reported','待定价':'Unpriced',
    '额度预计 · 对话定时发送':'Quota forecasts · Conversations & schedules',
    'AI 用量与额度监控':'AI usage and quota monitoring','API 折算费用':'API-equivalent cost',
    '排序':'Sort by','模型排序':'Model sorting','按 Tokens 排序':'Tokens, high to low','按费用排序':'Cost, high to low',
    '结束日期':'End date','度量':'Metric',
    '首次启动时在服务器终端设置登录密码，之后在内网和公网均可使用此密码。可在这里修改，或运行 python3 server.py --set-password 重设。':'Set a password in the server terminal at first startup, then use it locally or remotely. Change it here, or reset it with python3 server.py --set-password.',
    '登录':'Sign in','退出登录':'Sign out','对话与 API 标价 →':'Conversations & API prices →','远程访问设置':'Remote access settings',
    '实时额度':'Live quotas','用量总览':'Usage overview','模型用量':'Model usage','每日用量':'Daily usage','工具使用':'Tool usage','工具':'Tool','次数':'Count','暂无工具记录':'No tool records','暂无用量记录':'No usage records','加载中…':'Loading…','暂无额度数据':'No quota data',
    '额度预计 · 对话定时 →':'Quotas & conversations →','实时使用额度与 API 价值预测 (Codex · Antigravity · Claude)':'Live quotas and API-equivalent forecast (Codex · Antigravity · Claude)',
    '数据源: 官方实时额度接口 + 本地日志 API 等价折算':'Sources: live quota APIs and local logs','各来源 Token 消耗':'Token usage by source','总 Tokens':'Total tokens',
    '输入 + 输出':'Input + output','缓存读取':'Cache read','Claude 系列模型（所有来源合计）':'Claude models (all sources)','暂无用量':'No usage',
    '正常可用':'Available','API 额度折算与预测':'API-equivalent estimate and forecast','本地账号':'Local account','官方实时':'Live',
    '活跃天数':'Active days','连续使用':'Consecutive days','缓存命中':'Cache hits','没有输入明细':'No input details','最忙的一天':'Busiest day',
    '日均费用':'Average daily cost','总览':'Overview','订阅':'Subscription','订阅回报':'Subscription return','API 等价':'API equivalent',
    '订阅数据为本地估算，请核对实际账单。':'Subscription data is estimated locally; check your actual bill.','开始日期':'Start date','估算月费':'Estimated monthly cost','暂无订阅记录':'No subscription records',
    '按官方 API 标价自动折算':'Estimated using API list prices','常用工具':'Top tools','费用':'Cost','费用 / 占比':'Cost / share','占比':'Share',
    '无记录':'No records','按天存档 · 无请求数':'Daily archive · request count unavailable','stats-cache 估算':'stats-cache estimate',
    '暂无额度窗口数据':'No quota window data','API 等价费用':'Estimated API equivalent','请求':'Requests','会话':'Sessions',
    '模型':'Model','来源':'Source','暂无模型记录':'No model records','额度窗口':'Quota window','读取失败：':'Could not load: ',
    '额度预计 · 对话定时发送 · API 标价':'Quota forecasts · Conversations · API pricing','设置':'Settings','← 用量总览':'← Overview',
    '实时使用额度与预计（官方接口，每分钟刷新）':'Live quotas and forecasts (refreshed every minute)','本机对话阅读与发送':'Read and send local conversations',
    'Codex 支持 /goal、/goal 目标、/goal pause、/goal resume 和 /goal clear。其他斜杠命令会明确提示暂不支持。':'Codex supports /goal, /goal objective, /goal pause, /goal resume, and /goal clear. Other slash commands are reported as unsupported.',
    '对话来源':'Conversation source','全部来源':'All sources','选择本机对话':'Select a conversation','刷新列表':'Refresh list','选择对话查看记录':'Select a conversation',
    '加载更早消息':'Load earlier messages','刷新对话':'Refresh conversation','用户与助手对话记录':'User and assistant messages','选择对话后显示完整记录':'Select a conversation to read messages',
    '模型:':'Model:','输入自定义模型 ID':'Custom model ID','思考强度:':'Reasoning effort:','默认强度 (Default)':'Default effort',
    'low（低 · 省额度）':'low','medium（中）':'medium','high（高）':'high','xhigh（超高）':'xhigh','max（最高 Max）':'max',
    '要发送的消息，如：请继续':'Message, e.g. Please continue','立即发送':'Send now','指定时间一次':'Once at a specified time','每天':'Daily',
    '每隔 N 分钟':'Every N minutes','额度重置后自动发送':'After quota reset','添加定时':'Add schedule','定时任务':'Scheduled tasks','发送记录':'Send history',
    'API 标价（USD / 1M tokens）':'API prices (USD / 1M tokens)','页面导航':'Page navigation','对话与定时发送':'Conversations & schedules','面板登录密码':'Dashboard password',
    '首次可通过公网域名的 Cloudflare 邮箱验证设置密码。之后在内网、公网均可使用此密码登录，无需读取服务器令牌文件。':'First-time setup can use Cloudflare Access email verification. Afterwards use the same dashboard password locally and remotely.',
    '设置 / 修改密码':'Set / change password','正在读取状态…':'Loading status…','刷新状态':'Refresh status','连接配置':'Connection configuration',
    'Access 保护整个公网域名，包括所有页面和 API；面板使用自己设置的密码登录。连接器启动中不代表隧道已经连接。':'Access protects the entire public hostname, including pages and APIs. The dashboard also uses its own password. Starting the connector does not mean the tunnel is connected.',
    '可以稍后填写。先保存，再检查；只有点击「启用」才会创建云端资源并开放远程访问。启用后如需修改，请先停用。':'You can configure this later. Save and check first. Cloud resources are created only when you enable remote access. Disable it before making changes.',
    '公网主机名':'Public hostname','填写完整主机名，不含 https://、端口或路径；须属于你在 Cloudflare 中已激活的 Zone，并使用尚未分配给其他服务的主机名。':'Enter a full hostname without https://, port, or path. It must be in an active Cloudflare zone and not assigned to another service.',
    '允许登录的邮箱':'Allowed email addresses','每行一个，或用逗号分隔。仅允许这些完整邮箱地址登录，不开放整个邮箱域名；不接受通配符。':'One per line or comma-separated. Only these full addresses are allowed; wildcards and entire email domains are not accepted.',
    '输入新 Token；留空保留已保存的 Token':'New token; leave blank to keep the saved token','正在读取保存状态…':'Loading saved state…',
    '保存':'Save','检查配置':'Check configuration','启用':'Enable','停用':'Disable',
    '停用会中断公网访问，包括当前通过公网打开的页面。服务器本机和已配置的内网入口继续可用。':'Disabling interrupts public access, including this page if opened remotely. Local and configured LAN access remain available.',
    '配置前准备':'Before you begin','拥有一个已激活、DNS 由 Cloudflare 托管的 Zone；选择一个尚未被其他 DNS 记录或 Access 应用占用的完整子域名。':'Use an active Cloudflare-hosted zone and an unused subdomain without conflicting DNS records or Access applications.',
    '先在 Cloudflare 完成 Zero Trust 初始化，并配置可用的登录方式（例如邮箱验证码或身份提供商）。本页面不会修改账户级登录方式。':'Initialize Cloudflare Zero Trust and configure a sign-in method, such as email OTP or an identity provider. This page does not change account-level sign-in methods.',
    '在运行面板的电脑上安装':'Install ','；允许它向 Cloudflare 发起 TCP 或 UDP 7844 出站连接，VPN 或防火墙也需要放行。':' on the dashboard host; allow outbound TCP or UDP 7844 to Cloudflare through the VPN or firewall.',
    '在 Cloudflare「我的个人资料 → API Tokens」创建自定义用户 API Token，添加下面的权限，并分别设置账号和区域资源范围：':'Create a custom user API token under Cloudflare My Profile → API Tokens. Add the permissions below and scope both account and zone resources:',
    '（包含 DNS 读取；Zone 资源范围须包含此域名所属区域）':' (includes DNS read; zone resources must include the target zone)',
    '如果 Cloudflare 界面把':'If Cloudflare lists ','和':' and ','分开列出，请分别选择编辑；组织权限可能显示为':' separately, grant Edit to each. Organization access may be shown as ',
    '。DNS 必须选择':'. DNS must be ','，不是账号级的 DNS 设置。':', not account-level DNS settings.',
    '在「Account Resources」包含域名所属账户，在「Zone Resources」包含域名所属 Zone；检查 Token 有效期、IP 限制和创建者的账户权限。系统会自动识别 Zone、账户与 Zero Trust 团队。检查主要验证读取和配置，不能保证所有写入权限有效；点击启用时才创建或修改本系统专用的 Access、Tunnel 和 DNS 记录。Token 只保存在服务器，不会回显。':'Include the owning account under Account Resources and the domain zone under Zone Resources. Check token expiration, IP restrictions, and the creator’s account permissions. The check verifies reads and configuration; it cannot guarantee write access. Enabling creates or updates dedicated Access, Tunnel and DNS resources. The token stays on the server and is never displayed again.',
    '参考 Cloudflare 官方文档：':'Cloudflare documentation: ','Tunnel API 配置':'Tunnel API setup','创建 API Token':'Create an API token','网络连接检查':'Connectivity checks',
    '登录面板':'Sign in to dashboard','设置登录密码':'Set dashboard password','修改登录密码':'Change password','首次设置验证':'First-time verification',
    '设置并登录':'Set and sign in','保存密码':'Save password','验证令牌':'Verify token','已有访问令牌':'Existing access token','密码':'Password','新密码':'New password','当前密码':'Current password','再次输入新密码':'Confirm new password','取消':'Cancel','确认操作':'Confirm action','确认':'Confirm',
    '首次设置密码，请先从公网域名通过 Cloudflare 邮箱验证；也可使用已有访问令牌完成首次验证。':'For first-time setup, verify your email through Cloudflare Access or enter the existing local access token.',
    '设置一个 10–256 个字符的密码，之后可在内网和公网登录。':'Set a password of 10–256 characters for local and remote sign-in.','修改后，其他浏览器需要使用新密码重新登录。':'Other browsers must sign in again after the password changes.','输入你设置的面板密码。':'Enter your dashboard password.',
    '前往公网入口验证邮箱':'Verify email through public access','已停用':'Disabled','检查中':'Checking','已就绪 · 可启用':'Ready to enable','配置中':'Configuring','连接器启动中 · 等待连接':'Connector starting','隧道已连接':'Tunnel connected','发生错误':'Error',
    'API Token 已保存；留空保留，填写可替换。':'API token saved. Leave blank to keep it, or enter a replacement.','尚未保存 API Token。':'No API token saved.',
    '正在提交…':'Submitting…','已保存；保存不会启用远程访问。':'Saved. Remote access is not enabled yet.','有未保存的修改；请先保存再检查或启用。':'Unsaved changes. Save before checking or enabling.',
    '密码已保存，可以在内网和公网使用。':'Password saved for local and remote access.','状态未知':'Status unknown','未知状态':'Unknown status','服务器未提供状态说明':'No status message from server','cloudflared 已安装':'cloudflared installed','cloudflared 未安装；启用前需在服务器安装':'Install cloudflared on the server before enabling','隧道连接本机回环地址':'Tunnel connects to localhost','尚未启用隧道监听保护':'Tunnel protection not enabled','正在读取对话列表…':'Loading conversations…','暂无本机对话':'No local conversations','正在加载更早消息…':'Loading earlier messages…','正在读取对话…':'Loading conversation…','暂无可显示的用户与助手消息':'No user or assistant messages',
    '访问令牌无效':'Invalid access token','两次输入的新密码不一致':'Passwords do not match','登录失败，请重试':'Sign-in failed. Try again.','登录服务暂时不可用，请重试':'Sign-in service unavailable. Try again.','尚未登录，请点击页面上的「登录」继续':'Sign in to continue','已取消登录，请点击页面上的「登录」继续':'Sign-in canceled. Select Sign in to continue.',
    '密码不正确':'Incorrect password','密码长度须为 10–256 个字符':'Password must contain 10–256 characters','尝试次数过多，请在 15 分钟后重试':'Too many attempts. Try again in 15 minutes.',
    '已检测到 ~/.claude':'Found ~/.claude','未安装 · 接口已预留，安装后自动统计 ~/.claude/projects':'Not installed; ~/.claude/projects will be read after installation',
    '用户':'User','助手':'Assistant','已提交发送':'Message submitted','确认向该对话发送消息？':'Send a message to this conversation?',
    '价格为 API 等价估算，非订阅账单；内置价格可能过期，请核对来源。修改会重新计算历史估算。':'API-equivalent estimates are not subscription bills. Built-in prices may be outdated; verify sources. Changes recalculate historical estimates.',
    '调用本机 Agent 获取新资料':'Research with local agent','正在获取…':'Researching…','尚未检查':'Not checked yet',
    'Agent 只生成待确认建议，不会自动覆盖手动价格。搜索结果可能有误，应用前请核对原始来源。':'The agent produces suggestions for review and never overwrites manual prices automatically. Verify the source before applying.',
    '定时获取建议':'Schedule research','小时一次':'hours between checks','保存更新设置':'Save schedule','手动设置模型价格':'Edit model prices','模型 ID':'Model ID','输入':'Input','缓存读':'Cache read','缓存写':'Cache write','输出':'Output','保存价格':'Save price','暂无建议':'No suggestions','查看来源':'View source','应用建议':'Apply suggestion',
    '官方实时':'Live','本地日志':'Local logs','已达上限':'Limit reached','所有模型':'All models','剩余':'Remaining','重置':'Reset','更新时间：':'Updated: ',
    '暂无':'None','类型':'Type','消息':'Message','状态':'Status','时间':'Time','对话':'Conversation','下次 / 监控状态':'Next run / status','触发':'Trigger','删除':'Delete','删':'Delete','默认':'Default','模型 / 强度':'Model / effort'
  };
  Object.assign(dictionary, {"模型与价格": "Models & pricing", "模型与 API 价格": "Models & API pricing", "本机对话": "Local conversations", "模型价格设置": "Model pricing settings", "正在读取价格…": "Loading prices…", "新建对话": "New conversation", "首页显示设置": "Overview display settings", "隐藏首页账号邮箱": "Hide account email on overview", "保存后，首页接口也会隐藏邮箱字段。": "The overview API also removes email fields when this is enabled.", "保存显示设置": "Save display settings", "远程访问已连接，需通过 Access 登录": "Remote access is connected; sign in through Access", "远程访问未启用": "Remote access is disabled", "设置已保存，尚未启用远程访问": "Settings saved; remote access is not enabled", "连接组件运行中，正在连接 Cloudflare": "Connector running; connecting to Cloudflare", "正在恢复已启用的远程访问": "Restoring remote access", "正在检查 Cloudflare 设置": "Checking Cloudflare settings", "正在验证 Cloudflare 设置": "Validating Cloudflare settings", "正在准备受保护的远程入口": "Preparing protected remote access", "正在配置整个域名及 API 的 Access 登录保护": "Configuring Access protection for the entire hostname and APIs", "Access 已配置，连接组件正在连接 Cloudflare": "Access configured; connecting to Cloudflare", "Access 已保护入口，正在配置域名和本机连接": "Access protection ready; configuring DNS and the local connector", "Cloudflare 账号、域名和 Access 团队检查通过，尚未启用": "Cloudflare account, zone, and Access checks passed; not enabled yet", "连接组件已退出，正在等待重新连接": "Connector exited; waiting to reconnect", "连接组件启动失败，稍后会重试": "Connector startup failed; retrying later", "远程访问已停用；已有 Access 保护保留，本机访问方式保持不变": "Remote access disabled; Access protection and local access are retained", "远程访问配置损坏，已保留仅本机访问": "Remote configuration is invalid; local access only", "本机尚未安装 cloudflared 连接组件": "cloudflared is not installed on this machine", "无法连接 Cloudflare，请检查本机网络后重试": "Could not connect to Cloudflare; check the host network and retry", "Cloudflare 未确认请求成功，请检查 API Token 权限": "Cloudflare did not confirm success; check API token permissions", "请先停用远程访问并等待当前操作完成，再修改设置": "Disable remote access and wait for the operation to finish before editing settings", "请先保存域名、至少一个允许登录的邮箱和 Cloudflare API Token": "Save the hostname, at least one allowed email, and a Cloudflare API token first", "请先在 Cloudflare 完成 Zero Trust 初始化和登录方式设置": "Initialize Cloudflare Zero Trust and configure a sign-in method first", "此域名已有其他 DNS 记录，请使用空闲的子域名": "DNS records already exist for this hostname; choose an unused subdomain", "此域名或其路径已有其他 Access 应用，请使用专用子域名，避免覆盖原有策略": "An Access application already covers this hostname; choose a dedicated subdomain", "Cloudflare 未返回连接凭据": "Cloudflare did not return tunnel credentials", "Access 策略校验未通过，已停止启用": "Access policy verification failed; activation stopped", "当前已有操作或远程访问正在运行，请先停用后重试": "An operation or remote access is active; disable it before retrying", "请等待当前配置操作完成后再停用": "Wait for configuration to finish before disabling", "域名和 API Token 必须是文本": "Hostname and API token must be text", "域名格式不正确": "Invalid hostname", "只填写完整域名，不包含 https://、端口或路径": "Enter a hostname without https://, port, or path", "请使用 Cloudflare 托管的域名，不能填写 IP 地址": "Use a Cloudflare-hosted hostname, not an IP address", "最多填写 20 个允许登录的完整邮箱地址": "Provide at most 20 full allowed email addresses", "邮箱地址必须是文本": "Email addresses must be text", "请填写完整邮箱地址，不能使用通配符": "Enter full email addresses without wildcards", "此入口已经配置过域名；请保留该域名，避免覆盖或遗留其他入口": "This entry already has a hostname; retain it to avoid orphaned resources", "保存的入口属于其他 Cloudflare 账号，不能覆盖": "The saved entry belongs to another Cloudflare account", "未找到此域名的有效 Cloudflare 区域，请检查托管状态和 Token 的 Zone Read 权限": "No active Cloudflare zone found; check DNS hosting and Zone Read permissions", "内网入口：": "LAN URL: ", "已用": "Used", "近 5h 累计:": "Last 5h total:", "近 5h 合计:": "Last 5h total:", "近 24h 合计:": "Last 24h total:", "订阅周期:": "Subscription period:", "· 默认": "· Default", "tokens（约 97% 为上下文缓存命中读取）": "tokens (mostly cached context reads)", "全部模型剩余额度 (": "Remaining quota by model (", "默认模型（跟随对话）": "Default model (follow conversation)", "自定义模型...": "Custom model…", "未知": "Unknown", "周一": "Mon", "周二": "Tue", "周三": "Wed", "周四": "Thu", "周五": "Fri", "周六": "Sat", "周日": "Sun", "额度预计 · 对话与定时发送 · API 标价": "Quota forecasts, conversations, schedules, and API pricing", "Cloudflare Tunnel + Access 远程访问设置": "Cloudflare Tunnel + Access settings", "点击立即重新扫描日志并刷新": "Rescan logs and refresh now", "刷新中…": "Refreshing…", "已重置": "Reset", "服务器返回了无法读取的状态，请刷新重试。": "The server returned an unreadable response. Refresh and retry.", "请登录后重试。": "Sign in and retry.", "请检查连接后刷新。": "Check the connection and refresh.", "停用将中断此公网地址的访问，包括当前通过公网打开的页面。确认停用？": "Disable public access? This also disconnects a page opened through the public URL.", "请求失败，请检查连接后刷新状态。": "Request failed; check the connection and refresh the status.", "对话列表格式不正确": "Invalid conversation list", "对话数据格式不正确": "Invalid conversation data", "《战争与和平》": "War and Peace", "《悲惨世界》": "Les Misérables", "《基督山伯爵》": "The Count of Monte Cristo", "《堂吉诃德》": "Don Quixote", "《安娜·卡列尼娜》": "Anna Karenina", "《卡拉马佐夫兄弟》": "The Brothers Karamazov", "《米德尔马契》": "Middlemarch", "《尤利西斯》": "Ulysses", "《白鲸》": "Moby-Dick", "《罪与罚》": "Crime and Punishment", "《简·爱》": "Jane Eyre", "《远大前程》": "Great Expectations", "《双城记》": "A Tale of Two Cities", "《傲慢与偏见》": "Pride and Prejudice", "《泰坦尼克号》": "Titanic", "《指环王：王者归来》": "The Return of the King", "《教父》": "The Godfather", "《教父2》": "The Godfather Part II", "《肖申克的救赎》": "The Shawshank Redemption", "《阿甘正传》": "Forrest Gump", "《星际穿越》": "Interstellar", "《盗梦空间》": "Inception", "《阿凡达》": "Avatar", "《辛德勒的名单》": "Schindler’s List", "《阿拉伯的劳伦斯》": "Lawrence of Arabia", "《七武士》": "Seven Samurai", "《美国往事》": "Once Upon a Time in America", "《宾虚》": "Ben-Hur", "《乱世佳人》": "Gone with the Wind", "《公民凯恩》": "Citizen Kane", "《绿里奇迹》": "The Green Mile", "《角斗士》": "Gladiator", "《勇敢的心》": "Braveheart", "《黑暗骑士》": "The Dark Knight", "《2001太空漫游》": "2001: A Space Odyssey", "《现代启示录》": "Apocalypse Now", "《低俗小说》": "Pulp Fiction", "《霸王别姬》": "Farewell My Concubine", "《与狼共舞》": "Dances with Wolves", "《千与千寻》": "Spirited Away", "《卡萨布兰卡》": "Casablanca"});
  function translateText(node) {
    const parent=node.parentElement;if(!parent||parent.closest('script,style,code,.message-body,#conv'))return;
    const value=node.nodeValue, trimmed=value.trim(); if(!trimmed)return;
    if(parent.closest('#convtitle') && trimmed!=='选择对话查看记录')return;
    const translated=localize(value);
    if(translated!==value)node.nodeValue=translated;
  }
  function localize(input) {
    const value=String(input??'');if(!english)return value;
    const trimmed=value.trim();if(!trimmed)return value;
    let translated=dictionary[trimmed];
    if(!translated) {
      const matches=[[/^待确认建议 \((\d+)\)$/, 'Suggestions to review ($1)'],[/^查看全部 API 标价 \((\d+)\)$/, 'View all API prices ($1)'],[/^所有模型 \((\d+)\)$/, 'All models ($1)'],[/^套餐 (.*)$/, 'Plan $1'],[/^启用 · 已执行(\d+)$/, 'Enabled · Run $1 times'],[/^停用 · 已执行(\d+)$/, 'Disabled · Run $1 times'],[/^邮箱已验证：(.*)。设置一个 10–256 个字符的密码，之后可在内网和公网登录。$/, 'Email verified: $1. Set a password of 10–256 characters for local and remote sign-in.'],[/^上次检查：(.*)$/, 'Last checked: $1'],[/^更新时间：(.*)$/, 'Updated: $1'],[/^更新于 (.*)$/, 'Updated at $1'],[/^已加载 (\d+) \/ (\d+) 条消息$/, 'Loaded $1 / $2 messages'],[/^发送失败：(.*)$/, 'Send failed: $1'],[/^添加定时失败：(.*)$/, 'Could not add schedule: $1'],[/^读取对话失败：(.*)$/, 'Could not load conversation: $1'],[/^读取列表失败：(.*)$/, 'Could not load list: $1'],[/^读取状态失败：(.*)$/, 'Could not load status: $1'],[/^实时接口不可用: (.*)$/, 'Live API unavailable: $1'],[/^操作失败：(.*)$/, 'Action failed: $1']];
      for(const [pattern,replacement] of matches)if(pattern.test(trimmed)){translated=trimmed.replace(pattern,replacement);break;}
    }

    if(!translated) {
      const patterns=[
        [/^(\d{4}-\d{2}-\d{2}) 无记录$/, '$1 No records'],
        [/^已用 ([\d.]+)% · 剩余 ([\d.]+)%$/, 'Used $1% · Remaining $2%'],
        [/^每分钟自动更新 · (.*)$/, 'Updated every minute · $1'],
        [/^(\d+)天(\d+)小时后重置 \((.*)\)$/, 'Resets in $1d $2h ($3)'],
        [/^(\d+)小时(\d+)分后重置 \((.*)\)$/, 'Resets in $1h $2m ($3)'],
        [/^(\d+)分钟后重置 \((.*)\)$/, 'Resets in $1m ($2)'],
        [/^已重置 \((.*)\)$/, 'Reset ($1)'],
        [/^默认模型（跟随对话: (.*)）$/, 'Default model (follow conversation: $1)'],
        [/^平均每天 (.*)$/, 'Daily average $1'],[/^始于 (.*)$/, 'Since $1'],[/^最长 (.*) 天$/, 'Longest $1 days'],
        [/^([\d.]+) 天$/, '$1 days'],[/^([\d.]+) 个$/, '$1 sessions'],[/^([\d,.]+) 次请求$/, '$1 requests'],
        [/^输入 (.*) · 输出 (.*)$/, 'Input $1 · Output $2'],[/^命中 (.*)%$/, '$1% hit rate'],
        [/^相当于(.*)$/, 'Equivalent to $1'],[/^最长会话够看(.*)$/, 'Longest session in $1 viewings'],
        [/^([\d.]+) 本$/, '$1 books'],[/^([\d.]+) 遍$/, '$1 times'],[/^输入与输出共 (.*) token$/, '$1 input and output tokens'],
        [/^持续 (.*)$/, 'Duration $1'],[/^只有 (.*)% 的输入没走缓存$/, '$1% of input was uncached'],
        [/^花掉 (.*)$/, 'Spent $1'],[/^按 (.*) 个活跃日算$/, 'Across $1 active days'],
        [/^(.*) 进行中$/, '$1 ongoing'],[/^API 等价 (.*) · 已付 (.*)$/, 'API equivalent $1 · Paid $2'],
        [/^每日(费用|请求|Tokens)$/, 'Daily $1'],[/^(\d+)月$/, 'Month $1'],[/^(\d+)月(\d+)日$/, '$1/$2'],
        [/^(\d+) 小时 (\d+) 分$/, '$1h $2m'],[/^Tokens 总数 (.*)$/, 'Total tokens $1']
      ];
      for(const [pattern,replacement] of patterns)if(pattern.test(trimmed)){translated=trimmed.replace(pattern,replacement);break;}
      if(translated) {
        for(const [zh,en] of Object.entries(dictionary))if(zh.startsWith('《'))translated=translated.replaceAll(zh,en);
        translated=translated.replaceAll('费用','cost').replaceAll('请求','requests');
        if(translated.startsWith('Daily average '))translated=translated.replace(/ 个$/, ' sessions');
      }
    }
    if(!translated&&/\/月/.test(trimmed))translated=trimmed.replaceAll('/月','/month');
    return translated ? value.replace(trimmed,translated) : value;
  }
  window.QCi18n.text=localize;

  function translate(root) {
    if(!english)return;
    if(root.nodeType===Node.TEXT_NODE){translateText(root);return;}
    if(root.nodeType!==Node.ELEMENT_NODE && root.nodeType!==Node.DOCUMENT_NODE)return;
    if(root.nodeType===Node.ELEMENT_NODE){for(const attr of ['placeholder','aria-label','title']){const value=root.getAttribute(attr);if(value&&localize(value)!==value)root.setAttribute(attr,localize(value));}}
    const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);let node;while(node=walker.nextNode())translateText(node);
    for(const el of root.querySelectorAll?.('[placeholder],[aria-label],[title]') || [])for(const attr of ['placeholder','aria-label','title']){const value=el.getAttribute(attr);if(value&&localize(value)!==value)el.setAttribute(attr,localize(value));}
  }
  document.documentElement.lang=english?'en':'zh-CN';
  if(english)document.title='QuotaCanvas';
  const start=()=>{
    for(const button of document.querySelectorAll('[data-language-switch]')){button.textContent=english?'中文':'English';button.addEventListener('click',()=>{try{localStorage.setItem('quotacanvas.language',english?'zh':'en')}catch{}location.reload()});}
    translate(document.body);
    if(english)new MutationObserver(changes=>{for(const change of changes){if(change.type==='characterData')translate(change.target);else for(const node of change.addedNodes)translate(node)}}).observe(document.body,{subtree:true,childList:true,characterData:true});
  };
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start);else start();
})();
