# HostBridge MCP

**Remote Linux host operations for locally controlled AI agents.**  
**让本地 AI Agent 通过 MCP 操作远程 Linux 宿主机。**

[English](#english) | [简体中文](#简体中文)

> **Status / 状态:** Early functional prototype / 早期可运行原型。Not independently security-audited or production-hardened. / 尚未经过独立安全审计或生产级加固。
>
> **Warning / 警告:** Enabling arbitrary shell execution can grant effective administrator-level access if the service user can control Docker or use privileged commands. Do not expose this endpoint without strong authentication, trusted HTTPS, network restrictions, and explicit host-owner authorization. / 开启任意 Shell 执行后，如果服务账号能管理 Docker 或运行特权命令，实际上可能取得宿主机管理员权限。必须获得主机所有者授权，并配置 HTTPS、认证和网络访问控制。

---

## English

### Overview

HostBridge MCP is a **host-native MCP server** that lets an AI agent running on your own computer use tools on a remote Linux machine via **MCP Streamable HTTP**. It can sit behind an existing Dockerized Nginx HTTPS reverse proxy.

**Model access stays on the client:** The remote server does not need Codex, Cursor, a model-provider login, or a model API key. The local agent decides which remote tools to call. Remote file contents and command output may nevertheless be sent to the local agent's cloud model provider; follow your organization's data policy.

Connecting the MCP server **does not** automatically make an agent's built-in local terminal or file editor operate remotely. The agent must explicitly call the HostBridge MCP tools.

### Architecture

```text
Local computer                             Remote Linux host
+---------------------------+              +-------------------------------+
| Cursor / Codex            |              | Existing Nginx (Docker)       |
| Model login and API keys  |--- HTTPS --->| TLS / network access control  |
| MCP client                |  Bearer token+---------------+---------------+
+---------------------------+                              |
                                               MCP Streamable HTTP
                                              +------------v-------------+
                                              | HostBridge MCP           |
                                              | Python / systemd         |
                                              | Dedicated Linux account  |
                                              +------------+-------------+
                                                           |
                                              +------------v-------------+
                                              | Files / Shell / Docker*   |
                                              +--------------------------+
* Docker and privileged operations depend on the service account's permissions.
```

### Implemented tools

The current `src/hostbridge_mcp/server.py` exposes the following tools:

| Tool | Purpose |
| --- | --- |
| `execute_command` | Execute a Bash command with a timeout and bounded returned output; disabled by default |
| `read_file` | Read UTF-8 files under the configured file root |
| `write_file` | Write UTF-8 files, with explicit overwrite and temporary-file replacement |
| `list_directory` | List files and directories |
| `file_info` | Inspect size, type, mode, and modification time |
| `create_directory` | Create directories |
| `delete_file` | Delete a regular file |

The server currently uses a **single static Bearer token**, basic filesystem path checks, a service-user security boundary, and systemd/Nginx deployment templates. These are **not** a complete multi-user authorization system, filesystem sandbox, or tamper-resistant audit facility. Docker and systemd have **no separate first-class MCP tools** at present; their commands can only be invoked through `execute_command` when enabled and permitted.

### Deployment conventions

| Item | Convention |
| --- | --- |
| Repository | `hostbridge-mcp` |
| Python package | `hostbridge_mcp` |
| ASGI entry point | `hostbridge_mcp.server:app` |
| systemd unit | `hostbridge-mcp.service` |
| Service account | `hostbridge` |
| Repository directory | `/opt/hostbridge-mcp` |
| Environment file | `/etc/hostbridge-mcp.env` |
| Server authentication variable | `MCP_ACCESS_TOKEN` |
| Client authentication variable | `HOSTBRIDGE_MCP_TOKEN` |
| Example MCP URL | `https://mcp.example.com/mcp` |
| Client MCP registration name | `hostbridge` |

`mcp.example.com` is an **example**, not a hosted service. Use your own hostname and a trusted TLS certificate whose Subject Alternative Name covers it.

### Installation and configuration

See [Installation and deployment](docs/installation.md) for the full walkthrough and the templates in [`deploy/`](deploy/). A typical deployment places the Python service on the **host** under systemd and uses the already-running **Nginx container** as an HTTPS reverse proxy.

1. Install a compatible Python environment and the project's dependencies; ensure `hostbridge_mcp.server:app` imports successfully.
2. Create the dedicated `hostbridge` Linux account and the configured workspace.
3. Copy `deploy/env/hostbridge-mcp.env.example` to `/etc/hostbridge-mcp.env`; generate a strong random `MCP_ACCESS_TOKEN`, and restrict the file to administrators.
4. Review the systemd template before installation. Use `WorkingDirectory=/opt/hostbridge-mcp` for the repository layout and adapt `ExecStart` to the installed Python environment.
5. Make the MCP listener reachable by Nginx **without** publishing its port publicly. With Nginx in Docker bridge networking, `127.0.0.1` inside that container is **not** the host machine.
6. Configure HTTPS, upstream routing and network access restrictions in Nginx. Test certificate validation **without** `curl -k`.
7. Start `hostbridge-mcp.service` and verify MCP initialization with an authenticated client. Enable shell access only after security review.

**Packaging note:** Do not run `uv sync --locked` unless the repository actually includes a matching `pyproject.toml` and `uv.lock`. If these files have not yet been committed, prepare/install the virtual environment following [the installation guide](docs/installation.md) and verify the Python import before starting systemd. The repository is not advertised as a one-command production installer.

### Client configuration

**Cursor** — a typical local `~/.cursor/mcp.json` entry:

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

Set `HOSTBRIDGE_MCP_TOKEN` in the **local Cursor environment** to the same secret as `MCP_ACCESS_TOKEN` on the server, and restart Cursor. Verify environment-variable substitution in your Cursor version. Never commit a real token.

**Codex CLI** — run locally:

```bash
export HOSTBRIDGE_MCP_TOKEN='<your-secret>'
codex mcp add hostbridge \
  --url https://mcp.example.com/mcp \
  --bearer-token-env-var HOSTBRIDGE_MCP_TOKEN
codex mcp list
```

See the client examples under [`deploy/clients/`](deploy/clients/) and confirm their placeholders match your deployment; examples in this README represent the **recommended normalized configuration** and may differ from older templates in the repository.

### Security and limitations

- Deploy only to machines that you are authorized to administer.
- Require a certificate valid for the **actual MCP hostname**. `curl -k` only bypasses a diagnostic failure and is not an acceptable permanent solution.
- Restrict the public entry point with approved source-IP rules or another identity-aware access layer, **in addition to** the MCP token. Hidden paths are not access controls.
- The current token implementation is shared/static; it does **not** provide user-specific identities, permission policies, token rotation, or per-user audit.
- `MCP_FILE_ROOT` constrains the **file tools**, but **does not sandbox** arbitrary shell commands. Commands run as the service's Linux user and may access other permitted files and processes.
- Docker daemon access is effectively host-administrator access. Avoid granting it casually, including via the `docker` group or `/var/run/docker.sock`.
- The current command executor inherits process environment variables; **do not enable `execute_command` on a sensitive deployment until secret filtering and execution isolation are reviewed**.
- Do not assume an interrupted HTTP connection means the remote action failed. Durable job tracking, safe retries and robust recovery are not yet implemented.
- File operation checks are not a complete defense against symlink races or other adversarial filesystem conditions.

Further operational notes: [Installation](docs/installation.md). A dedicated security document may be added as the project matures.

### Roadmap

- [x] Host-native Streamable HTTP MCP server
- [x] Basic Bearer-token authentication
- [x] File and directory tools
- [x] Optional command execution with timeouts
- [x] Example systemd, Nginx and client configuration files
- [ ] Reproducible, tested Python package/lockfile installation
- [ ] Per-user identity, scoped authorization and token lifecycle
- [ ] Secret-filtered execution and stronger filesystem/process isolation
- [ ] Dedicated Docker/service management tools with approval controls
- [ ] Durable jobs, idempotent operations and recovery after disconnects
- [ ] Automated tests, multi-distribution compatibility and security review

### License

Licensed under the [MIT License](LICENSE).

---

## 简体中文

### 项目简介

HostBridge MCP 是一个运行在 **Linux 宿主机**上的 MCP 服务，通过 **MCP Streamable HTTP** 将远程文件和命令执行能力提供给本地 Cursor、Codex 等 AI Agent。可以复用现有运行在 Docker 中的 Nginx HTTPS 反向代理。

**模型认证与调用留在本地：** 远端不必安装 Codex、Cursor，不需要登录任何模型供应商，也不需要保存模型 API Key。本地 Agent 负责推理、决策和调用远端工具。但若本地 Agent 使用云端模型，读取到的配置、文件和命令输出仍可能发送给模型服务商，应遵守所在组织的数据安全规定。

**注意：** 添加远程 MCP 并不会让 Cursor/Codex 内置的本地 Shell 或文件编辑工具自动切换至 VPS。必须明确使用 HostBridge MCP 的远端工具。

### 系统架构

```text
本地电脑                                     远程 Linux 宿主机
+---------------------------+              +-------------------------------+
| Cursor / Codex            |              | 现有 Nginx Docker             |
| 本地模型登录与 API Key     |--- HTTPS --->| TLS / 网络访问限制             |
| MCP Client                |  Bearer Token+---------------+---------------+
+---------------------------+                              |
                                               MCP Streamable HTTP
                                              +------------v-------------+
                                              | HostBridge MCP           |
                                              | Python / systemd         |
                                              | 独立 Linux 账号           |
                                              +------------+-------------+
                                                           |
                                              +------------v-------------+
                                              | 文件 / Shell / Docker*   |
                                              +--------------------------+
* Docker 和特权操作受 Linux 服务账号权限控制。
```

### 当前已实现的工具

当前 `src/hostbridge_mcp/server.py` 暴露以下 MCP 工具：

| 工具 | 功能 |
| --- | --- |
| `execute_command` | 执行 Bash 命令，支持超时与返回输出限制；默认关闭 |
| `read_file` | 在配置的文件根目录下读取 UTF-8 文本 |
| `write_file` | 写入 UTF-8 文件，覆盖需显式指定，采用临时文件替换 |
| `list_directory` | 列出目录内容 |
| `file_info` | 查询文件类型、大小、权限和修改时间 |
| `create_directory` | 创建目录 |
| `delete_file` | 删除普通文件 |

当前实现包含**单个静态 Bearer Token**、基础路径检查、Linux 账号权限以及 systemd/Nginx 部署模板。这些能力**不等于**完整的多用户授权、文件系统沙箱或不可篡改的审计系统。目前尚无专用 Docker/systemd MCP 工具；只能在明确启用 `execute_command` 且服务账号有权限时，通过 Shell 间接管理。

### 统一命名与部署约定

| 项目 | 约定 |
| --- | --- |
| 仓库名 | `hostbridge-mcp` |
| Python 包名 | `hostbridge_mcp` |
| ASGI 入口 | `hostbridge_mcp.server:app` |
| systemd 服务 | `hostbridge-mcp.service` |
| Linux 用户 | `hostbridge` |
| 仓库部署路径 | `/opt/hostbridge-mcp` |
| 环境文件 | `/etc/hostbridge-mcp.env` |
| 服务端 Token 环境变量 | `MCP_ACCESS_TOKEN` |
| 客户端 Token 环境变量 | `HOSTBRIDGE_MCP_TOKEN` |
| 示例 MCP 地址 | `https://mcp.example.com/mcp` |
| 客户端 MCP 注册名称 | `hostbridge` |

`mcp.example.com` 仅为示例，请替换为自己的域名，并确保 HTTPS 证书的 SAN 覆盖该域名。

### 安装与部署

请参阅 [完整安装文档](docs/installation.md) 和 [`deploy/` 示例配置](deploy/)。建议将 Python MCP 服务以 systemd 方式**部署在宿主机**，继续由现有 Nginx Docker 负责 HTTPS 反向代理。

1. 准备兼容的 Python 环境、安装依赖，并验证 `hostbridge_mcp.server:app` 能正确导入。
2. 创建专用的 `hostbridge` Linux 账号及工作目录。
3. 将 `deploy/env/hostbridge-mcp.env.example` 复制到 `/etc/hostbridge-mcp.env`，生成高强度随机 `MCP_ACCESS_TOKEN`，限制文件权限。
4. 安装前核对 systemd 模板。按照仓库布局使用 `WorkingDirectory=/opt/hostbridge-mcp`，并根据实际 Python 环境修改 `ExecStart`。
5. 确保 Nginx 能访问 MCP 内部监听地址，但**不要把 MCP 端口直接发布到公网**。Nginx 使用 Docker bridge 网络时，容器里的 `127.0.0.1` 并非宿主机地址。
6. 配置 Nginx HTTPS、上游转发与网络访问限制。验证证书时不要使用 `curl -k` 绕过校验。
7. 启动 `hostbridge-mcp.service`，使用带认证的 MCP 客户端验证初始化及工具调用。完成安全检查后再考虑启用 Shell。

**打包说明：** 只有仓库实际包含相互匹配的 `pyproject.toml` 与 `uv.lock` 时，才能直接运行 `uv sync --locked`。若尚未提交这些文件，应按[安装文档](docs/installation.md)准备虚拟环境并验证模块导入。当前项目不宣称已提供一键生产部署安装器。

### 本地客户端配置

**Cursor** — 本地 `~/.cursor/mcp.json` 示例：

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

在本地设置 `HOSTBRIDGE_MCP_TOKEN`，它的**值**应与 VPS 的 `MCP_ACCESS_TOKEN` 一致。完整重启 Cursor，并检查当前版本是否正确展开环境变量。不要将真实 Token 提交到 Git。

**Codex CLI** — 在本地电脑执行：

```bash
export HOSTBRIDGE_MCP_TOKEN='<your-secret>'
codex mcp add hostbridge \
  --url https://mcp.example.com/mcp \
  --bearer-token-env-var HOSTBRIDGE_MCP_TOKEN
codex mcp list
```

可参考 [`deploy/clients/`](deploy/clients/) 的客户端示例。README 展示的是**推荐统一配置**；仓库中如果仍有旧版模板，应同步修改其注册名称、域名与 Token 变量占位符。

### 安全与限制

- 只能部署在已取得明确管理授权的主机上。
- HTTPS 证书必须匹配**实际访问域名**；`curl -k` 仅适合临时诊断，不能作为正式客户端配置的替代办法。
- 公网入口应同时采用网络层白名单或获批准的身份网关以及 MCP Token 认证。隐藏域名或路径不等于安全措施。
- 当前为**共享静态 Token**，尚不支持独立用户身份、细粒度权限策略、Token 生命周期管理和完整用户级审计。
- `MCP_FILE_ROOT` 只限制对应的**文件工具**，**不会隔离任意 Shell 命令**。Shell 的实际能力由服务运行账号权限决定。
- 能访问 Docker daemon 通常等同于取得宿主机管理员权限，不应轻易授予 `docker` 用户组或 Docker Socket 访问权限。
- 当前命令执行器会继承服务进程环境变量；**在完成密钥过滤与执行隔离审查前，不应在敏感环境启用 `execute_command`**。
- HTTP 连接中断不能证明远端命令执行失败。持久化任务、可靠重试和异常恢复仍在规划中。
- 现有文件检查不是针对符号链接竞争等恶意文件系统情境的完整安全隔离。

更多部署注意事项参阅 [安装文档](docs/installation.md)。专门的安全文档将在项目后续完善。

### 开发路线图

- [x] 宿主机原生的 Streamable HTTP MCP 服务
- [x] 基础 Bearer Token 认证
- [x] 文件与目录工具
- [x] 可选 Shell 执行及超时限制
- [x] systemd、Nginx 和客户端配置模板
- [ ] 可复现、经过测试的 Python 包和锁文件安装
- [ ] 独立用户身份、细粒度授权和 Token 生命周期管理
- [ ] 命令执行密钥过滤与更强的文件系统、进程隔离
- [ ] 带人工批准机制的专用 Docker/系统服务管理工具
- [ ] 持久化任务、幂等操作与断连恢复
- [ ] 自动化测试、多发行版兼容性与安全审计

### 许可证

本项目采用 [MIT License](LICENSE)。
