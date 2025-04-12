import base64
import json
import random
import re
import ssl
import time
from io import BytesIO
from pathlib import Path

import httpx
from arclet.alconna import AllParam
from nonebot import get_plugin_config, logger
from nonebot.internal.adapter import Bot, Event
from nonebot_plugin_alconna import Alconna, Args, Match, on_alconna
from nonebot_plugin_alconna.builtins.extensions.reply import ReplyRecordExtension
from nonebot_plugin_alconna.builtins.uniseg.market_face import MarketFace
from nonebot_plugin_alconna.uniseg import Image, MsgId, Reference, Reply, Text, UniMessage, message_reaction
from PIL import Image as PILImage

from .api import AsyncChatClient
from .browser import get_browser
from .config import Config

# 从文件加载系统提示词
SYSTEM_PROMPT_RAW = Path(__file__).parent.joinpath("prompt.txt").read_text(encoding="utf-8")
config = get_plugin_config(Config)

zssm = on_alconna(Alconna("zssm", Args["content?", AllParam]), extensions=[ReplyRecordExtension()])


async def url_to_base64(url: str) -> str:
    """将URL图片转换为base64编码

    Args:
        url: 图片URL

    Returns:
        str: base64编码的图片数据
    """
    ssl_context = ssl.create_default_context()
    ssl_context.options |= ssl.OP_NO_TLSv1 | ssl.OP_NO_TLSv1_1 | ssl.OP_NO_TLSv1_3
    ssl_context.set_ciphers("HIGH:!aNULL:!MD5")

    async with httpx.AsyncClient(verify=ssl_context) as client:
        try:
            response = await client.get(url, timeout=30.0)
            response.raise_for_status()
        except httpx.HTTPError as e:
            logger.error(f"获取图片失败: {url}, 错误: {e}")
            raise

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


async def process_image(image: Image) -> str | None:
    """处理图片内容, 返回图片描述

    Args:
        image: 图片对象

    Returns:
        Optional[str]: 图片描述内容, 失败时返回None
    """
    if not image.url or not config.zssm_ai_vl_token:
        return None

    try:
        async with AsyncChatClient(config.zssm_ai_vl_endpoint, config.zssm_ai_vl_token) as client:
            logger.info(f"处理图片: {image.url}")
            last_time = time.time()
            last_chunk = ""
            i = 0

            async for chunk in client.stream_create(
                config.zssm_ai_vl_model,
                [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {"url": await url_to_base64(image.url)},
                            },
                            {
                                "type": "text",
                                "text": "请你作为你文本模型姐妹的眼睛, 告诉她这张图片的内容",
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
                    logger.info(f"图片处理进度: {i}, {small_chunk}")

            logger.info(f"图片处理完成: {i}, {last_chunk}")
            return client.content

    except Exception as e:
        logger.error(f"图片处理失败: {e}")
        return None


async def process_web_page(url: str) -> str | None:
    """处理网页内容

    Args:
        url: 网页URL

    Returns:
        Optional[str]: 网页内容, 失败时返回None
    """
    try:
        browser = await get_browser(proxy={"server": config.zssm_browser_proxy} if config.zssm_browser_proxy else None)
        page = await browser.new_page()

        try:
            await page.goto(url, timeout=60000)
        except Exception as e:
            logger.error(f"打开链接失败: {url}, 错误: {e}")
            await page.close()
            return None

        # 获取页面的内容
        page_content = await page.query_selector("html")
        content_text = None

        if page_content:
            content_text = await page_content.inner_text()

        await page.close()

    except Exception as e:
        logger.error(f"处理网页失败: {url}, 错误: {e}")
        return None
    else:
        return content_text


async def generate_ai_response(system_prompt: str, user_prompt: str) -> str | None:
    """生成AI响应

    Args:
        system_prompt: 系统提示词
        user_prompt: 用户提示词

    Returns:
        Optional[str]: AI生成的响应, 失败时返回None
    """
    if not config.zssm_ai_text_token:
        return None

    try:
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
                        logger.info(f"AI响应进度: {i}, {small_chunk}")
                except Exception as e:
                    logger.error(f"处理AI响应块失败: {e}")

            logger.info(f"AI响应完成: {i}, {last_chunk}")

            data: str = client.content
            data = data.strip("`").strip("json").strip()

            llm_output = json.loads(data)

            if llm_output.get("block", True):
                return "（抱歉, 我现在还不会这个）"
            if llm_output.get("keyword"):
                return f"关键词：{' | '.join(llm_output['keyword'])}\n\n{llm_output['output']}"
            return f"{llm_output['output']}"

    except json.JSONDecodeError as e:
        logger.error(f"JSON解析失败: {data}")
        logger.error(e)
        return None
    except KeyError as e:
        logger.error(f"缺少必要字段: {data}")
        logger.error(e)
        return None
    except Exception as e:
        logger.error(f"生成AI响应失败: {e}")
        return None


@zssm.handle()
async def handle(msg_id: MsgId, ext: ReplyRecordExtension, event: Event, bot: Bot, content: Match[UniMessage]):
    """处理zssm命令

    Args:
        msg_id: 消息ID
        ext: 回复记录扩展
        event: 事件对象
        bot: 机器人对象
        content: 消息内容
    """
    msg = event.get_message()
    random_number = str(random.randint(10000000, 99999999))  # noqa: S311
    system_prompt = SYSTEM_PROMPT_RAW + random_number
    user_prompt = ""
    image_list: list[Image] = []

    # 处理回复消息
    reply = ext.get_reply(msg_id)
    if reply:
        reply_msg_raw = reply.msg

        if not reply_msg_raw:
            return await UniMessage(Text("上一条消息内容为空")).send(reply_to=Reply(msg_id))

        if isinstance(reply_msg_raw, str):
            reply_msg_raw = msg.__class__(reply_msg_raw)

        reply_msg = UniMessage.generate_sync(message=reply_msg_raw)
        image_list.extend(reply_msg.get(Image))

        reply_msg_display = ""
        for item in reply_msg:
            if isinstance(item, Image):
                reply_msg_display += f"[图片 {hash(item.url)}]"
            elif isinstance(item, Reference):
                return await UniMessage(Text("不支持引用消息")).send(reply_to=Reply(msg_id))
            elif isinstance(item, MarketFace):
                return await UniMessage(Text("不支持商城表情")).send(reply_to=Reply(msg_id))
            reply_msg_display += str(item)

        user_prompt += f"<type: text>\n{reply_msg_display}\n</type: text>"

    # 处理输入内容
    if content.available:
        any_content = content.result
        image_list.extend(any_content.get(Image))

        any_content_display = ""
        for item in any_content:
            if isinstance(item, Image):
                any_content_display += f"[图片 {hash(item.url)}]"
            any_content_display += str(item)

        if reply:
            user_prompt += f"<type: interest>\n{any_content_display}\n</type: interest>"
        else:
            user_prompt += f"<type: text>\n{any_content_display}\n</type: text>"

    if not user_prompt and not image_list:
        return await UniMessage(Text("请回复或输入内容")).send(reply_to=Reply(msg_id))

    # 验证API配置
    if not config.zssm_ai_text_token or not config.zssm_ai_vl_token:
        return await UniMessage(Text("未配置 Api Key, 暂时无法使用")).send(reply_to=Reply(msg_id))

    await message_reaction("424", msg_id, event, bot)

    # 处理图片, 最多2张
    if len(image_list) > 2:
        return await UniMessage(Text("图片数量超过限制, 最多 2 张")).send(reply_to=Reply(msg_id))

    for image in image_list:
        image_content = await process_image(image)
        if image_content:
            user_prompt += f"\n<type: image, id: {hash(image.url)}>\n{image_content}\n</type: image, id: {hash(image.url)}>"
        else:
            return await UniMessage(Text("图片识别失败")).send(reply_to=Reply(msg_id))

    # 处理URL
    reg_match = re.compile(r"\b(?:https?):\/\/[^\s\/?#]+[^\s]*\b")
    msg_url_list = reg_match.findall(str(user_prompt))

    if msg_url_list:
        msg_url = msg_url_list[0]
        logger.info(f"处理URL: {msg_url}")

        await UniMessage(Text("正在尝试打开第一条链接")).send(reply_to=Reply(msg_id))

        page_content = await process_web_page(msg_url)
        if page_content:
            user_prompt += f"\n<type: web_page, url: {msg_url}>\n{page_content}\n</type: web_page>"
        else:
            return await UniMessage(Text("无法获取页面内容")).send(reply_to=Reply(msg_id))

    # 如果处理了URL或图片, 更新反应
    if msg_url_list or image_list:
        await message_reaction("314", msg_id, event, bot)

    # 准备最终的用户提示
    user_prompt = f"<random number: {random_number}>\n{user_prompt}\n</random number: {random_number}>"
    logger.info(f"最终用户提示: \n{user_prompt}")

    # 生成AI响应
    response = await generate_ai_response(system_prompt, user_prompt)

    if response is None:
        return await UniMessage(Text("AI 回复解析失败, 请重试")).send(reply_to=Reply(msg_id))

    await message_reaction("144", msg_id, event, bot)
    await UniMessage(Text(response)).send(reply_to=Reply(msg_id))
