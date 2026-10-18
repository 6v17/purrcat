# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Graph（任务图）校验器 —— 格式 / 功能 / 关键词汇 三重校验。

本文件同时承担两个角色（单一事实来源，逻辑不会漂移）：
1. 宿主侧权威校验：合并网关调用 ``validate_graph_folder``，未全绿禁止合并；
2. 沙盒自测脚本：工厂会把本文件逐字拷贝为沙盒里的 ``evals/validate.py``，
   直接 ``uv run evals/validate.py`` 即可离线自查。

因此本文件禁止依赖任何包内相对导入，只用标准库。
"""

import json
import os
import sys

# ==========================================
# 专有词汇表（关键词汇校验的白名单）
# ==========================================

# 合法节点类型（对应 src/harness/node/extensions/<type>/<type>.json）
NODE_TYPES = {
    "task_input",
    "task_output",
    "string",
    "template_renderer",
    "message_card_builder",
    "appender",
    "json_builder",
    "json_extractor",
    "env_loader",
    "skill_info",
    "mcp_info",
    "agent_loop",
    "human_intervention",
    "command",
    "file_reader",
    "file_writer",
}

# 已废弃节点类型（信封协议重构中移除）
DEPRECATED_TYPES = {
    "image_generator",
    "preview",
    "text_file_reader",
    "if_else_router",
    "switch_router",
    "python_runner",
}

# 各类型的静态端口（dynamic 端口由 config 动态生成，此处不含）
STATIC_INPUTS = {
    "agent_loop": ["messages", "agentloop"],
    "appender": ["base_list", "append_list"],
    "command": ["command", "os", "trigger"],
    "env_loader": [],
    "file_reader": ["trigger", "source"],
    "file_writer": ["trigger", "content", "filename"],
    "human_intervention": ["trigger", "context_data", "prompt"],
    "json_builder": ["trigger"],
    "json_extractor": ["data"],
    "mcp_info": ["trigger"],
    "message_card_builder": ["content", "role", "trigger"],
    "skill_info": ["trigger"],
    "string": ["trigger"],
    "task_input": [],
    "task_output": [],
    "template_renderer": ["template", "trigger"],
}
STATIC_OUTPUTS = {
    "agent_loop": ["messages", "summary"],
    "appender": ["merged_list"],
    "command": ["stdout", "stderr", "exit_code", "skipped"],
    "env_loader": [],
    "file_reader": ["content", "file"],
    "file_writer": ["file"],
    "human_intervention": ["human_reply", "context_data"],
    "json_builder": ["json_string"],
    "json_extractor": [],
    "mcp_info": ["mcp_kit_string"],
    "message_card_builder": ["message_list"],
    "skill_info": ["skill_kit_string"],
    "string": ["text", "number", "boolean", "json"],
    "task_input": [],
    "task_output": [],
    "template_renderer": ["rendered_text"],
}
# 具备动态端口的类型（dynamic_inputs / dynamic_outputs / dynamic_vars）
DYNAMIC_INPUT_TYPES = {"task_output", "json_builder", "template_renderer"}
DYNAMIC_OUTPUT_TYPES = {"task_input", "env_loader", "json_extractor"}

REQUIRED_TOP = ["name", "description", "description-zh"]


def _check(checks, title, ok, level, detail=""):
    checks.append({"title": title, "ok": bool(ok), "level": level, "detail": detail})
    return bool(ok)


def validate_graph_doc(doc, expected_name=None):
    """校验一个已解析的 graph.json dict，返回结构化报告。"""
    checks = []

    if not isinstance(doc, dict):
        _check(checks, "graph.json 顶层为对象", False, "error", "顶层必须是 JSON 对象")
        return _report(checks)
    _check(checks, "graph.json 顶层为对象", True, "error")

    # ---- 格式校验 ----
    for key in REQUIRED_TOP:
        if not doc.get(key):
            _check(checks, f"必填字段 `{key}` 非空", False, "error", f"缺少或为空：`{key}`")

    name = doc.get("name")
    if expected_name and name and str(name) != expected_name:
        _check(
            checks,
            "name 与文件夹名一致",
            False,
            "error",
            f"name={name!r}，文件夹={expected_name!r}（CI 与市场安装都要求两者一致）",
        )
    elif expected_name and name:
        _check(checks, "name 与文件夹名一致", True, "error")

    if "version" not in doc:
        _check(checks, "建议声明 version", False, "warn", '建议加 "version": "2.0"')

    nodes = doc.get("nodes") or []
    edges = doc.get("edges") or []
    if not isinstance(nodes, list):
        _check(checks, "nodes 为数组", False, "error", "nodes 必须是数组")
        return _report(checks)
    if not isinstance(edges, list):
        _check(checks, "edges 为数组", False, "error", "edges 必须是数组")
        return _report(checks)

    # ---- 关键词汇 + 功能校验：节点 ----
    ids = {}
    has_task_input = False
    has_task_output = False
    global_vars = set()
    for i, node in enumerate(nodes):
        if not isinstance(node, dict):
            _check(checks, f"nodes[{i}] 为对象", False, "error")
            continue
        nid = node.get("id")
        ntype = node.get("type")
        if not nid:
            _check(checks, f"nodes[{i}] 含 `id`", False, "error", "节点缺少 id")
        elif nid in ids:
            _check(checks, f"节点 id `{nid}` 唯一", False, "error", "id 重复")
        else:
            ids[nid] = i
        if not node.get("name"):
            _check(checks, f"节点 `{nid}` 含 `name`", False, "warn", "缺少节点显示名")

        if ntype in DEPRECATED_TYPES:
            _check(
                checks,
                f"节点 `{nid}` 未使用已废弃类型",
                False,
                "error",
                f"`{ntype}` 已在下线清单：{sorted(DEPRECATED_TYPES)}",
            )
        elif ntype not in NODE_TYPES:
            _check(
                checks,
                f"节点 `{nid}` 的类型 `{ntype}` 属于白名单",
                False,
                "error",
                f"未知节点类型，合法值：{sorted(NODE_TYPES)}",
            )

        if ntype == "task_input":
            has_task_input = True
            for gv in node.get("config", {}).get("global_vars", []) or []:
                if isinstance(gv, dict) and gv.get("name"):
                    global_vars.add(gv["name"])
        if ntype == "task_output":
            has_task_output = True

    # ---- 功能校验：边引用 + 端口 ----
    incoming = {nid: 0 for nid in ids}
    for j, edge in enumerate(edges):
        if not isinstance(edge, dict):
            _check(checks, f"edges[{j}] 为对象", False, "error")
            continue
        src, dst = edge.get("source"), edge.get("target")
        if src not in ids:
            _check(
                checks,
                f"edges[{j}].source `{src}` 指向已定义节点",
                False,
                "error",
                "source 引用了不存在的节点 id",
            )
        if dst not in ids:
            _check(
                checks,
                f"edges[{j}].target `{dst}` 指向已定义节点",
                False,
                "error",
                "target 引用了不存在的节点 id",
            )
        elif src in ids:
            incoming[dst] = incoming.get(dst, 0) + 1

        src_type = (
            nodes[ids[src]].get("type")
            if src in ids and isinstance(nodes[ids[src]], dict)
            else None
        )
        dst_type = (
            nodes[ids[dst]].get("type")
            if dst in ids and isinstance(nodes[ids[dst]], dict)
            else None
        )

        # 端口名校验（dynamic 端口名由 config 决定，故仅做警告级提示）
        sh = edge.get("sourceHandle")
        if sh and sh not in STATIC_OUTPUTS.get(src_type, []) and src_type not in DYNAMIC_OUTPUT_TYPES:
            _check(
                checks,
                f"edges[{j}].sourceHandle `{sh}` 属于 `{src_type}` 的输出端口",
                False,
                "warn",
                f"静态输出端口为 {STATIC_OUTPUTS.get(src_type, [])}；若为动态端口请确认 config 已声明",
            )
        th = edge.get("targetHandle")
        if th and th not in STATIC_INPUTS.get(dst_type, []) and dst_type not in DYNAMIC_INPUT_TYPES:
            _check(
                checks,
                f"edges[{j}].targetHandle `{th}` 属于 `{dst_type}` 的输入端口",
                False,
                "warn",
                f"静态输入端口为 {STATIC_INPUTS.get(dst_type, [])}；若为动态端口请确认 config 已声明",
            )

    # ---- 功能校验：孤立节点 ----
    for nid, idx in ids.items():
        node = nodes[idx]
        ntype = node.get("type")
        if ntype in ("task_input", "env_loader"):
            continue  # 无输入端口的开局节点
        if incoming.get(nid, 0) == 0:
            has_trigger = "trigger" in STATIC_INPUTS.get(ntype, [])
            if not has_trigger:
                _check(
                    checks,
                    f"节点 `{nid}` 有上游输入",
                    False,
                    "warn",
                    f"`{nid}`（{ntype}）既无连边又没有 trigger 端口，开局不会执行",
                )

    if not has_task_output:
        _check(checks, "建议存在 task_output 节点", False, "warn", "图中未声明全局输出节点")

    # ---- 功能校验：global_schema ----
    gs = doc.get("global_schema")
    if gs is not None:
        if not isinstance(gs, dict):
            _check(checks, "global_schema 为对象", False, "error")
        else:
            for k, v in gs.items():
                if not isinstance(v, dict):
                    _check(checks, f"global_schema.{k} 为对象", False, "error")
                elif "type" not in v:
                    _check(
                        checks,
                        f"global_schema.{k} 声明 `type`",
                        False,
                        "warn",
                        "缺少 type，前端表单无法渲染该字段",
                    )
            if has_task_input:
                missing = [k for k, v in gs.items() if isinstance(v, dict) and v.get("required") and k not in global_vars]
                if missing:
                    _check(
                        checks,
                        "必填 global_schema 键已声明为 task_input 全局变量",
                        False,
                        "warn",
                        f"未在 task_input.global_vars 中声明：{missing}",
                    )

    return _report(checks)


def _report(checks):
    errors = sum(1 for c in checks if c["level"] == "error" and not c["ok"])
    warnings = sum(1 for c in checks if c["level"] == "warn" and not c["ok"])
    return {"checks": checks, "errors": errors, "warnings": warnings, "ok": errors == 0}


def validate_graph_folder(folder, expected_name=None):
    """校验一个 graph 文件夹（含 graph.json），返回结构化报告。"""
    checks = []
    path = os.path.join(folder, "graph.json")
    if not os.path.isfile(path):
        _check(checks, "graph.json 存在", False, "error", f"未找到 {path}")
        return _report(checks)
    try:
        with open(path, "r", encoding="utf-8") as f:
            doc = json.load(f)
    except Exception as e:
        _check(checks, "graph.json 可解析", False, "error", f"解析失败：{e}")
        return _report(checks)
    _check(checks, "graph.json 可解析", True, "error")
    res = validate_graph_doc(doc, expected_name)
    res["checks"] = checks + res["checks"]
    res["errors"] = sum(1 for c in res["checks"] if c["level"] == "error" and not c["ok"])
    res["warnings"] = sum(1 for c in res["checks"] if c["level"] == "warn" and not c["ok"])
    res["ok"] = res["errors"] == 0
    return res


def _locate_folder():
    """沙盒自测用：在父目录里找含 graph.json 的文件夹。"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if os.path.isfile(os.path.join(root, "graph.json")):
        return root, os.path.basename(root)
    for item in sorted(os.listdir(root)):
        sub = os.path.join(root, item)
        if os.path.isdir(sub) and os.path.isfile(os.path.join(sub, "graph.json")):
            return sub, item
    return None, None


def _print_report(title, report):
    print("=" * 56)
    print(title)
    print("=" * 56)
    for c in report["checks"]:
        if c["ok"]:
            mark = "✅"
        elif c["level"] == "error":
            mark = "❌"
        else:
            mark = "⚠️ "
        line = f"  {mark} [{c['level']}] {c['title']}"
        if not c["ok"] and c["detail"]:
            line += f" — {c['detail']}"
        print(line)
    print(
        f"\n错误 {report['errors']}，警告 {report['warnings']}，"
        f"结论：{'✅ 通过' if report['ok'] else '❌ 未通过'}"
    )
    return report["ok"]


def main():
    folder, name = _locate_folder()
    if not folder:
        print("❌ 未在沙盒中找到含 graph.json 的文件夹")
        return 1
    report = validate_graph_folder(folder, expected_name=name)
    ok = _print_report(f"Graph 校验：{name}/graph.json", report)

    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")
    try:
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "validation.json"), "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    except OSError:
        pass

    print("\n提示：修正 ✗ 项后重跑本脚本；全绿后再用 Request(graph_merge) 申请合并。")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
