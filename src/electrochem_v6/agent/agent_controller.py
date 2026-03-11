"""
AI Agent controller - manages conversation and tool calling.
AI Agent控制器 - 管理对话流程和工具调用。
"""

import json
import logging
from typing import List, Dict, Any, Optional, Callable
from electrochem_v6.llm.base_client import BaseLLMClient
from .tool_executor import execute_tool
from .tools import ALL_TOOLS
from .prompts import SYSTEM_PROMPT

_logger = logging.getLogger(__name__)


def _debug_log(tag: str, payload):
    """统一的Debug输出，保证中文不会变成??"""
    try:
        if isinstance(payload, str):
            text = payload
        else:
            text = json.dumps(payload, ensure_ascii=False, default=str)
    except Exception:
        text = str(payload)
    _logger.debug("[%s]: %s", tag, text)


class AgentController:
    """AI Agent控制器"""
    
    def __init__(self, llm_client: BaseLLMClient, system_prompt: str = None):
        """
        初始化Agent
        
        Args:
            llm_client: LLM客户端实例
            system_prompt: 系统提示词(不提供则使用默认)
        """
        self.llm = llm_client
        self.conversation_history: List[Dict] = []
        self.system_prompt = system_prompt or SYSTEM_PROMPT
        self.max_iterations = 10  # 最大工具调用迭代次数
    
    def chat(self, user_message: str, callback: Optional[Callable[[str], None]] = None) -> str:
        """
        处理用户消息
        
        Args:
            user_message: 用户输入
            callback: 进度回调函数(用于GUI更新状态)
        
        Returns:
            AI的最终回复
        """
        # 添加用户消息到历史
        self.conversation_history.append({
            "role": "user",
            "content": user_message
        })
        
        # 构建完整消息(系统提示 + 历史)
        messages = [
            {"role": "system", "content": self.system_prompt}
        ] + self.conversation_history
        
        # 迭代处理(支持多轮工具调用)
        for iteration in range(self.max_iterations):
            if callback:
                callback(f"🤔 思考中... (第{iteration + 1}轮)")
            
            try:
                # 调用LLM
                response = self.llm.chat(messages, tools=ALL_TOOLS)
                
                if 'error' in response:
                    error_msg = f"LLM调用失败: {response['error']}"
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
                        tool_name = tool_call['function']['name']
                        tool_args = tool_call['function']['arguments']
                        
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
                    
            except Exception as e:
                error_msg = f"处理出错: {str(e)}"
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
    
    def get_history(self) -> List[Dict]:
        """获取对话历史"""
        return self.conversation_history.copy()
    
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
            return False


__all__ = ["AgentController"]


