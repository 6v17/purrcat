# 后端 API 参考（src/server）

覆盖 `src/server` 下的全部接口。**只描述当前接口，不含历史/兼容别名。**

## 模块总览

| 模块 | 前缀 | 端点数 |
| --- | --- | --- |
| [webmin.py](#1-极简模式插件系统-apiwebmin) | `/api/webmin` | 9 |
| [chat.py](#2-会话与对话-apichat--apisessions) | `/api` | 17 |
| [config.py](#3-配置-apiconfig) | `/api/config` | 31 |
| [tools.py](#4-工具-apibtools) | `/api/tools` | 23 |
| [filesystem.py](#5-文件系统-apifilesystem) | `/api/filesystem` | 12 |
| [evolve.py](#6-进化工厂-apievolve) | `/api/evolve` | 12 |
| [system.py](#7-系统-apisystem) | `/api/system` | 10 |
| [task.py](#8-任务-apitasks) | `/api/tasks` | 10 |
| [memory.py](#9-记忆-apimemory) | `/api/memory` | 9 |
| [graph.py](#10-图谱-apigraphs) | `/api/graphs` | 5 |
| [paradigms.py](#11-范式-apiparadigms) | `/api/paradigms` | 4 |
| [request.py](#12-待办请求-apirequests) | `/api/requests` | 4 |
| [acp.py](#13-acp-网关-acp) | `/acp` | 4 |
| [terminal.py](#14-终端-websocket) | `/api/terminal` | 1（WS） |
| [main.py](#15-通用) | — | 1 |

> 极简模式宿主与 UI 插件的接入方式见 §1、§16。

---

## 1. 极简模式插件系统 `/api/webmin/*`

宿主专用。插件一般经 `callAction` 间接使用。

### GET `/api/webmin/manifest`
返回当前扫描到的全部插件。新增插件后无需重启即可感知（前端 `Ctrl+R`）。

```json
{
  "plugins": [
    {
      "id": "builtin-history", "name": "历史", "icon": "history",
      "slot": "panel", "slotDef": { "type": "panel", "area": "panel" },
      "entry": "index.html",
      "configSchema": [], "config": {},
      "builtin": true, "backend": { "kind": "npm" } | null,
      "root": "builtin|sandbox|user|", "origin": "builtin|sandbox|user|", "rootOk": true,
      "dependency": [{ "type": "skill", "id": "xxx" }]
    }
  ],
  "rail": { "stage": 1, "hidden": {}, "opacity": 1 },
  "panelContainer": {},
  "active": { "panel": "builtin-history" }
}
```

### GET `/api/webmin/plugin/{plugin_id}/{path}`
读取插件目录内静态文件（热插拔核心）。`path` 省略时回退到 `entry`。做了路径穿越校验，`../` 一律 `404`。

### GET `/api/webmin/plugin-dir/{plugin_id}/{path}`
列出插件目录内**一层**子项（不含文件内容），供插件扫描自身数据目录。

```json
{ "path": "data", "entries": [{ "name": "a.json", "isDir": false }] }
```

### POST `/api/webmin/plugin-rpc/{plugin_id}/{handler}`
调用插件自带后端子进程（`server/server.js`）的 handler。请求体 `{ "payload": {}, "timeout": 30 }`，返回 `{ "status": "ok", "result": ... }`。

### POST `/api/webmin/plugin/{plugin_id}/delete`
删除插件：用户/沙盒插件移动为同根目录下 `<id>.trash`（可恢复），**内置插件返回 403**。

### GET `/api/webmin/config`
读取宿主配置：`{ "plugins": { "<plugin_id>": {...} } }`。

### PUT `/api/webmin/config`
按分节更新，未提供的分节保持原值（避免局部保存清空其它分节）。

```json
{ "plugins": { "id": {} }, "rail": { "stage": 0-2, "opacity": 0-1, "hidden": {} }, "active": { "panel": "id|__none__" } }
```

### POST `/api/webmin/wallpaper`
把用户选中的本地壁纸复制进托管目录 `~/.purrcat/webmin-wallpapers`。请求 `{ "path": "<本地绝对路径>" }`，返回 `{ "status": "ok", "filename": "...", "url": "/api/webmin/wallpaper/<filename>" }`。

### GET `/api/webmin/wallpaper/{filename}`
静态托管已导入的壁纸文件。

---

## 2. 会话与对话 `/api/chat` · `/api/sessions`

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/sessions` | 会话列表 |
| POST | `/api/sessions/new` | 新建会话 |
| GET | `/api/sessions/{session_id}` | 读取某分支聊天历史（query `branch_id`，默认 `main`） |
| GET | `/api/sessions/{session_id}/branches` | 该会话全部子分支元数据 |
| PUT | `/api/sessions/{session_id}/rename` | 重命名会话 |
| POST | `/api/sessions/{session_id}/checkout` | 检出/切换分支 |
| POST | `/api/sessions/{session_id}/branch` | 新建子分支 |
| DELETE | `/api/sessions/{session_id}/branches/{branch_id}` | 删除分支 |
| DELETE | `/api/sessions/{session_id}` | 删除会话 |
| GET | `/api/sessions/{session_id}/status` | 轻量轮询：后台 Agent 是否仍活跃 |
| GET | `/api/sessions/{session_id}/paradigm` | 读取会话当前绑定 Agent Loop（`{paradigm}`，空串=默认） |
| POST | `/api/sessions/{session_id}/paradigm` | 热切换 Agent Loop（只换循环逻辑，保留 KV Cache） |
| POST | `/api/chat` | 发送单条消息 |
| POST | `/api/chat/batch` | 批量发送 |
| POST | `/api/chat/interrupt` | 人类强制打断：物理掐断正在执行的工具 |
| POST | `/api/chat/compress-memory` | 手动触发记忆压缩：全局大总结并截断上下文 |
| GET | `/api/agent/token` | 获取上下文 Token 使用进度（query `session_id`） |

---

## 3. 配置 `/api/config`

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET / PUT | `/api/config/model` | 读取 / 更新模型配置 |
| GET / PUT | `/api/config/sensor` | 读取 / 更新传感器配置 |
| POST | `/api/config/sensor/reload` | 停掉所有 Sensor 进程并按配置重新拉起启用项 |
| GET / PUT | `/api/config/file` | 读取 / 更新文件配置 |
| GET / PUT | `/api/config/mcp` | 读取 / 更新 MCP 配置 |
| POST | `/api/config/mcp/reload` | 重新握手所有 MCP Server（新增即时拉起、改配置自动重启） |
| GET / PUT | `/api/config/app` | 读取 / 更新应用配置 |
| GET | `/api/config/acp` | ACP 接入状态：relay 部署情况 / 端口 / uv 可用性 |
| PUT | `/api/config/acp` | 更新 ACP 接入设置（当前仅后端端口 `acp_port`） |
| POST | `/api/config/acp/redeploy` | 重新部署 relay 脚本（文件被误删 / 版本落后时一键修复） |
| POST | `/api/config/acp/reset-token` | 重置 ACP 网关 token（旧令牌立即失效，relay 需重启重连） |
| GET | `/api/config/deploy` | 各依赖项就绪状态 + 部署任务进度与日志（前端轮询） |
| POST | `/api/config/deploy/{item}` | 一键部署指定依赖项（后台线程，进度走 GET /deploy 轮询） |
| GET / PUT | `/api/config/sandbox-registry` | 沙箱镜像 registry 前缀（留空=自动依次尝试官方与公共源） |
| GET / PUT | `/api/config/markdown/{filename}` | 读取 / 保存 `SOUL.md`、`GOAL.md`（`filename` 仅允许 `SOUL`、`GOAL`） |
| GET | `/api/config/info` | 读取 `.purrcat/core/info.json`（提供 skills、workshops 列表） |
| GET / PUT | `/api/config/cron` | 读取 / 更新定时配置 |
| GET | `/api/config/meta` | 返回当前生效的路径常量（供前端展示） |
| GET | `/api/config/setup-status` | 首启引导：数据盘是否已配置 |
| POST | `/api/config/setup-data-root` | 首次启动设置数据盘（仅首启引导） |
| POST | `/api/config/change-data-root` | 随时更改数据根目录：搬迁数据、落盘配置、销毁旧沙盒，前端随后重启生效 |

---

## 4. 工具 `/api/tools`

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/tools/skills` | 获取内存里的 Skill 名称与描述 |
| POST | `/api/tools/skills/install` | 按 GitHub URL 下载第三方 Skill 并热更新内存 |
| POST | `/api/tools/skills/install-batch` | 批量安装（同一仓库 zip 只下载一次） |
| POST | `/api/tools/skills/uninstall` | 删除本地已安装 Skill（目录名或 `SKILL.md` 的 name 匹配） |
| POST | `/api/tools/skills/refresh` | 手动扫描本地 Skill 文件夹并更新内存检索树 |
| GET | `/api/tools/mcp` | 获取内存/缓存里的 MCP 服务器及其工具名与描述 |
| GET | `/api/tools/mcp/list` | 返回 `mcp_config.json` 中已配置的 MCP Server 名称列表 |
| POST | `/api/tools/mcp/install` | 解析合并 MCP Server JSON 配置，落盘并热更新（官方 MCP 额外下载源码） |
| POST | `/api/tools/mcp/uninstall` | 从配置移除该 Server，清理本地源码并热更新 Schema |
| POST | `/api/tools/mcp/refresh` | 手动刷新 MCP Schema 并更新内存检索树 |
| GET | `/api/tools/cron` | 读取 `cron.json` 返回现有闹钟列表 |
| POST | `/api/tools/cron` | 添加闹钟 |
| DELETE | `/api/tools/cron/{identifier}` | 删除闹钟（支持传 id 或 title） |
| GET / POST | `/api/tools/heartbeat` | 读取心跳配置 + `GOAL.md` / 保存心跳（开启时必须提交非空 GOAL） |
| GET | `/api/tools/market/sensors` | 从官方 `PurrPod/sensors` 拉取 `registry.json` 给前端市场 |
| GET | `/api/tools/market/sensors/installed` | 已配置（不论 enabled）的传感器名列表 |
| POST | `/api/tools/market/sensors/install` | 安装 Sensor（支持覆盖式重新下载） |
| POST | `/api/tools/market/sensors/uninstall` | 从配置移除 Sensor 并删除本地代码 |
| GET | `/api/tools/market/graphs` | 从官方 `PurrPod/graphs` 拉取 `registry.json` 给前端市场 |
| GET | `/api/tools/market/graphs/installed` | 已安装 Graph（文件夹结构）名字列表 |
| POST | `/api/tools/market/graphs/install` | 安装 Graph（文件夹结构） |
| POST | `/api/tools/market/graphs/uninstall` | 删除 `{GRAPHS_DIR}/{name}` 文件夹 |
| GET | `/api/tools/market/ui-plugins` | 从官方 `PurrPod/ui-plugins` 拉取 `registry.json` 给前端市场 |
| GET | `/api/tools/market/ui-plugins/installed` | 已安装 UI 插件（用户根 `~/.purrcat/webmin-plugins`）名字列表 |
| POST | `/api/tools/market/ui-plugins/install` | 安装 UI 插件（含依赖 skill/mcp/sensor/graph/agentloop/plugin 自动安装） |
| POST | `/api/tools/market/ui-plugins/uninstall` | 卸载 UI 插件（目录移入 `<id>.trash`） |

---

## 5. 文件系统 `/api/filesystem`

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/filesystem/list` | 列出目录内容，返回 `{ name, isDir, path }[]` |
| GET | `/api/filesystem/read` | 读取文件文本（`/agent_vm` 沙盒路径自动转换，含缺失层回退） |
| GET | `/api/filesystem/stat` | 文件元信息（大小），IDE 大文件拦截用 |
| POST | `/api/filesystem/write` | 写入文件文本（自动建父目录，沙盒路径自动转换） |
| GET | `/api/filesystem/history_list` | 直接读 `.agent_history`，返回真实存在的备份文件列表 |
| GET | `/api/filesystem/backups` | 校验哪些快照仍在硬盘上存活 |
| POST | `/api/filesystem/undo` | 前端一键回滚（最高权限） |
| POST | `/api/filesystem/ack` | 用户确认更改，删除磁盘备份 |
| POST | `/api/filesystem/ack_all` | 一键接受全部更改，清理全部备份 |
| GET | `/api/filesystem/diffs` | 全局读取所有未确认的代码变更（DiffView） |
| GET | `/api/filesystem/resolve` | 返回沙盒/相对路径对应的宿主机真实绝对路径 |
| GET | `/api/filesystem/preview` | 接收绝对路径，返回文件流供前端预览 |

---

## 6. 进化工厂 `/api/evolve`

`type` 参数指定加工厂类型（如 `skill`、`ui_plugin` 等）。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/evolve/list` | 扫描指定加工厂的沙盒列表（query `type`） |
| POST | `/api/evolve/init` | 初始化沙盒并分配 workplace |
| GET | `/api/evolve/file` | 读取沙盒内文件（query `workplace_id, name, type, filename`） |
| PUT | `/api/evolve/file` | 写入沙盒内文件 |
| POST | `/api/evolve/test/run` | 运行评测 |
| GET | `/api/evolve/test/iterations` | 列出评测轮次 |
| GET | `/api/evolve/test/report` | 读取某轮评测报告 |
| GET | `/api/evolve/test/benchmark` | 读取某轮体检的结构化结论（`benchmark.json`） |
| GET | `/api/evolve/diff` | 沙盒与源文件的差异 |
| POST | `/api/evolve/handle` | 处理进化请求 |
| POST | `/api/evolve/rollback` | 回滚 |
| DELETE | `/api/evolve/workplace/{workplace_id}` | 前端手动彻底删除工厂沙盒（query `type`） |

---

## 7. 系统 `/api/system`

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/system/env/detect` | 探测运行环境 |
| GET | `/api/system/env-status` | 环境状态（完整） |
| GET | `/api/system/env/status` | 环境状态（简化） |
| POST | `/api/system/env/install` | 触发环境安装 |
| GET | `/api/system/env/install/status` | 环境安装进度 |
| GET | `/api/system/image-status` | 镜像状态（query `image_name`） |
| POST | `/api/system/image/pull` | 拉取镜像 |
| GET | `/api/system/container-engine` | 容器引擎信息 |
| POST | `/api/system/agent/upload` | 上传单个文件到 `agent_vm/.buffer/upload`，供 Agent 读取 |
| GET | `/api/system/agent/stats` | 今日调用统计 + 热力图 |

---

## 8. 任务 `/api/tasks`

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/tasks` | 任务列表（合并磁盘与内存） |
| POST | `/api/tasks/run` | 创建并启动新任务（工作流名 + 初始参数，后台异步执行） |
| GET | `/api/tasks/{task_id}/state` | 统一状态 + 前端气泡所需的 memory（支持活跃/休眠任务） |
| POST | `/api/tasks/{task_id}/submit` | 注入人工指令（任务须在内存中活跃） |
| POST | `/api/tasks/{task_id}/push` | 精确注入：只向指定 Agent 节点注入（任务须活跃） |
| POST | `/api/tasks/{task_id}/nodes/{node_id}/reset` | 重置节点，触发级联清理及引擎重启 |
| POST | `/api/tasks/{task_id}/stop` | 优雅终止：只杀进程、保留 checkpoint 供查看 |
| GET | `/api/tasks/{task_id}/log` | 统一日志读取（直接读纯文本盘，不唤醒休眠引擎） |
| GET | `/api/tasks/{task_id}/artifact` | 按 `purrcat://` URI（或绝对路径兜底）返回产物文件（query `uri, mime`） |
| DELETE | `/api/tasks/{task_id}` | 物理删除任务（同时支持清理休眠与活跃任务） |

---

## 9. 记忆 `/api/memory`

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/memory/events` | 事件列表（SQLite + FTS5） |
| GET | `/api/memory/experiences` | 工作经验列表（VectorDB） |
| GET | `/api/memory/graph` | 记忆图谱 |
| GET | `/api/memory/search` | 搜索（query `q`） |
| DELETE | `/api/memory/experiences/{exp_id}` | 删除工作经验 |
| DELETE | `/api/memory/events/{event_id}` | 删除事件 |
| DELETE | `/api/memory/graph/relation` | 物理删除图谱关系边（query `source_node_id, target_node_id`） |
| GET / PUT | `/api/memory/markdown` | 读取 / 覆盖写入 `.purrcat/core/MEMORY.md` |

---

## 10. 图谱 `/api/graphs`

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/graphs` | Graph 列表，返回 `[{ name, path }]` |
| GET | `/api/graphs/nodes` | 所有可用节点类型定义 |
| GET | `/api/graphs/{name}` | 读取某个 Graph |
| GET | `/api/graphs/{name}/schema` | 工作流全局输入参数 Schema（前端据此动态生成表单） |
| POST | `/api/graphs/{name}` | 保存 Graph |

---

## 11. 范式 `/api/paradigms`

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/paradigms` | 列出 paradigms 目录下所有可编辑文件 |
| GET | `/api/paradigms/{name}` | 读取某 paradigm 的完整结构化内容（含 hooks） |
| POST | `/api/paradigms/{name}` | 整体写回（新建/保存同一接口）`{ "data": {...} }` |
| DELETE | `/api/paradigms/{name}` | 删除指定 paradigm（默认 `PARADIGM.yaml` 除外） |

---

## 12. 待办请求 `/api/requests`

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/requests` | 所有待处理请求（前端弹窗提示用） |
| POST | `/api/requests/{req_id}/resolve` | 前端点同意 / 拒绝 / 忽略时调用 |
| GET | `/api/requests/resolved` | 所有已处理完毕的请求 |
| DELETE | `/api/requests/{req_id}` | 彻底删除某请求记录 |

---

## 13. ACP 网关 `/acp`

对外接入网关，前缀为 `/acp`（非 `/api`）。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/acp/rpc` | JSON-RPC 2.0 单条分发（v1 不做 batch），直调 dispatch |
| GET | `/acp/stream` | SSE：按 ACP session 订阅对应 purrcat 会话的事件流（query `session`） |
| POST | `/acp/file` | multipart 上传：落 `agent_vm/sensor/files/acp/`，返回 sandbox 路径 |
| GET | `/acp/file` | 下载 sandbox 文件（仅允许 `/agent_vm` 前缀，防任意路径读取） |

---

## 14. 终端 WebSocket

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| WS | `/api/terminal/ws` | WebSocket 终端桥接（query `cmd`） |

---

## 15. 通用

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 健康检查 |

其它：

- 静态托管：`/minimal` → `ui/web-minimal`（极简宿主，附 `no-store` 中间件）。
- 生命周期：`shutdown` 事件会停止全部插件后端子进程。

---

## 16. 极简宿主与插件的接入方式

两条通道：

| 通道 | 适用 | 说明 |
| --- | --- | --- |
| **A. `callAction` 动作总线** | 插件 → 宿主（推荐） | `postMessage` 封装，宿主统一收口（原生能力、坐标换算、配置注入）。见下 |
| **B. 同源 `fetch('/api/...')`** | 插件直连后端（高级） | 插件 iframe 与宿主同源，可直接调用本文件任意 `/api/*`。稳定性自担 |

### `callAction` 协议
插件侧（iframe）唯一通道是 `postMessage`：

```js
var id = ++seq;
window.parent.postMessage(
  { type: 'callAction', id: id, actionId: 'state.get', payload: {} }, '*'
);
```

宿主 → 插件（`window.addEventListener('message', ...)`）：

| 消息 | 含义 |
| --- | --- |
| `{ type: 'callActionResult', id, ok, data \| error }` | 上一次 callAction 的结果，按 id 对应 |
| `{ type: 'configApply', config }` | 用户在设置面板改了配置 → 实时下发全量 config |
| `{ type: 'event', event, data }` | 宿主广播：`host.unmount`、`host.nativeCover`（`{covered}`）、`layout.empty`（`{empty}`）、`session.switched`、`branch.switched`、`config.updated` |

### actionId 清单
（payload 细节以 `ui/web-minimal/assets/host.js` 的 `dispatch` 为准）

| 分类 | actionId |
| --- | --- |
| 会话／对话 | `state.get`、`chat.send`、`chat.sendBatch`、`chat.interrupt`、`chat.traceToSkill`、`sessions.list`、`sessions.new`、`session.switch`、`session.rename`、`session.delete`、`session.branch`、`requests.list`、`requests.resolve` |
| 配置 | `config.get`（payload `{plugin_id}`）、`config.set`、`settings.meta`、`settings.open`、`settings.close` |
| 文件／数据 | `dialog.files`、`dialog.folder`、`dialog.pickWallpaper`、`ref.graphs` |
| 容器（float 插件） | `slot.move`、`slot.close`、`slot.hide` |
| 插件自身 | `plugin.delete`、`plugin.rpc`（`{plugin_id, handler, payload}`） |
| 内置浏览器（仅 Electron 主窗口） | `browser.available`、`browser.newTab`、`browser.closeTab`、`browser.navigate`、`browser.reload`、`browser.goBack`、`browser.goForward`、`browser.bounds`、`browser.hide`、`browser.locate`、`browser.pickStart`、`browser.pickEnd`、`browser.pickElement`、`browser.openExternal`、`browser.openUrl` |
| 其它 | `input.dropdown`（输入区下拉时告知宿主让位） |

---

## 17. 约束

- 插件只能引用**插件目录内**的文件；宿主的静态路由做了路径穿越校验。
- 插件 id 冲突按 `用户 > 沙盒 > 内置` 生效；想改造内置插件请另起 id。
- 宿主 CSS 变量**不跨 iframe 继承**，插件用 `var(--wm-*, fallback)` 自带兜底。
- 新增插件或改动 `plugin.json` 后，用户按 `Ctrl+R` 刷新即可生效（无需重启应用）。
