import nonebot
from nonebot.adapters.satori import Adapter as SatoriAdapter

nonebot.init()

driver = nonebot.get_driver()
driver.register_adapter(SatoriAdapter)

nonebot.load_plugins("nonebot_plugin_zssm")

if __name__ == "__main__":
    nonebot.run()
