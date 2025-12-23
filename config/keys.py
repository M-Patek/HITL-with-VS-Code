import os
import json

# --- Gateway & API Configuration ---
GATEWAY_API_BASE = os.getenv("GATEWAY_API_BASE", "https://generativelanguage.googleapis.com/v1beta/openai/")
GATEWAY_SECRET = os.getenv("GATEWAY_SECRET", "") 

_keys_str = os.getenv("GEMINI_API_KEYS", "[]")
GEMINI_API_KEYS = []

try:
    parsed = json.loads(_keys_str)
    if isinstance(parsed, list):
        GEMINI_API_KEYS = [k for k in parsed if isinstance(k, str) and k.strip()]
    elif isinstance(parsed, str) and parsed.strip():
        GEMINI_API_KEYS = [parsed.strip()]
except Exception:
    # Fallback for simple comma-separated string or raw string
    if _keys_str and not _keys_str.startswith("["):
        if "," in _keys_str:
             GEMINI_API_KEYS = [k.strip() for k in _keys_str.split(",") if k.strip()]
        else:
             GEMINI_API_KEYS = [_keys_str.strip()]

# Filter out empty keys
GEMINI_API_KEYS = [k for k in GEMINI_API_KEYS if k]

# --- Vector DB ---
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY", "")
PINECONE_ENVIRONMENT = os.getenv("PINECONE_ENVIRONMENT", "us-east-1")
VECTOR_INDEX_NAME = os.getenv("VECTOR_INDEX_NAME", "swarm-memory")

# --- Model Tiers ---
TIER_1_FAST = "gemini-2.5-flash-preview-09-2025"
TIER_2_PRO = "gemini-2.5-flash-preview-09-2025" 
GEMINI_MODEL_NAME = TIER_2_PRO

__all__ = ["GEMINI_API_KEYS", "GATEWAY_API_BASE", "GEMINI_MODEL_NAME", "PINECONE_API_KEY", "PINECONE_ENVIRONMENT", "VECTOR_INDEX_NAME"]
