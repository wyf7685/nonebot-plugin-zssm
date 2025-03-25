from nonebot_plugin_alconna import on_alconna
from nonebot import get_plugin_config
from nonebot_plugin_alconna.builtins.extensions.reply import ReplyRecordExtension
from nonebot_plugin_alconna.uniseg import Reply, UniMessage, Text, MsgId
from .api import AsyncChatClient
from .config import Config
from pathlib import Path
from .browser import get_browser
from loguru import logger
import random
import re

system_prompt_raw = (
    Path(__file__).parent.joinpath("prompt.txt").read_text(encoding="utf-8")
)
config = get_plugin_config(Config)

zssm = on_alconna("zssm", extensions=[ReplyRecordExtension()])


@zssm.handle()
async def handle(msg_id: MsgId, ext: ReplyRecordExtension):
    if reply := ext.get_reply(msg_id):
        reply_msg_raw = reply.msg
    else:
        return await UniMessage(Text("未找到上一条消息")).send(reply_to=Reply(msg_id))

    reply_msg = str(reply_msg_raw)

    random_number = str(random.randint(10000000, 99999999))
    system_prompt = system_prompt_raw + random_number
    user_prompt = (
        f"<random number: {random_number}> \n<type: text>\n{reply_msg}\n</type: text>\n"
    )
    reg_match = re.compile(
        r"\b(?:https?|ftp):\/\/[^\s\/?#]+[^\s]*|\b(?:www\.)?[a-zA-Z0-9-]+\.[a-zA-Z]{2,}(?:\.[a-zA-Z]{2,})*(?:\/[^\s]*)?\b"
    )
    msg_url_list = reg_match.findall(reply_msg)
    if msg_url_list:
        browser = await get_browser(
            proxy={"server": config.zssm_browser_proxy}
            if config.zssm_browser_proxy
            else None
        )
        msg_url = msg_url_list[0]
        logger.info(f"msg_url: {msg_url}")
        await UniMessage(Text("正在尝试打开消息中的第一条链接")).send(
            reply_to=Reply(msg_id)
        )
        page = await browser.new_page()
        try:
            await page.goto(msg_url, timeout=60000)
        except Exception:
            return await UniMessage(Text("打开链接失败")).send(reply_to=Reply(msg_id))
        # 获取页面的内容
        page_content = await page.query_selector("html")
        if page_content:
            page_content = await page_content.inner_text()
            user_prompt += (
                f"<type: web_page, url: {msg_url}>\n{page_content}\n</type: web_page>\n"
            )
        await page.close()
        if not page_content:
            return await UniMessage(Text("无法获取页面内容")).send(
                reply_to=Reply(msg_id)
            )

    user_prompt += f"</random number: {random_number}>\n"
    logger.info(f"user_prompt: \n{user_prompt}")
    if not config.zssm_ai_token:
        return await UniMessage(Text("未配置 Api Key，暂时无法使用")).send(
            reply_to=Reply(msg_id)
        )
    async with AsyncChatClient(config.zssm_ai_endpoint, config.zssm_ai_token) as client:
        response = await client.create(
            config.zssm_ai_model,
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        logger.info(response.json())

    await UniMessage(Text(response.json()["choices"][0]["message"]["content"])).send(
        reply_to=Reply(msg_id)
    )
