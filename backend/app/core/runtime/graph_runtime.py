"""图运行时 —— 将 GraphTemplate 编译为可执行的 langgraph StateGraph。

GraphRuntime 是多 agent 编排的引擎入口：
    1. compile():  将声明式 GraphTemplate 编译为 StateGraph
    2. ainvoke():  首次执行（从入口节点开始）
    3. aresume():  人工决策后恢复执行
    4. arecover(): 僵尸恢复（从 checkpoint 继续）

编译后的图结构：
    每个 NodeSpec 产生两个 langgraph 节点：
        {node_id}          业务节点 → NodeRunner.run(spec, state)
        {node_id}__gate    控制门 → PausePolicy → RoutePolicy → 条件路由

    边拓扑：
        业务节点 ──直连边──→ 控制门 ──条件边──→ 下一个业务节点 / END

控制门执行流程（_make_gate_node）：
    1. 调用 PausePolicy（如果配置）→ 决定是否 interrupt()
    2. 调用 RoutePolicy → 获取 ControlDecision
    3. 根据 decision.action 设置 route_label：
       "route"  → 跳转到下一节点（递增 revision_count + 发出 REROUTE 事件）
       "finish" → END（terminal_status="completed"）
       "fail"   → END（terminal_status="failed"）
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.runtime.node_runner import NodeRunner
from app.core.runtime.policies import DefaultRoutePolicy
from app.core.runtime.template import GraphTemplate, NodeSpec
from app.schemas.event import EventType
from app.schemas.runtime_state import RuntimeState
from app.services.event_service import EventLogger
from app.services.sse_service import sse_manager


class GraphRuntime:
    """可复用的 StateGraph 运行时。

    接收声明式 GraphTemplate，编译为 langgraph StateGraph，
    提供统一的 invoke / resume / recover 生命周期接口。

    每个工作流执行实例（run）创建一个新的 GraphRuntime。

    Args:
        template:         图模板定义（节点 + 路由 + 策略）
        db:               数据库会话
        workflow_id:      工作流 UUID
        run_id:           本次执行实例 UUID
        execution_attempt:执行尝试号
        thread_id:        langgraph checkpoint 线程标识
        event_logger:     事件日志器
        checkpointer:     langgraph 检查点保存器（AsyncPostgresSaver 或 None）
    """

    def __init__(
        self,
        template: GraphTemplate,
        db: AsyncSession,
        workflow_id: uuid.UUID,
        run_id: uuid.UUID,
        execution_attempt: int,
        thread_id: str,
        event_logger: EventLogger,
        checkpointer=None,
    ):
        self.template = template
        self.db = db
        self.workflow_id = workflow_id
        self.run_id = run_id
        self.execution_attempt = execution_attempt
        self.thread_id = thread_id
        self.event_logger = event_logger
        self.checkpointer = checkpointer

    @property
    def config(self) -> dict:
        """langgraph 配置字典，包含 thread_id 和 workflow 元数据。"""
        return {
            "configurable": {"thread_id": self.thread_id},
            "metadata": {
                "workflow_id": str(self.workflow_id),
                "run_id": str(self.run_id),
                "template": self.template.name,
                "execution_attempt": self.execution_attempt,
            },
        }

    def initial_state(self, data: dict) -> RuntimeState:
        """构造 RuntimeState 初始值。

        从 data 中提取 revision_count / max_revisions 字段，
        构建标准四键 RuntimeState {data, control, runtime, errors}。

        Args:
            data: 业务初始数据（由模板的 make_initial_data() 或等效函数提供）
        """
        revision_count = int(data.get("revision_count", 0) or 0)
        max_revisions = int(data.get("max_revisions", 3) or 3)
        return {
            "data": data,
            "control": {
                "current_node": self.template.entrypoint,
                "revision_count": revision_count,
                "max_revisions": max_revisions,
                "route_label": self.template.entrypoint,
                "terminal_status": None,
            },
            "runtime": {
                "workflow_id": str(self.workflow_id),
                "run_id": str(self.run_id),
                "execution_attempt": self.execution_attempt,
                "thread_id": self.thread_id,
                "template": self.template.name,
            },
            "errors": [],
        }

    def compile(self):
        """编译 GraphTemplate 为可执行的 langgraph StateGraph。

        为每个 NodeSpec 创建一对节点（业务 + 控制门），
        用直连边连接，控制门用条件边路由到下一个目标或 END。

        Returns:
            已编译的 langgraph StateGraph（可执行）
        """
        graph = StateGraph(RuntimeState)
        runner = NodeRunner(
            self.db,
            self.workflow_id,
            self.run_id,
            self.execution_attempt,
            self.event_logger,
        )

        for spec in self.template.nodes:
            graph.add_node(spec.id, self._make_business_node(runner, spec))
            graph.add_node(spec.gate_id, self._make_gate_node(spec))
            graph.add_edge(spec.id, spec.gate_id)
            graph.add_conditional_edges(spec.gate_id, self._gate_router, self._gate_mapping(spec))

        graph.set_entry_point(self.template.entrypoint)
        return graph.compile(checkpointer=self.checkpointer)

    async def ainvoke(self, data: dict):
        """首次执行工作流图。

        Args:
            data: 业务初始数据（与 initial_state 中的 data 结构一致）
        Returns:
            图的最终状态（包含 data / control / runtime / errors）
        """
        return await self.compile().ainvoke(self.initial_state(data), self.config)

    async def aresume(self, decision: dict):
        """人工决策后恢复执行。

        使用 langgraph Command(resume=decision) 重新进入
        上次 interrupt() 挂起的位置。

        Args:
            decision: 人工决策字典（来自 DecisionRequest.model_dump()）
        Returns:
            图的最终状态
        """
        return await self.compile().ainvoke(Command(resume=decision), self.config)

    async def arecover(self):
        """僵尸恢复 —— 从 checkpoint 继续执行。

        用于进程崩溃或超时后的恢复，不传递 resume 值。
        直接 ainvoke(None) 让 langgraph 从最后一个 checkpoint 继续。
        """
        return await self.compile().ainvoke(None, self.config)

    def _make_business_node(self, runner: NodeRunner, spec: NodeSpec):
        """创建业务节点闭包 —— 包装 NodeRunner.run(spec, state)。

        Args:
            runner: NodeRunner 实例（所有业务节点共享）
            spec:   当前 NodeSpec
        Returns:
            闭包 async def node(RuntimeState) -> RuntimeState
        """

        async def _node(state: RuntimeState) -> RuntimeState:
            return await runner.run(spec, dict(state))

        return _node

    def _make_gate_node(self, spec: NodeSpec):
        """创建控制门闭包 —— 评估 PausePolicy → RoutePolicy → 条件路由。

        控制门执行顺序：
            1. 如果配置了 PausePolicy：
               a. 调用 build_pause(state, spec) 获取 PauseRequest
               b. 有 PauseRequest → interrupt(payload) 挂起图
               c. resume 时收到 human_decision → 存入 control["human_decision"]
            2. 调用 RoutePolicy.decide(state, spec) 获取 ControlDecision
            3. 根据 decision.action 设置路由：
               "route"  → route_label=next_node, revision_count+1, 发出 REROUTE 事件
               "finish" → route_label="done", terminal_status="completed"
               "fail"   → route_label="fail", terminal_status="failed"
            4. 持久化 last_decision 和完成时间到 control

        Args:
            spec: 当前 NodeSpec
        Returns:
            闭包 async def gate(RuntimeState) -> RuntimeState
        """

        async def _gate(state: RuntimeState) -> RuntimeState:
            current_state = dict(state)
            data = dict(current_state.get("data") or {})
            control = dict(current_state.get("control") or {})

            # 1. 暂停策略评估
            if spec.pause_policy is not None:
                pause = spec.pause_policy.build_pause({"data": data, "control": control, "runtime": current_state.get("runtime") or {}}, spec)
                if pause is not None:
                    payload = pause.to_interrupt_payload(current_state)
                    decision = interrupt(payload)
                    if isinstance(decision, dict):
                        control["human_decision"] = decision
                        apply_decision = getattr(spec.pause_policy, "apply_decision", None)
                        if callable(apply_decision):
                            applied = apply_decision(
                                {"data": data, "control": control, "runtime": current_state.get("runtime") or {}},
                                spec,
                                dict(decision),
                            )
                            if isinstance(applied, dict):
                                data = dict(applied.get("data") or data)
                                control = dict(applied.get("control") or control)
                                if isinstance(applied.get("decision"), dict):
                                    control["human_decision"] = applied["decision"]
                    control["last_pause"] = payload

            # 2. 路由策略评估
            route_policy = spec.route_policy or DefaultRoutePolicy()
            decision = route_policy.decide({"data": data, "control": control, "runtime": current_state.get("runtime") or {}}, spec)
            route_label = decision.next_node or "done"

            # 3. 根据决策设置路由
            if decision.action == "route" and decision.next_node:
                next_revision = int(control.get("revision_count", data.get("revision_count", 0)) or 0) + 1
                control["revision_count"] = next_revision
                data["revision_count"] = next_revision
                await self._emit_reroute(spec.id, decision.next_node, control)
            elif decision.action == "finish":
                route_label = "done"
                control["terminal_status"] = "completed"
            elif decision.action == "fail":
                route_label = "fail"
                control["terminal_status"] = "failed"
                control["terminal_reason"] = decision.reason

            # 4. 持久化路由信息
            control["route_label"] = route_label
            control["last_decision"] = decision.model_dump(mode="json")
            control["last_gate_completed_at"] = datetime.now(timezone.utc).isoformat()
            return {
                "data": data,
                "control": control,
                "runtime": dict(current_state.get("runtime") or {}),
                "errors": list(current_state.get("errors") or []),
            }

        return _gate

    def _gate_router(self, state: RuntimeState) -> str:
        """条件边路由函数 —— 从 control.route_label 读取目标节点名。

        由 langgraph 的 add_conditional_edges 调用，
        返回的字符串必须能在 _gate_mapping 中找到对应目标。
        """
        return (state.get("control") or {}).get("route_label") or "done"

    def _gate_mapping(self, spec: NodeSpec) -> dict:
        """构建条件边路由映射表。

        将所有可能的 route_label（节点 id / "done" / "fail"）
        映射到对应的 langgraph 节点名或 END 常量。

        集合来源：模板中所有节点 id ∪ spec.allowed_routes ∪ default_next。
        """
        targets = set(self.template.node_ids)
        targets.update(spec.allowed_routes)
        if spec.default_next != "done":
            targets.add(spec.default_next)
        mapping = {target: target for target in targets}
        mapping["done"] = END
        mapping["fail"] = END
        return mapping

    async def _emit_reroute(self, from_node: str, to_node: str, control: dict) -> None:
        """发出 REROUTE 事件（入库 + SSE 广播）。

        当 RoutePolicy 返回 action="route" 时调用。
        事件中区分触发来源：人工 jump 或策略自动路由。

        Args:
            from_node: 来源节点 id
            to_node:   目标节点 id
            control:   当前 control dict（用于检查 human_decision）
        """
        human_decision = control.get("human_decision") or {}
        human_action = human_decision.get("action")
        event = await self.event_logger.log(
            event_type=EventType.REROUTE,
            payload={
                "from_node": from_node,
                "to_node": to_node,
                "trigger": "human_decision" if human_action and human_action not in {"approve", "abort"} else "policy",
                "action": human_action or "",
                "feedback": human_decision.get("feedback", ""),
            },
            node_name="__workflow__",
        )
        await sse_manager.broadcast(self.workflow_id, {
            "event_type": EventType.REROUTE.value,
            "node_name": event.node_name,
            "seq": event.seq,
            "from_node": from_node,
            "to_node": to_node,
        })
