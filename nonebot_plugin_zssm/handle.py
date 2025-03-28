import base64
import json
import random
import re
import ssl
import time
from io import BytesIO
from pathlib import Path

import httpx
from nonebot import get_plugin_config, logger
from nonebot.adapters.satori import Bot, MessageEvent
from nonebot_plugin_alconna import on_alconna
from nonebot_plugin_alconna.builtins.extensions.reply import ReplyRecordExtension
from nonebot_plugin_alconna.builtins.uniseg.market_face import MarketFace
from nonebot_plugin_alconna.uniseg import (
    Image,
    MsgId,
    Reference,
    Reply,
    Text,
    UniMessage,
)
from PIL import Image as PILImage

from .api import AsyncChatClient
from .browser import get_browser
from .config import Config

system_prompt_raw = Path(__file__).parent.joinpath("prompt.txt").read_text(encoding="utf-8")
config = get_plugin_config(Config)

zssm = on_alconna("zssm", extensions=[ReplyRecordExtension()])


async def url_to_base64(url: str) -> str:
    ssl_context = ssl.create_default_context()
    ssl_context.options |= ssl.OP_NO_TLSv1 | ssl.OP_NO_TLSv1_1 | ssl.OP_NO_TLSv1_3
    ssl_context.set_ciphers("HIGH:!aNULL:!MD5")
    async with httpx.AsyncClient(verify=ssl_context) as client:
        response = await client.get(url)
        image = PILImage.open(BytesIO(response.content))
        # 把图片控制在5mb以内
        if len(response.content) > 5 * 1024 * 1024:
            image.thumbnail((4096, 4096))
        if image.mode != "RGB":
            image = image.convert("RGB")
        buffered = BytesIO()
        image.save(buffered, format="JPEG", quality=80)
        b64_content = base64.b64encode(buffered.getvalue()).decode()
        return f"data:image/jpeg;base64,{b64_content}"


@zssm.handle()
async def handle(msg_id: MsgId, ext: ReplyRecordExtension, event: MessageEvent, bot: Bot):
    msg = event.get_message()
    channel_id = event.channel.id
    if reply := ext.get_reply(msg_id):
        reply_msg_raw = reply.msg
    else:
        return await UniMessage(Text("未找到上一条消息")).send(reply_to=Reply(msg_id))

    if not reply.msg:
        return await UniMessage(Text("上一条消息内容为空")).send(reply_to=Reply(msg_id))

    if not config.zssm_ai_text_token or not config.zssm_ai_vl_token:
        return await UniMessage(Text("未配置 Api Key, 暂时无法使用")).send(reply_to=Reply(msg_id))

    await bot.reaction_create(channel_id=channel_id, message_id=msg_id, emoji="424")

    if isinstance(reply_msg_raw, str):
        reply_msg_raw = msg.__class__(reply_msg_raw)

    reply_msg = UniMessage.generate_sync(message=reply_msg_raw)
    image_list = reply_msg.get(Image)
    reply_msg_display = ""
    for item in reply_msg:
        if isinstance(item, Image):
            reply_msg_display += f"[图片 {item.id}]"
        if isinstance(item, Reference):
            return await UniMessage(Text("不支持引用消息")).send(reply_to=Reply(msg_id))
        if isinstance(item, MarketFace):
            return await UniMessage(Text("不支持商城表情")).send(reply_to=Reply(msg_id))
        reply_msg_display += str(item)

    random_number = str(random.randint(10000000, 99999999))  # noqa: S311
    system_prompt = system_prompt_raw + random_number
    user_prompt = f"<random number: {random_number}> \n<type: text>\n{reply_msg_display}\n</type: text>\n"

    for image in image_list:
        image: Image
        image_url = image.url
        if not image_url:
            continue
        async with AsyncChatClient(config.zssm_ai_vl_endpoint, config.zssm_ai_vl_token) as client:
            logger.info(f"image_url: {image_url}")
            last_time = time.time()
            last_chunk = ""
            i = 0
            try:
                async for chunk in client.stream_create(
                    config.zssm_ai_vl_model,
                    [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image_url",
                                    "image_url": {"url": await url_to_base64(image_url)},
                                },
                                {
                                    "type": "text",
                                    "text": "请你作为你文本模型姐妹的眼睛，告诉她这张图片的内容",
                                },
                            ],
                        },
                    ],
                ):
                    i += 1
                    last_chunk = chunk
                    if time.time() - last_time > 5:
                        last_time = time.time()
                        small_chunk = f"{chunk[:20]}...{len(chunk) - 40}...{chunk[-20:]}" if len(chunk) > 60 else chunk
                        logger.info(f"stream_create: {i}, {small_chunk}")
                logger.info(f"stream_create_end: {i}, {last_chunk}")

            except Exception as e:
                logger.error(e)
                return await UniMessage(Text("图片识别失败")).send(reply_to=Reply(msg_id))
            user_prompt += f"<type: image, id: {image.id}>\n{client.content}\n</type: image>\n"

    reg_match = re.compile(
        # r"\b(?:https?|ftp):\/\/[^\s\/?#]+[^\s]*|\b(?:www\.)?[a-zA-Z0-9-]+\.[a-zA-Z]{2,}(?:\.[a-zA-Z]{2,})*(?:\/[^\s]*)?\b"
        r"\b(?:https?):\/\/[^\s\/?#]+[^\s]*\b"
    )
    msg_url_list = reg_match.findall(str(reply_msg))
    if msg_url_list:
        browser = await get_browser(proxy={"server": config.zssm_browser_proxy} if config.zssm_browser_proxy else None)
        msg_url = msg_url_list[0]
        logger.info(f"msg_url: {msg_url}")
        await UniMessage(Text("正在尝试打开消息中的第一条链接")).send(reply_to=Reply(msg_id))
        page = await browser.new_page()
        try:
            await page.goto(msg_url, timeout=60000)
        except Exception:
            return await UniMessage(Text("打开链接失败")).send(reply_to=Reply(msg_id))
        # 获取页面的内容
        page_content = await page.query_selector("html")
        if page_content:
            page_content = await page_content.inner_text()
            user_prompt += f"<type: web_page, url: {msg_url}>\n{page_content}\n</type: web_page>\n"
        await page.close()
        if not page_content:
            return await UniMessage(Text("无法获取页面内容")).send(reply_to=Reply(msg_id))

    if msg_url_list or image_list:
        await bot.reaction_create(channel_id=channel_id, message_id=msg_id, emoji="314")

    user_prompt += f"</random number: {random_number}>\n"
    logger.info(f"user_prompt: \n{user_prompt}")
    async with AsyncChatClient(config.zssm_ai_text_endpoint, config.zssm_ai_text_token) as client:
        last_time = time.time()
        last_chunk = ""
        i = 0
        async for chunk in client.stream_create(
            config.zssm_ai_text_model,
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        ):
            try:
                i += 1
                last_chunk = chunk
                if time.time() - last_time > 5:
                    last_time = time.time()
                    small_chunk = f"{chunk[:20]}...{len(chunk) - 40}...{chunk[-20:]}" if len(chunk) > 60 else chunk
                    logger.info(f"stream_create: {i}, {small_chunk}")
            except Exception as e:
                logger.error(e)
                return await UniMessage(Text("AI 回复失败")).send(reply_to=Reply(msg_id))
        logger.info(f"stream_create_end: {i}, {last_chunk}")
        try:
            data: str = client.content
            data = data.strip("`").strip("json").strip()
            llm_output = json.loads(data.strip("`").strip("json").strip())
            if llm_output.get("block", True):
                response = "（抱歉，我现在还不会这个）"
            elif llm_output.get("keyword"):
                response = f"关键词：{' | '.join(llm_output['keyword'])}\n\n{llm_output['output']}"
            else:
                response = f"{llm_output['output']}"
        except json.JSONDecodeError:
            return await UniMessage(Text("AI 回复解析失败，可能是模型未按照指定要求输出，请重试")).send(reply_to=Reply(msg_id))
        except KeyError:
            return await UniMessage(Text("AI 回复解析失败，可能是模型输出格式不正确，请重试")).send(reply_to=Reply(msg_id))

    await bot.reaction_create(channel_id=channel_id, message_id=msg_id, emoji="144")

    await UniMessage(Text(response)).send(reply_to=Reply(msg_id))
