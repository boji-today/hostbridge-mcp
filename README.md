# HostBridge MCP

**Secure remote host operations for local AI agents.**

[English](#english) | [简体中文](#简体中文)

> **Project status: Design / early development.** This repository describes the intended architecture. Features marked *planned* are not yet implemented or production-tested. Do not expose an unrestricted host command executor to the public internet.

## English

### Overview

HostBridge MCP aims to let locally operated AI agents such as Codex and Cursor administer remote Linux hosts through the Model Context Protocol (MCP), without placing model credentials or AI inference services on the remote machine.

The remote host is an execution endpoint, not an AI model host. A local agent decides what to do; the remote MCP service authenticates requests, executes permitted operations, and returns results.

### Design goals

- **Local-first AI:** Model authentication, API keys, and agent orchestration stay on the user's computer.
- **Host-native execution:** Operate on the real Linux host, not an isolated Docker container or an SSH loopback from a container.
- **Secure access:** HTTPS, per-user authentication, least privilege, auditing, and network access controls.
- **Operational control:** Shell commands, configuration files, Docker, services, logs, and processes, subject to explicit authorization.
- **Resilient operations:** Planned durable jobs with IDs and status tracking for disruptive actions such as restarting Docker or Nginx.
- **Legacy-friendly deployment:** Prefer isolated runtimes and systemd, without changing the operating system's default Python.

### Architecture

```text
Local workstation                      Remote Linux host
+-------------------------+           +--------------------------------+
| Codex / Cursor          |           | Existing HTTPS Nginx proxy     |
| AI model & credentials  | -- HTTPS ->| Authentication / access rules  |
| MCP client              |           +----------------+---------------+
+-------------------------+                            |
                                                      | MCP Streamable HTTP
                                      +---------------v----------------+
                                      | HostBridge MCP (systemd)       |
                                      | Authorized host tools         |
                                      +---------------+----------------+
                                                      |
                                      +---------------v----------------+
                                      | Host Shell / Files / Docker   |
                                      | systemd / Logs / Job runner*  |
                                      +--------------------------------+

* Durable job runner is planned.
```

### Planned capabilities

| Area | Intended capability | Status |
| --- | --- | --- |
| MCP transport | Streamable HTTP behind Nginx HTTPS | Planned |
| Authentication | Individual credentials and access policies | Planned |
| Host tools | Execute commands; read and update authorized files | Planned |
| Operations | Docker, systemd, process and log management | Planned |
| Durable jobs | Submit, inspect and reconcile long-running jobs | Planned |
| Audit | Record actor, operation, time and result | Planned |
| Deployment | systemd service and versioned configuration | Planned |

### Deployment approach

The initial target is a CentOS 7 host with an existing Dockerized Nginx HTTPS reverse proxy. The intended application runtime is an isolated Python 3.11 environment managed by `uv`; the existing system Python remains untouched. Other supported Linux distributions and a native compiled build may be evaluated later.

A proposed deployment layout (not yet a working installer):

```text
/opt/remote-mcp/           # Application and isolated runtime
/etc/remote-mcp.env        # Restricted service configuration
/etc/systemd/system/       # systemd service definition
```

No production installation command is published until the server implementation, authentication checks and deployment scripts are available and tested.

### Security model

HostBridge MCP is intended to manage powerful system capabilities. Treat its credentials like administrator credentials.

- Require explicit authorization from the owner or operator of every managed host.
- Enforce HTTPS and authentication **before** any tool executes.
- Use a dedicated non-root service account and narrowly scoped privileged operations; avoid unrestricted `sudo`, Docker socket exposure, and privileged containers.
- Restrict network reachability; a hidden hostname or URL path is not an access control.
- Validate inputs, cap resource usage, and record security-relevant operations.
- Do not assume a job failed merely because the HTTP connection dropped. Reconcile durable job state before retrying.
- Do not treat this as a secure production administration service until access controls and recovery paths have been independently tested.

**Data handling:** The remote server does not need model API keys. However, a local cloud-backed agent may send remote command outputs or file contents to its model provider. Obtain the appropriate approval before using it with confidential infrastructure.

### Roadmap

- [ ] Minimal host-native MCP endpoint and local client compatibility tests
- [ ] HTTPS reverse proxy deployment guide
- [ ] Authentication and authorization with per-user credentials
- [ ] Restricted command and file tools
- [ ] Docker and systemd operations
- [ ] Durable, auditable jobs for disruptive operations
- [ ] Installation, rollback and recovery tests on supported Linux versions

### Technology

Model Context Protocol (Streamable HTTP), Nginx, Linux systemd, uv and an isolated Python runtime are the initial intended components. The implementation language may change without changing the project goals.

### License

**To be determined.** A license file will be added before publishing code for reuse. Until then, do not assume an open-source license is granted.

---

## 简体中文

**让本地 AI Agent 安全地操作远程 Linux 宿主机。**

> **项目状态：设计与早期开发。** 本仓库目前描述目标架构；标记为“计划中”的能力尚未实现或完成生产验证。不要将具备任意宿主机命令执行能力的接口直接暴露到公网。

### 项目简介

HostBridge MCP 旨在让本地运行的 Codex、Cursor 等 AI Agent 通过模型上下文协议（MCP）管理远程 Linux 主机，**远端不登录模型服务、不存储模型 API Key，也不承担模型推理**。

本地 Agent 负责分析与决策；远程 MCP 服务负责认证、授权、执行宿主机操作并返回结果。

### 设计目标

- **模型留在本地：** 模型凭证、Agent 控制与模型调用留在用户电脑上。
- **宿主机原生执行：** 直接操作真实 Linux 主机，不依赖容器内部 Shell 或容器回连宿主机 SSH。
- **安全访问：** HTTPS、独立用户认证、最小权限、操作审计和网络访问限制。
- **完整运维能力：** 在明确授权下管理 Shell、配置文件、Docker、系统服务、日志和进程。
- **可靠的长任务：** 计划支持带 Job ID 的持久化任务，处理重启 Docker、Nginx 等可能中断连接的操作。
- **兼容旧系统：** 优先采用独立运行环境与 systemd，不覆盖系统默认 Python。

### 架构

```text
本地电脑                                    远程 Linux 宿主机
+-------------------------+           +--------------------------------+
| Codex / Cursor          |           | 现有 Nginx HTTPS 反向代理      |
| 模型凭证与 Agent 决策    | -- HTTPS ->| 身份认证 / 网络访问控制       |
| MCP Client              |           +----------------+---------------+
+-------------------------+                            |
                                                      | MCP Streamable HTTP
                                      +---------------v----------------+
                                      | HostBridge MCP（systemd）     |
                                      | 已授权的宿主机操作工具       |
                                      +---------------+----------------+
                                                      |
                                      +---------------v----------------+
                                      | Shell / 文件 / Docker        |
                                      | systemd / 日志 / 作业执行器* |
                                      +--------------------------------+

* 持久化作业执行器为计划功能。
```

### 计划功能

| 模块 | 目标能力 | 状态 |
| --- | --- | --- |
| MCP 接口 | 经 Nginx HTTPS 转发的 Streamable HTTP | 计划中 |
| 身份认证 | 独立访问凭证与权限策略 | 计划中 |
| 宿主机工具 | 执行命令、读写授权范围内的文件 | 计划中 |
| 运维工具 | Docker、systemd、进程与日志管理 | 计划中 |
| 持久化作业 | 提交、查询和核对长任务状态 | 计划中 |
| 安全审计 | 记录执行者、操作、时间与结果 | 计划中 |
| 部署 | systemd 服务及版本化配置 | 计划中 |

### 部署方向

第一阶段目标环境为 **CentOS 7 + 已有的 Nginx Docker HTTPS 反向代理**。计划使用 `uv` 管理独立 Python 3.11 环境，不替换系统原有 Python。后续再评估其他 Linux 发行版和原生编译版本。

建议目录（目前不是已完成的安装器）：

```text
/opt/remote-mcp/           # 程序和独立运行环境
/etc/remote-mcp.env        # 限权的服务配置
/etc/systemd/system/       # systemd 服务配置
```

在 MCP 服务、身份认证和部署脚本完成测试以前，暂不发布声称可以直接用于生产环境的一键安装命令。

### 安全原则

- 只能管理已明确授权的主机。
- 任何工具调用前必须完成 HTTPS 传输和身份认证。
- 优先使用专用非 root 用户和精确授权；避免无约束 sudo、直接暴露 Docker Socket 或使用特权容器。
- 通过网络访问控制减少暴露面，不把隐藏域名或路径当作安全措施。
- 限制命令资源消耗，记录关键管理操作。
- HTTP 连接中断不意味着操作失败；重试前应检查作业最终状态。
- 在认证、权限与恢复机制通过测试前，不应将其视为生产级远程管理系统。

**数据提醒：** 远端不保存模型 Key，但本地 Agent 如使用云端模型，可能把读取到的文件内容和命令输出提交给模型服务商。管理公司或其他敏感环境前必须获得相应许可。

### 路线图

- [ ] 实现宿主机原生 MCP 接口并测试客户端兼容性
- [ ] 编写 Nginx HTTPS 接入文档
- [ ] 实现独立用户身份认证与权限校验
- [ ] 提供受限 Shell 和文件工具
- [ ] 增加 Docker 与 systemd 运维工具
- [ ] 增加可审计的持久化作业
- [ ] 验证 Linux 兼容性、安装、回滚与故障恢复

### 技术路线

首期计划采用 MCP Streamable HTTP、Nginx、Linux systemd、uv 和独立 Python 运行环境。未来可以替换实现语言，而不改变项目目标。

### 许可证

**待确定。** 正式发布可复用代码前将补充 LICENSE 文件；在此之前不默认授予开源使用许可。
