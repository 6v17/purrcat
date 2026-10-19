"""KernelUpgrade(action='merge')：代发合并审批请求

Agent 只看到 KernelUpgrade，无法再直接向 Request 传 *_merge。
"""

from src.tool.utils.format import error_response, text_response
from src.tool.request.request_operations import submit_request
from .shared import MERGE_REQUEST_TYPES


def merge_module(t: str, target: str, reason: str) -> dict:
    req_type = MERGE_REQUEST_TYPES.get(t)
    if not req_type:
        return error_response(
            "ui-plugin 直接写盘即生效，无合并审批环节。",
            "❌ 无需合并",
        )

    result = submit_request(request_type=req_type, target=target, reason=reason)
    msg = (
        f"✅ 合并申请已提交给用户审批 (请求ID: {result['id']})。\n"
        f"申请类型: {req_type} | 目标: {target}\n\n"
        f"💡 系统指示：\n"
        f"1. 该合并需要用户 Yes/No 审批，请勿反复调用本工具催促。\n"
        f"2. 请挂起当前合并相关任务，等待系统通知（审批通过/拒绝）。\n"
        f"3. 若当前有其他无关联的独立任务，可继续执行。"
    )
    return text_response(msg, f"⏳ 合并申请已提交: {result['id']}")
