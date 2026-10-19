"""
Sensor 指南生成器模块 (evolve/sensor/guide_generator.py)
单文件指南：覆盖 ACP 协议规范、凭证与配置、文件收发与提交全流程。
"""


def generate_sensor_guide(sensor_name: str, goal: str = "") -> str:
    goal_section = f"\n> 🎯 **本次构建目标**：{goal}\n" if goal else ""
    return f"""# {sensor_name} 传感器工厂指南 (GUIDE)

本指南覆盖 ACP 协议规范、凭证与配置、失败上报、文件收发与提交全流程，动手前请先通读。
{goal_section}
## 1. Sensor 是什么

Sensor 是一个**独立的常驻子进程**，由宿主机 SensorManager 用 `uv run <name>.py` 拉起，
通过 stdin/stdout 的**单行 JSON-RPC（ACP 方言）**与宿主机网关双向通信：

* **session/prompt（你 → Agent）**：外部事件（用户消息、提醒、状态变化）注入当前活跃会话
* **session/update（Agent → 你）**：Agent 的回复通过你转发到外部渠道（群聊、邮件等）

会话规则：stdio sensor **固定当前活跃会话**——宿主 stdio 桥会在你发 session/new 时
无条件改写 `_meta` 注入 follow 标记（网关本身的默认值是"新开会话"，别自己传这个标记），
你无需（也不应）实现任何会话切换逻辑。

铁律：
* stdout **只能**输出协议 JSON-RPC（一行一条）。调试 print 必须走 stderr：`sys.stdout = sys.stderr`
* 严禁退出主进程。连接崩溃要无限重连（带 sleep 缓冲），守护线程只救意外退出
* 配置凭证一律从环境变量读取（由 activate_sensor.json 的 env 注入），禁止硬编码密钥
* 有游标/会话状态的（长轮询 cursor、扫码换的 token 等），持久化到脚本同目录的
  state 文件并随更新落盘——sensor 会被热重启，不落盘就丢消息或丢登录态
* 一切外部网络调用放后台线程，主线程只跑 stdin 读取循环
* 连接成功**保持静默**：只有失败（缺凭证、连不上、异常）才用 session/prompt 上报失败详情，
  详情里带上缺失/出错的凭证名；严禁每次连上成功后都推一条"连接成功"之类的调试信息
* 凭证由 Agent 引导用户获取后直接填在沙盒 `sensor_config.json` 的 `env` 里（见第 3 节），
  sensor 只需从环境变量读取，不必在会话里解释怎么申请
* 合并前必须通过协议体检（见第 7 节），体检报告会被宿主复跑核对，无法用自述蒙混

### 动手前的资料准备

Sensor 开发通常都要对接外部平台的接口，接口细节不能靠猜：

* **以官方开发者文档为准**。确认来源正确（官方域名 / 官方仓库，而非二手博客、聚合站），
  并确认文档**未过时**——对照你实际调用的 API 版本，核对当前仍有效的端点、字段名、
  鉴权方式与限流规则；平台改版后残留的旧示例是踩坑重灾区。
* **没有思路时，查找同类开源项目借鉴思路**：对应平台的官方 SDK、社区 bot 框架、
  已有的 adapter 实现，都是很好的参考——重点借鉴它的请求构造、鉴权刷新、
  重连与去重（幂等）策略，再改写成符合本指南协议的单文件实现。
* 借鉴时只取**思路与接口用法**：不要整体拷贝许可证不兼容的代码，
  也不要照搬其中过时或已被平台废弃的调用方式（同上，先核对官方文档）。
* 拿不准的地方以**能实跑验证**为准：写一个最小请求真打一次接口（或官方/SDK 自带的调试工具），
  比连读多篇未标日期的文章可靠。

## 2. 协议规范（JSON-RPC 2.0 over stdio）

### 出向（stdout → 网关）

握手（启动后立即顺序发出，id 1/2）：
```json
{{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {{"clientInfo": {{"name": "{sensor_name}"}}}}}}
{{"jsonrpc": "2.0", "id": 2, "method": "session/new", "params": {{"clientInfo": {{"name": "{sensor_name}"}}}}}}
```

注入外部事件（sessionId 用 session/new 响应回传的值）：
```json
{{"jsonrpc": "2.0", "id": 3, "method": "session/prompt", "params": {{"sessionId": "<sid>", "prompt": [{{"type": "text", "text": "[{sensor_name} 收到用户消息] 你好"}}]}}}}
```
prompt 响应不会立即返回——Agent 跑完当前轮次后网关才回 `{{"stopReason": "end_turn"}}`。
连发多条 prompt 无需自行排队——网关按序处理，stopReason 也会按 FIFO 逐条回填，
因此**不要在等 stopReason 的同时阻塞你的事件监听**（prompt 全部 fire-and-forget 即可）。

取消当前轮次（用户说"停下"等场景；通知无 id，网关不回响应）：
```json
{{"jsonrpc": "2.0", "method": "session/cancel", "params": {{"sessionId": "<sid>"}}}}
```
被取消的 prompt 会收到 `{{"stopReason": "cancelled"}}`。

触发后台任务图谱（时钟类 sensor 专用，无需等 Agent 应答的自动化触发；
available 检查 initialize 响应的 `agentCapabilities._meta.purrcat.dev.launch_task`）：
```json
{{"jsonrpc": "2.0", "id": 4, "method": "_purrcat/launch_task", "params": {{"graph_name": "my_graph", "inputs": {{"key": "value"}}, "title": "任务标题"}}}}
```

上传文件给 Agent（content_b64 为 base64 编码的原始字节，单文件 ≤ 20MB；
网关落盘到 `/agent_vm/sensor/files/{sensor_name}/` 并在响应中返回沙盒路径，
**拿到路径后请再用 session/prompt 告知 Agent**，如
`[{sensor_name} Sensor 收到文件] {{path}} ({{mime}}, {{size}})`）：
```json
{{"jsonrpc": "2.0", "id": 4, "method": "_purrcat/upload_file", "params": {{"name": "photo.jpg", "mime": "image/jpeg", "content_b64": "..."}}}}
```

### 入向（stdin ← 网关）

Agent 文本回复（agent_message_chunk 逐条到达；消息级粒度——
一条事件即一条完整 assistant 消息，一个轮次可能有多条；
messageId 每条唯一，变化即新消息边界）：
```json
{{"jsonrpc": "2.0", "method": "session/update", "params": {{"sessionId": "<sid>", "update": {{"sessionUpdate": "agent_message_chunk", "messageId": "msg_1", "content": {{"type": "text", "text": "回复内容"}}}}}}}}
```
其他 update 类型见下方词汇总表（受 tool_detail 配置控制是否下发）。

Agent 发的文件（Agent 消息里含本地文件链接时网关自动追加）：
```json
{{"jsonrpc": "2.0", "method": "_purrcat/file", "params": {{"name": "a.png", "mime": "image/png", "size": 11, "content_b64": "..."}}}}
```
你需 base64 解码后自行发送到外部渠道。若渠道 API 是"先上传换 key 再发消息"两段式（如飞书），请在后台线程完成，**严禁阻塞 stdin 读取循环**。

还有 request 的响应（`{{"id": ..., "result": ...}}`）——按 id 匹配你发出的请求。

### 词汇总表

**sessionUpdate 值**（`session/update` 的 `update.sessionUpdate` 字段）——ACP 标准词汇：

| 词汇 | 说明 | tool_detail=false 时 |
|---|---|---|
| `agent_message_chunk` | Agent 文本回复。**消息级粒度**：一条事件即一条完整 assistant 消息，每条一个唯一 messageId（id 变化即新消息边界），一个轮次可能有多条。消费端建议同时容忍旧拼写 `agent_message` | ✅ 下发（唯一总是下发的词汇） |
| `agent_thought_chunk` | Agent 思考过程文本 | ❌ 过滤 |
| `tool_call` | 工具调用开始（status=pending；含 `toolCallId`/`title`/`kind`，文件类工具带 `locations`，参数对象带 `rawInput`） | ❌ 过滤 |
| `tool_call_update` | 工具状态流转（in_progress → completed/failed），content 带截断后的结果文本 | ❌ 过滤 |
| `usage_update` | token 用量（`used`=窗口已用，`size`=模型上限） | ❌ 过滤 |
| `session_info_update` | 会话元数据（updatedAt），每轮结束前同步 | ❌ 过滤 |
| `user_message_chunk` | 历史回放专用（编辑器 session/load 场景），stdio sensor 不会收到 | — |

**PurrCat 扩展词汇**（`_purrcat/` 前缀）：

| 词汇 | 方向 | 说明 |
|---|---|---|
| `_purrcat/upload_file` | sensor → 网关（方法） | 上传文件给 Agent（base64，单文件 ≤ 20MB；见上方出向示例） |
| `_purrcat/launch_task` | sensor → 网关（方法） | 触发后台任务图谱（时钟类 sensor 专用，无需等 Agent 应答） |
| `_purrcat/file` | 网关 → sensor（通知） | Agent 消息提及本地文件时网关自动追加（base64，解码后自行发送到外部渠道） |
| `_purrcat/turn_end` | 网关 → sensor（通知） | 轮次终结标记（params 带 stopReason）；不消费则忽略 |

## 3. 凭证与配置 ⭐（最重要）

凭证在开发阶段一次性配置好：

1. Agent 先引导用户到外部平台获取所需凭证（App Secret、API Token 等）；
2. 拿到凭证后，由 Agent（或用户）**直接在沙盒的 `sensor_config.json` 里把 `env` 填成真实值**；
3. 合并时系统会把沙盒里的 `env` 原样写进正式注册配置（`activate_sensor.json`）并注入环境变量——
   **用户无需再去配置中心重填**。若某个键在沙盒里留空，合并会保留正式配置里已有的旧值，
   不会把用户之前填好的凭证清空。

因此 sensor 代码本身只需：

* 从环境变量读取凭证（禁止硬编码密钥）；
* 缺凭证或连接失败时用 session/prompt **上报失败详情**（含缺失/出错的凭证名），并保持进程存活待命；
* 连上成功、事件处理成功时**保持静默**，不要推送任何成功调试信息。

## 4. 单文件骨架

依赖用 PEP 723 内联声明（uv 会自动建环境）。沙盒初始化时已生成可运行的
ACP 骨架（initialize → session/new → 凭证校验 → update 消费循环），
按 TODO 注释替换真实外部服务逻辑即可。

## 5. 测试方法

沙盒根目录已内置**真网关夹具**，它会扮演网关拉起你的 sensor（凭证留空，逼出失败上报路径），
自动核对握手顺序、失败上报、sessionId 回填、stdout 纯净、空转存活：

```bash
cd /agent_vm/sensor_workplace/<uuid>
uv run evals/gateway_probe.py
```

失败项的排查线索在 `evals/probe_stderr.log`（sensor 的 stderr 全量日志）。

需要观察单条下发消息的处理时，也可以直接用 echo 手测：

```bash
echo '{{"jsonrpc":"2.0","method":"session/update","params":{{"update":{{"sessionUpdate":"agent_message_chunk","content":{{"type":"text","text":"hello"}}}}}}}}' | uv run {sensor_name}.py
```

## 6. sensor_config.json（合并注册的唯一依据）

沙盒根目录维护 `sensor_config.json`，合并时系统只认它：

```json
{{
  "name": "{sensor_name}",
  "env": {{ "MY_TOKEN": "" }},
  "icon": "",
  "tool_detail": false,
  "source": "remote"
}}
```

* `env`：声明全部所需凭证。**开发阶段由 Agent 引导用户获取后在此填真实值**，合并即完成配置；
  留空的键会保留正式配置里的旧值（不会清空用户已填的凭证）。代码里 `os.environ.get("X")`
  读到的每个键都**必须**在此声明——协议体检会做双向交叉校验，漏声明会导致合并后用户无从配置
* `icon`：配置页卡片头像的图标链接（可留空；留空或加载失败都会回退默认图标）
* `tool_detail`：true 时 Agent 的工具调用细节（工具名/结果片段）也会推送到本 sensor；false（默认）时只推送回复正文
* `source`：`"remote"`（默认，外部源在远程平台）或 `"local"`（外部源是可本地构造的文件/本地服务）。
  标 `local` 的 sensor 有机会把"外部事件 → 注入会话"这一段也纳入自动化闭环

## 7. 验收标准（协议体检）

提交 `Request(request_type="sensor_test", target="<uuid>/{sensor_name}")` 后，宿主会**亲自扮演网关**
实跑你的 sensor（L0 静态契约 + L1 协议夹具）。全绿即可放心合并——体检**不再硬性拦截**，
未通过只会让合并结果带上一条提醒。判据：

| # | 判据 | 说明 |
|---|---|---|
| 1 | 协议纯净 | stdout 只有合法 JSON-RPC，日志全在 stderr |
| 2 | 永不退出 | 空转与异常输入下进程都存活 |
| 3 | 契约自述 | sensor_config.json 合法，代码读的 env 键全部已声明 |
| 4 | 依赖可装 | `uv run` 能建成环境并完成握手（PEP 723 有效） |
| 5 | 握手时序 | 先 `initialize`(id=1) 再 `session/new`(id=2) |
| 6 | 失败上报 | 缺凭证/连接失败时上报失败详情（含凭证名）；连接成功时静默，不发成功调试信息 |
| 7 | sessionId 回填 | 用 session/new 响应回传的 sessionId 发所有 prompt（回填错会让注入静默失效） |
| 8 | 故障可见 | 异常不崩溃，关键路径日志可读 |

体检产物落在 `iteration-N/`：`report.html`（瑞士风 HTML 体检报告，结论与逐条判据一页呈现）、`benchmark.json`、
`handshake.json`（全量抓包）、`sensor_stderr.log`。**外部渠道未被 mock**，所以"Agent 回复在渠道里长什么样""幂等去重""游标续传"
这类真实链路行为不在自动体检范围内，报告会显式列在「未覆盖项」里——别把它们当成已验证。

## 8. 提交合并

建议体检通过后再调用 `Request(request_type="sensor_merge", target="{sensor_name}")`，
并在 reason 中简述功能点供用户 Code Review。批准后系统会：

1. 拷贝 `{sensor_name}.py` 至正式目录并写入 activate_sensor.json（enabled=true）
2. Git 提交版本记录
3. 热重启 Sensor 线程池——沙盒 `env` 里填好的凭证会**直接生效**（留空的键保留正式配置里的旧值），
   用户无需在配置中心重填；若确有留空凭证，该 sensor 会主动上报失败详情，请引导用户补齐。

⚠️ 合并前系统会核对最近一次协议体检结论，但**仅作提醒、不再阻止合并**：
报告缺失、仍有硬伤或晚于最后一次代码改动时，合并结果里会提示你重跑 `sensor_test`。
"""
