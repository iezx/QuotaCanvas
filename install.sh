#!/usr/bin/env bash
set -euo pipefail
umask 077

repo_url=https://github.com/iezx/QuotaCanvas.git
install_dir=${QUOTACANVAS_INSTALL_DIR:-"$HOME/QuotaCanvas"}
data_dir=${QUOTACANVAS_DATA_DIR:-"$HOME/.local/share/quotacanvas"}
config_dir="$HOME/.config/quotacanvas"
unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
backup_dir="$HOME/.local/state/quotacanvas-backups"
service=quotacanvas.service

fail() { printf '%s\n' "$*" >&2; exit 1; }
git_project() { git -C "$install_dir" "$@"; }
service_ctl() { systemctl --user "$@"; }

case "${1:-}" in
    ''|--upgrade) ;;
    --help|-h)
        printf '%s\n' 'Usage: bash install.sh [--upgrade]' \
          'Optional: QUOTACANVAS_INSTALL_DIR and QUOTACANVAS_DATA_DIR (absolute paths).'
        exit 0 ;;
    *) fail "Unknown option: $1" ;;
esac
[[ $EUID != 0 ]] || fail 'Run as the Linux user who runs your agents. / 请用运行 Agent 的 Linux 用户执行，无需 sudo。'
[[ $install_dir = /* && $data_dir = /* && $unit_dir = /* ]] || fail 'Use absolute paths. / 请使用绝对路径。'
for tool in git python3 flock systemctl loginctl realpath; do
    command -v "$tool" >/dev/null || fail "Missing dependency / 缺少依赖: $tool"
done
python3 -c 'import sys, venv; assert sys.version_info >= (3, 10)' ||
    fail 'Python 3.10+ with venv is required. Debian/Ubuntu: sudo apt install python3-venv'
service_ctl show-environment >/dev/null ||
    fail 'A systemd user session is required. / 请在该用户的 systemd 登录会话中运行。'
install -d -m 700 "$config_dir"
exec 9>"$config_dir/install.lock"
flock -n 9 || fail 'QuotaCanvas installation or update already running. / QuotaCanvas 正在安装或升级。'
export QUOTACANVAS_DATA_DIR="$data_dir"
python="$install_dir/.venv/bin/python"

setup_venv() {
    python3 -m venv "$install_dir/.venv" &&
        "$python" -m pip install -r "$install_dir/requirements.txt"
}

start_dashboard() {
    service_ctl start "$service" && sleep 2 && service_ctl is-active --quiet "$service"
}

version_at() {
    git_project show "$1:package.json" | python3 -B -c '
import json
import re
import sys

try:
    version = json.load(sys.stdin)["version"]
    if not isinstance(version, str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ValueError("expected a major.minor.patch version")
except (KeyError, TypeError, ValueError) as error:
    raise SystemExit(str(error))
print(version)
'
}

upgrade() {
    export GIT_TERMINAL_PROMPT=0
    previous=$(git_project rev-parse HEAD)
    installed_version=$(version_at "$previous") || fail 'Cannot read the installed QuotaCanvas version / 无法读取本机版本。'
    upstream=$(git_project rev-parse --abbrev-ref --symbolic-full-name '@{upstream}')
    git_project fetch
    target=$(git_project rev-parse "$upstream")
    upstream_version=$(version_at "$target") || fail 'Cannot read the upstream QuotaCanvas version / 无法读取上游版本。'
    printf 'Installed / 本机: v%s (%s)\nUpstream / 上游: v%s (%s)\n' \
        "$installed_version" "${previous:0:8}" "$upstream_version" "${target:0:8}"
    if [[ $previous == "$target" ]]; then
        printf '%s\n' 'QuotaCanvas is up to date. / QuotaCanvas 已是最新。'
        return
    fi
    python3 -B -c 'import sys; current, latest = (tuple(map(int, v.split("."))) for v in sys.argv[1:]); sys.exit(latest < current)' \
        "$installed_version" "$upstream_version" ||
        fail 'The upstream version is older. Automatic downgrade skipped. / 上游版本较旧，已跳过降级。'
    [[ -z $(git_project status --porcelain) ]] ||
        fail 'Local source changes found. Save them before updating. / 请先保存本地源码改动。'
    git_project merge-base --is-ancestor "$previous" "$target" ||
        fail 'Local branch cannot fast-forward. / 本地分支无法快进升级。'
    if [[ $installed_version == "$upstream_version" ]]; then
        printf '%s\n' 'New upstream revision of the same version. / 同一版本有新的上游提交。'
    fi

    data_path=$(realpath "$data_dir")
    backup_path=$(realpath -m "$backup_dir")
    [[ $backup_path != "$data_path" && $backup_path != "$data_path/"* ]] ||
        fail 'The data directory cannot contain the backup directory.'
    install -d -m 700 "$backup_dir"
    backup=$(mktemp -d "$backup_dir/data.XXXXXX")
    cp -a -- "$data_dir" "$backup/data"
    printf 'Backup / 备份: %s\n' "$backup"

    venv_state=''
    if ! git_project diff --quiet "$previous" "$target" -- requirements.txt; then
        venv_state=$(mktemp -d "$(git_project rev-parse --absolute-git-dir)/quotacanvas-venv.XXXXXX")
    fi

    was_running=false
    if service_ctl is-active --quiet "$service"; then
        was_running=true
        service_ctl stop "$service"
    fi
    if ! git_project merge --ff-only "$target"; then
        if $was_running; then start_dashboard; fi
        fail 'Fast-forward failed. / Git 更新失败。'
    fi

    if [[ -n $venv_state ]]; then
        if ! mv -- "$install_dir/.venv" "$venv_state/old"; then
            git_project reset --keep "$previous"
            if $was_running; then start_dashboard; fi
            fail 'Could not stage the previous virtual environment. / 无法备份原虚拟环境。'
        fi
    fi

    if { [[ -z $venv_state ]] || setup_venv; } &&
       "$python" -m py_compile "$install_dir/server.py" &&
       { ! $was_running || start_dashboard; }; then
        if [[ -n $venv_state ]]; then rm -rf -- "$venv_state"; fi
        printf 'QuotaCanvas updated / 已升级: v%s (%s)\n' "$upstream_version" "${target:0:8}"
        return
    fi

    if $was_running; then service_ctl stop "$service"; fi
    git_project reset --keep "$previous"
    if [[ -n $venv_state ]]; then
        if [[ -e $install_dir/.venv ]]; then mv -- "$install_dir/.venv" "$venv_state/failed"; fi
        mv -- "$venv_state/old" "$install_dir/.venv"
    fi
    if $was_running; then start_dashboard; fi
    fail 'Update failed and the previous version was restored. / 升级失败，已恢复原版本。'
}

if [[ ${1:-} == --upgrade ]]; then
    upgrade
    exit
fi

quote_unit() {
    local value=$1
    [[ $value != *$'\n'* && $value != *$'\r'* ]] || fail 'Paths cannot contain line breaks.'
    value=${value//\\/\\\\}
    value=${value//\"/\\\"}
    value=${value//%/%%}
    printf '"%s"' "$value"
}

if [[ -e $unit_dir/$service ]] &&
   ! grep -Fxq '# Managed by QuotaCanvas install.sh' "$unit_dir/$service"; then
    fail "Existing custom service: $unit_dir/$service. Use manual upgrade or back it up before switching."
fi
if [[ ! -e $install_dir ]]; then
    git clone "$repo_url" "$install_dir"
fi
git_project rev-parse --verify '@{upstream}' >/dev/null ||
    fail 'Installation directory must be a Git checkout with an upstream branch. / 安装目录需是跟踪上游分支的 Git 仓库。'
[[ -f $install_dir/server.py && -f $install_dir/requirements.txt ]] ||
    fail 'Invalid QuotaCanvas installation. / 安装目录缺少 QuotaCanvas 文件。'
installed_version=$(version_at HEAD) || fail 'Cannot read the installed QuotaCanvas version / 无法读取本机版本。'

install -d -m 700 "$data_dir"
if [[ -d $install_dir/data && ! $install_dir/data -ef $data_dir && -z $(ls -A -- "$data_dir") ]]; then
    if service_ctl is-active --quiet "$service"; then service_ctl stop "$service"; fi
    cp -a -- "$install_dir/data/." "$data_dir/"
    chmod 700 "$data_dir"
fi
python3 -B -c '
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, sys.argv[1])
from auth import AuthManager, PASSWORD_ITERATIONS, configure_password

path = Path(sys.argv[2])
try:
    configure_password(AuthManager(path))
    record = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(record, dict)
            or record.get("iterations") != PASSWORD_ITERATIONS
            or not re.fullmatch(r"[0-9a-f]{32}", str(record.get("salt", "")))
            or not re.fullmatch(r"[0-9a-f]{64}", str(record.get("hash", "")))):
        raise ValueError("Invalid existing password file / 已有密码文件无效")
except (OSError, ValueError) as error:
    raise SystemExit(str(error))
' "$install_dir" "$data_dir/password.json" ||
    fail 'Installation stopped: a valid password is required. / 安装已停止，必须在终端成功设置密码。'

setup_venv
install -d -m 700 "$unit_dir"
install -m 700 "$(realpath "${BASH_SOURCE[0]}")" "$config_dir/updater.sh"
unit_path=${install_dir//%/%%}
unit_python=$(quote_unit "$python")
unit_data=$(quote_unit "QUOTACANVAS_DATA_DIR=$data_dir")
unit_install=$(quote_unit "QUOTACANVAS_INSTALL_DIR=$install_dir")
unit_updater=$(quote_unit "$config_dir/updater.sh")
cat > "$unit_dir/$service" <<EOF
# Managed by QuotaCanvas install.sh
[Unit]
Description=QuotaCanvas
[Service]
WorkingDirectory=$unit_path
Environment=$unit_data
Environment=PATH=%h/.local/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=:$unit_python server.py
Restart=on-failure
[Install]
WantedBy=default.target
EOF
cat > "$unit_dir/quotacanvas-update.service" <<EOF
[Unit]
Description=Update QuotaCanvas
[Service]
Type=oneshot
Environment=$unit_data
Environment=$unit_install
Environment=PATH=%h/.local/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=:/bin/bash $unit_updater --upgrade
EOF
cat > "$unit_dir/quotacanvas-update.timer" <<'EOF'
[Unit]
Description=Check daily for QuotaCanvas updates
[Timer]
OnCalendar=daily
Persistent=true
[Install]
WantedBy=timers.target
EOF

loginctl enable-linger "$(id -un)" || sudo loginctl enable-linger "$(id -un)"
service_ctl daemon-reload
service_ctl enable "$service"
start_dashboard
service_ctl enable --now quotacanvas-update.timer
printf 'QuotaCanvas v%s: http://127.0.0.1:8088/\nData / 数据: %s\n' "$installed_version" "$data_dir"
printf '%s\n' 'Enabled at boot / 已启用开机启动: quotacanvas.service' \
    'Daily update check / 已启用每日更新检查: quotacanvas-update.timer'
