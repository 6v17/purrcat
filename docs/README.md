# PurrCat 文档中心

本目录是 PurrCat 的开发者文档入口，分为两大板块：

## API 参考（`docs/api/`）

后端 `src/server` 的全部 HTTP / WebSocket / SSE 接口，按模块拆分，逐接口给出参数、响应与调用示例。

- [API 总览与模块索引](api/README.md)

## 插件开发（`docs/plugins/`）

PurrCat 专属的四类扩展插件的开发指南，含各自专有词汇表与最小可运行示例。

- [插件体系总览](plugins/README.md)
  - [Sensor 开发（感官中枢）](plugins/sensor.md)
  - [Graph 开发（任务编排中枢）](plugins/graph.md)
  - [AgentLoop 开发（主循环范式）](plugins/agentloop.md)
  - [UI Plugin 开发（极简模式界面插件）](plugins/ui-plugin.md)

---

> API 文档与 `src/server` 真实路由的一致性由 `scripts/check_api_docs.py` 校验（CI 工作流 `.github/workflows/api-docs.yml`）。
