"""
AgentLoop 指南生成器模块 (evolve/agentloop/guide_generator.py)
单文件指南：覆盖范式模型、阶段/动作词汇表、校验与提交全流程。
"""


def generate_agentloop_guide(name: str, goal: str = "") -> str:
    goal_section = f"\n> 🎯 **本次构建目标**：{goal}\n\n" if goal else ""
    return f"""# {name} AgentLoop 工厂指南 (GUIDE)

AgentLoop（范式 / PARADIGM）用一份 YAML 声明**每一轮循环在哪些阶段注入什么内容、执行什么检查**，
从而定制 Agent 的思考与行动流程。本指南覆盖结构规范、专有词汇表、校验与提交全流程，动手前请先通读。
{goal_section}
> ⚠️ **动手前先查证能力，严禁瞎编工具 / 技能**：凡是要写进 `skill_info.skills` 的**技能名**、或要经 `CallMCP` 调用的 **MCP 工具名**，
> 都必须先确认它真实存在于宿主机。**写之前请先调用 `Search` 工具查证**：
> `Search(route="skill", query="<技能名或用途>")`、`Search(route="mcp", query="<服务器名或工具名>")`，
> 或用 `Search(route="local", query="<用途>")` 一次混合搜索技能库与 MCP 工具。
> **搜不到就不要写**——宁可改用原生工具、或把该步骤交给 Agent 自行处理，也绝不捏造一个不存在的技能 / MCP 工具名。

## 1. 运行时模型

* Agent 每轮循环依次触发若干**阶段（stage）**；每个阶段可挂若干 **hook**，按声明顺序执行。
* hook 三种典型作用：**注入**内容、**检查**并决定循环能否结束、**反馈**（通过/失败提示词）。
* 命中 `on_loop_end` 的检查不满足时，若未达 `loop_end_max_retry` 上限，本轮回打重试。
* 范式支持**会话级热切换**，且切换前后系统提示前缀保持一致（不破坏 KV Cache）。

## 2. YAML 结构

```yaml
name: {name}                      # 安装标识，必须与本文件名一致
description: 一句话中文描述
description-en: One-line English description.
path: agent_vm                     # 执行环境标识（保持默认即可）
loop_end_max_retry: 3              # on_loop_end 检查未通过时的最大重试轮数（可选）
hooks:                             # 阶段 → hook 列表（必填、非空）
  on_build_system_prompt:
    - injection: {{ content: "@RULES" }}
  on_loop_start:
    - skill_info: {{ skills: ["my-skill"], failed_prompt: "缺少技能，请先获取。" }}
  on_loop_end:
    - tool_use_check:
        name: "Memo"                   # 必须是宿主机原生工具名（见第 4 节工具清单）
        parameter_check:               # 检查项列表：任一项匹配即算「用了且满足条件」
          - action: "add"              # 一项内多个键需同时满足（精确相等）
        successed_prompt: "记忆已更新。"
        failed_prompt: "结束前请先用 Memo 记录本轮经验。"
```

**顶层字段**

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `name` | 是 | 安装标识，与文件名一致 |
| `description` | 建议 | 中文描述（市场展示）|
| `description-en` | 建议 | 英文描述 |
| `path` | 建议 | 执行环境，保持 `agent_vm` |
| `loop_end_max_retry` | 否 | `on_loop_end` 检查未通过时的最大重试轮数 |
| `hooks` | 是 | 阶段 → hook 列表的映射，非空 |

## 3. 阶段清单（专有词汇表 · 阶段）

`hooks` 的键即阶段名，全部可选、按需声明：

| 阶段 | 时机 | 典型 hook |
| --- | --- | --- |
| `on_build_system_prompt` | 构建系统提示时 | `injection`、`memo_injection` |
| `on_input_received` | 收到用户输入时（携带本批 received_messages） | `keyword_check`、`injection`、`search` |
| `on_loop_start` | 一轮循环开始时 | `injection`、`skill_info`、`file_operation` |
| `on_loop_epoch` | 循环内每个 epoch（每次模型调用）前 | `injection`、`file_operation`、`command_run` |
| `on_tool_calling` | 即将调用工具时 | `tool_use_check`、`injection` |
| `on_loop_end` | 一轮循环结束判定时 | `tool_use_check`、`file_operation` |

> `keyword_check` 只检查「本批收到的输入」是否含关键词，因此仅在带 `received_messages` 的
> `on_input_received` 阶段有意义。

## 4. 动作清单（专有词汇表 · 动作）

每个 hook 是「单键对象」：`<action>` 为键，值为该 action 的参数对象。

| action | 必填参数 | 说明 |
| --- | --- | --- |
| `injection` | `content` | 直接注入提示文本；`content` 支持 `@引用` |
| `memo_injection` | — | 注入记忆，参数 `type`（`full`/`light`/自定义 key）、`count` |
| `skill_info` | `skills` | 拼装指定技能的描述提示；缺失时给 `failed_prompt` |
| `search` | `query` | 调 Search 检索并注入结果，`route` ∈ `skill`/`mcp`/`memory`/`local`/`web` |
| `tool_use_check` | `name` | 检查本轮是否调用**原生工具** `name`（可要求 `parameter_check`），据此放行或回打；检查 MCP 工具须用 `CallMCP` 的参数检查（见下方「工具使用检查的语义」） |
| `keyword_check` | `keyword` | 关键词命中检查，`type` 控制匹配的消息类型 |
| `file_operation` | `action` | 文件检查/操作，`action` ∈ `read`/`exist_check`/`write_in`/`add_in`/`delete` |
| `command_run` | `command` | 执行命令并按结果判定（`on_loop_epoch` 常用） |

**通用可选参数**：`delay`（仅第 `delay` 个 epoch 执行）、`interval`（每 `interval` 个 epoch 执行一次）、
`expect`（仅 `on_loop_end`：取 `false` 或 `"fail"` 时，表示该检查“未满足”才算通过，用以放行跳出循环）。

**工具使用检查的语义（重点）**

* `name` 只能填**宿主机真实存在的原生工具**——工具集固定，只有下面这几个，模型正是用这些名字调用工具：

  `FileSystem`、`Bash`、`BrainStorm`、`Cron`、`CallMCP`、`Memo`、`Request`、`Search`、`Fetch`、`Task`、`KernelUpgrade`。

* **外部拓展工具（MCP）不是原生工具**，模型是通过原生工具 `CallMCP(server_name, tool_name, arguments)` 间接调用的。
  所以**要检查「是否用了某个 MCP 工具」，必须检查 `CallMCP` 的入参**，而不是把 MCP 工具名直接写进 `name`（那样永远匹配不到）：

  ```yaml
  - tool_use_check:
      name: "CallMCP"
      parameter_check:
        - tool_name: "chrome_navigate"   # 直接命中该 MCP 工具
        # - server_name: "chrome"       # 需要时再限定服务器
      failed_prompt: "结束前请先用 CallMCP 调用 chrome_navigate。"
  ```

* **skill 与 MCP 都必须真实存在于宿主机**才能被检查或注入：`skill_info.skills`、`search(route='mcp')` 等注入动作，
  以及上面的 `CallMCP` 参数检查，都只有在宿主机确实装了这个 skill / 配了这个 MCP 时才成立；
  不存在时注入会走 `failed_prompt`，`CallMCP` 也会直接报「不在配置里」。
  **因此写这些名字之前必须先用 `Search` 工具查证**（`route="skill"` / `route="mcp"` / `route="local"`），
  确认存在再写；搜不到就不写，不要凭印象编造技能名或 MCP 工具名。

* `parameter_check` 的匹配语义：拿**本轮实际调用 `name` 工具时的入参**逐项比对；一项内多个键需**同时**命中（值精确相等），
  多项之间为**或**——任一项命中即视为「用了且满足条件」。

**`@引用` 符号**（`injection.content` 内可直接使用）：
`@RULES`、`@INFO`、`@SOUL`、`@MEMORY`、`@SYS`、`@USERQUERY`、`@TASKSPACE`。

## 5. 校验脚本（格式 / 功能 / 关键词汇）

沙盒根目录内置自测脚本 `evals/validate.py`，做三重校验：

* **格式**：YAML 可解析；顶层为映射；`name` 与文件名一致；必填字段齐备。
* **关键词汇**：`hooks` 的每个阶段、每个动作都必须属于白名单；动作的必填参数齐备；
  `file_operation.action` 取值合法；`tool_use_check.name` 属于原生工具白名单（MCP 工具请走 `CallMCP`）；`@引用` 符号已登记。
* **功能**：`loop_end_max_retry` 为整数；`file_operation` 具备可用的 `path`。

```bash
cd /agent_vm/agentloop_workplace/<uuid>
uv run evals/validate.py
```

结论写入 `evals/outputs/validation.json`。**有 ❌（error）项一律不许提交合并**，⚠️（warn）项按需处理。

## 6. 提交合并

校验全绿后调用 `Request(request_type="agentloop_merge", target="{name}")`，
并在 reason 中简述范式功能点供用户 Code Review。批准后系统会：
1. 把 `{name}.yaml` 拷贝到正式目录 `~/.purrcat/paradigms/`；
2. Git 提交版本记录。
合并前系统会**宿主侧重跑同一套校验**（防止篡改脚本），有错直接拒绝——所以务必先自查再申请。
"""


__all__ = ["generate_agentloop_guide"]
