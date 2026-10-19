"""KernelUpgrade 工具大模型输入结构 - Agent自主进化沙盒"""

KERNELUPGRADE_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "KernelUpgrade",
        "description": (
            "Agent 的核心自我进化工具，用于在隔离沙盒中创建/升级、从市场安装、合并与测试各类模块。"
            "支持 type：skill（技能）、mcp（MCP Server）、sensor（外部感知器）、graph（任务图）、"
            "agentloop（主循环范式）、ui-plugin（极简模式 UI 插件）。\n"
            "action 语义：\n"
            "- create：在某 type 的隔离沙盒中搭建全新骨架（再读沙盒内 GUIDE.md 开发）；\n"
            "- upgrade：把正式区中已存在的该 type 对象（必要时连带配置）搬进沙盒再改；"
            "注意：MCP 只有源码落在受管 mcps 目录里的才能升级，外部自行下载、仅注册在 mcp_config.json 的 MCP 会报错；\n"
            "- install：从官方市场 / URL 安装到正式区（仅此 action 的 target 可为名字或 URL）；\n"
            "- merge：代发合并审批请求（等同原 Request 的 *_merge，仍需用户 Yes/No）；\n"
            "- test：代发架构级测试（skill→Trigger+盲测审批、sensor→协议体检、mcp→后台并发评测）；"
            "graph/agentloop/ui-plugin 无架构级测试，需你自行在沙盒跑自测脚本，调用本 action 会返回报错。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "执行的具体操作",
                    "enum": ["create", "upgrade", "install", "merge", "test"],
                },
                "type": {
                    "type": "string",
                    "description": "要操作的对象类型",
                    "enum": [
                        "skill",
                        "mcp",
                        "sensor",
                        "graph",
                        "agentloop",
                        "ui-plugin",
                    ],
                },
                "target": {
                    "type": "string",
                    "description": (
                        "目标对象。一般为名字。特殊情形：\n"
                        "- action='test' 且 type='mcp'：填沙盒路径前缀 'uuid/mcp名'；"
                        "type='skill' 填 '工作区uuid/技能名'；type='sensor' 填 '工作区uuid/传感器名'。\n"
                        "- action='install'：type='skill' 可填官方收录名或指向含 SKILL.md 目录的 GitHub URL；"
                        "type='mcp' 可填官方收录名或 mcpServers 配置串（JSON）；"
                        "type='graph' 可填官方收录名或含 graph.json 的 GitHub URL；"
                        "type='agentloop' 可填官方收录名、YAML 文件路径或 URL；其余填官方收录名。\n"
                        "- action='create'/'upgrade'：type='ui-plugin' 填插件 id（小写字母/数字/-/_）。"
                    ),
                },
                "goal": {
                    "type": "string",
                    "description": "仅 action='create'/'upgrade'：本次开发目标，会写入沙盒的 GOAL.md 并影响生成的指南与骨架。",
                },
                "reason": {
                    "type": "string",
                    "description": "仅 action='merge'/'test'：申请理由，明确告诉用户为什么需要这次审批（merge 请简述修改点供人类 Code Review）。",
                },
            },
            "required": ["action", "type", "target"],
            "additionalProperties": False,
        },
    },
}
