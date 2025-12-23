import os

# --- Gateway & API Configuration ---
GATEWAY_API_BASE = os.getenv("GATEWAY_API_BASE", "https://generativelanguage.googleapis.com/v1beta/openai/")
GATEWAY_SECRET = os.getenv("GATEWAY_SECRET", "") # Google AI Studio Key

# --- Vector DB ---
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY", "")
PINECONE_ENVIRONMENT = os.getenv("PINECONE_ENVIRONMENT", "us-east-1")
VECTOR_INDEX_NAME = os.getenv("VECTOR_INDEX_NAME", "swarm-memory")

# --- Model Tiers ---
TIER_1_FAST = "gemini-2.5-flash-preview-09-2025"
TIER_2_PRO = "gemini-2.5-flash-preview-09-2025" 
GEMINI_MODEL_NAME = TIER_2_PRO
