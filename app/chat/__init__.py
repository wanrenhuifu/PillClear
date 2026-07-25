"""/chat 智能体编排流水线（无 Web 框架依赖）。

process_chat() 是唯一公开接口：接受 LLM/RAG/Rules/Repo 四个依赖，
返回 ChatResult 供 HTTP 层直接序列化。
"""

from app.chat.pipeline import ChatResult, process_chat

__all__ = ["ChatResult", "process_chat"]
