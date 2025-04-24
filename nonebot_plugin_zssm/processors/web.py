from nonebot import logger

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
        browser = await get_browser(proxy={"server": config.proxy} if config.proxy else None)
        async with await browser.new_page() as page:
            try:
                await page.goto(url, timeout=60000)
            except Exception as e:
                logger.error(f"打开链接失败: {url}, 错误: {e}")
                return None

            # 获取页面的内容
            page_content = await page.query_selector("html")
            return page_content and await page_content.inner_text()

    except Exception as e:
        logger.error(f"处理网页失败: {url}, 错误: {e}")
        return None
