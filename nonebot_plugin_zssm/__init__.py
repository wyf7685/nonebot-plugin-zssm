from nonebot import get_driver, require
from nonebot.plugin import PluginMetadata, inherit_supported_adapters

from .browser import install_browser
from .config import Config, config

require("nonebot_plugin_alconna")

__plugin_meta__ = PluginMetadata(
    name="nonebot-plugin-zssm",
    description="这是什么？问一下！用 ai 来解释群友发送的「未知」内容",
    usage="对着任意你不懂的内容发送「zssm」即可",
    homepage="https://github.com/djkcyl/nonebot-plugin-zssm",
    type="application",
    config=Config,
    supported_adapters=inherit_supported_adapters("nonebot_plugin_alconna"),
    extra={"author": "djkcyl", "version": "0.3.2"},
)

if config.zssm_browser_install_on_startup:
    get_driver().on_startup(install_browser)

from . import handle  # noqa: E402, F401
