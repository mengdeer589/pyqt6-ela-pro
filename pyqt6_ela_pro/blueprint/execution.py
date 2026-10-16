"""
运行指示（ComfyUI 式执行状态展示）。

``ElaExecutionController`` 提供**纯 UI** 的运行指示 API：把节点标记为
running / done / error、展示耗时徽标、高亮执行路径上的边（流动虚线）。

重要：本控制器**不执行任何业务逻辑**——不调度、不求值、不跑模型。
它只接收开发者（或模拟器，如 Demo 的 QTimer 顺序模拟）发来的状态
通知并驱动界面反馈。

用法::

    ex = canvas.execution()
    ex.set_path([n1.id, n2.id, n3.id])   # 可选：路径边流动虚线
    ex.start(n1.id)                       # running：脉冲描边 + 旋转圈
    ex.finish(n1.id, 123.0)               # done：success 描边 + "123 ms" 徽标
    ex.fail(n2.id, "模拟失败")            # error：danger 描边 + tooltip
    ex.reset()                            # 全部回 idle，清耗时与路径

移植自 InstructionX_UIKit.blueprint.execution（原库为 PyQt6，
类名 Ela* 前缀；原库无 LICENSE，保留出处）。
"""

from __future__ import annotations

import time

from PyQt6.QtCore import QObject, pyqtSignal

__all__ = ["ElaExecutionController"]


class ElaExecutionController(QObject):
    """节点图运行指示控制器（纯 UI，无业务执行）。

    信号:
        node_started(str): 某节点进入 running。
        node_finished(str, float): 某节点完成，参数为耗时毫秒。
        finished(): 所有曾 running 的节点均已结束（finish / fail）。

    由 ``ElaBlueprintCanvas.execution()`` 取得（画布持有唯一实例）。
    """

    node_started = pyqtSignal(str)
    node_finished = pyqtSignal(str, float)
    finished = pyqtSignal()

    def __init__(self, canvas, parent=None):
        super().__init__(parent or canvas)
        self._canvas = canvas
        self._t0 = {}
        self._active = set()
        self._path_edges = []

    # -- 节点状态 ----------------------------------------------------------
    def start(self, node_id: str) -> None:
        """标记节点 running（脉冲描边 + 标题栏旋转圈），记录起始时刻。

        幂等：已在 running 的节点重复调用直接返回——不覆盖起始时刻、
        不重复发射 ``node_started``。
        """
        node = self._canvas.graph.node(node_id)
        if node is None:
            return
        if node_id in self._active:
            return
        self._t0[node_id] = time.perf_counter()
        self._active.add(node_id)
        node.set_status("running")
        self.node_started.emit(node_id)

    def finish(self, node_id: str, elapsed_ms=None) -> None:
        """标记节点 done：success 描边 + 耗时徽标。

        :param elapsed_ms: 耗时毫秒；缺省自动计时（自 ``start`` 起算，
            未 ``start`` 过则为 0）。

        ``finished`` 只在**确有 running 节点被这次调用结束**时检查 ——
        对从未 ``start`` 的节点调用 ``finish`` 属于「补一个状态」而不是
        「一轮执行结束」，不发 ``finished``（原先空集合也发，宿主每收一次
        就误判一轮结束）。
        """
        node = self._canvas.graph.node(node_id)
        if node is None:
            return
        was_active = node_id in self._active
        t0 = self._t0.pop(node_id, None)  # 显式耗时同样要清掉计时起点
        if elapsed_ms is None:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0 if t0 is not None else 0.0
        self._active.discard(node_id)
        node.set_elapsed_ms(elapsed_ms)
        node.set_status("done")
        self.node_finished.emit(node_id, float(elapsed_ms))
        if was_active:
            self._maybe_finished()

    def fail(self, node_id: str, message: str = "") -> None:
        """标记节点 error：danger 描边 + 错误图标，tooltip 显示 ``message``。"""
        node = self._canvas.graph.node(node_id)
        if node is None:
            return
        was_active = node_id in self._active
        self._active.discard(node_id)
        self._t0.pop(node_id, None)
        node.error_message = str(message)
        node.set_status("error")
        if was_active:
            self._maybe_finished()

    # -- 路径高亮 ----------------------------------------------------------
    def set_path(self, node_ids) -> None:
        """高亮执行路径上的边（流动虚线动画）。

        :param node_ids: 按执行顺序排列的节点 id 序列。**序列中从前到后
            存在的每一条边**都会被标记为 flowing：只要一条边的两个端点
            都在序列里、且方向与序列顺序一致（``from`` 在前）。相邻节点
            之间的边是最常见的一档；分支 DAG（一个节点扇出到多个下游）
            给出的序列也能把两条分支边都点亮 —— 只认「相邻两节点」的
            旧实现会把它们漏掉。
        """
        self._clear_path()
        graph = self._canvas.graph
        order = {}
        for index, nid in enumerate(node_ids):
            order.setdefault(nid, index)
        for edge in graph.edges():
            a, b = order.get(edge.from_node), order.get(edge.to_node)
            if a is None or b is None or a >= b:
                continue
            widget = self._canvas.edge_widget(edge.id)
            if widget is not None:
                widget.set_flowing(True)
                self._path_edges.append(widget)
        if self._path_edges:
            self._canvas._ensure_flow_timer()

    def path_edge_ids(self) -> list:
        """当前被高亮的路径边 id 列表（测试 / 调试用）。"""
        return [w.edge.id for w in self._path_edges]

    def _clear_path(self) -> None:
        for widget in self._path_edges:
            widget.set_flowing(False)
        self._path_edges = []

    # -- 复位 --------------------------------------------------------------
    def reset(self) -> None:
        """全部节点回 idle、清耗时与错误信息、取消路径高亮。"""
        self._clear_path()
        self._active.clear()
        self._t0.clear()
        for node in self._canvas.graph.nodes():
            node.error_message = ""
            node.set_elapsed_ms(None)
            node.set_status("idle")

    # -- 内部 --------------------------------------------------------------
    def _maybe_finished(self) -> None:
        if not self._active:
            self.finished.emit()
