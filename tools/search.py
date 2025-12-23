import os
import asyncio
try:
    from tavily import TavilyClient
    TAVILY_AVAILABLE = True
except ImportError:
    TAVILY_AVAILABLE = False

class GoogleSearchTool:
    def __init__(self):
        self.api_key = os.getenv("TAVILY_API_KEY")
        self.client = None
        if TAVILY_AVAILABLE and self.api_key:
            self.client = TavilyClient(api_key=self.api_key)

    async def search(self, query: str) -> str:
        if not self.client:
            return self._fallback_search(query)
        try:
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(None, lambda: self.client.search(query, max_results=3))
            context = []
            for res in response.get("results", []):
                context.append(f"Source: {res.get('title')}\nURL: {res.get('url')}\nContent: {res.get('content', '')[:500]}")
            return "\n---\n".join(context)
        except:
            return self._fallback_search(query)

    def _fallback_search(self, query: str) -> str:
        return f"[Mock Search Result] Found generic info about '{query}'. Python 3.12 is the latest stable version."
