"""
Base LLM client interface.
All LLM providers must implement this interface.
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Iterator


class BaseLLMClient(ABC):
    """LLM客户端基类"""
    
    @abstractmethod
    def chat(self, messages: List[Dict[str, str]], tools: Optional[List[Dict]] = None, 
             temperature: float = 0.7, max_tokens: int = 4000) -> Dict[str, Any]:
        """
        发送对话请求
        
        Args:
            messages: 对话消息列表 [{"role": "user", "content": "..."}]
            tools: 可用工具列表（Function Calling格式）
            temperature: 温度参数（0-1，越高越随机）
            max_tokens: 最大token数
        
        Returns:
            响应字典，包含content或tool_calls
        """
        pass
    
    @abstractmethod
    def stream_chat(self, messages: List[Dict[str, str]], tools: Optional[List[Dict]] = None,
                    temperature: float = 0.7, max_tokens: int = 4000) -> Iterator[Dict[str, Any]]:
        """
        流式对话请求
        
        Returns:
            迭代器，逐块返回响应
        """
        pass
    
    def get_model_name(self) -> str:
        """获取模型名称"""
        return getattr(self, 'model', 'unknown')
    
    def test_connection(self) -> bool:
        """测试连接是否正常"""
        try:
            response = self.chat([{"role": "user", "content": "test"}], max_tokens=10)
            return response is not None
        except Exception:
            return False


__all__ = ["BaseLLMClient"]




