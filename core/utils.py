import os
import logging

logger = logging.getLogger("Utils")

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
    Pricing Source (Approx. Gemini 1.5 Flash):
    - Input: $0.075 / 1M tokens
    - Output: $0.30 / 1M tokens
    """
    # 简单的费率表 (USD per 1M tokens)
    pricing = {
        "flash": {"input": 0.075, "output": 0.30},
        "pro":   {"input": 3.50,  "output": 10.50},
    }
    
    rate = pricing["flash"] # Default to Flash
    if "pro" in model_name.lower():
        rate = pricing["pro"]
        
    input_cost = (input_tokens / 1_000_000) * rate["input"]
    output_cost = (output_tokens / 1_000_000) * rate["output"]
    
    return round(input_cost + output_cost, 6)
