import requests
import socket
import ipaddress
import logging
from urllib.parse import urlparse, urlunparse
from typing import Optional

# Optional Playwright support
try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

logger = logging.getLogger(__name__)

class BrowserTool:
    """
    Tool for safe web browsing and scraping.
    """
    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (GeminiSwarm/1.0; SafeBot)'
        }

    def _is_safe_url(self, url: str) -> bool:
        """
        [Security] Validates URL to prevent SSRF (Server-Side Request Forgery).
        """
        try:
            parsed = urlparse(url)
            hostname = parsed.hostname
            if not hostname:
                return False
                
            # Allow http and https only
            if parsed.scheme not in ('http', 'https'):
                return False

            # Resolve IP
            try:
                ip_list = socket.getaddrinfo(hostname, None)
                for item in ip_list:
                    ip_addr = item[4][0]
                    ip_obj = ipaddress.ip_address(ip_addr)
                    if ip_obj.is_private or ip_obj.is_loopback:
                        logger.warning(f"Blocked access to private IP: {ip_addr} ({hostname})")
                        return False
            except socket.gaierror:
                logger.warning(f"DNS resolution failed for {hostname}")
                return False
                
            return True
        except Exception:
            return False

    def scrape_url(self, url: str) -> str:
        """
        Fetches the content of a URL safely.
        """
        if not self._is_safe_url(url):
            return "Error: URL blocked by security policy (Private IP or invalid protocol)."

        try:
            # [Fix] SSRF Defense: Disable redirects
            response = requests.get(
                url, 
                headers=self.headers, 
                timeout=10,
                allow_redirects=False 
            )
            
            if response.status_code in (301, 302, 307, 308):
                return f"Error: Redirects are disabled for security. Target: {response.headers.get('Location')}"

            response.raise_for_status()
            return response.text[:10000] # Limit return size
            
        except Exception as e:
            return f"Error scraping URL: {e}"

    async def capture_screenshot(self, url: str) -> str:
        """
        Captures a screenshot using Playwright (if available).
        """
        if not PLAYWRIGHT_AVAILABLE:
            return "Error: Playwright not installed."

        # [Fix] Security: Re-validate URL for Playwright & Check Scheme
        if not self._is_safe_url(url):
             logger.warning(f"🚫 Blocked screenshot request for unsafe URL: {url}")
             return "Error: URL blocked by security policy."

        parsed = urlparse(url)
        if parsed.scheme not in ('http', 'https'):
            return "Error: Only HTTP/HTTPS protocols are supported for screenshots."

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                
                # Set a strict timeout
                await page.goto(url, timeout=15000, wait_until="networkidle")
                
                # Capture as base64
                import base64
                screenshot_bytes = await page.screenshot(type='jpeg', quality=50)
                encoded = base64.b64encode(screenshot_bytes).decode('utf-8')
                
                await browser.close()
                return f"data:image/jpeg;base64,{encoded}"
        except Exception as e:
            logger.error(f"Screenshot failed: {e}")
            return f"Error capturing screenshot: {e}"
