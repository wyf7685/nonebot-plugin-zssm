from importlib.metadata import version

from nonebot import get_driver, require
from nonebot.plugin import PluginMetadata, inherit_supported_adapters

require("nonebot_plugin_alconna")
from . import handle as handle
from .browser import install_browser
from .config import Config, plugin_config

try:
    __version__ = version("nonebot_plugin_zssm")
except Exception:
    __version__ = None


__plugin_meta__ = PluginMetadata(
    name="nonebot-plugin-zssm",
    description="这是什么？问一下！用 ai 来解释群友发送的「未知」内容",
    usage="对着任意你不懂的内容发送「zssm」即可",
    homepage="https://github.com/djkcyl/nonebot-plugin-zssm",
    type="application",
    config=Config,
    supported_adapters=inherit_supported_adapters("nonebot_plugin_alconna"),
    extra={"author": "djkcyl", "version": __version__},
)

if plugin_config.browser.install_on_startup:
    get_driver().on_startup(install_browser)
