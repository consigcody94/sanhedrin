"""
Sanhedrin A2A Server.

FastAPI-based A2A Protocol server exposing CLI adapters as agents.
"""

from sanhedrin.server.app import app, create_app, serve
from sanhedrin.server.task_manager import TaskManager
from sanhedrin.server.agent_card import AgentCardBuilder, build_agent_card
from sanhedrin.server.handlers import JSONRPCHandler

__all__ = [
    "app",
    "create_app",
    "serve",
    "TaskManager",
    "AgentCardBuilder",
    "build_agent_card",
    "JSONRPCHandler",
]
