from nonebot import require, get_driver
from nonebot.plugin import PluginMetadata

from .browser import install_browser


require("nonebot_plugin_alconna")

__plugin_meta__ = PluginMetadata(
    name="nonebot-plugin-zssm",
    description="这是什么？问一下！用 ai 来解释群友发送的「未知」内容",
    usage="对着任意你不懂的内容发送「zssm」即可",
    homepage="https://github.com/djkcyl/nonebot-plugin-zssm",
    type="application",
    supported_adapters={"~onebot.v11", "~onebot.v12", "~qq"},
    extra={"author": "djkcyl", "version": "0.1.8"},
)

from . import handle  # noqa

driver = get_driver()
driver.on_startup(install_browser)
