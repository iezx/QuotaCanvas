"""Commands exposed by this dashboard, grouped by supported execution surface."""
import os


def item(command, zh, en, kind='native', insert=None):
    return {'command': command, 'insert': insert if insert is not None else command,
            'description_zh': zh, 'description_en': en, 'kind': kind}


def command_list(source):
    if source not in ('codex', 'agy', 'cc'):
        raise ValueError('Invalid agent source')
    commands = [
        item('/help', '查看可用命令', 'Show available commands', 'client'),
        item('/model', '为后续发送选择模型', 'Choose the model for subsequent messages', 'client', '/model '),
        item('/effort', '为后续发送选择思考强度', 'Choose reasoning effort for subsequent messages', 'client', '/effort '),
        item('/new', '新建对话', 'Create a new conversation', 'client'),
        item('/clear', '打开新对话，保留原有记录', 'Open a new conversation and retain existing history', 'client'),
    ]
    if source == 'codex':
        commands += [
            item('/goal', '查看目标状态', 'Read goal status'),
            item('/goal <目标>', '设置并执行目标', 'Set and run an objective', insert='/goal '),
            item('/goal pause', '暂停目标', 'Pause the goal'),
            item('/goal resume', '继续目标', 'Resume the goal'),
            item('/goal clear', '清除目标', 'Clear the goal'),
            item('/status', '查看当前对话状态', 'Read conversation status'),
            item('/compact', '压缩当前对话上下文', 'Compact conversation context'),
            item('/rename <名称>', '重命名对话', 'Rename the conversation', insert='/rename '),
            item('/fork', '从当前对话创建分支', 'Fork this conversation'),
            item('/stop', '停止当前运行的回合', 'Interrupt the active turn'),
            item('/usage', '查看账号额度窗口', 'Read account rate limits'),
            item('/mcp', '查看 MCP 连接状态', 'List MCP connection statuses'),
        ]
    elif source == 'agy':
        commands += [
            item('/goal <目标>', '原生目标模式', 'Native goal mode', insert='/goal '),
            item('/plan <任务>', '规划任务', 'Plan a task', insert='/plan '),
            item('/grill-me <任务>', '让 Agent 询问需求', 'Ask the agent to clarify requirements', insert='/grill-me '),
            item('/usage', '查看原生额度信息', 'Read native usage information'),
            item('/context', '查看原生上下文信息', 'Read native context information'),
        ]
    else:
        commands += [
            item('/goal', '查看原生目标状态', 'Read native goal status'),
            item('/goal <目标>', '设置原生目标', 'Set a native goal', insert='/goal '),
            item('/goal clear', '清除原生目标', 'Clear the native goal'),
        ]
    if os.name == 'nt' and source == 'codex':
        for entry in commands:
            if entry['kind'] != 'client':
                entry['enabled'] = False
                entry['description_zh'] += '（需要 Linux/WSL2）'
                entry['description_en'] += ' (requires Linux/WSL2)'
    return commands
