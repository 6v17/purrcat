# 通用

> 源码：`main.py` ｜ 前缀：`/api` ｜ 端点：1 个

`main.py` 中直接注册的通用路由与静态托管，不属于任何 `src/server/api/*.py` 业务模块。

**约定**

- 应用为 FastAPI（`title="PurrCat API System"`），CORS 中间件允许全部来源、方法与请求头（本地优先，无鉴权）。
- 静态文件挂载注册在所有 API 路由之后，避免贪婪前缀匹配遮蔽接口。

---

## GET `/api/health`

健康检查。Electron 生产模式据此轮询后端是否就绪。该路由必须注册在静态挂载之前，否则会被静态挂载吞掉而返回 `404`。

**请求**

无请求参数。

**响应**

```json
{ "message": "PurrCat Backend is running." }
```

**示例**

```bash
curl 'http://127.0.0.1:8000/api/health'
```

---

## 静态托管与生命周期

- **极简宿主静态托管**：将 `ui/web-minimal` 目录以 StaticFiles（`html=True`）挂载到 `/minimal`（目录存在时）。访问 `http://127.0.0.1:8000/minimal` 即打开极简模式宿主页面。
- **极简模式禁用缓存**：中间件对以 `/minimal` 或 `/api/webmin` 开头的请求追加 `Cache-Control: no-store, no-cache, must-revalidate, max-age=0` 与 `Pragma: no-cache`，改动宿主/插件资源后刷新页面即生效。
- **MIME 修正**：启动时强制将 `.js`/`.mjs` 注册为 `text/javascript`、`.css` 注册为 `text/css`，规避 Windows 注册表误判导致白屏。
- **生命周期**：`shutdown` 事件会调用 `plugin_runtime.stop_all()` 停止全部插件后端子进程；终端 PTY 子进程另有退出清理钩子统一回收。
