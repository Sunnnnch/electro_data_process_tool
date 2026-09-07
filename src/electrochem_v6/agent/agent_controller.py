"""
AI Agent controller - manages conversation and tool calling.
AI Agent控制器 - 管理对话流程和工具调用。
"""

import json
import logging
import threading
from typing import Any, Callable, Dict, List, Optional

from electrochem_v6.core.job_control import ProcessingCancelledError
from electrochem_v6.llm.base_client import BaseLLMClient
from electrochem_v6.llm.error_utils import sanitize_llm_error

from .prompts import SYSTEM_PROMPT
from .tool_executor import execute_tool
from .tools import ALL_TOOLS

_logger = logging.getLogger(__name__)


def _debug_log(tag: str, payload):
    """统一的Debug输出，保证中文不会变成??"""
    try:
        if isinstance(payload, str):
            text = payload
        else:
            text = json.dumps(payload, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(payload)
    _logger.debug("[%s]: %s", tag, text)


class AgentController:
    """​AI Agent控制器"""

    # Maximum number of messages kept in conversation_history.
    # When exceeded the oldest messages (after the first system turn) are
    # dropped to keep the context within LLM token limits.
    MAX_HISTORY_MESSAGES = 80

    def __init__(self, llm_client: BaseLLMClient, system_prompt: Optional[str] = None):
        """
        初始化Agent

        Args:
            llm_client: LLM客户端实例
            system_prompt: 系统提示词(不提供则使用默认)
        """
        self.llm = llm_client
        self.conversation_history: List[Dict] = []
        self.last_tool_calls: List[str] = []
        self.system_prompt = system_prompt or SYSTEM_PROMPT
        self.max_iterations = 10  # 最大工具调用迭代次数

    def _stream_response(
        self,
        messages: List[Dict],
        *,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> Dict[str, Any]:
        """Aggregate a streaming response, including fragmented tool calls."""
        content_parts: list[str] = []
        tool_calls: dict[int, dict[str, Any]] = {}
        received_chunk = False
        iterator = self.llm.stream_chat(messages, tools=ALL_TOOLS)
        if iterator is None:
            raise NotImplementedError
        watcher_stop = threading.Event()
        watcher = None
        if cancel_check:
            def _watch_cancellation() -> None:
                while not watcher_stop.wait(0.1):
                    if cancel_check():
                        cancel_stream = getattr(self.llm, "cancel_active_stream", None)
                        if callable(cancel_stream):
                            cancel_stream()
                        return

            watcher = threading.Thread(target=_watch_cancellation, daemon=True, name="electrochem-ai-cancel")
            watcher.start()
        try:
            for chunk in iterator:
                received_chunk = True
                if cancel_check and cancel_check():
                    close = getattr(iterator, "close", None)
                    if callable(close):
                        close()
                    raise ProcessingCancelledError("AI request was cancelled")
                if not isinstance(chunk, dict):
                    continue
                if chunk.get("error"):
                    return {"error": chunk["error"]}
                if chunk.get("content"):
                    content_parts.append(str(chunk["content"]))
                for fallback_index, fragment in enumerate(chunk.get("tool_calls") or []):
                    if not isinstance(fragment, dict):
                        continue
                    index = int(fragment.get("index", fallback_index) or 0)
                    target = tool_calls.setdefault(
                        index,
                        {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
                    )
                    if fragment.get("id"):
                        target["id"] = str(fragment["id"])
                    if fragment.get("type"):
                        target["type"] = str(fragment["type"])
                    function_fragment = fragment.get("function")
                    if not isinstance(function_fragment, dict):
                        function_fragment = {}
                    function_target = target.get("function")
                    if not isinstance(function_target, dict):
                        function_target = {"name": "", "arguments": ""}
                        target["function"] = function_target
                    if function_fragment.get("name"):
                        function_target["name"] = str(function_target.get("name") or "") + str(
                            function_fragment["name"]
                        )
                    if function_fragment.get("arguments"):
                        function_target["arguments"] = str(function_target.get("arguments") or "") + str(
                            function_fragment["arguments"]
                        )
        finally:
            watcher_stop.set()
            if watcher is not None:
                watcher.join(timeout=0.2)
        if cancel_check and cancel_check():
            raise ProcessingCancelledError("AI request was cancelled")
        if not received_chunk:
            raise NotImplementedError
        response: Dict[str, Any] = {"role": "assistant", "content": "".join(content_parts)}
        if tool_calls:
            response["tool_calls"] = [tool_calls[index] for index in sorted(tool_calls)]
        return response

    def chat(
        self,
        user_message: str,
        callback: Optional[Callable[[str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> str:
        """
        处理用户消息

        Args:
            user_message: 用户输入
            callback: 进度回调函数(用于GUI更新状态)

        Returns:
            AI的最终回复
        """
        history_before_turn = self.conversation_history.copy()
        tool_calls_before_turn = self.last_tool_calls.copy()
        self.last_tool_calls = []
        # 添加用户消息到历史
        self.conversation_history.append({
            "role": "user",
            "content": user_message
        })

        # Trim old history to stay within token budget
        self._trim_history()

        # 构建完整消息(系统提示 + 历史)
        messages = [
            {"role": "system", "content": self.system_prompt}
        ] + self.conversation_history

        # 迭代处理(支持多轮工具调用)
        for iteration in range(self.max_iterations):
            if cancel_check and cancel_check():
                self.conversation_history = history_before_turn
                self.last_tool_calls = tool_calls_before_turn
                raise ProcessingCancelledError("AI request was cancelled")
            if callback:
                callback(f"🤔 思考中... (第{iteration + 1}轮)")

            try:
                # 调用LLM
                try:
                    response = self._stream_response(messages, cancel_check=cancel_check)
                except (NotImplementedError, TypeError):
                    response = self.llm.chat(messages, tools=ALL_TOOLS)
                if cancel_check and cancel_check():
                    raise ProcessingCancelledError("AI request was cancelled")

                if 'error' in response:
                    error_msg = f"LLM调用失败: {sanitize_llm_error(response['error'])}"
                    self.conversation_history.append({
                        "role": "assistant",
                        "content": error_msg
                    })
                    return error_msg

                # 检查是否有工具调用
                if 'tool_calls' in response and response['tool_calls']:
                    # 添加助手的工具调用消息
                    self.conversation_history.append(response)
                    messages.append(response)

                    # 执行所有工具
                    tool_messages = []
                    for tool_call in response['tool_calls']:
                        if cancel_check and cancel_check():
                            raise ProcessingCancelledError("AI request was cancelled")
                        tool_name = tool_call['function']['name']
                        tool_args = tool_call['function']['arguments']
                        self.last_tool_calls.append(str(tool_name))

                        if callback:
                            callback(f"🔧 执行工具: {tool_name}...")

                        # ✅ 添加调试:打印工具调用
                        _debug_log("调用工具", tool_name)
                        _debug_log("参数", tool_args)

                        # 执行工具
                        result = execute_tool(tool_name, tool_args)

                        # ✅ 添加调试:打印工具结果
                        _debug_log("工具返回", result)

                        # 构建工具结果消息
                        tool_message = {
                            "role": "tool",
                            "tool_call_id": tool_call['id'],
                            "name": tool_name,
                            "content": json.dumps(result, ensure_ascii=False, default=str)  # ✅ 添加default=str处理特殊类型
                        }

                        tool_messages.append(tool_message)
                        self.conversation_history.append(tool_message)

                    # 添加工具结果到消息
                    messages.extend(tool_messages)

                    # 继续下一轮(让LLM根据工具结果生成回复)
                    continue

                else:
                    # 没有工具调用,这是最终回复
                    assistant_message = response.get('content', '')
                    self.conversation_history.append({
                        "role": "assistant",
                        "content": assistant_message
                    })
                    return assistant_message

            except ProcessingCancelledError:
                self.conversation_history = history_before_turn
                self.last_tool_calls = tool_calls_before_turn
                raise
            except Exception as e:
                error_msg = f"处理出错: {sanitize_llm_error(e)}"
                self.conversation_history.append({
                    "role": "assistant",
                    "content": error_msg
                })
                return error_msg

        # 达到最大迭代次数
        timeout_msg = "处理超时,请简化您的问题或分步骤提问。"
        self.conversation_history.append({
            "role": "assistant",
            "content": timeout_msg
        })
        return timeout_msg

    def reset(self):
        """重置对话历史"""
        self.conversation_history = []
        self.last_tool_calls = []

    def get_history(self) -> List[Dict]:
        """获取对话历史"""
        return self.conversation_history.copy()

    def get_last_tool_calls(self) -> List[str]:
        """Return tool names used by the most recent user turn."""
        return self.last_tool_calls.copy()

    def _trim_history(self) -> None:
        """Drop oldest messages when conversation_history exceeds the cap.

        Keeps the most recent messages so the LLM always has fresh context.
        After truncation, any leading ``tool`` role messages (which would
        lack their matching ``assistant`` tool_calls entry) are stripped so
        that the LLM API never receives dangling tool results.
        """
        if len(self.conversation_history) <= self.MAX_HISTORY_MESSAGES:
            return
        # Keep the newest MAX_HISTORY_MESSAGES entries
        trimmed = self.conversation_history[-self.MAX_HISTORY_MESSAGES:]
        # Strip orphaned tool-result messages at the front
        while trimmed and trimmed[0].get("role") == "tool":
            trimmed.pop(0)
        self.conversation_history = trimmed

    def export_conversation(self, file_path: str) -> bool:
        """导出对话记录"""
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump({
                    "model": self.llm.get_model_name(),
                    "conversation": self.conversation_history
                }, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            _logger.warning("导出对话记录失败: %s", file_path, exc_info=True)
            return False


__all__ = ["AgentController"]
