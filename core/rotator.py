import asyncio
import random
import logging
import httpx
from typing import List, Dict, Any, Optional, Literal
from config.keys import TIER_1_FAST, TIER_2_PRO

logger = logging.getLogger("GeminiRotator")

class GeminiKeyRotator:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.is_gateway = "googleapis.com" not in self.base_url

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

        url = ""
        if self.is_gateway:
            url = f"{self.base_url}/v1/chat/completions"
            headers["Authorization"] = f"Bearer {self.api_key}"
            payload["model"] = target_model
        else:
            url = f"{self.base_url}/v1beta/models/{target_model}:generateContent?key={self.api_key}"

        retries = 3
        async with httpx.AsyncClient(timeout=60.0) as client:
            for attempt in range(retries):
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
                    
                    elif response.status_code in [429, 500, 503]:
                        wait_time = 2 ** attempt
                        logger.warning(f"API Error {response.status_code}. Retrying in {wait_time}s...")
                        await asyncio.sleep(wait_time)
                    else:
                        logger.error(f"API Failed: {response.text}")
                        break
                        
                except Exception as e:
                    logger.error(f"Request failed: {e}")
                    await asyncio.sleep(1)
                
        return ""
