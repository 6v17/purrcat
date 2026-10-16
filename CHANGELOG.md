# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0]

First stable release. This version reworks the front-end delivery model and the workflow engine, and slims down the tool set.

**English**

### Added

- **UI plugin system (`ui-plugin`)**: a new plugin type that lets developers fully customize the style and behavior of front-end panel views. Ships with a hot-swappable subprocess plugin runtime, a dedicated plugin market with automatic dependency install, plugin root/dependency/origin metadata, and the `create_ui_plugin` KernelUpgrade capability with an authoring guide.
- **Minimal UI with built-in plugins**: the app now runs on minimal UI mode and bundles the essential built-in plugins — session/history, sessions & pending approvals, task, memory graph, built-in browser, market, evolve factory, and background.
- **Developer documentation**: a modular server API reference (`docs/api/*`) and plugin development guides (`docs/plugins`: graph / agentloop / sensor / ui-plugin), with CI validating that the docs stay in sync with the server routes.

### Changed

- **Front-end rewritten to minimal UI mode**: the entire original hand-drawn React front-end has been removed. The former UI is published to the official plugin repository as a hand-drawn-style UI plugin, so users who prefer it can install it back. Minimal UI adds a multi-tab panel container with slot/area layout, drag-to-resize width, per-plugin opacity/width, a built-in browser that takes over clicked web links, and panel plugins replicating the former pages (task, memory, market, evolve, sessions).
- **Workflow engine (harness) rewritten**: nodes now exchange self-describing JSON envelopes (`type`/`data`/`mime`/`meta`) with `purrcat://` URIs for file payloads and engine-side type validation; graphs are stored as folders (`graph.json` + `asset/`) with automatic migration on startup. The agent loop node is now driven by the agentloop paradigm plugin and shares the main agent's memory system (memo cache sync). Nodes added: `command`, `file_reader`, `file_writer`, `string`, and a multi-format preview node. Glue nodes removed: `image_generator`, `text_file_reader`, `html_viewer`, `json_builder`, `if_else_router`, `switch_router`, `python_runner`.
- **Evolution factory evaluation overhauled**: sensor protocol self-check (L0/L1), eval assertions and verdict scoring in the MCP factory, refreshed skill/sensor evaluators, and factory reports rendered as self-contained Swiss-style HTML with an iteration archive list.
- **Tool set simplified**: removed the ComputerUse tool and its exclusive dependencies, and removed the install request types from the Request tool.
- **Marketplace**: added the ui-plugin market, agentloop market endpoints and tab, installing skills from a GitHub link, deleting installed plugins, and a reinstall action.
- **Infrastructure**: cross-layer API port coordination between the app layers; host-native settings; per-session token usage (including subagents) persisted and surfaced in the minimal UI ring.

### Fixed

- Token ring showing 0 on load — per-session usage is now read from persisted session metadata and restored on init/session switch.
- Config editor failing in minimal mode; sidebar highlight error.
- Subagent branch cancel/delete now match the internal id, wait for teardown, and key active tasks by unique id; `fix the file change accept error when the file is moved`.
- Sensor SRE mismatch caused by a leaked venv environment; MCP subprocess venv env is now stripped before merge.
- Node reset acting on a stale task due to a selection-closure race.
- Background-agent config read error.
- Plugin origin detection on cross-drive roots; stale plugin JS cache and panels overflowing past the viewport.
- Boot-session race, context-ring visibility and link color in minimal UI.
- Stale eval run directory cleaned before copy; bogus token-savings card skipped.
- Skill upgrade target guarded and empty rollback commit tolerated.

---

**中文**

### 新增

- **UI 插件体系（`ui-plugin`）**：新增插件类型，开发者可自由定制前端面板的样式与功能。配套热插拔子进程插件运行时、带依赖自动安装的独立插件市场、插件根目录/依赖/来源元数据，以及 `create_ui_plugin` 的 KernelUpgrade 能力与编写指南。
- **极简 UI 与内置插件**：应用现以极简 UI 模式运行，并内置一批必要插件——会话/历史、会话与待审批、任务、记忆图谱、内置浏览器、市场、进化工厂、背景。
- **开发者文档**：模块化的服务端 API 参考（`docs/api/*`）与插件开发指南（`docs/plugins`：graph / agentloop / sensor / ui-plugin），并加入 CI 校验文档与服务端路由一致。

### 变更

- **前端改为极简 UI 模式**：删除了全部原有的手绘风格 React 前端。原前端以手绘风格 UI 插件的形式发布到官方插件仓库，偏好原风格的用户可重新安装。极简 UI 新增多标签页面板容器（slot/area 布局、拖拽调宽、每插件透明度/宽度）、接管网页链接的内置浏览器，以及复刻原页面的面板插件（任务、记忆、市场、进化、会话）。
- **工作流引擎（harness）重写**：节点改为交换自描述的 JSON 信封（`type`/`data`/`mime`/`meta`），文件载荷使用 `purrcat://` URI 并在引擎侧做类型校验；图改为文件夹形式存储（`graph.json` + `asset/`），启动时自动迁移。智能体循环节点改由 agentloop 范式插件驱动，并与主 agent 共享记忆系统（memo 缓存同步）。新增节点：`command`、`file_reader`、`file_writer`、`string` 及多格式预览节点。移除胶水节点：`image_generator`、`text_file_reader`、`html_viewer`、`json_builder`、`if_else_router`、`switch_router`、`python_runner`。
- **进化工厂评测体系优化**：新增 sensor 协议自检（L0/L1），MCP 工厂加入评测断言与判定评分，刷新 skill/sensor 评测器，工厂报告改为自包含的瑞士风格 HTML 并带迭代归档列表。
- **工具简化**：删除 ComputerUse 工具及其专属依赖，删除 Request 工具的 install 请求类型。
- **市场**：新增 ui-plugin 市场、agentloop 市场端点与标签页、从 GitHub 链接安装技能、卸载已装插件与"重装"操作。
- **基础设施**：应用各层之间统一 API 端口协调；宿主原生设置；按会话持久化 token 用量（含子代理）并在极简 UI 圆环展示。

### 修复

- 加载时 token 圆环显示为 0——改为从持久化的会话元数据读取按会话用量，并在初始化/切换会话时恢复。
- 极简模式下配置编辑器失效；侧边栏高亮报错。
- 子代理分支取消/删除改为按内部 id 匹配、等待清理完成、按唯一 id 记录活动任务；修复文件移动后接受改动的报错。
- venv 环境泄露导致的 sensor SRE 不匹配；MCP 子进程合并前会剥离泄露的 venv 环境。
- 节点重置因选择闭包竞态而作用于过期任务。
- 后台 agent 配置读取报错。
- 跨盘符根目录下的插件来源识别；插件 JS 缓存过期与面板溢出视口。
- 极简 UI 启动会话竞态、上下文圆环可见性与链接颜色。
- 复制前清理过期的评测运行目录；跳过错误的 token 节省卡片。
- 技能升级目标加保护，并容忍空的回滚提交。

## [1.0.0-beta.4]

Distribution model change: the one-line source installer replaces pre-built desktop installers.

**English**

### Added

- One-line installers (Windows / Linux / macOS) — this is now the only install path. The script clones the source, auto-installs missing prerequisites (git / uv / Node.js 18+ / Docker / embedding model) with multi-level fallbacks (winget → official installers → GitHub releases), and registers a global `purrcat` command.
- One-click start and update: `purrcat desktop start` lazily installs dependencies on first launch and boots the desktop app; `purrcat desktop update` pulls the latest source and syncs dependencies.
- Deploy page in Config Center: visual deployment of the embedding model, Docker, and the sandbox image (multi-source pull with automatic fallback: ghcr.io → NJU mirror → Docker Hub), greatly lowering the deployment barrier.
- Agent Loop Editor: edit the execution paradigm (`PARADIGM.yaml`) from the UI, with per-session paradigm selection and hot switching.
- Live streaming of the model's reasoning content into the thinking bubble.
- Vision inline mode.
- Market: batch "install all" button on repo detail pages.

### Changed

- Sensor module refactored onto the ACP protocol: a new ACP server, stdio bridge, and unified message dispatch replace the legacy sensor vocabulary layer; sensors get a dedicated config page with editor relay and stable-path deploy.
- Full UI localization: Chinese/English switching in Config Center, covering chat, market, Agent Loop Editor, sidebar menus and toasts; market plugin details include a zh/en description toggle. Default language is fixed to English instead of following the system language.
- Tool output limits switched from characters to tokens (10,000) with a shared token utility.
- FileSystem list returns single-level `ls`-style output (type/size/mtime); hidden entries are no longer filtered.
- Skill loading returns the full SOP as the tool result.
- Simplified tool result display: the frontend extracts pure content from the JSON wrapper.
- Prompt wording cleanup: replaced "老板" (boss) with "用户" (user) across tool descriptions.

### Fixed

- Data-root migration error on startup.
- Force-interrupt stuck in the "dozing" state; chat action buttons vanishing after interrupt.
- Vision returning empty analysis when thinking models exhausted the max_tokens budget on reasoning.
- Sandboxed Bash: the shared container no longer sleeps on subprocess exit; one automatic retry on EOF.
- Garbled lint-checker output and `biome` not found on Windows.
- Brainstorm sub-agent snapshots missing sibling tool results in the same batch; sub-agent final reply is now appended to the branch finish notification.
- Browser webview covering the chat area after closing the panel, and stale pages after closing a tab.
- Terminal view error, file-url parse error, and chat draft restore broken by React StrictMode double-run.
- Embedding model no longer auto-downloads at startup (the Deploy page is the single writer); onnx/openvino exports skipped with a corrected size hint.
- Installer hardening: BOM stripped from `install.ps1` for `irm | iex` compatibility, `npm.cmd` used to bypass execution-policy blocking, and Node/uv/git fallbacks improved.

---

**中文**

### 新增

- 一键安装指令（Windows / Linux / macOS），并成为唯一的安装方式：脚本自动克隆源码、补齐缺失的前置依赖（git / uv / Node.js 18+ / Docker / 向量模型，内置多级回退：winget → 官方安装器 → GitHub Releases），并注册全局 `purrcat` 命令。不再提供打包好的安装包。
- 一键启动与一键更新：`purrcat desktop start` 首次启动自动安装依赖并拉起桌面端；`purrcat desktop update` 拉取最新源码并同步依赖。
- 配置中心新增部署页面：向量模型、Docker、沙箱镜像全部可视化部署（镜像多源拉取自动回退：ghcr.io → 南大镜像站 → Docker Hub），进一步降低部署难度。
- 主循环编辑器：在界面中直接编辑执行范式（`PARADIGM.yaml`），支持按会话选择范式并热切换。
- 模型思考内容实时流式展示到思考气泡。
- 视觉内联模式。
- 市场：仓库详情页新增"全部安装"批量按钮。

### 变更

- Sensor 模块基于 ACP 协议重构：新增 ACP 服务端、stdio 桥接与统一消息分发，移除旧版 sensor 词汇层；Sensor 提供独立配置页，支持编辑器中继与稳定路径部署。
- 界面完整本地化：配置中心支持中英文切换，覆盖聊天、市场、主循环编辑器、侧边栏菜单与提示语；市场插件详情支持中英文描述切换。默认语言固定为英文，不再跟随系统语言。
- 工具输出上限从字符数改为 token 数（10000），使用统一的 token 计算工具。
- 文件列表改为单层 `ls` 风格输出（类型/大小/修改时间），不再过滤隐藏条目。
- 技能加载返回完整 SOP 作为工具结果。
- 简化工具结果展示：前端从 JSON 包装中提取纯内容。
- 提示词措辞清理：工具描述中的"老板"统一改为"用户"。

### 修复

- 启动时数据根目录迁移报错。
- 强制中断卡在"打盹"状态；中断后聊天操作按钮消失。
- 思考模型把 max_tokens 预算耗尽在推理上导致视觉分析返回空内容。
- 沙箱 Bash：子进程退出不再休眠共享容器；EOF 时自动重试一次。
- Windows 下检查器输出乱码、找不到 `biome`。
- BrainStorm 子代理快照丢失同批次兄弟工具结果；子代理最终回复现在会追加到分支完成通知中。
- 关闭面板后浏览器 webview 遮挡聊天区域、关闭标签页后显示旧页面。
- 终端视图报错、文件 URL 解析错误、React StrictMode 双执行导致草稿恢复失败。
- 向量模型不再在启动时自动下载（部署页面为唯一入口）；跳过 onnx/openvino 导出并修正体积提示。
- 安装脚本加固：`install.ps1` 去除 BOM 以兼容 `irm | iex`、改用 `npm.cmd` 绕过执行策略限制、完善 Node/uv/git 回退逻辑。

## [1.0.0-beta.3]

Bug-fix and stability release.

### Fixed

- Electron process lifecycle hardening: single-instance lock (second launch focuses the existing window), auxiliary windows destroyed on close, and a quit watchdog to prevent orphaned backend processes.
- Browser panel: tab close now activates the correct neighbor tab, and view focus handling fixed.
- Harness DAG engine: reload error fixed.
- Long-term memory stayed empty in fresh installs: the memory worker now defers (instead of dropping) pending experiences while the embedding model is unavailable.
- Terminal failed to spawn when the agent_vm working directory was missing.
- Bash tool: default timeout reduced to 30s; timeout errors now report the actual limit and include partial output captured so far.
- Skill trigger test scoring miscalculation fixed.

### Changed

- Config center: model form drafts survive tab switches and collapse; default vision template updated to `openai:deepseek-v4-flash-vision-exp`.
- Subprocess PATH is enriched from the Windows registry, so dependencies installed after the backend starts are found without a reboot.
- UI lint cleanup across ChatPage, ConfigModal, AgentBrowserPanel and IDEPanel.

## [1.0.0-beta.2]

Bug-fix and stability release.

### Fixed

- MCP sessions are no longer recycled mid-task: `callmcp` now runs in-process instead of a subprocess, so long-lived MCP servers (e.g. Chrome via chrome-devtools) stay alive across tool calls. Anti-hang protection via a configurable timeout on tool calls.
- Terminal failed to connect in some scenarios.
- Opening a page in the external browser misbehaved.
- MCP config template produced invalid `env` entries.
- UI refresh error after merging MCP market installs.

### Changed

- The agent now has full access to files inside the sandbox.

### Docs

- Requirements slimmed down (Docker core-only), GOAL.md mechanism and PARADIGM added to the architecture overview.

## [1.0.0-beta.1]

First public beta release.

### Added

**Hybrid Memory and Knowledge Graph**

- Three-tier memory architecture: short-term working memory (`memo`), core general memory (`MEMORY.md`), and long-term structured memory (PurrMemo).
- Episodic memory engine (SQLite + FTS5) and semantic memory engine (ChromaDB + NetworkX).
- RRF hybrid retrieval fusing BM25 keyword matching and vector search, executed concurrently.
- Background daemon for asynchronous memory digestion, with a decay mechanism that cleans up long-unused memories.
- Knowledge graph with dynamic relation strengthening/weakening and HTML visualization export.
- Memory page in the UI: events, experiences, graph view, and a MEMORY.md editor.

**Harness DAG Workflow Engine**

- Multi-agent concurrent execution under a single persona, avoiding inter-agent natural-language chatter.
- 20 built-in node types, including conditional routing (if/else, switch), LLM-vision image generation, human intervention, and template rendering.
- Safe rollback: inject commands at any node; downstream states are cleared for breakpoint recovery.
- Workflows load from a single JSON file and hot-update at runtime.

**Secure Toolchain**

- Sandboxed Bash: commands run in isolated Docker containers, with optional directory mounts.
- FileSystem suite (read / edit / write / search / glob) with PDF/DOCX/XLSX converted to Markdown via MarkItDown.
- Physical black/white lists for cross-boundary file operations; exports trigger automatic Git snapshots.
- Native tools: CallMCP, hybrid Search, Fetch, Memo, Cron, Task, BrainStorm, KernelUpgrade. External MCP servers supported.

**Agent Core**

- Git-style session branching: new, branch, and switch sessions.
- Automatic repair: malformed tool calls are intercepted and rolled back to a safe state.
- Context truncation: older history is replaced by memo summaries at safe cut points when token limits are exceeded.
- Persona system: `SOUL.md` defines values; a heartbeat-driven mechanism (Heartbeat + GOAL.md) patrols and reports during idle time.
- Dedicated vision consultant isolates image processing from the main session.
- Customizable agent loop: the execution paradigm (triggers, lifecycle hooks, periodic injections, tool-use checks, loop exit conditions) is defined declaratively in `PARADIGM.yaml` using near-natural-language rules — rewrite the loop's behavior without touching core code.

**Self-Evolution**

- Skill factory: the agent authors and upgrades its own skills in an isolated evolution sandbox, complete with generated scaffolding, guides, and eval cases; skills that pass evaluation are promoted into the live retrieval tree.
- MCP factory: same mechanism for MCP servers — scaffold, build, and evaluate new MCP servers autonomously, then register them into the tool tree.

**Proactive Perception**

- Sensor framework: independent subprocesses with PEP 723 inline dependencies (managed by uv), communicating over Stdio JSON-RPC.
- Built-in sensors: System (heartbeat/polling), Feishu (WebSocket), RSS, and Audio (Whisper + pyttsx3).

**Model Gateway**

- API key load balancing with idle-first key allocation.
- Semaphore queuing and jittered exponential backoff (up to 8 retries).
- Strong key-to-session binding for stable KV cache hit rates across session switches.

**Desktop Client and Distribution**

- Electron desktop client with built-in browser tabs and terminal.
- Web UI mode for lightweight deployment (`python main.py --api --headless`).
- Cross-platform builds: Windows (NSIS), macOS (arm64 dmg), Linux (AppImage).
- In-app auto-update on Windows and Linux via GitHub Releases, with differential downloads.
- Release automation: one-command tagging, changelog extraction, and asset upload via GitHub Actions.

**CLI**

- `purrcat setup`: one-step environment initialization (uv, Docker, embedding model, Playwright).
- `purrcat install`: install extensions (skill, node, graph, mcp).

This list highlights the major capabilities; more features are documented at [purrpod.github.io](https://purrpod.github.io/).

### Known Issues

- The application is unsigned. Windows SmartScreen may warn on first launch (choose "Run anyway"); on macOS, right-click the app and choose Open to bypass Gatekeeper.
- macOS builds do not support silent auto-update (requires an Apple Developer certificate); download the new dmg manually.
- Sandboxed Bash requires Docker; the tool is unavailable without it.
- Local file access, terminal, and related features depend on the Electron runtime and may misbehave in a plain browser.
