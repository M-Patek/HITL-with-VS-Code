import aiohttp
import asyncio
import logging
import time
import json
from typing import List, Dict, Any, Tuple, Optional

logger = logging.getLogger("GeminiRotator")

class AllKeysExhaustedError(Exception):
    """Raised when all available API keys have been tried and failed."""
    pass

class GeminiKeyRotator:
    def __init__(self, base_url: str, keys: List[str]):
        if not keys:
            raise ValueError("API Key list cannot be empty.")
            
        self.keys = keys
        self.current_index = 0
        self.base_url = base_url.rstrip('/')
        self._index_lock = asyncio.Lock() # Use Async Lock
        
        # Caching specific key index to maintain consistency for cached sessions
        self.active_cache_name = None
        self.cached_key_index = -1

    async def _get_next_key(self):
        async with self._index_lock:
            if self.active_cache_name and self.cached_key_index != -1:
                return self.keys[self.cached_key_index]

            key = self.keys[self.current_index]
            self.current_index = (self.current_index + 1) % len(self.keys)
        return key

    async def call_gemini_with_rotation(
        self, 
        model_name: str, 
        contents: List[Dict[str, Any]], 
        system_instruction: str = None,
        cached_content_name: str = None,
        complexity: str = "simple",
        max_retries: int = None
    ) -> Tuple[str, Dict[str, int]]:
        """
        [Async & Thread-Safe Fix]
        Replaces Google SDK with direct REST API calls using aiohttp.
        This ensures API keys are passed per-request, preventing global state pollution.
        """
        
        if max_retries is None:
            max_retries = len(self.keys) * 2
            
        retries = 0
        last_error = None
        
        # Normalize model name for REST API
        if not model_name.startswith("models/"):
            model_name = f"models/{model_name}"

        url = f"{self.base_url}/v1beta/{model_name}:generateContent"
        
        while retries < max_retries:
            if cached_content_name and self.cached_key_index != -1:
                key = self.keys[self.cached_key_index]
            else:
                key = await self._get_next_key()

            headers = {
                "Content-Type": "application/json",
                "x-goog-api-key": key # Pass key in header safely
            }

            payload = {
                "contents": contents,
                "generationConfig": {
                    "temperature": 0.2 if complexity == "complex" else 0.1,
                    "maxOutputTokens": 8192
                }
            }

            if system_instruction:
                payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}
            
            # Note: Caching via REST needs specific handling, omitted for brevity/compatibility
            # relying on stateless requests for robustness in this fix.

            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(url, json=payload, headers=headers, timeout=60) as response:
                        if response.status != 200:
                            err_text = await response.text()
                            
                            # Handle Quota Limits
                            if response.status == 429: 
                                logger.warning(f"Key {key[:8]}... exhausted (429). Rotating.")
                                retries += 1
                                await asyncio.sleep(1)
                                continue
                            
                            raise Exception(f"HTTP {response.status}: {err_text}")
                        
                        result = await response.json()
                        
                        # Parse Response
                        try:
                            candidate = result["candidates"][0]
                            content_parts = candidate["content"]["parts"]
                            text_response = "".join([p.get("text", "") for p in content_parts])
                            
                            usage_meta = result.get("usageMetadata", {})
                            usage = {
                                "prompt_tokens": usage_meta.get("promptTokenCount", 0),
                                "completion_tokens": usage_meta.get("candidatesTokenCount", 0),
                                "total_tokens": usage_meta.get("totalTokenCount", 0)
                            }
                            
                            return text_response, usage
                        except (KeyError, IndexError) as e:
                            # Handle safety blocks or empty responses
                            if result.get("promptFeedback", {}).get("blockReason"):
                                return "[Blocked by Safety Filters]", {"total_tokens": 0}
                            raise Exception(f"Malformed response: {result}")

            except Exception as e:
                logger.error(f"Gemini REST API Error with key {key[:8]}...: {e}")
                retries += 1
                last_error = str(e)
                await asyncio.sleep(min(retries, 5)) 
        
        raise AllKeysExhaustedError(f"Failed after {retries} retries. Last error: {last_error}")
