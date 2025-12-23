import asyncio
import logging
import google.generativeai as genai
from typing import List, Dict, Any, Tuple
from google.api_core import exceptions

logger = logging.getLogger(__name__)

class GeminiKeyRotator:
    """
    Manages a list of Gemini API keys and rotates them to handle rate limits.
    [Optimization] Thread-safe and stateless design for high concurrency.
    """
    def __init__(self, base_url: str, keys: List[str]):
        if not keys:
            raise ValueError("API Key list cannot be empty.")
            
        self.keys = keys
        self.current_index = 0
        self.base_url = base_url.rstrip('/')
        
        # [Fix] Use asyncio Lock for thread-safe index updates
        self._index_lock = asyncio.Lock()
        
        # [Fix] Removed stateful caching fields (cached_key_index, active_cache_name)
        # to prevent race conditions in concurrent tasks.

    async def _get_next_key(self) -> str:
        """Safely retrieves the next key in round-robin fashion."""
        async with self._index_lock:
            key = self.keys[self.current_index]
            self.current_index = (self.current_index + 1) % len(self.keys)
        return key

    def _configure_genai(self, api_key: str):
        genai.configure(api_key=api_key)

    async def call_gemini_with_rotation(
        self, 
        model_name: str, 
        contents: List[Dict[str, Any]], 
        generation_config: Dict[str, Any] = None,
        safety_settings: List[Dict[str, Any]] = None,
        tools: List[Any] = None,
        cached_content_name: str = None # [Compat] Parameter kept for compatibility but ignored
    ) -> Tuple[str, Dict[str, int]]:
        """
        Calls Gemini API with automatic key rotation on 429 errors.
        """
        
        # [Info] cached_content_name is ignored in this stateless version
        # to prevent cross-task state pollution.
        if cached_content_name:
            logger.debug("cached_content_name ignored for stateless rotation safety.")

        max_retries = len(self.keys) * 2 # Try enough times to cycle through keys
        retries = 0
        
        last_error = None

        while retries < max_retries:
            # [Fix] Always rotate key on every attempt/retry to balance load
            api_key = await self._get_next_key()
            self._configure_genai(api_key)
            
            try:
                model = genai.GenerativeModel(
                    model_name=model_name,
                    generation_config=generation_config,
                    safety_settings=safety_settings,
                    tools=tools
                )
                
                # Note: If caching was needed, it should be handled per-request context,
                # not stored in the global rotator instance.
                
                response = await model.generate_content_async(contents)
                
                usage_metadata = {}
                if hasattr(response, 'usage_metadata'):
                    usage_metadata = {
                        "prompt_token_count": response.usage_metadata.prompt_token_count,
                        "candidates_token_count": response.usage_metadata.candidates_token_count,
                        "total_token_count": response.usage_metadata.total_token_count
                    }

                return response.text, usage_metadata

            except exceptions.ResourceExhausted as e:
                logger.warning(f"Key {api_key[-4:]} exhausted (429). Rotating...")
                retries += 1
                last_error = e
                await asyncio.sleep(1) # Backoff slightly
                
            except Exception as e:
                # For non-rate-limit errors, we might not want to retry, or retry selectively
                logger.error(f"API Error with key {api_key[-4:]}: {e}")
                raise e
        
        raise RuntimeError(f"All keys exhausted. Last error: {last_error}")
