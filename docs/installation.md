# HostBridge MCP — Installation & Deployment / 安装与部署

> **Language / 语言:** [English](#english) · [简体中文](#简体中文)
>
> **Deployment model / 部署模式:** Local Cursor/Codex → HTTPS (Nginx in Docker) → MCP server on the Linux host → host tools.
>
> **Security notice / 安全提示:** This server may expose shell execution, file writes, and Docker management. Deploy only on systems you administer or are explicitly authorized to manage. Do not expose an unauthenticated endpoint. / 本服务可能提供 Shell 执行、文件写入和 Docker 管理能力。只能部署于你拥有管理授权的服务器，禁止将未认证的接口直接暴露在公网。

---

## English

### 1. Purpose and architecture

HostBridge MCP exposes authorized Linux VPS file and command operations over **MCP Streamable HTTP** to local clients such as Cursor and Codex. Model authentication and API keys remain on the **client machine**; the VPS does not need to log in to a model provider.

```text
Local Cursor / Codex (model credentials stay local)
           │ HTTPS + MCP authentication
           ▼
    Existing Nginx Docker (TLS)
           │ HTTP (internal / Docker bridge)
           ▼
  HostBridge MCP on Linux host (systemd)
           │ Effective Linux service-user permissions
           ├─ Read/write authorized files
           ├─ Execute commands
           └─ Docker/systemctl (only if explicitly granted)
```

**Important:** Registering an MCP server does not automatically redirect Cursor/Codex built-in shell or file tools to the VPS. The agent must call the remote MCP tools. File and command results may still be sent to the cloud model used by the local agent, so comply with your organization's data-handling policy.

### 2. Requirements and conventions

- Authorized Linux VPS with systemd and a Dockerized Nginx reverse proxy.
- Valid HTTPS certificate covering the public MCP hostname.
- This repository including `pyproject.toml`, `uv.lock`, `src/hostbridge_mcp/server.py`, and `deploy/` examples.
- Git, an appropriate Python version matching `requires-python`, and [uv](https://docs.astral.sh/uv/getting-started/installation/).
- A separate secret for each user wherever supported; never commit production tokens.

Replace the following illustrative values with your actual deployment settings:

| Setting | Example | Description |
|---|---|---|
| Project directory | `/opt/hostbridge-mcp` | Repository and `.venv` |
| Service account | `hostbridge` | Dedicated Linux principal |
| Environment file | `/etc/hostbridge-mcp.env` | Server token/settings |
| Workspace | `/srv/agent-workspace` | Initial file-tool scope, if implemented |
| Listen endpoint | `127.0.0.1:8765` | **Example only**; replace Docker bridge gateway |
| Public MCP URL | `https://mcp.example.com/mcp` | HTTPS endpoint |
| systemd unit | `hostbridge-mcp.service` | Existing repository unit filename |

> **Repository contract:** The files under `deploy/` are templates. Verify actual environment variable names, exported ASGI app name, command flags, and tool names against the **current** `server.py`. References such as `MCP_ACCESS_TOKEN`, `MCP_FILE_ROOT`, `MCP_ENABLE_COMMANDS`, and `server:app` only apply if the deployed code implements them.

### 3. Clone and install dependencies

```bash
git clone https://github.com/<owner>/hostbridge-mcp.git /opt/hostbridge-mcp
cd /opt/hostbridge-mcp
uv --version
uv sync --locked
```

`uv sync --locked` checks that the committed lockfile remains consistent with `pyproject.toml` instead of silently regenerating it. Update and commit both files when changing dependencies. See the [uv project documentation](https://docs.astral.sh/uv/concepts/projects/sync/).

Grant the service account read access to the repository and `.venv` and appropriate permissions on the workspace. Do not make the entire checkout world-writable.

### 4. Create a dedicated service account

```bash
sudo useradd --system --home /opt/hostbridge-mcp \
  --shell /usr/sbin/nologin hostbridge
sudo mkdir -p /srv/agent-workspace
sudo chown hostbridge:hostbridge /srv/agent-workspace
sudo chmod 750 /srv/agent-workspace
```

Skip user creation if it already exists. Do **not** add the account to the `docker` group by default: Docker daemon access is effectively host-administrator-level access.

### 5. Install the environment file

```bash
sudo install -m 600 -o root -g root \
  deploy/env/hostbridge-mcp.env.example /etc/hostbridge-mcp.env
sudoedit /etc/hostbridge-mcp.env
```

If the example expects `MCP_ACCESS_TOKEN`, generate a random value with `openssl rand -hex 32`. Keep it out of Git, logs, screenshots, and public documentation. Verify that authentication is enabled, the command/file scope is appropriate, no model-provider keys are on the server, and the listen address is not reachable directly from the public Internet.

**Security boundary:** A file-root option limits tools that explicitly enforce it; it does **not** sandbox arbitrary shell commands, which retain the process user's Linux privileges.

### 6. Install the systemd unit

Review `deploy/systemd/hostbridge-mcp.service` and match `User`, `WorkingDirectory`, `EnvironmentFile`, and `ExecStart` to the installation.

For an installable `src/` package exporting an ASGI object named `app`, one possible startup configuration is:

```ini
# Illustration only: verify the actual entry point in your repository.
[Service]
User=hostbridge
WorkingDirectory=/opt/hostbridge-mcp
EnvironmentFile=/etc/hostbridge-mcp.env
ExecStart=/opt/hostbridge-mcp/.venv/bin/uvicorn hostbridge_mcp.server:app --host 127.0.0.1 --port 8765 --workers 1
Restart=on-failure
RestartSec=5
```

If the project exports a different entry point, use that instead. Adjust the copied unit **before** starting it:

```bash
sudo install -m 644 deploy/systemd/hostbridge-mcp.service \
  /etc/systemd/system/hostbridge-mcp.service
sudo systemctl daemon-reload
sudo systemctl enable --now hostbridge-mcp
sudo systemctl status hostbridge-mcp --no-pager
sudo journalctl -u hostbridge-mcp -n 80 --no-pager
```

Systemd restrictions such as `ProtectSystem=strict` and `ReadWritePaths` may limit file writes and host operations. Adjust privileges narrowly instead of disabling hardening wholesale.

### 7. Configure Dockerized Nginx

Determine the Nginx network and its bridge gateway:

```bash
docker inspect nginx --format \
  '{{range $name, $v := .NetworkSettings.Networks}}{{println $name}}{{end}}'
docker network inspect <network-name> --format \
  '{{(index .IPAM.Config 0).Gateway}}'
```

Bind the MCP process to a host interface reachable by the Nginx container, but not directly exposed to the Internet. Add host-firewall restrictions for the allowed sources. Do **not** publish port 8765 externally.

Based on `deploy/nginx/hostbridge-mcp.conf.example`, add an HTTPS route (assuming `/mcp` is also the upstream MCP path):

```nginx
location /mcp {
    proxy_pass http://127.0.0.1:8765;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto https;
    proxy_set_header Authorization $http_authorization;
    proxy_buffering off;
    proxy_read_timeout 300s;
    client_max_body_size 2m;
}
```

MCP Streamable HTTP does not require WebSocket Upgrade headers. Use a certificate whose Subject Alternative Name covers `mcp.example.com`, with a complete, trusted chain. `curl -k` is a **diagnostic bypass**, not a solution for production Cursor/Codex clients. Do not globally disable TLS verification.

```bash
docker exec nginx nginx -t
docker exec nginx nginx -s reload
```

Use defense in depth: combine MCP credentials with source-IP restrictions or an approved identity-aware gateway, especially if providing arbitrary host shell capabilities.

### 8. Verify HTTPS, authentication, and MCP

From a client machine, **without `-k`**:

```bash
curl -i https://mcp.example.com/mcp
```

An authenticated server commonly returns `401 Unauthorized` without a token. A `502` suggests a proxy/upstream problem; a certificate mismatch must be fixed before client configuration.

Test an MCP initialization request:

```bash
export HOSTBRIDGE_MCP_TOKEN='<your-token>'
curl -i https://mcp.example.com/mcp \
  -H "Authorization: Bearer $HOSTBRIDGE_MCP_TOKEN" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  --data '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl-test","version":"1.0"}}}'
```

The expected result is a JSON-RPC MCP initialize response; exact details depend on the SDK and protocol version. An HTTP 200 alone does not prove tool execution: perform `tools/list` and a safe tool call with a real MCP client.

### 9. Configure Cursor

Use `deploy/clients/cursor/mcp.json.example` as the repository reference. A typical local `~/.cursor/mcp.json` entry is:

```json
{
  "mcpServers": {
    "hostbridge": {
      "url": "https://mcp.example.com/mcp",
      "headers": {
        "Authorization": "Bearer ${env:HOSTBRIDGE_MCP_TOKEN}"
      }
    }
  }
}
```

Set `HOSTBRIDGE_MCP_TOKEN` on the **client machine** and fully restart Cursor. Environment-variable interpolation may depend on Cursor version and launch environment; check the MCP logs and current client documentation if it is not expanded. Never commit a plaintext token. Confirm the connection in Cursor's MCP settings, then explicitly request a harmless **remote** tool call.

### 10. Configure Codex CLI

Use `deploy/clients/codex/config.toml.example` or register from your local terminal:

```bash
export HOSTBRIDGE_MCP_TOKEN='<your-token>'
codex mcp add hostbridge \
  --url https://mcp.example.com/mcp \
  --bearer-token-env-var HOSTBRIDGE_MCP_TOKEN
codex mcp list
```

Use the repository TOML example and the current Codex documentation for manual configuration. The environment variable must be visible to the **local Codex process**. The VPS does not require your model API key.

### 11. Enable writes and administrative commands deliberately

Begin with read-only tools. Once authentication and audit behavior have been verified, enable file writes or shell operations in accordance with the actual `server.py` settings. Test using a disposable workspace, and confirm backups, timeouts, and rollback procedures.

- Git/file operations run with the MCP process user's actual Linux permissions.
- Docker inspection/restart/Compose operations require daemon access; **do not automatically grant the `docker` group**, which is effectively root-equivalent.
- Service restarts and privileged host changes require a separately reviewed authorization strategy.
- Keep human approval for high-risk Agent tool calls and maintain audit logs.

### 12. Upgrade and troubleshoot

```bash
cd /opt/hostbridge-mcp
git pull --ff-only
uv sync --locked
sudo systemctl restart hostbridge-mcp
sudo systemctl status hostbridge-mcp --no-pager
sudo journalctl -u hostbridge-mcp -f
```

| Symptom | What to check |
|---|---|
| `401 Unauthorized` | Token, Authorization header, local env-variable injection |
| `502 Bad Gateway` | Upstream address, listener, Docker networking/firewall |
| TLS hostname mismatch | Certificate SAN and public hostname |
| MCP initialization error | SDK/ASGI lifespan, URL path, protocol compatibility |
| Permission denied | Service user, Docker socket, systemd hardening |
| Commands run locally | The Agent used its built-in shell instead of the remote MCP tool |

For operational permissions, credential handling, and exposure controls, read [Security](security.md).

---

## 简体中文

### 1. 目标与架构

HostBridge MCP 将 Linux VPS 的文件操作和命令执行能力以 MCP Streamable HTTP 接口提供给 **本地** Cursor、Codex 等客户端。AI 模型登录信息和模型 API Key 始终保留在客户端；服务器不需要安装或登录第三方模型。

```text
本地 Cursor / Codex（模型凭证保留在本地）
             │ HTTPS + MCP 身份认证
             ▼
      现有 Nginx Docker（TLS）
             │ HTTP（内网 / Docker 网桥）
             ▼
  Linux 宿主机 HostBridge MCP（systemd）
             │ 当前服务账号的 Linux 权限
             ├─ 读取/修改允许访问的文件
             ├─ 执行命令
             └─ Docker / systemctl（仅在明确授权后）
```

**重要限制：** 连接远程 MCP 并不意味着 Cursor/Codex 的内置终端及文件编辑器自动切换到远端。Agent 必须调用 HostBridge MCP 提供的工具才能操作 VPS。文件或命令输出可能经本地 Agent 发送到其所连接的云端模型，请遵守公司数据政策。

### 2. 前提条件

- Linux VPS，具备安装服务和修改 Nginx 的授权；示例采用 systemd。
- VPS 已运行 Docker 版 Nginx，外部通过有效 HTTPS 域名访问，且能添加反向代理规则。
- 项目仓库中已有 `pyproject.toml`、`uv.lock`、`src/hostbridge_mcp/server.py` 与 `deploy/` 示例文件。
- 已安装 Git 和 Python；Python 版本须满足 `pyproject.toml` 的 `requires-python`。
- 安装 [uv](https://docs.astral.sh/uv/getting-started/installation/)；实际命令取决于操作系统及环境策略。
- 为每个使用者准备独立的 MCP 认证凭证；不要把真实 Token 提交到 Git。

本指南统一使用以下示例值，请按实际环境替换：

| 参数 | 示例 | 用途 |
|---|---|---|
| 项目目录 | `/opt/hostbridge-mcp` | 克隆代码、创建 `.venv` |
| 服务用户 | `hostbridge` | 最小权限运行 MCP |
| 环境文件 | `/etc/hostbridge-mcp.env` | 服务端 Token 与配置 |
| 工作目录 | `/srv/agent-workspace` | 文件工具的初始访问范围（如服务支持） |
| 监听地址 | `127.0.0.1:8765` | 示例 Docker 网桥网关地址，**必须替换** |
| 公网 URL | `https://mcp.example.com/mcp` | Cursor/Codex 的 MCP 地址 |
| systemd 单元 | `hostbridge-mcp.service` | 按仓库现有文件名 |

> **注意：** `deploy/` 目录中的配置为仓库提供的模板。此文档没有预设 `server.py` 的确切环境变量名、启动对象以及工具名；部署时必须以当前仓库版本为准。下面给出的 `MCP_ACCESS_TOKEN`、`MCP_FILE_ROOT`、`MCP_ENABLE_COMMANDS` 等变量及 `server:app` 仅适用于服务端确实实现了这些约定的版本。

### 3. 获取代码与安装依赖

```bash
# 在 VPS 上执行；将 URL 替换为你的仓库地址
git clone https://github.com/<owner>/hostbridge-mcp.git /opt/hostbridge-mcp
cd /opt/hostbridge-mcp

# 确保 uv 可用
uv --version

# 严格使用已提交的锁文件安装依赖
uv sync --locked
```

`uv sync --locked` 会检查 `uv.lock` 是否与 `pyproject.toml` 一致，并在不一致时报告错误，而不是悄悄改动锁文件。需要新增依赖时，应在开发环境更新并提交两个文件。参考 [uv 官方文档](https://docs.astral.sh/uv/concepts/projects/sync/)。

如果由专用用户运行服务，需要让该用户能够读取代码和 `.venv`，并能够访问指定工作目录。不要把项目目录整体设为全员可写。

### 4. 创建专用系统账号与工作目录

```bash
sudo useradd --system --home /opt/hostbridge-mcp \
  --shell /usr/sbin/nologin hostbridge
sudo mkdir -p /srv/agent-workspace
sudo chown hostbridge:hostbridge /srv/agent-workspace
sudo chmod 750 /srv/agent-workspace
```

如果账号已存在，不要重复创建。需要为项目树及虚拟环境设置合理的只读或属主权限，保证 `hostbridge` 可以读取和启动服务。**默认不要把服务用户加入 `docker` 组**：Docker Socket 权限通常等同于宿主机高权限。

### 5. 配置服务端环境文件

从仓库示例复制到 Git 仓库以外的受保护路径：

```bash
sudo install -m 600 -o root -g root \
  deploy/env/hostbridge-mcp.env.example /etc/hostbridge-mcp.env
sudoedit /etc/hostbridge-mcp.env
```

若示例使用 `MCP_ACCESS_TOKEN`，可通过 `openssl rand -hex 32` 生成高熵随机值。将其写入环境文件，不要写到 `README.md`、提交记录或共享截图中。

检查配置时请确认：

1. 认证已启用，且令牌非默认值；
2. 文件操作范围与命令执行开关符合预期；
3. 没有模型 API Key 或第三方模型登录信息；
4. 服务监听在 Nginx 可访问、但公网无法直接访问的地址；
5. 对拥有完整 Shell 能力的服务，**文件根目录不是 Shell 沙箱**：命令能访问服务用户本身可访问的其他路径。

### 6. 配置 systemd

先检查 `deploy/systemd/hostbridge-mcp.service` 中的 `WorkingDirectory`、`User`、`EnvironmentFile`、`ExecStart`，确保与本机实际路径一致。

如果服务暴露 `app` ASGI 对象，且使用 `src/` 布局安装，可用的启动方式之一是：

```ini
# 示意：以实际项目导出对象及部署模板为准
[Service]
User=hostbridge
WorkingDirectory=/opt/hostbridge-mcp
EnvironmentFile=/etc/hostbridge-mcp.env
ExecStart=/opt/hostbridge-mcp/.venv/bin/uvicorn hostbridge_mcp.server:app --host 127.0.0.1 --port 8765 --workers 1
Restart=on-failure
RestartSec=5
```

如果当前 `server.py` 不是以 `app` 作为 ASGI 入口，必须使用项目实际支持的入口；不要直接照搬上述 `ExecStart`。

```bash
sudo install -m 644 deploy/systemd/hostbridge-mcp.service \
  /etc/systemd/system/hostbridge-mcp.service
sudo systemctl daemon-reload
sudo systemctl enable --now hostbridge-mcp
sudo systemctl status hostbridge-mcp --no-pager
sudo journalctl -u hostbridge-mcp -n 80 --no-pager
```

若模板内监听地址尚未更新，请**先编辑目标单元**，再执行 `enable --now`。注意：`systemd` 的 `ProtectSystem=strict`、`ProtectHome`、`ReadWritePaths` 等选项可能阻止文件写入或 Docker 管理，应按所需权限精确调整，而非一次性关闭全部限制。

### 7. Nginx Docker HTTPS 反向代理

先定位 Nginx 使用的 Docker 网络和网桥地址：

```bash
# 把 nginx 换成实际容器名
docker inspect nginx --format \
  '{{range $name, $v := .NetworkSettings.Networks}}{{println $name}}{{end}}'

docker network inspect <network-name> --format \
  '{{(index .IPAM.Config 0).Gateway}}'
```

如果 MCP 监听在宿主机网桥网关（例如 `127.0.0.1:8765`），该地址应仅供内部网络访问，并通过防火墙限制允许的来源。**不要直接将 8765 映射到公网。**

参考 `deploy/nginx/hostbridge-mcp.conf.example`，在现有 HTTPS 虚拟主机中添加 MCP 路由。以下配置假设 MCP 的上游路径也是 `/mcp`：

```nginx
location /mcp {
    proxy_pass http://127.0.0.1:8765;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto https;
    proxy_set_header Authorization $http_authorization;
    proxy_buffering off;
    proxy_read_timeout 300s;
    client_max_body_size 2m;
}
```

MCP Streamable HTTP 不要求 WebSocket Upgrade。TLS 证书必须覆盖 `mcp.example.com`，且客户端信任证书链。`curl -k` 只能跳过 TLS 校验作诊断，不能作为正式客户端解决方案。不要使用 `NODE_TLS_REJECT_UNAUTHORIZED=0` 关闭全局校验。

```bash
docker exec nginx nginx -t
docker exec nginx nginx -s reload
```

**安全建议：** 采用独立的 HTTPS 身份验证（如受控 IP、零信任访问网关）与 MCP Token 双层保护；如果需要在公网长期提供完整 Shell 权限，请优先使用具备强设备/用户身份验证的入口。

### 8. 验证 HTTPS、认证与 MCP 协议

**无 Token 请求**（在客户端执行，故意不使用 `-k`）：

```bash
curl -i https://mcp.example.com/mcp
```

如果应用按 Bearer Token 拒绝未认证请求，通常应返回 `401 Unauthorized`。出现 `502` 应检查 Nginx 到 MCP 的连通性；出现证书域名错误应先修复 TLS 配置。

**带 Token 的 MCP initialize 请求：**

```bash
export HOSTBRIDGE_MCP_TOKEN='<your-token>'
curl -i https://mcp.example.com/mcp \
  -H "Authorization: Bearer $HOSTBRIDGE_MCP_TOKEN" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  --data '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl-test","version":"1.0"}}}'
```

期待返回 MCP JSON-RPC 初始化结果，具体响应依所用 SDK/协议版本而异。只收到 `200` 并不能证明所有工具都能使用；需要进一步从真实 MCP 客户端完成 `tools/list` 和工具调用。

### 9. 连接 Cursor

参考仓库中的 `deploy/clients/cursor/mcp.json.example`。一般可以在本地用户目录的 `~/.cursor/mcp.json` 配置：

```json
{
  "mcpServers": {
    "hostbridge": {
      "url": "https://mcp.example.com/mcp",
      "headers": {
        "Authorization": "Bearer ${env:HOSTBRIDGE_MCP_TOKEN}"
      }
    }
  }
}
```

在**本地电脑**设置 `HOSTBRIDGE_MCP_TOKEN`，并重启 Cursor 以确保环境变量被读取。环境变量展开行为可能随 Cursor 版本及启动方式变化；若无法成功替换，请查看 MCP 日志、当前版本文档，并优先使用官方支持的秘密存储方式，不要提交明文 Token。

在 Cursor 的 MCP 设置界面确认服务处于已连接状态，再让 Agent **明确调用 hostbridge 的远程工具**执行只读测试（例如查询远端主机名），不要误用本地终端。

### 10. 连接 Codex CLI

参考 `deploy/clients/codex/config.toml.example`。可以在本地终端执行：

```bash
export HOSTBRIDGE_MCP_TOKEN='<your-token>'
codex mcp add hostbridge \
  --url https://mcp.example.com/mcp \
  --bearer-token-env-var HOSTBRIDGE_MCP_TOKEN
codex mcp list
```

如果使用 TOML 配置，按仓库示例和当前 Codex 版本调整；Token 环境变量必须在 **启动 Codex 的本地进程** 中可见。Codex 模型凭证不需要上传到 VPS。

### 11. 开放文件写入、Docker 与系统操作

第一轮建议仅验证只读工具；随后根据 `server.py` 的实现显式启用命令执行，并使用测试项目验证写入、回滚、超时与权限错误处理。

- 普通 `git`、文件修改取决于服务进程的 Linux 权限和 systemd 沙箱配置。
- `docker ps`、`docker restart`、`docker compose` 需要 Docker 守护进程访问权限；**不要无条件将服务账号加入 `docker` 组**，该组通常等同于宿主机 root 权限。
- `systemctl restart` 等系统操作应使用专门授权的执行路径，严格限制提权范围。若确需完整管理员权限，应将此服务视为高危远程管理入口，配合强身份认证、人工审批、审计和备份。
- 建议保留 Agent 工具审批；不要对高权限执行工具启用无条件自动调用。

### 12. 升级、重启与排错

```bash
cd /opt/hostbridge-mcp
git pull --ff-only
uv sync --locked
sudo systemctl restart hostbridge-mcp
sudo systemctl status hostbridge-mcp --no-pager
sudo journalctl -u hostbridge-mcp -f
```

| 现象 | 检查方向 |
|---|---|
| `401 Unauthorized` | Token、客户端 Header、环境变量加载 |
| `502 Bad Gateway` | Nginx 上游地址、监听网卡、Docker 网络/防火墙 |
| TLS hostname mismatch | 证书 SAN 是否包含当前 MCP 域名 |
| MCP initialize fails | 服务端 SDK/ASGI 生命周期、请求路径、协议兼容性 |
| Tool permission denied | Linux 用户、Docker Socket、systemd 沙箱 |
| 只有本地执行结果 | Agent 未调用远程 MCP 工具 |

有关暴露面、Token 管理、权限和审计，请继续阅读 [安全指南](security.md)。
