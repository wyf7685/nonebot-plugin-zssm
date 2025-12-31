from nonebot import logger, require
from playwright.async_api import Browser, BrowserType, Error, Playwright, async_playwright

from ..config import plugin_config
from .installer import install_browser

_browser: Browser | None = None
_playwright: Playwright | None = None


async def init(**kwargs) -> Browser:
    if plugin_config.browser.use_htmlrender:
        try:
            require("nonebot_plugin_htmlrender")
            from nonebot_plugin_htmlrender import get_browser

            return await get_browser(**kwargs)
        except Exception as e:
            logger.warning(f"无法使用 nonebot_plugin_htmlrender 提供浏览器支持: {e!r}")

    global _browser, _playwright  # noqa: PLW0603

    if _playwright is None:
        _playwright = await async_playwright().start()

    try:
        _browser = await launch_browser(**kwargs)
    except Error:
        await install_browser()
        _browser = await launch_browser(**kwargs)

    return _browser


async def launch_browser(**kwargs) -> Browser:
    assert _playwright is not None, "Playwright 没有安装"

    browser_type = plugin_config.browser.type.lower()
    browser: BrowserType = getattr(_playwright, browser_type)
    logger.info(f"使用 {browser_type} 启动")
    return await browser.launch(**kwargs)


async def get_browser(**kwargs) -> Browser:
    return _browser if _browser and _browser.is_connected() else await init(**kwargs)
