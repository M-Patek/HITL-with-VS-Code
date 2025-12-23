import os
import logging

logger = logging.getLogger("Utils")

# [Maintenance] 集中管理费率配置 (USD per 1M tokens)
# TODO: Move to a proper config file or fetch from API
PRICING_TIERS = {
    "flash": {
        "input": 0.075,
        "output": 0.30,
        "description": "Gemini 1.5 Flash (Fast & Cheap)"
    },
    "pro": {
        "input": 3.50,
        "output": 10.50,
        "description": "Gemini 1.5 Pro (Reasoning Heavy)"
    },
    # Fallback default
    "default": {
        "input": 0.10,
        "output": 0.40
    }
}

def load_prompt(base_path: str, filename: str) -> str:
    """加载 Prompt 模板文件"""
    try:
        path = os.path.join(base_path, filename)
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        logger.error(f"Failed to load prompt {filename}: {e}")
        return ""

def calculate_cost(model_name: str, input_tokens: int, output_tokens: int) -> float:
    """
    [Roo Code Soul] 计算 Token 成本 (USD)
    使用集中管理的 PRICING_TIERS 进行计算。
    """
    model_lower = model_name.lower()
    
    # Select Tier
    if "flash" in model_lower:
        rate = PRICING_TIERS["flash"]
    elif "pro" in model_lower:
        rate = PRICING_TIERS["pro"]
    else:
        rate = PRICING_TIERS["default"]
        
    input_cost = (input_tokens / 1_000_000) * rate["input"]
    output_cost = (output_tokens / 1_000_000) * rate["output"]
    
    return round(input_cost + output_cost, 6)
