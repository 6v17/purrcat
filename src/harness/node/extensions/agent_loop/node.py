import asyncio
import json
import os
from typing import Any, Dict

import yaml

from src.agent.hook_handler import HookHandler
from src.harness.node.agent_node import AgentNode
from src.harness.utils.llm_helper import call_llm
from src.harness.utils.tool_helper import extract_tool_calling, get_system_schema
from src.utils.config import AGENT_VM_DIR
from src.utils.paradigm_api import resolve_paradigm_path

SANDBOX_TASKSPACE_ROOT = "/agent_vm/_taskspace"


class Node(AgentNode):
    """范式（agentloop）驱动的智能体循环，与 src/agent 主循环语义对齐。

    - 输入一个符合 YAML 格式的 agentloop（也可传范式名或绝对路径），按 hook 驱动执行；
    - 循环终止：模型不再调用工具且 on_loop_end 全部通过（尊重 expect: fail 与 loop_end_max_retry）；
    - summary：优先读取 @TASKSPACE/<summary_file>，缺失回退最后一条 assistant 文本。
    """

    def _resolve_agentloop(self, raw, context) -> tuple:
        """解析 agentloop 输入，返回 (config_dict, paradigm_path_or_None)。"""
        if isinstance(raw, dict):
            return raw, None

        if isinstance(raw, str) and raw.strip():
            text = raw.strip()
            try:
                loaded = yaml.safe_load(text)
            except Exception:
                loaded = None
            if isinstance(loaded, dict) and ("hooks" in loaded or "name" in loaded):
                return loaded, None
            # 否则视为范式名或绝对路径
            if os.path.isabs(text) and os.path.exists(text):
                with open(text, "r", encoding="utf-8") as f:
                    return (yaml.safe_load(f) or {}), text
            path = resolve_paradigm_path(text)
            self.log(context, "SYSTEM", f"📄 [AgentLoop] 从范式文件加载: {path}")
            with open(path, "r", encoding="utf-8") as f:
                return (yaml.safe_load(f) or {}), path

        path = resolve_paradigm_path(None)
        self.log(
            context, "SYSTEM", f"📄 [AgentLoop] 未提供 agentloop，回退默认范式: {path}"
        )
        with open(path, "r", encoding="utf-8") as f:
            return (yaml.safe_load(f) or {}), path

    async def execute(self, inputs: Dict[str, Any], context: Any) -> Dict[str, Any]:
        self.log(context, "SYSTEM", "🤖 [Agent循环] 开始执行（范式驱动）")

        # 1) 构建 hook 执行器
        config_dict, paradigm_path = self._resolve_agentloop(
            self.unpack(inputs, "agentloop"), context
        )
        handler = HookHandler(config_dict=config_dict, paradigm_path=paradigm_path)

        # 2) taskspace（按 (task_name, node_id) 稳定复用，有效防重复）
        taskspace_host = os.path.join(
            AGENT_VM_DIR, "_taskspace", context.task_name, self.node_id
        )
        os.makedirs(taskspace_host, exist_ok=True)
        sandbox_dir = f"{SANDBOX_TASKSPACE_ROOT}/{context.task_name}/{self.node_id}"
        handler.add_alias("@TASKSPACE", host_path=taskspace_host, content=sandbox_dir)
        self.log(context, "SYSTEM", f"🗂️ [TASKSPACE] 专属工作目录: {sandbox_dir}")

        # 3) 记忆 + 上游 messages + force_push
        messages = self.load_memory_from_file(context)
        newly_user = []
        upstream = self.unpack(inputs, "messages") or []
        if upstream:
            messages.extend(upstream)
            newly_user += [m for m in upstream if m.get("role") == "user"]
            await asyncio.to_thread(self.append_memory_to_file, context, upstream)

        pending = context.node_memory.setdefault(self.node_id, {}).pop("force_push", [])
        if pending:
            self.log(context, "SYSTEM", f"🔔 [人工指令] 收到 {len(pending)} 条人工指令")
            fps = [{"role": "user", "content": f"[人工指令] {m}"} for m in pending]
            messages.extend(fps)
            newly_user += fps
            await asyncio.to_thread(self.append_memory_to_file, context, fps)

        messages = self._sanitize_messages(messages)

        # 4) on_input_received：对本批新增 user 消息触发
        if newly_user:
            await self._fire_hooks(
                handler,
                "on_input_received",
                messages,
                context,
                epoch=0,
                received_messages=[
                    {"type": "user", "content": str(m.get("content", ""))}
                    for m in newly_user
                ],
                fire_input=False,
            )

        # 5) 系统提示：仅当 messages 无 system 角色时构建
        if not any(m.get("role") == "system" for m in messages):
            results = handler.execute("on_build_system_prompt", epoch=0)
            parts = [r["inject_prompt"] for r in results if r.get("inject_prompt")]
            if parts:
                sys_msg = {"role": "system", "content": "\n\n---\n\n".join(parts)}
                messages.insert(0, sys_msg)
                await asyncio.to_thread(self.append_memory_to_file, context, [sys_msg])

        # 6) on_loop_start
        await self._fire_hooks(handler, "on_loop_start", messages, context, epoch=0)

        # 7) 主循环
        tools = get_system_schema()
        used_tools: Dict[str, list] = {}
        loop_epoch = 0
        loop_end_retry = 0
        last_assistant_text = ""

        while True:
            loop_epoch += 1
            self.log(
                context, "SYSTEM", f"🔄 [Agent循环] 开始新一轮思考 (epoch={loop_epoch})"
            )
            await self._fire_hooks(
                handler, "on_loop_epoch", messages, context, epoch=loop_epoch
            )

            response, messages = await call_llm(context.model, messages, tools)
            self._accumulate_tokens(context, response)
            assistant_msg = response.choices[0].message

            finish_reason = getattr(response.choices[0], "finish_reason", None)
            if finish_reason == "length":
                self.log(
                    context,
                    "WARNING",
                    "⚠️ [输出截断] 模型输出因长度上限被截断，本轮工具参数可能不完整",
                )

            if assistant_msg.content:
                last_assistant_text = assistant_msg.content
                preview = (
                    assistant_msg.content[:200] + "..."
                    if len(assistant_msg.content) > 200
                    else assistant_msg.content
                )
                self.log(context, "SYSTEM", f"💭 [模型回复] {preview}")

            await asyncio.to_thread(self.append_memory_to_file, context, [messages[-1]])
            await asyncio.to_thread(self._sync_dump_memory, context, messages)

            tool_calls = extract_tool_calling(response)
            if tool_calls:
                self.log(
                    context,
                    "SYSTEM",
                    f"🔧 [工具调用] 检测到 {len(tool_calls)} 个工具调用",
                )
                current_tools: Dict[str, list] = {}
                for t in tool_calls:
                    args = {}
                    if t.function.arguments:
                        try:
                            args = json.loads(t.function.arguments)
                        except Exception:
                            args = {}
                    used_tools.setdefault(t.function.name, []).append(args)
                    current_tools.setdefault(t.function.name, []).append(args)

                tool_msgs = await self.run_tool_calls(response, context)
                messages.extend(tool_msgs)
                if tool_msgs:
                    await asyncio.to_thread(
                        self.append_memory_to_file, context, tool_msgs
                    )
                    await asyncio.to_thread(self._sync_dump_memory, context, messages)

                await self._fire_hooks(
                    handler,
                    "on_tool_calling",
                    messages,
                    context,
                    epoch=loop_epoch,
                    used_tools=current_tools,
                )
                continue

            # 无工具调用 → 判定是否结束循环
            all_success = await self._fire_hooks(
                handler,
                "on_loop_end",
                messages,
                context,
                epoch=loop_epoch,
                used_tools=used_tools,
                loop_end_retry=loop_end_retry,
            )
            if all_success:
                self.log(
                    context, "SYSTEM", "✅ [循环结束] 所有结束条件通过，正常关闭循环"
                )
                break

            loop_end_retry += 1
            hint = {
                "type": "workflow_hint",
                "content": "未满足结束循环条件，已自动打回",
            }
            hint_msg = {"role": "user", "content": json.dumps(hint, ensure_ascii=False)}
            messages.append(hint_msg)
            await asyncio.to_thread(self.append_memory_to_file, context, [hint_msg])
            await self._fire_hooks(
                handler,
                "on_input_received",
                messages,
                context,
                epoch=0,
                received_messages=[hint],
                fire_input=False,
            )

        # 8) summary：优先 @TASKSPACE/<summary_file>，回退最后 assistant 文本
        summary = self._read_summary(context, taskspace_host)
        if not summary:
            summary = last_assistant_text or "任务完成"

        display_summary = (
            str(summary)[:1500] + "..." if len(str(summary)) > 1500 else str(summary)
        )
        self.log(context, "SYSTEM", f"📊 [总结内容]:\n{display_summary}")
        return {"messages": messages, "summary": summary}

    async def _fire_hooks(
        self, handler, stage, messages, context, fire_input=True, **kwargs
    ):
        """执行 hook → 以 role=user 注入 inject_prompt →（可选）触发 on_input_received。

        返回 all_success（无 hook 时视为 True）。
        """
        results = handler.execute(stage, **kwargs)
        all_success = all(r.get("success") for r in results) if results else True

        injected = []
        for r in results:
            if r.get("inject_prompt"):
                hint = {"type": "workflow_hint", "content": r["inject_prompt"]}
                msg = {"role": "user", "content": json.dumps(hint, ensure_ascii=False)}
                messages.append(msg)
                injected.append(hint)

        if injected:
            await asyncio.to_thread(
                self.append_memory_to_file, context, messages[-len(injected) :]
            )
            # 非递归触发「收到输入时」：钩子自身的注入不再触发下一层
            if fire_input:
                sub = handler.execute(
                    "on_input_received", epoch=0, received_messages=injected
                )
                sub_msgs = []
                for r in sub:
                    if r.get("inject_prompt"):
                        h = {"type": "workflow_hint", "content": r["inject_prompt"]}
                        m = {
                            "role": "user",
                            "content": json.dumps(h, ensure_ascii=False),
                        }
                        messages.append(m)
                        sub_msgs.append(m)
                if sub_msgs:
                    await asyncio.to_thread(
                        self.append_memory_to_file, context, sub_msgs
                    )

        return all_success

    @staticmethod
    def _accumulate_tokens(context, response):
        usage = getattr(response, "usage", None)
        if usage and hasattr(context, "total_tokens"):
            with context._lock:
                context.total_tokens += usage.total_tokens

    def _read_summary(self, context, taskspace_host) -> str:
        filename = (self.config.get("summary_file") or "summary.txt").strip()
        path = os.path.join(taskspace_host, filename)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    text = f.read().strip()
                if text:
                    self.log(context, "SYSTEM", f"📥 [总结转递] 读取 {filename} 成功")
                    return text
            except Exception as e:
                self.log(context, "WARNING", f"⚠️ [总结读取失败] {e}")
        return ""
