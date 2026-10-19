"""KernelUpgrade 各 action 模块共享的常量与工具函数"""

# action × type 全矩阵：create/upgrade 建沙盒，install 从市场/URL 落正式区，
# merge/test 由本工具代发 Request（Agent 不再直接向 Request 传 test/merge）。
ACTIONS = ("create", "upgrade", "install", "merge", "test")
TYPES = ("skill", "mcp", "sensor", "graph", "agentloop", "ui-plugin")

# 合并请求类型映射（ui-plugin 无合并概念：直接写盘即生效）
MERGE_REQUEST_TYPES = {
    "skill": "skill_merge",
    "mcp": "mcp_merge",
    "sensor": "sensor_merge",
    "agentloop": "agentloop_merge",
    "graph": "graph_merge",
}


def market():
    """懒加载插件市场的落地实现（复用 src/server/api/tools.py 已有的下载/安装能力）"""
    from src.server.api import tools

    return tools


def data_root() -> str:
    from src.utils.config import DATA_ROOT

    return DATA_ROOT


def record_trace_meta(workplace_id: str):
    """trace2skill：记录来源会话的 Token 快照，供后续盲测报告对比"省下多少 token" """
    if not workplace_id:
        return
    try:
        from src.agent.manager import manager
        from src.evolve import record_trace_meta as _record

        _record(workplace_id, manager.get_active_session_id())
    except Exception:
        pass
