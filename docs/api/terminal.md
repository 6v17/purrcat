# 终端 WebSocket

> 源码：`src/server/api/terminal.py` ｜ 前缀：`/api/terminal` ｜ 端点：1 个

基于 PTY（伪终端）的终端桥接接口，让 PowerShell/bash 认为自己在跟真终端对话，从而启用 readline、退格、Tab 补全、颜色、提示符等交互特性。Windows 使用 `pywinpty`（VS Code/Jupyter 同款），*nix 使用标准库 `pty` + `os.fork`。

**约定**

- 单条 WebSocket 长连接对应一个 PTY 子进程；连接断开即杀掉该进程及其子进程树。
- 主程序退出（Ctrl+C / uvicorn shutdown）时会统一清理所有活跃终端子进程。
- 终端工作目录优先为 `AGENT_VM_DIR`，创建失败时回退用户主目录。

---

## WS `/api/terminal/ws`

建立终端桥接连接：接受连接后启动 PTY（交互 shell 或指定命令），双向转发输入输出。

**请求**

| 参数 | 位置 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| cmd | query | string | 否 | 不传 → 启动交互 shell；传字符串 → 执行该命令（执行完保持可交互） |

**消息协议**

前端 → 服务端（文本帧）：

- 普通文本：作为 stdin 原样写入 PTY。
- 控制消息：以 `\x00`（NULL）开头，其后为 JSON。目前仅支持尺寸调整：

```text
"\x00{\"type\":\"resize\",\"cols\":120,\"rows\":30}"
```

服务端 → 前端（文本帧）：

- PTY 原始输出文本（含 ANSI 转义序列）。
- 启动失败或运行异常时，以红色 ANSI 包裹的错误文本回传，例如 `\r\n\x1b[31m[Failed to spawn] ...\x1b[0m\r\n`；失败后连接关闭。

无独立 JSON 响应；交互数据全部经 WebSocket 文本帧双向流动。

**示例**

```javascript
const ws = new WebSocket('ws://127.0.0.1:8000/api/terminal/ws?cmd=dir');
ws.onmessage = (e) => console.log(e.data);
ws.send('\x00{"type":"resize","cols":120,"rows":30}');
ws.send('echo hello\r');
```
