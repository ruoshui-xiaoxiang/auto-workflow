# -*- coding: utf-8 -*-
"""繁星系统：H3 完整工作流 + agent 身份/契约。"""
import os

__version__ = "0.1.0"
CONTRACT_ID = "fanxing-agent-v1"
HERE = os.path.dirname(os.path.abspath(__file__))
CONTRACT_PATH = os.path.join(HERE, "contract", CONTRACT_ID + ".md")
DEFAULT_REGISTRY = os.path.join(HERE, "registry", "agents.json")
TOOLS_DIR = os.path.dirname(HERE)
