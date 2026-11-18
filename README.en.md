# QuotaCanvas

[简体中文](README.md) · [繁體中文](README.zh-TW.md) · English

A browser dashboard for local Codex, Antigravity, Claude Code, and DeepSeek Harness usage. For supported agents, it also displays quotas, reads conversations, and schedules messages.

**v0.0.2 · Linux / Windows x64 · [MIT License](LICENSE)**

![QuotaCanvas usage overview with sample data](docs/demo-overview-en.png)

## Install and start

### Windows (x64)

1. Download `QuotaCanvas-v0.0.2-windows-x64.zip` from GitHub **Releases** and extract the entire folder.
2. Double-click `QuotaCanvas.exe` and set a dashboard password on first launch. Python is included.
3. Click **Open local dashboard** or visit [http://127.0.0.1:8088](http://127.0.0.1:8088). Closing the main window stops the service.

Use the main window to change your password, start QuotaCanvas at sign-in, or show the tok/s overlay. To monitor another host, select **Remote** under **Monitor source**, then enter its dashboard URL and password. For a host protected by Cloudflare Access, select **Verify Access in browser**. Settings and history are stored in `%LOCALAPPDATA%\QuotaCanvas` and survive app updates.

### Linux

Requires Python 3.10 or later. On Debian or Ubuntu, run `sudo apt install python3-venv` if virtual environments are unavailable.

```bash
git clone https://github.com/iezx/QuotaCanvas.git
cd QuotaCanvas
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python server.py
```

Set a 10–256 character dashboard password when prompted. Open [http://127.0.0.1:8088](http://127.0.0.1:8088) and sign in. Press Ctrl+C to stop the service.

Run QuotaCanvas under the same Linux account you use for your agents. The default log homes are `~/.codex`, `~/.gemini/antigravity-cli`, `~/.claude`, and `~/.dsh`. Override them with `CODEX_HOME`, `AGY_HOME`, `CLAUDE_HOME`, and `DSH_HOME`.

### Persist Linux data

The default data directory is `data/` inside the installation. Keep the dashboard password, prices, schedules, history, and Cloudflare configuration in a separate directory on local disk. Run the following as the Linux user who runs QuotaCanvas.

```bash
install -d -m 700 "$HOME/.local/share/quotacanvas"
export QUOTACANVAS_DATA_DIR="$HOME/.local/share/quotacanvas"
```

To move an existing installation’s data, stop the dashboard and confirm that the destination is empty. From the old installation directory, run `cp -a -- data/. "$QUOTACANVAS_DATA_DIR/"`. If you already use a custom data directory, keep using that path. Each agent stores its original conversations and logs separately. Back those up as well if you move to a different host.

Set the same `QUOTACANVAS_DATA_DIR` before starting the dashboard or resetting its password in a terminal. For startup at boot, set it in the systemd service.

### Start at boot with systemd

Run `.venv/bin/python server.py` once from the installation directory as the same Linux user. Sign in to verify the setup, then press Ctrl+C. Run `mkdir -p ~/.config/systemd/user` and save the following as `~/.config/systemd/user/quotacanvas.service`.

```ini
[Unit]
Description=QuotaCanvas

[Service]
WorkingDirectory=%h/QuotaCanvas
Environment=QUOTACANVAS_DATA_DIR=%h/.local/share/quotacanvas
Environment=PATH=%h/.local/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=%h/QuotaCanvas/.venv/bin/python server.py
Restart=on-failure

[Install]
WantedBy=default.target
```

This example uses `~/QuotaCanvas`. Adjust `WorkingDirectory` and `ExecStart` to match your installation. Set `QUOTACANVAS_DATA_DIR` in `Environment` to your existing data path. Add the directories for any agents or cloudflared installed outside the listed paths to `PATH`. Put existing flags such as `--lan-host` after `server.py`.

```bash
sudo loginctl enable-linger "$(id -un)"
systemctl --user daemon-reload
systemctl --user enable --now quotacanvas.service
systemctl --user status quotacanvas.service
```

`enable-linger` allows the user service to start at boot and keep running after sign-out. Use `journalctl --user -u quotacanvas.service -n 50` to view logs or `systemctl --user disable --now quotacanvas.service` to stop the service and disable startup.

### Upgrade an existing Linux installation

1. Stop the dashboard. Press Ctrl+C if it runs in a terminal. For the user service above, run `systemctl --user stop quotacanvas.service`. For a system service, run `sudo systemctl stop <service-name>`.
2. Open your existing QuotaCanvas installation directory as the same Linux user. If you configured `QUOTACANVAS_DATA_DIR` at startup, set it to that same absolute path in this shell. Run `git status --short --branch` and save any source changes before proceeding. The commands below back up your data before updating the code and dependencies.

   ```bash
   data_dir="${QUOTACANVAS_DATA_DIR:-$PWD/data}"
   backup_dir=$(mktemp -d "$HOME/quotacanvas-backup.XXXXXX") &&
     cp -a -- "$data_dir" "$backup_dir/data" &&
     printf '%s\n' "$backup_dir" &&
     git pull --ff-only &&
     .venv/bin/python -m pip install -r requirements.txt
   ```

3. Once all commands succeed, start the dashboard with your previous options. The default command is `.venv/bin/python server.py`. For systemd, keep the existing unit’s options and data directory. Run `systemctl --user start quotacanvas.service` for the user service or `sudo systemctl start <service-name>` for a system service. Reload the dashboard and sign in with your existing password.

If you installed from a source archive, stop the dashboard and back up the data directory. Then extract the new release to a separate directory and recreate `.venv` using the Linux installation steps above. Copy the old installation’s `data/` into the new directory or continue using the same `QUOTACANVAS_DATA_DIR`. If the systemd unit points to a path that changed, update its working directory and startup command, then reload it with `systemctl --user daemon-reload` for a user service or `sudo systemctl daemon-reload` for a system service before starting it. Keep the old directory until you verify the upgrade.

## Use the dashboard

- **Usage overview** shows tokens, API-equivalent costs, and recent output rates. Sort models by tokens or cost. Model IDs come from the logs, and unpriced models still count toward token totals.
- **Models & API pricing** lets you select a known model or enter a custom ID. Set input, cache-read, cache-write, and output prices in USD per million tokens. Saving recalculates estimates.
- **Price research** supports one-off or scheduled lookups with a local agent. To use another AI, copy the prompt from the pricing page and import its JSON response. Check the source, then select **Apply suggestion**.
- **Local conversations** lets you read, create, continue, and schedule messages for supported agents. Native Codex questions appear below the conversation. Enter `/help` for commands supported by the selected agent.
- **Settings** shows finished-task output rates and quota exhaustion history. You can also hide email addresses, set subscription dates, and limit failed sign-in attempts.

Bundled prices come from `model_prices.json`. Manual prices and research suggestions are stored in `data/prices.json`. Choose a provider to narrow the research scope. The pricing page shows the next scheduled check. Apply the suggestions you approve. Built-in rate changes use the usage timestamp and the UTC effective date. Manual prices take precedence.

## Linux command reference

Activate `.venv` in the project folder. Stop the existing process before changing startup flags or running administrative commands.

| Command | Action |
| --- | --- |
| `python server.py` | Start on `127.0.0.1:8088` |
| `python server.py --lan-host 192.168.1.10` | Listen on loopback and the specified private IPv4 address. Use your host’s LAN address |
| `python server.py --host 0.0.0.0` | Listen on all IPv4 interfaces. Use a firewall and an HTTPS reverse proxy for direct public access |
| `python server.py --port 9090 --interval 60` | Use port 9090 and refresh usage every 60 seconds |
| `python server.py --set-password` | Reset the dashboard password interactively, then restart the service |
| `python server.py --disable-remote` | Persistently stop the tunnel connection and retain Cloudflare Access settings |
| `python server.py --once` | Collect once, print the summary, and exit |
| `python server.py --web-cache "$HOME/.cache/quotacanvas/web"` | Serve static pages from a snapshot on local disk |
| `python server.py --help` | List all startup options |

## Windows command reference

Open PowerShell in the extracted folder and close the running QuotaCanvas app first.

| Command | Action |
| --- | --- |
| `.\QuotaCanvas.exe --lan-host 192.168.1.10` | Keep loopback and listen on this private IPv4 address. Substitute your host’s LAN address |
| `.\QuotaCanvas.exe --port 9090` | Use port 9090 |
| `.\QuotaCanvas.exe --set-password` | Open the password reset dialog, then reopen the app after saving |
| `.\QuotaCanvas.exe --disable-remote` | Persistently stop the tunnel and retain Cloudflare Access settings |
| `.\QuotaCanvas.exe --help` | List startup options |

## Remote access through Cloudflare

### Install cloudflared

Install it on the host running QuotaCanvas. These commands apply to Debian and Ubuntu. For other Linux distributions, follow the matching package instructions. [Cloudflare package repository](https://pkg.cloudflare.com/index.html)

```bash
sudo install -d -m 0755 /usr/share/keyrings
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null
echo 'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main' | sudo tee /etc/apt/sources.list.d/cloudflared.list
sudo apt update
sudo apt install cloudflared
cloudflared --version
```

**Windows** users can install the x64 MSI. Reopen PowerShell and run `cloudflared --version`, then restart QuotaCanvas and follow the steps below. [Official Cloudflare downloads](https://developers.cloudflare.com/tunnel/downloads/#windows)

### Configure Tunnel + Access

1. Use a domain with Cloudflare-hosted DNS and an unused hostname such as `dashboard.example.com`. Set up a login method in Zero Trust, such as a one-time email code.
2. Create a custom API token. Limit its account and zone resources to the target account and domain. [Create an API token](https://developers.cloudflare.com/fundamentals/api/get-started/create-token/)
3. In QuotaCanvas **Settings → Cloudflare Tunnel + Access**, enter the hostname, allowed email addresses, and API token. Select **Save → Check configuration → Enable**.
4. Once the tunnel is connected, open the HTTPS hostname. Complete the Cloudflare Access login, then sign in to QuotaCanvas.

| Scope | Token permission | Level |
| --- | --- | --- |
| Zone | Zone | Read |
| Zone | DNS | Edit |
| Account | Cloudflare Tunnel | Edit |
| Account | Access: Apps and Policies | Edit |
| Account | Access: Organizations, Identity Providers, and Groups | Read |

If Cloudflare lists **Access: Apps** and **Access: Policies** separately, give both Edit. The final permission may appear as **Access: Organizations**.

Allow outbound TCP or UDP 7844 for `cloudflared`. The tunnel uses loopback as its origin, and you can keep a separate LAN entry with `--lan-host`. Grant access only to people you trust to send instructions to your local agents. [Cloudflare connectivity checks](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/troubleshoot-tunnels/connectivity-prechecks/)

### Reconnect or stop the tunnel

Turn on **Connect tunnel when QuotaCanvas starts** in Settings to reconnect an enabled tunnel at startup. With the option off, select **Connect tunnel** from the local or LAN dashboard. Select **Disable** to stop the current tunnel connection.
