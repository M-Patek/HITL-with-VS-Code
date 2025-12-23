import asyncio
import random
import logging
import httpx
from typing import List, Dict, Any, Optional, Literal
from config.keys import TIER_1_FAST, TIER_2_PRO

logger = logging.getLogger("GeminiRotator")

class GeminiKeyRotator:
    # [Optimization] 接收 Key 列表
    def __init__(self, base_url: str, api_keys: List[str]):
        self.base_url = base_url.rstrip("/")
        self.api_keys = api_keys if api_keys else [""]
        self.current_key_index = 0
        self.is_gateway = "googleapis.com" not in self.base_url
        
        if not self.api_keys or self.api_keys[0] == "":
            logger.warning("⚠️ No API Keys provided to Rotator!")

    def _get_current_key(self) -> str:
        if not self.api_keys: return ""
        return self.api_keys[self.current_key_index]

    def _rotate_key(self):
        # [Optimization] 简单的轮询切换
        if not self.api_keys: return
        self.current_key_index = (self.current_key_index + 1) % len(self.api_keys)
        logger.info(f"🔄 Switched to API Key #{self.current_key_index}")

    def _get_model_by_complexity(self, complexity: str) -> str:
        if complexity == "simple":
            return TIER_1_FAST
        elif complexity == "complex":
            return TIER_2_PRO
        else:
            return TIER_2_PRO

    async def call_gemini_with_rotation(
        self,
        model_name: str,
        contents: List[Dict[str, Any]],
        system_instruction: str = "",
        response_schema: Optional[Any] = None,
        complexity: Literal["simple", "complex"] = "complex",
        semantic_cache_tool: Optional[Any] = None
    ) -> str:
        target_model = model_name
        if complexity:
            target_model = self._get_model_by_complexity(complexity)
            
        headers = {"Content-Type": "application/json"}
        
        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": 0.7 if complexity == "complex" else 0.3, 
            }
        }

        if system_instruction:
            payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}

        if response_schema:
            payload["generationConfig"]["responseMimeType"] = "application/json"
            if hasattr(response_schema, "model_json_schema"):
                payload["generationConfig"]["responseSchema"] = response_schema.model_json_schema()
            elif isinstance(response_schema, dict):
                payload["generationConfig"]["responseSchema"] = response_schema

        retries = 3
        async with httpx.AsyncClient(timeout=60.0) as client:
            for attempt in range(retries):
                current_key = self._get_current_key()
                
                # 动态构建 URL
                if self.is_gateway:
                    url = f"{self.base_url}/v1/chat/completions"
                    headers["Authorization"] = f"Bearer {current_key}"
                    payload["model"] = target_model
                else:
                    url = f"{self.base_url}/v1beta/models/{target_model}:generateContent?key={current_key}"

                try:
                    response = await client.post(url, headers=headers, json=payload)
                    
                    if response.status_code == 200:
                        data = response.json()
                        candidates = data.get("candidates", [])
                        if candidates:
                            content = candidates[0].get("content", {})
                            parts = content.get("parts", [])
                            if parts:
                                return parts[0].get("text", "")
                        return "" 
                    
                    # [Optimization] 遇到限流或服务错误时切换 Key
                    elif response.status_code in [429, 500, 503]:
                        logger.warning(f"API Error {response.status_code}. Rotating key and retrying...")
                        self._rotate_key()
                        wait_time = 1 ** attempt # 稍微减少等待时间，因为换了Key
                        await asyncio.sleep(wait_time)
                    else:
                        logger.error(f"API Failed: {response.text}")
                        break
                        
                except Exception as e:
                    logger.error(f"Request failed: {e}")
                    await asyncio.sleep(1)
                
        return ""
