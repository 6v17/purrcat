"""KernelUpgrade(action='test')：代发架构级测试

只有架构必须安排的测试才在此代发（skill/sensor 走审批队列，mcp 直接后台评测）；
graph / agentloop / ui-plugin 无架构级测试，需 Agent 自行在沙盒跑自测脚本。
"""

import os

from src.tool.utils.format import error_response, text_response
from src.tool.request.request_operations import submit_request
from src.utils.config import AGENT_VM_DIR
from src.utils.graph_api import graph_file
from src.evolve import run_mcp_eval_background


def test_module(t: str, target: str, reason: str) -> dict:
    if t == "skill":
        return _test_skill(target, reason)
    if t == "sensor":
        return _test_sensor(target, reason)
    if t == "mcp":
        return _test_mcp(target)
    if t in ("graph", "agentloop"):
        return error_response(
            f"❌ 架构未为 {t} 安排测试：请自行在沙盒内运行自测脚本完成格式/功能/关键词汇三重校验"
            f"（agentloop 为 `uv run evals/validate.py`，graph 为 `uv run <图名>/evals/validate.py`），"
            "全绿后调用 KernelUpgrade(action='merge', ...) 申请合并。",
            "❌ 无架构级测试",
        )
    return error_response(
        "❌ UI 插件无架构级测试：请在沙盒中自测（刷新页面验证交互），确认无误后告知用户。",
        "❌ 无架构级测试",
    )


def _test_skill(target: str, reason: str) -> dict:
    from src.tool.request.request import _validate_skill_test

    err = _validate_skill_test(target)
    if err:
        return error_response(*err)

    has_graph = os.path.exists(graph_file("skill_eval"))
    result = submit_request(
        request_type="skill_test",
        target=target,
        reason=reason,
        extra={"trigger_started": False, "has_graph": has_graph},
    )

    trigger_note = (
        "🎯 Trigger 激发测试无需审批，系统即将自动启动，完成后通过系统级通知汇报结果。"
    )
    if not has_graph:
        trigger_note += (
            "\n⚠️ 注意：本地无 skill test 的图（图库缺少 skill_eval 测试图），将跳过后台盲测；"
            "如需完整盲测，请用户先安装 skill_eval 测试图，再重新提交申请。"
        )
        blind_note = ""
    else:
        blind_note = (
            "\n✅ 后台盲测申请已提交用户审批，获批后系统将自动在后台运行，"
            "期间请挂起等待，禁止轮询。"
        )
    return text_response(
        f"{trigger_note}{blind_note}", f"⏳ skill_test 已受理: {result['id']}"
    )


def _test_sensor(target: str, reason: str) -> dict:
    from src.tool.request.request import _validate_sensor_test

    err = _validate_sensor_test(target)
    if err:
        return error_response(*err)

    result = submit_request(
        request_type="sensor_test",
        target=target,
        reason=reason,
        extra={"eval_started": False},
    )
    return text_response(
        "🔬 Sensor 协议体检无需审批，系统即将自动启动（宿主亲自扮演网关实跑你的 sensor），"
        "完成后通过系统级通知汇报结果。\n"
        "💡 体检全绿后才能申请合并；若改动了代码，务必重跑本体检。",
        f"⏳ sensor_test 已受理: {result['id']}",
    )


def _test_mcp(target: str) -> dict:
    """MCP 测试：宿主侧重跑沙盒内的并发评测（需先产出 schema_dump.json）"""
    parts = target.split("/")
    if len(parts) != 2 or not all(parts):
        return error_response(
            f"执行失败：target 格式不正确，应为 'uuid/mcp_name'。当前输入为: '{target}'",
            "❌ 路径格式错误",
        )
    workplace_id, mcp_name = parts

    schema_path = os.path.join(
        AGENT_VM_DIR,
        "mcp_workplace",
        workplace_id,
        mcp_name,
        "evals",
        "outputs",
        "schema_dump.json",
    )
    if not os.path.exists(schema_path):
        return error_response(
            "❌ 执行被拒绝：未检测到测试前置产物！\n\n"
            "由于当前 MCP 还处于沙盒开发期，你必须先亲自在沙盒里测试 scripts/evaluation.py 能否跑通！\n"
            "只有当上述脚本成功执行，并生成了 `evals/outputs/schema_dump.json` 之后，你才有资格调用测试！",
            "❌ 缺失前置产物",
        )

    stale_warning = _stale_schema_warning(schema_path)
    from src.agent.manager import manager

    run_mcp_eval_background(
        workplace_id, mcp_name, manager.get_active_session_id()
    )

    msg = (
        f"🚀 MCP '{mcp_name}' 的并发测试流水线已在后台启动！\n"
        f"💡 提示：测试完成后系统会主动推送结果报告，请耐心等待系统级通知。\n"
    )
    if stale_warning:
        msg = f"{stale_warning}\n\n{msg}"
    return text_response(msg, f"⏳ {mcp_name} 宿主机评测中")


def _stale_schema_warning(schema_path: str) -> str:
    """过期提醒（不拦截）：schema_dump 可能是旧代码生成的、会静默假绿。
    比对"快照时间"与"最近源码(含 evals.json)时间"，快照更旧时在返回消息里提醒，
    让 Agent 自行判断是否重跑刷新。"""
    mcp_dir = os.path.abspath(os.path.join(schema_path, "..", "..", ".."))
    schema_mtime = os.path.getmtime(schema_path)

    skip = (".venv", "venv", "__pycache__", "node_modules", ".git", "scripts")
    newest_src = 0.0
    for dirpath, dirnames, filenames in os.walk(mcp_dir):
        dirnames[:] = [d for d in dirnames if d not in skip]
        for fn in filenames:
            if fn.endswith(".py"):
                newest_src = max(newest_src, os.path.getmtime(os.path.join(dirpath, fn)))
    evals_json = os.path.join(mcp_dir, "evals", "evals.json")
    if os.path.exists(evals_json):
        newest_src = max(newest_src, os.path.getmtime(evals_json))

    if schema_mtime < newest_src:
        return (
            "⚠️ **注意：测试快照可能已过期！**\n"
            "源码/工具描述相较 `schema_dump.json` 有新改动，当前快照可能仍是旧代码生成的，"
            "报告会用旧描述渲染。若确实改了描述/逻辑，请先在沙盒重跑 "
            "`python scripts/evaluation.py` 刷新快照后再测；若改动无关描述，可忽略本提醒。"
        )
    return ""
