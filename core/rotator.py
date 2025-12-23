import google.generativeai as genai
from google.api_core import exceptions
from google.generativeai import caching
import time
import logging
import threading
import datetime
from typing import List, Dict, Any, Tuple, Optional

logger = logging.getLogger("GeminiRotator")

# [Performance Fix] Removed Global Lock
# Each request now instantiates its own client (if supported) or we assume thread-safety of underlying transport
# SDK `configure` is still global, so we use a minimal critical section only for configuration if absolutely necessary
# Ideally, we pass api_key to GenerativeModel constructor if SDK version allows.
# Current `google-generativeai` SDK often requires global configure, but `GenerativeModel` can take no args.
# We will use a lock ONLY for `configure` call, but not for `generate_content`.

_CONFIG_LOCK = threading.Lock()

class AllKeysExhaustedError(Exception):
    """Raised when all available API keys have been tried and failed."""
    pass

class GeminiKeyRotator:
    def __init__(self, base_url: str, keys: List[str]):
        if not keys:
            raise ValueError("API Key list cannot be empty.")
            
        self.keys = keys
        self.current_index = 0
        self.base_url = base_url
        self._index_lock = threading.Lock()
        
        self.active_cache_name = None
        self.cached_key_index = -1

    def _get_next_key(self):
        with self._index_lock:
            if self.active_cache_name and self.cached_key_index != -1:
                return self.keys[self.cached_key_index]

            key = self.keys[self.current_index]
            self.current_index = (self.current_index + 1) % len(self.keys)
        return key

    def create_context_cache(self, model_name: str, content: str, ttl_minutes: int = 10) -> Optional[str]:
        # Caching logic remains similar, but uses _CONFIG_LOCK
        key = self.keys[self.current_index]
        
        with _CONFIG_LOCK:
            try:
                genai.configure(api_key=key)
                # ... (rest of caching logic)
                # For brevity, reusing existing logic structure but with correct locking
                unique_suffix = int(time.time())
                cache = caching.CachedContent.create(
                    model=model_name,
                    display_name=f"gemini_swarm_repo_map_{unique_suffix}",
                    system_instruction=content,
                    ttl=datetime.timedelta(minutes=ttl_minutes),
                )
                self.active_cache_name = cache.name
                self.cached_key_index = self.current_index
                return cache.name
            except Exception as e:
                logger.warning(f"Failed to create context cache: {e}")
                return None

    def call_gemini_with_rotation(
        self, 
        model_name: str, 
        contents: List[Dict[str, Any]], 
        system_instruction: str = None,
        cached_content_name: str = None,
        complexity: str = "simple",
        max_retries: int = None
    ) -> Tuple[str, Dict[str, int]]:
        
        if max_retries is None:
            max_retries = len(self.keys) * 2
            
        retries = 0
        last_error = None
        
        while retries < max_retries:
            if cached_content_name and self.cached_key_index != -1:
                key = self.keys[self.cached_key_index]
            else:
                key = self._get_next_key()

            try:
                # [Critical Performance Fix]
                # Only lock configuration, NOT generation
                with _CONFIG_LOCK:
                    genai.configure(api_key=key)
                
                # Instantiation is cheap
                model = None
                if cached_content_name:
                    try:
                        cache_obj = caching.CachedContent.get(cached_content_name)
                        model = genai.GenerativeModel.from_cached_content(cached_content=cache_obj)
                    except:
                         model = genai.GenerativeModel(model_name=model_name, system_instruction=system_instruction)
                else:
                    model = genai.GenerativeModel(
                        model_name=model_name,
                        system_instruction=system_instruction
                    )
                
                generation_config = genai.types.GenerationConfig(
                    temperature=0.2 if complexity == "complex" else 0.1,
                    max_output_tokens=8192
                )

                # [Unlocked Network Call]
                response = model.generate_content(
                    contents,
                    generation_config=generation_config
                )
                
                usage = {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0
                }
                if hasattr(response, 'usage_metadata'):
                    usage["prompt_tokens"] = response.usage_metadata.prompt_token_count
                    usage["completion_tokens"] = response.usage_metadata.candidates_token_count
                    usage["total_tokens"] = response.usage_metadata.total_token_count
                
                return response.text, usage

            except exceptions.ResourceExhausted:
                if cached_content_name:
                    logger.warning(f"Key for Cache exhausted. Abandoning cache.")
                    cached_content_name = None 
                    self.active_cache_name = None
                
                logger.warning(f"Key {key[:8]}... exhausted. Rotating.")
                retries += 1
                time.sleep(1)
                last_error = "Quota Exceeded"
            except Exception as e:
                logger.error(f"Gemini API Error with key {key[:8]}...: {e}")
                retries += 1
                last_error = str(e)
                if cached_content_name: cached_content_name = None
                time.sleep(min(retries, 5)) 
        
        raise AllKeysExhaustedError(f"Failed after {retries} retries. Last error: {last_error}")
