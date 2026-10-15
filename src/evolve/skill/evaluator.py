"""
Skill 测试执行器 (evolve/skill/evaluator.py)
利用底层 Harness 原生双 Agent 工作流完成隔离环境下的盲测与自评。
已升级为【错位并发】模式：多测试用例隔离并行，极大缩短评测耗时。
"""

import os
import json
import shutil
import asyncio
import threading
import re
import math
from datetime import datetime
from src.harness.process import Task
from src.utils.config import AGENT_VM_DIR


def _load_json(path: str):
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _write_json(path: str, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def run_skill_eval_background(workplace_id: str, skill_name: str, main_session_id: str):
    """启动后台线程跑自动化流水线"""

    def _bg_task():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            report = loop.run_until_complete(_async_run_evals(workplace_id, skill_name))
            from src.agent.manager import manager

            manager.agent_force_push(
                f"🔔 【测试结果】技能 '{skill_name}' 的自动化沙盒盲测已完成！\n\n{report}",
                type="system",
            )
        except Exception as e:
            from src.agent.manager import manager

            manager.agent_force_push(
                f"❌ 技能 '{skill_name}' (工作区: {workplace_id}) 的后台测试运行崩溃: {e}",
                type="system",
            )
        finally:
            loop.close()

    threading.Thread(
        target=_bg_task, daemon=True, name=f"EvalRunner_{workplace_id}"
    ).start()


def run_skill_trigger_eval_background(workplace_id: str, skill_name: str):
    """启动后台线程跑 Trigger 激发测试（无需审批，提交即运行）"""

    def _bg_task():
        try:
            report = _run_trigger_evals(workplace_id, skill_name)
            from src.agent.manager import manager

            manager.agent_force_push(
                f"🎯 【Trigger 测试结果】技能 '{skill_name}' 的激发路由测试已完成！\n\n{report}",
                type="system",
            )
        except Exception as e:
            from src.agent.manager import manager

            manager.agent_force_push(
                f"❌ 技能 '{skill_name}' (工作区: {workplace_id}) 的 trigger 测试运行崩溃: {e}",
                type="system",
            )

    threading.Thread(
        target=_bg_task, daemon=True, name=f"TriggerEval_{workplace_id}"
    ).start()


def _run_trigger_evals(workplace_id: str, skill_name: str) -> str:
    """以影子节点方式将沙盒技能注入检索快照，跑 triggers 激发测试"""
    workplace_root = os.path.join(AGENT_VM_DIR, "skill_workplace", workplace_id)
    dev_skill_dir = os.path.join(workplace_root, skill_name)
    evals_file = os.path.join(dev_skill_dir, "evals", "evals.json")

    if not os.path.exists(evals_file):
        return f"测试失败：未找到 {evals_file}"

    try:
        with open(evals_file, "r", encoding="utf-8") as f:
            evals_data = json.load(f)
    except json.JSONDecodeError:
        return "测试失败：evals.json 格式错误，无法解析为有效的 JSON。"

    triggers = evals_data.get("triggers", [])
    if not triggers:
        return "Trigger 报告：evals.json 中没有任何 trigger 测试用例。"

    # 解析沙盒 SKILL.md，组装影子技能节点
    skill_md_path = os.path.join(dev_skill_dir, "SKILL.md")
    if not os.path.exists(skill_md_path):
        return "测试失败：沙盒内未找到 SKILL.md。"

    from pathlib import Path
    from src.utils.skill_helper import _parse_skill_md
    from src.tool.search.skill_search import SkillSearcher

    parsed = _parse_skill_md(Path(skill_md_path))
    metadata = parsed.get("metadata", {})
    sandbox_skill = {
        "name": metadata.get("name", skill_name),
        "description": metadata.get("description", metadata.get("desc", "")),
        "content": parsed.get("content", ""),
        "dir_name": skill_name,
    }
    if not sandbox_skill["description"]:
        return "测试失败：SKILL.md 的 frontmatter 缺少 description，无法参与激发检索。"

    searcher = SkillSearcher()

    iteration_dir, iteration_idx = _get_next_iteration_dir(workplace_root)
    os.makedirs(iteration_dir, exist_ok=True)

    trigger_cases = []
    success = 0

    for idx, t_case in enumerate(triggers):
        query = t_case.get("query", "")
        should_trigger = t_case.get("should_trigger", True)
        item = {
            "index": idx + 1,
            "query": query,
            "should_trigger": bool(should_trigger),
        }

        try:
            res = searcher.simulate_trigger(query, sandbox_skill)
        except Exception as e:
            item.update(
                {
                    "hit": False,
                    "status": "fail",
                    "detail": f"框架崩溃: {e}",
                    "rank": None,
                    "score": None,
                    "competitors": [],
                }
            )
            trigger_cases.append(item)
            continue

        hit = res["is_triggered"]
        item.update(
            {
                "hit": bool(hit),
                "rank": res.get("rank"),
                "score": res.get("score"),
                "competitors": res.get("competitors", []),
            }
        )
        if should_trigger and hit:
            item["status"] = "pass"
            item["detail"] = f"唤醒成功（排名第 {res['rank']}，得分 {res['score']}）"
            success += 1
        elif should_trigger and not hit:
            item["status"] = "fail"
            item["detail"] = f"激发失败（得分 {res['score']}，未进 Top 3 或低于唤醒阈值）"
        elif not should_trigger and not hit:
            item["status"] = "pass"
            item["detail"] = "反例拦截成功（技能保持静默）"
            success += 1
        else:
            item["status"] = "fail"
            item["detail"] = f"反例拦截失败（不该触发却排名第 {res['rank']}）"
        trigger_cases.append(item)

    _write_json(
        os.path.join(iteration_dir, "trigger_result.json"),
        {
            "skill_name": skill_name,
            "iteration": iteration_idx,
            "generated_at": _now_iso(),
            "total": len(triggers),
            "passed": success,
            "cases": trigger_cases,
        },
    )
    _render_skill_report(workplace_root, iteration_dir, iteration_idx, skill_name)

    return (
        f"🎯 Trigger 激发路由唤醒率 {success}/{len(triggers)}，"
        f"报告已生成（iteration-{iteration_idx}/report.html）。"
    )


def _get_latest_iteration_idx(workplace_root: str) -> int:
    """返回当前最大迭代编号；尚无迭代时返回 0"""
    max_idx = 0
    if os.path.exists(workplace_root):
        for item in os.listdir(workplace_root):
            match = re.match(r"iteration-(\d+)$", item)
            if match:
                idx = int(match.group(1))
                if idx > max_idx:
                    max_idx = idx
    return max_idx


def _get_next_iteration_dir(workplace_root: str) -> tuple[str, int]:
    """分配新的迭代目录 iteration-N（Trigger 与盲测共用同一套计数）"""
    next_idx = _get_latest_iteration_idx(workplace_root) + 1
    return os.path.join(workplace_root, f"iteration-{next_idx}"), next_idx


def _get_eval_iteration_dir(workplace_root: str) -> tuple[str, int]:
    """盲测归入最近一轮 Trigger 测试的迭代目录（一个迭代 = trigger 结果 + 盲测结果同目录）；
    仅当最新迭代已含 eval_result.json（重复盲测）或尚无迭代时才新开一代。"""
    latest_idx = _get_latest_iteration_idx(workplace_root)
    if latest_idx > 0:
        dir_path = os.path.join(workplace_root, f"iteration-{latest_idx}")
        if not os.path.exists(os.path.join(dir_path, "eval_result.json")):
            return dir_path, latest_idx
    return _get_next_iteration_dir(workplace_root)


def _render_skill_report(
    workplace_root: str, iteration_dir: str, iteration_idx: int, skill_name: str
) -> str:
    """将 trigger_result / eval_result / trace_meta 渲染为单一 report.html（瑞士风）。

    报告即输出物：不列文件清单、不贴路径，只呈现结论与证据。
    """
    from src.evolve import report_html as H

    trigger = _load_json(os.path.join(iteration_dir, "trigger_result.json"))
    evals = _load_json(os.path.join(iteration_dir, "eval_result.json"))
    trace_meta = _load_json(os.path.join(workplace_root, "trace_meta.json"))

    blocks = []

    # trace2skill 专属：图标化展示技能为后台盲测省下的 token
    if trace_meta and evals and evals.get("cases"):
        baseline = int(trace_meta.get("consumed_total") or 0)
        token_vals = [int(c.get("tokens") or 0) for c in evals["cases"]]
        if baseline > 0 and token_vals:
            mean_tokens = int(round(sum(token_vals) / len(token_vals)))
            # 用例全部崩溃时 tokens 全为 0，此时对比会把整个会话累计量当成“节省量”，故不渲染
            if mean_tokens > 0:
                blocks.append(H.token_savings(baseline - mean_tokens, baseline, mean_tokens))
            else:
                blocks.append(H.note("盲测未产出有效 token 数据，本轮不做 token 节省对比。"))

    overview = []
    if evals:
        total, passed = evals.get("total", 0), evals.get("passed", 0)
        rsum = evals.get("summary", {}) or {}
        overview.append(
            {
                "label": "盲测通过",
                "value": f"{passed}/{total}",
                "icon_name": "target",
                "tone": "ok" if total and passed == total else "",
            }
        )
        token_mean = (rsum.get("tokens") or {}).get("mean")
        if token_mean is not None:
            overview.append(
                {"label": "平均 Tokens", "value": f"{token_mean:g}", "icon_name": "coin"}
            )
        time_mean = (rsum.get("time_seconds") or {}).get("mean")
        if time_mean is not None:
            overview.append(
                {
                    "label": "平均耗时",
                    "value": f"{time_mean:g}",
                    "unit": "s",
                    "icon_name": "clock",
                }
            )
    if trigger:
        overview.append(
            {
                "label": "Trigger 唤醒率",
                "value": f"{trigger.get('passed', 0)}/{trigger.get('total', 0)}",
                "icon_name": "zap",
                "tone": "accent" if trigger.get("passed") == trigger.get("total") else "",
            }
        )
    if overview:
        blocks.append(H.stats(overview, cols=min(len(overview), 4)))

    section_no = 1
    if trigger:
        items = []
        for c in trigger.get("cases", []):
            expect = "应触发" if c.get("should_trigger") else "静默阻断（反例）"
            competitors = "、".join(c.get("competitors") or []) or "无"
            items.append(
                {
                    "title": f"案例 {c.get('index')}：{c.get('query', '')}",
                    "status": c.get("status", ""),
                    "meta": [("期望", expect), ("结果", c.get("detail", ""))],
                    "notes": [f"语义竞争者（Top 3）：{competitors}"],
                }
            )
        blocks.append(
            H.section(f"{section_no:02d}", "Trigger 激发测试", H.cases(items))
        )
        section_no += 1

    if evals:
        items = []
        for c in evals.get("cases", []):
            notes = [c.get("reason", "")] if c.get("reason") else []
            items.append(
                {
                    "title": f"用例 {c.get('case_id', '')}",
                    "status": "pass" if c.get("pass") else "fail",
                    "meta": [
                        ("耗时", f"{c.get('time_seconds')}s"),
                        ("Tokens", str(c.get("tokens"))),
                    ],
                    "notes": notes,
                }
            )
        blocks.append(
            H.section(f"{section_no:02d}", "自动化盲测（with_skill）", H.cases(items))
        )
        section_no += 1

    if not trigger and not evals:
        blocks.append(H.note("本轮迭代尚无可用结果。"))

    meta = [
        ("技能", skill_name),
        ("迭代", f"Iteration {iteration_idx}"),
        ("工作区", os.path.basename(os.path.dirname(iteration_dir))),
        ("生成时间", _now_iso()),
    ]
    html = H.page(
        title=f"{skill_name} · 技能评测报告",
        subtitle="Trigger 激发路由与隔离沙盒盲测结果。数据来自影子检索与双 Agent 裁判实跑，非 Agent 自报。",
        meta=meta,
        blocks=blocks,
        kicker="PURRCAT · SKILL FACTORY",
        footer_left="Skill Evolution Report",
        footer_right=f"Iteration {iteration_idx:02d}",
    )
    with open(os.path.join(iteration_dir, "report.html"), "w", encoding="utf-8") as f:
        f.write(html)
    return html


def record_trace_meta(workplace_id: str, session_id: str) -> dict:
    """trace2skill 专用：把来源会话的累计 Token 快照写入沙盒 trace_meta.json。

    该快照即「无技能时的参照成本」，后台盲测完成后由报告与盲测均值对比，
    图标化展示这个技能让后台盲测任务少花了多少 token。
    """
    workplace_root = os.path.join(AGENT_VM_DIR, "skill_workplace", workplace_id)
    if not workplace_id or not session_id or not os.path.isdir(workplace_root):
        return {}

    data = {
        "session_id": session_id,
        "source": "trace2skill",
        "recorded_at": _now_iso(),
        "consumed_total": 0,
        "consumed_main": 0,
        "consumed_sub": 0,
        "window_token": 0,
        "max_token": 0,
    }
    try:
        from src.agent.session_store import SessionStore

        consumed = SessionStore.get_session_consumed_tokens(session_id) or {}
        data["consumed_total"] = int(consumed.get("total") or 0)
        data["consumed_main"] = int(consumed.get("main") or 0)
        data["consumed_sub"] = int(consumed.get("sub") or 0)
        data["window_token"] = int(
            SessionStore.get_session_window_token(session_id) or 0
        )
    except Exception:
        return {}
    try:
        from src.agent import get_agent_max_token

        data["max_token"] = int(get_agent_max_token() or 0)
    except Exception:
        pass

    _write_json(os.path.join(workplace_root, "trace_meta.json"), data)
    return data


def _calculate_stats(values: list[float]) -> dict:
    if not values:
        return {"mean": 0.0, "stddev": 0.0}
    mean = sum(values) / len(values)
    variance = sum((x - mean) ** 2 for x in values) / len(values)
    stddev = math.sqrt(variance)
    return {"mean": round(mean, 2), "stddev": round(stddev, 2)}


def _format_and_save_trace(memory_path: str, output_trace_path: str):
    trace_lines = ["# Trace(U:user;A:assistant;C:calltool;R:result's snip)"]
    if os.path.exists(memory_path):
        try:
            with open(memory_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    msg = json.loads(line)
                    role = msg.get("role")
                    if role == "user":
                        content = msg.get("content", "")
                        trace_lines.append(f'\n[U]"{content}"')
                    elif role == "assistant":
                        content = msg.get("content", "")
                        reasoning = msg.get("reasoning_content", "")
                        a_text = ""
                        if reasoning:
                            a_text += f"{reasoning}\n"
                        if content:
                            a_text += f"{content}"
                        if a_text.strip():
                            trace_lines.append(f"\n[A]{a_text.strip()}")
                        tool_calls = msg.get("tool_calls", [])
                        for tc in tool_calls:
                            func_name = tc.get("function", {}).get(
                                "name", "unknown_tool"
                            )
                            trace_lines.append(f"\n[C]{func_name}")
                    elif role == "tool":
                        raw_content = msg.get("content", "")
                        snip = ""
                        try:
                            parsed = json.loads(raw_content)
                            if isinstance(parsed, dict):
                                if (
                                    "metadata" in parsed
                                    and "snip" in parsed["metadata"]
                                ):
                                    snip = parsed["metadata"]["snip"]
                                elif "summary" in parsed:
                                    snip = str(parsed["summary"])
                                else:
                                    snip = raw_content[:100] + "..."
                            else:
                                snip = raw_content[:100] + "..."
                        except json.JSONDecodeError:
                            snip = raw_content[:100] + "..."
                        snip = snip if snip else "执行成功 (无简述)"
                        trace_lines.append(f"\n[R]{snip}")
        except Exception as e:
            trace_lines.append(f"\n[Error] 解析轨迹失败: {str(e)}")
    else:
        trace_lines.append("\n[Error] 未找到测试工人的记忆文件")

    with open(output_trace_path, "w", encoding="utf-8") as out_f:
        out_f.write("\n".join(trace_lines))


# 🌟 核心拆分 1：单例测试运行器协程
async def _run_single_eval_case(
    case, dev_skill_dir, iteration_dir, workplace_id, skill_name, iteration_idx
):
    try:
        case_id = case.get("id", "unknown")
        eval_run_dir = os.path.join(iteration_dir, f"eval-{case_id}", "with_skill")
        sandbox_eval_dir = f"/agent_vm/skill_workplace/{workplace_id}/iteration-{iteration_idx}/eval-{case_id}/with_skill"

        def ignore_eval_files(dir_path, contents):
            return ["evals", "README.md", ".git", ".gitignore", "__pycache__"]

        # 同一代重跑评测时先清掉上一轮残留目录，否则 copytree 会撞上已存在目录（WinError 183）
        shutil.rmtree(eval_run_dir, ignore_errors=True)
        shutil.copytree(dev_skill_dir, eval_run_dir, ignore=ignore_eval_files)
        outputs_dir = os.path.join(eval_run_dir, "outputs")
        os.makedirs(outputs_dir, exist_ok=True)

        assets_list = case.get("files", case.get("assets", []))
        for asset_path in assets_list:
            src_asset = os.path.join(dev_skill_dir, asset_path)
            if os.path.exists(src_asset):
                dst_asset = os.path.join(eval_run_dir, os.path.basename(asset_path))
                if os.path.isdir(src_asset):
                    shutil.copytree(src_asset, dst_asset, dirs_exist_ok=True)
                else:
                    shutil.copy2(src_asset, dst_asset)

        prompt = case.get("prompt", "")
        expected = case.get("expected_output", "")
        assertions = case.get("assertions", [])
        qa_expected = (
            f"【预期结果】\n{expected}\n\n【硬性断言检查清单(Assertions)】\n"
            + "\n".join([f"- {a}" for a in assertions])
        )

        host_skill_md_path = os.path.abspath(os.path.join(eval_run_dir, "SKILL.md"))

        task = Task(
            task_name=f"Eval_{skill_name}_{case_id}",
            inputs={
                "host_skill_md_path": host_skill_md_path,
                "workplace_dir": sandbox_eval_dir,
                "prompt": prompt,
                "expected_output": qa_expected,
            },
            graph_name="skill_eval",
            # 💡 核心修复：注入 iteration_idx 确保每次迭代生成独立的 Task 存档
            task_id=f"eval_{workplace_id}_iter{iteration_idx}_{case_id}",
        )

        res = await task.run()

        elapsed = task.execution_time
        tokens = task.total_tokens

        # 清洗并存储隔离区内独立的 trace.md
        agent_memory_path = os.path.join(
            task.checkpoint_dir, "nodes", "nd_agent_exec", "memory.jsonl"
        )
        trace_filepath = os.path.join(eval_run_dir, "trace.md")
        _format_and_save_trace(agent_memory_path, trace_filepath)

        timing_data = {"total_tokens": tokens, "duration_ms": int(elapsed * 1000)}
        with open(os.path.join(eval_run_dir, "timing.json"), "w") as f:
            json.dump(timing_data, f, indent=2)

        is_pass = False
        reason = "未知错误"

        if res.get("status") == "success":
            outputs = res.get("outputs", {})
            eval_res = outputs.get("eval_result", {})
            # 解包信封：{"type": ..., "data": ...}；data 可能是裸 dict 或 JSON 字符串
            if isinstance(eval_res, dict) and "data" in eval_res:
                eval_res = eval_res.get("data")
            if isinstance(eval_res, str):
                try:
                    eval_res = json.loads(eval_res)
                except Exception:
                    eval_res = {}

            is_pass = eval_res.get("pass", False)
            reason = eval_res.get("reason", "未提供理由")
            grading_data = eval_res.get("grading_data", {})

            # 兼容 skill_eval 图 v2.0：裁判经 task_done 输出
            # {"assertion_results": [...], "summary": {"passed","failed","total","pass_rate"}}
            # （或外层再包一层 {"status":..., "summary": {...}}）
            summary = eval_res.get("summary")
            assertion_results = eval_res.get("assertion_results", [])
            if isinstance(summary, dict):
                inner = summary.get("summary", summary)
                if summary.get("assertion_results"):
                    assertion_results = summary["assertion_results"]
                passed, total = inner.get("passed"), inner.get("total")
                if passed is not None and total:
                    is_pass = passed == total
                    grading_data = {
                        "assertion_results": assertion_results,
                        "summary": inner,
                    }
                    pass_rate = inner.get("pass_rate")
                    reason_lines = [f"裁判判定 {passed}/{total} 条断言通过"]
                    if isinstance(pass_rate, (int, float)):
                        reason_lines.append(f"（通过率 {pass_rate * 100:.0f}%）")
                    failed_items = [a for a in assertion_results if not a.get("passed")]
                    if failed_items:
                        reason_lines.append("未通过的断言：")
                        reason_lines.extend(
                            f"- {a.get('text', '')}：{a.get('evidence', '无证据')}"
                            for a in failed_items
                        )
                    reason = "\n".join(reason_lines)

            with open(
                os.path.join(eval_run_dir, "grading.json"), "w", encoding="utf-8"
            ) as f:
                json.dump(grading_data, f, ensure_ascii=False, indent=2)
        else:
            reason = res.get("message", "执行异常中断")
            grading_data = {"summary": {"passed": False, "reason": reason}}
            with open(
                os.path.join(eval_run_dir, "grading.json"), "w", encoding="utf-8"
            ) as f:
                json.dump(grading_data, f, ensure_ascii=False, indent=2)

        try:
            from src.tool.bash import close_session

            await asyncio.to_thread(close_session, task.task_id)
        except Exception:
            pass

        benchmark_item = {
            "case_id": case_id,
            "pass": is_pass,
            "time_seconds": round(elapsed, 2),
            "tokens": tokens,
            "reason": reason,
        }

        return benchmark_item, elapsed, tokens

    except Exception as e:
        return (
            {
                "case_id": case.get("id", "unknown"),
                "pass": False,
                "time_seconds": 0,
                "tokens": 0,
                "reason": f"框架崩溃: {str(e)}",
            },
            0.0,
            0,
        )


async def _async_run_evals(workplace_id: str, skill_name: str) -> str:
    workplace_root = os.path.join(AGENT_VM_DIR, "skill_workplace", workplace_id)
    dev_skill_dir = os.path.join(workplace_root, skill_name)
    evals_file = os.path.join(dev_skill_dir, "evals", "evals.json")

    if not os.path.exists(evals_file):
        return f"测试失败：未找到 {evals_file}"

    try:
        with open(evals_file, "r", encoding="utf-8") as f:
            evals_data = json.load(f)
    except json.JSONDecodeError:
        return "测试失败：evals.json 格式错误，无法解析为有效的 JSON。"

    cases = evals_data.get("evals", [])
    if not cases:
        return "测试报告：evals.json 中没有任何测试用例。"

    # 盲测与最近一轮 Trigger 测试共用同一迭代目录
    iteration_dir, iteration_idx = _get_eval_iteration_dir(workplace_root)
    os.makedirs(iteration_dir, exist_ok=True)

    # 🌟 核心拆分 2：启动错位并发任务池
    async def spawn_tasks():
        tasks = []
        for case in cases:
            # 创建独立协程扔进事件循环
            task_coro = asyncio.create_task(
                _run_single_eval_case(
                    case,
                    dev_skill_dir,
                    iteration_dir,
                    workplace_id,
                    skill_name,
                    iteration_idx,
                )
            )
            tasks.append(task_coro)
            # ✨ “看人下菜碟”：发布间隔错位 3 秒
            await asyncio.sleep(3)

        # 等待所有错位任务执行完毕并聚合并发结果
        return await asyncio.gather(*tasks)

    # 启动全量并发收集！
    results = await spawn_tasks()

    benchmark_cases = []
    total_time, total_tokens = 0.0, 0

    # 将并发获取的结果按顺序拼装
    for benchmark_item, elapsed, tokens in results:
        benchmark_cases.append(benchmark_item)
        total_time += elapsed
        total_tokens += tokens

    pass_values = [1.0 if c["pass"] else 0.0 for c in benchmark_cases]
    time_values = [c["time_seconds"] for c in benchmark_cases]
    token_values = [c["tokens"] for c in benchmark_cases]

    run_summary = {
        "with_skill": {
            "pass_rate": _calculate_stats(pass_values),
            "time_seconds": _calculate_stats(time_values),
            "tokens": _calculate_stats(token_values),
        }
    }
    benchmark_data = {"run_summary": run_summary, "cases": benchmark_cases}

    benchmark_path = os.path.join(iteration_dir, "benchmark.json")
    with open(benchmark_path, "w", encoding="utf-8") as f:
        json.dump(benchmark_data, f, ensure_ascii=False, indent=2)

    pass_count = sum(1 for c in benchmark_cases if c["pass"])
    _write_json(
        os.path.join(iteration_dir, "eval_result.json"),
        {
            "skill_name": skill_name,
            "iteration": iteration_idx,
            "generated_at": _now_iso(),
            "total": len(benchmark_cases),
            "passed": pass_count,
            "summary": run_summary["with_skill"],
            "cases": benchmark_cases,
        },
    )
    _render_skill_report(workplace_root, iteration_dir, iteration_idx, skill_name)

    token_mean = run_summary["with_skill"]["tokens"]["mean"]
    return (
        f"📊 盲测通过 {pass_count}/{len(benchmark_cases)}，"
        f"平均 {run_summary['with_skill']['time_seconds']['mean']}s / {token_mean} tokens，"
        f"报告已生成（iteration-{iteration_idx}/report.html）。"
    )
