from nonebot import logger
from yarl import URL

from ..browser import get_browser
from ..config import plugin_config

config = plugin_config.browser


async def process_web_page(url: str) -> str | None:
    """处理网页内容

    Args:
        url: 网页URL

    Returns:
        Optional[str]: 网页内容, 失败时返回None
    """
    try:
        if config.proxy:
            proxy_uri = URL(config.proxy)
            proxy = {
                "server": f"{proxy_uri.scheme}://{proxy_uri.host}:{proxy_uri.port}",
                "username": proxy_uri.user,
                "password": proxy_uri.password,
            }
        else:
            proxy = None

        logger.info(f"使用代理: {proxy} - {config.proxy}")
        browser = await get_browser(proxy=proxy)

        async with await browser.new_page() as page:
            try:
                await page.goto(url, timeout=60000)
            except Exception:
                logger.exception(f"打开链接失败: {url}")
                return None

            # 获取页面的内容
            page_content = await page.query_selector("html")
            return page_content and await page_content.inner_text()

    except Exception:
        logger.exception(f"处理网页失败: {url}")
        return None
