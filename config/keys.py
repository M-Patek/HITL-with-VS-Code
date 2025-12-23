import os
import json

# --- Gateway & API Configuration ---
# [Optimization] 从环境变量安全读取 JSON 格式的 Key 列表
GATEWAY_API_BASE = os.getenv("GATEWAY_API_BASE", "https://generativelanguage.googleapis.com/v1beta/openai/")
GATEWAY_SECRET = os.getenv("GATEWAY_SECRET", "") # Google AI Studio Key

_keys_str = os.getenv("GEMINI_API_KEYS", "[]")
try:
    GEMINI_API_KEYS = json.loads(_keys_str)
    # 兼容处理：如果是单个字符串，转为列表
    if isinstance(GEMINI_API_KEYS, str):
        GEMINI_API_KEYS = [GEMINI_API_KEYS]
except Exception:
    # 简单的非JSON字符串降级处理
    GEMINI_API_KEYS = []
    if _keys_str and not _keys_str.startswith("["):
        GEMINI_API_KEYS = [_keys_str]

# --- Vector DB ---
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY", "")
PINECONE_ENVIRONMENT = os.getenv("PINECONE_ENVIRONMENT", "us-east-1")
VECTOR_INDEX_NAME = os.getenv("VECTOR_INDEX_NAME", "swarm-memory")

# --- Model Tiers ---
TIER_1_FAST = "gemini-2.5-flash-preview-09-2025"
TIER_2_PRO = "gemini-2.5-flash-preview-09-2025" 
GEMINI_MODEL_NAME = TIER_2_PRO

# Ensure export
__all__ = ["GEMINI_API_KEYS", "GATEWAY_API_BASE", "GEMINI_MODEL_NAME", "PINECONE_API_KEY", "PINECONE_ENVIRONMENT", "VECTOR_INDEX_NAME", "TIER_1_FAST", "TIER_2_PRO"]
