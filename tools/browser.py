import requests
from bs4 import BeautifulSoup
import logging
import re

logger = logging.getLogger("Tools-Browser")

class WebLoader:
    """
    [Continue Soul] 网页内容抓取工具 (@Docs)
    用于实时抓取在线文档，扩充 AI 的知识库。
    """
    def __init__(self):
        # 伪装成浏览器，防止被简单的反爬拦截
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

    def scrape_url(self, url: str) -> str:
        """抓取 URL 并转换为简化文本"""
        try:
            logger.info(f"🌐 Scraping: {url}")
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 1. 移除无关元素 (噪音清洗)
            for element in soup(["script", "style", "nav", "footer", "iframe", "svg", "noscript"]):
                element.decompose()
            
            # 2. 提取标题
            title = soup.title.string if soup.title else url
            
            # 3. 提取主要文本
            # get_text 使用换行符分隔块级元素
            text = soup.get_text(separator='\n')
            
            # 4. 清理空行和多余空格
            lines = (line.strip() for line in text.splitlines())
            # 将多行文本合并，保留段落结构
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            clean_text = '\n'.join(chunk for chunk in chunks if chunk)
            
            # 5. 截断以防过长 (Gemini Context Window 很大，但还是节约点 Token)
            max_length = 20000 
            if len(clean_text) > max_length:
                clean_text = clean_text[:max_length] + "\n\n...[Content Truncated]..."

            return f"### 🌐 Source: {title}\nURL: {url}\n\n{clean_text}"
            
        except Exception as e:
            logger.error(f"Scrape failed: {e}")
            return f"[Error] Could not scrape {url}: {str(e)}"
