# UI Plugin 开发指南（极简模式界面插件）

> 落地目录：`~/.purrcat/webmin-plugins/<id>/` ｜ 市场仓库：`PurrPod/ui-plugins` ｜ 宿主：`ui/web-minimal`（`/minimal`）｜ 相关接口：[../api/webmin.md](../api/webmin.md)

UI Plugin 是极简模式（`web-minimal`）的界面插件。宿主是**纯静态页面**，插件以 **iframe** 挂载、按 `slot.area` 入驻不同区域，通过 **postMessage 的 `callAction` 动作总线**与宿主通信。

---

## 1. 插件目录结构

```text
ui-plugins/<id>/               # 市场仓库中的单元
├── plugin.json                # 清单（必需）
├── index.html                 # entry 入口页面（必需）
└── ...                        # 样式/脚本/图片等相对引用资源（可选）
```

**文件夹名 = `plugin.json` 的 `id` = 插件标识**，三者必须一致。

---

## 2. `plugin.json` 字段清单

```json
{
  "id": "doodle-chat",
  "name": "涂鸦聊天",
  "description": "English one-liner.",
  "description-en": "English one-liner.",
  "icon": "🖍️",
  "slot": { "area": "panel" },
  "entry": "index.html",
  "image": "cover.png",
  "root": "user",
  "builtin": false,
  "dependency": [],
  "configSchema": [
    { "key": "color", "type": "select", "label": "主题色",
      "options": [{ "value": "warm", "label": "暖" }, { "value": "cool", "label": "冷" }],
      "default": "warm" }
  ],
  "backend": { "kind": "npm" }
}
```

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `id` | 是 | 插件标识，与文件夹名一致 |
| `name` | 是 | 展示名 |
| `description` / `description-en` | 是 | 中/英文一句话描述 |
| `icon` | 是 | 图标（emoji 或图片路径）|
| `slot` | 是 | 入驻区域，见第 3 节。旧写法 `slotDef: { "type": "panel", "area": "panel" }` 亦可，`slot` 直接写区域对象即为新版 |
| `entry` | 是 | 入口 html（默认 `index.html`）|
| `image` | 否 | 市场封面图 |
| `root` | 否 | 来源标记：`user` / `sandbox` / `builtin`（同 id 冲突时优先级 **用户 > 沙盒 > 内置**）|
| `builtin` | 否 | 是否随宿主内置（内置插件不受用户删除影响）|
| `dependency` | 否 | 依赖数组，见 [README.md](README.md#依赖机制dependency) |
| `configSchema` | 否 | 声明式配置表单，见第 4 节 |
| `backend` | 否 | 后端形态；`{ "kind": "npm" }` 表示插件自带 `server/server.js`（Node 后端）|

---

## 3. `slot.area` 区域清单（专有词汇表 · 区域）

`area` 是插件声明的唯一入驻维度；**行为（单例 / 容器抽屉 / 浮窗）由宿主按区域内置**。

| `area` | 名称 | 宿主内置行为 | 窗口类型 |
| --- | --- | --- | --- |
| `rail` | 左侧白条 | 白条图标栏本身（含两态：仅图标 / 图标+文字）| 固定 |
| `sidebar` | 会话列表 | 同区域**单例**（同时只能有一个）| 固定 |
| `session` | 会话 | 同区域**单例** | 固定 |
| `background` | 背景 | 同区域**单例**（如网状斑点背景）| 固定 |
| `panel-container` | 面板容器 | 全局唯一容器，右上角抽屉切换视图；可用 `callAction` 的 `slot.move` 等控制 | 面板 |
| `panel` | 面板 | 与聊天区并排的栏目（内容插件）| 面板 |
| `pet` | 浮窗类 | **多实例**，可拖拽 / 缩放 / 隐藏 | 浮窗 |
| `popup` | 模态弹窗 | 居中模态弹窗 | 模态 |

> 宿主在 `UI_GROUPS` 中声明各区域行为；`slot` 只声明“入驻哪个区域”，**不要试图在插件里自行声明窗口类型**。

---

## 4. `configSchema` 配置表单

宿主据此渲染配置面板并调用 `configApply` 下发。`type` 取值：`text`（默认，单行文本）、`switch`（开关）、`number`（数字）、`select`（下拉，需 `options[]`）、`range`（滑块，配 `min` / `max` / `step`）、`wallpapers`（壁纸选择）。每个字段含 `key` / `type` / `label` / `default`。

插件侧读取方式：监听宿主下发的 `configApply`（见下节事件），或主动 `callAction('config.get', { plugin_id })`。

---

## 5. `callAction` 动作总线协议（核心）

### 5.1 插件 → 宿主

```js
window.parent.postMessage({ type: 'callAction', id: 'req-1', actionId: 'config.get', payload: { key: 'color' } }, '*');
```

- `type` 固定 `'callAction'`；`id` 为本次调用唯一标识（用于匹配响应）。

### 5.2 宿主 → 插件

| 消息 | 结构 | 说明 |
| --- | --- | --- |
| 调用结果 | `{ type: 'callActionResult', id, ok, data \| error }` | 对 `callAction` 的应答，按 `id` 匹配；`ok` 为布尔，成功取 `data`，失败取 `error` |
| 配置下发 | `{ type: 'configApply', config }` | 宿主合并后的插件配置，配置变更时推送 |
| 事件广播 | `{ type: 'event', event, data }` | 宿主主动广播，见 5.4 |

### 5.3 `actionId` 清单

**会话 / 对话**

| actionId | payload | 返回 |
| --- | --- | --- |
| `chat.send` | `{ message, sessionId? }` | 受理态 |
| `chat.sendBatch` | `{ messages[], sessionId? }` | 受理态 |
| `chat.interrupt` | `{ sessionId? }` | 受理态 |
| `chat.traceToSkill` | `{ sessionId?, ... }` | 追踪结果 |
| `sessions.list` | `—` | 会话数组 |
| `sessions.new` | `{ ... }` | 新会话信息 |
| `session.switch` | `{ sessionId }` | 切换结果 |
| `session.rename` | `{ sessionId, title }` | 结果 |
| `session.delete` | `{ sessionId }` | 结果 |
| `session.branch` | `{ sessionId, ... }` | 分支信息 |
| `session.setDraftParadigm` | `{ sessionId, paradigm }` | 结果 |
| `branch.select` | `{ sessionId, branchId }` | 结果 |
| `requests.list` | `—` | 待办请求数组 |
| `requests.resolve` | `{ requestId, decision }` | 结果 |

**配置 / 设置**

| actionId | payload |
| --- | --- |
| `config.get` | `{ plugin_id }` → 返回该插件配置值 |
| `config.set` | `{ ... }` |
| `settings.meta` | `—` |
| `settings.open` / `settings.close` | `{ tab? }` |

**文件 / 数据 / 对话框**

| actionId | payload | 说明 |
| --- | --- | --- |
| `dialog.files` | `{ ... }` | 选择文件 |
| `dialog.folder` | `{ ... }` | 选择文件夹 |
| `dialog.resolveFiles` | `{ paths[] }` | 解析路径信息 |
| `dialog.pickWallpaper` | `{ ... }` | 选壁纸 |
| `ref.graphs` | `—` | 返回可选 Graph 列表 |

**容器控制（面板 / 浮窗）**

| actionId | payload | 说明 |
| --- | --- | --- |
| `slot.move` | `{ area }` | 插件自身移入某区域 |
| `slot.close` | `—` | 关闭自身 |
| `slot.hide` | `{ hidden }` | 隐藏/显示自身（浮窗）|

**插件自身**

| actionId | payload | 说明 |
| --- | --- | --- |
| `plugin.delete` | `—` | 卸载自身（内置插件不可删）|
| `plugin.rpc` | `{ method, params }` | 调用插件自带 Node 后端（`backend.kind=npm`）|

**内置浏览器（宿主原生，供插件复用）**

| actionId | 说明 |
| --- | --- |
| `browser.available` / `browser.bounds` / `browser.hide` | 探测可用性、查询/设置视口 |
| `browser.newTab` / `browser.closeTab` / `browser.switchTab` | 标签页管理 |
| `browser.navigate` / `browser.reload` / `browser.goBack` / `browser.goForward` | 导航 |
| `browser.pickStart` / `browser.pickEnd` | 框选起止 |
| `browser.locate` / `browser.pickElement` | 定位 / 拾取元素 |
| `browser.openExternal` / `browser.openUrl` | 外部打开 |

**其它**

| actionId | 说明 |
| --- | --- |
| `state.get` | 读取宿主全局状态快照 |
| `input.dropdown` | 输入框下拉时告知宿主让位 |

> 以宿主 `ui/web-minimal/assets/host.js` 的 `dispatch()` 为准；完整字段见 [../api/webmin.md](../api/webmin.md)。

### 5.4 事件（`type: 'event'`）

| `event` | 时机 | `data` |
| --- | --- | --- |
| `host.unmount` | 宿主卸载插件 | 插件 id |
| `host.nativeCover` | 宿主原生界面覆盖插件的显示区域 | 覆盖信息 |
| `layout.empty` | 布局空置（无会话等）| — |
| `session.switched` | 当前会话切换 | 新会话信息 |
| `branch.switched` | 对话分支切换 | 分支信息 |
| `config.updated` | 插件配置被更新 | 新配置 |

---

## 6. 最小可运行示例

**`plugin.json`**

```json
{
  "id": "hello-panel",
  "name": "Hello 面板",
  "description": "A minimal panel plugin.",
  "description-en": "A minimal panel plugin.",
  "icon": "🐾",
  "slot": { "area": "panel" },
  "entry": "index.html",
  "configSchema": [
    { "key": "greeting", "type": "text", "label": "问候语", "default": "喵~" }
  ]
}
```

**`index.html`**

```html
<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>Hello</title>
<style>body{font-family:system-ui;margin:16px;background:transparent}</style></head>
<body>
  <h3 id="hi">喵~</h3>
  <button id="send">发到会话</button>
<script>
  let reqSeq = 0;
  const pending = new Map();
  function call(actionId, payload) {
    const id = 'r' + (++reqSeq);
    return new Promise(res => { pending.set(id, res);
      window.parent.postMessage({ type: 'callAction', id, actionId, payload }, '*'); });
  }
  window.addEventListener('message', e => {
    const m = e.data || {};
    if (m.type === 'callActionResult' && pending.has(m.id)) { pending.get(m.id)(m.ok ? m.data : m.error); pending.delete(m.id); }
    if (m.type === 'configApply') { document.getElementById('hi').textContent = m.config.greeting || '喵~'; }
  });
  document.getElementById('send').onclick = () => call('chat.send', { message: '你好，来自面板插件' });
</script>
</body>
</html>
```

---

## 7. 开发与调试

- **本地预览**：插件目录放到 `~/.purrcat/webmin-plugins/<id>/`，重启极简宿主（`/minimal` 页面 `Ctrl+R`）即可加载。
- **调试**：插件在 iframe 内运行，用浏览器开发者工具选中对应 iframe 上下文看 Console；`callAction` 出错会落宿主控制台。
- **资源引用**：`index.html` 内使用相对路径引用同目录资源。
- **自带后端**：声明 `backend: { "kind": "npm" }` 并提供 `server/server.js`（Node，含依赖），插件侧用 `plugin.rpc` 调用。
