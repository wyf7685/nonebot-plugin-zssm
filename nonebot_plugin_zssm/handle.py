import contextlib
import random
import re
from typing import Annotated

import httpx
from arclet.alconna import AllParam
from nonebot import logger
from nonebot.exception import ActionFailed
from nonebot.internal.adapter import Event
from nonebot.params import Depends
from nonebot_plugin_alconna import Alconna, Args, Match, on_alconna
from nonebot_plugin_alconna.builtins.extensions.reply import ReplyRecordExtension
from nonebot_plugin_alconna.builtins.uniseg.market_face import MarketFace
from nonebot_plugin_alconna.uniseg import Image, MsgId, Reference, UniMessage, message_reaction

from .config import plugin_config
from .constant import SYSTEM_PROMPT_RAW
from .processors.ai import generate_ai_response
from .processors.image import process_image
from .processors.pdf import process_pdf
from .processors.web import process_web_page

# 从文件加载系统提示词
PATTERN_URL = re.compile(r"\b(?:https?):\/\/[^\s\/?#]+[^\s]*\b")
PATTERN_PDF = re.compile(r"\b(?:https?):\/\/[^\s\/?#]+[^\s]*\.pdf\b")


async def display_unimsg(msg: UniMessage):
    display = ""
    for seg in msg:
        match seg:
            case Image():
                display += f"[图片 {hash(seg.url)}]"
            case Reference():
                await UniMessage.text("不支持引用消息").finish(reply_to=True)
            case MarketFace():
                await UniMessage.text("不支持商城表情").finish(reply_to=True)
            case _:
                display += str(seg)
    return display


async def extract_reply_content(event: Event, msg_id: MsgId, ext: ReplyRecordExtension) -> tuple[str, list[Image]]:
    if (reply := ext.get_reply(msg_id)) is None:
        return "", []

    if not (raw := reply.msg):
        await UniMessage.text("上一条消息内容为空").finish(reply_to=True)

    if isinstance(raw, str):
        raw = event.get_message().__class__(raw)

    msg = UniMessage.generate_sync(message=raw)
    display = await display_unimsg(msg)
    return f"<type: interest>\n{display}\n</type: interest>", msg[Image]


async def extract_param_content(content: Match[UniMessage]) -> tuple[str, list[Image]]:
    if not content.available:
        return "", []

    display = await display_unimsg(content.result)
    return f"<type: text>\n{display}\n</type: text>", content.result[Image]


async def process_images(image_list: list[Image]):
    for image in image_list:
        image_content = await process_image(image)
        if not image_content:
            await UniMessage.text("图片识别失败").finish(reply_to=True)
        yield f"\n<type: image, id: {hash(image.url)}>\n{image_content}\n</type: image, id: {hash(image.url)}>"


async def url_is_pdf(url: str) -> bool:
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.head(url, follow_redirects=True)
            content_type: str = resp.headers.get("Content-Type", "")
            return "application/pdf" in content_type.lower()
    except Exception:
        return bool(PATTERN_PDF.match(url))


async def process_url(url: str) -> str:
    logger.info(f"处理URL: {url}")

    # 尝试检测链接内容类型
    if await url_is_pdf(url):
        # 处理PDF链接
        await UniMessage.text("正在尝试处理PDF文件").send(reply_to=True)
        if pdf_content := await process_pdf(url):
            return f"\n<type: pdf, url: {url}>\n{pdf_content}\n</type: pdf>"

        await UniMessage.text("无法处理PDF文件，请检查文件是否有效且大小合适").finish(reply_to=True)

    # 处理普通网页链接
    await UniMessage.text("正在尝试打开链接").send(reply_to=True)

    if page_content := await process_web_page(url):
        return f"\n<type: web_page, url: {url}>\n{page_content}\n</type: web_page>"
    if pdf_content := await process_pdf(url):
        return f"\n<type: pdf, url: {url}>\n{pdf_content}\n</type: pdf>"

    await UniMessage.text("无法获取页面内容").finish(reply_to=True)


async def construct_user_prompt(
    reply_content: Annotated[tuple[str, list[Image]], Depends(extract_reply_content)],
    param_content: Annotated[tuple[str, list[Image]], Depends(extract_param_content)],
) -> str:
    raw_input = prompt = reply_content[0] + param_content[0]
    image_list = reply_content[1] + param_content[1]
    if not prompt and not image_list:
        await UniMessage.text("请回复或输入内容").finish(reply_to=True)

    # 处理图片, 最多2张
    if len(image_list) > 2:
        await UniMessage.text("图片数量超过限制, 最多 2 张").finish(reply_to=True)

    with contextlib.suppress(ActionFailed):
        await message_reaction("424")

    async for image_content in process_images(image_list):
        prompt += image_content

    # 处理URL和PDF
    if msg_urls := PATTERN_URL.findall(raw_input):
        # 尝试处理第一个链接
        prompt += await process_url(msg_urls[0])

    # 如果处理了URL/PDF或图片, 更新反应
    if msg_urls or image_list:
        with contextlib.suppress(ActionFailed):
            await message_reaction("314")

    return prompt


zssm = on_alconna(
    Alconna("zssm", Args["content?", AllParam]),
    extensions=[ReplyRecordExtension],
)


@zssm.handle()
async def check_config() -> None:
    # 验证API配置
    if not plugin_config.text.token or not plugin_config.vl.token:
        await UniMessage.text("未配置 Api Key, 暂时无法使用").finish(reply_to=True)


@zssm.handle()
async def handle(
    msg_id: MsgId,
    ext: ReplyRecordExtension,
    user_prompt: Annotated[str, Depends(construct_user_prompt)],
) -> None:
    random_number = str(random.randint(10000000, 99999999))  # noqa: S311
    system_prompt = SYSTEM_PROMPT_RAW + random_number
    user_prompt = f"<random number: {random_number}>\n{user_prompt}\n</random number: {random_number}>"
    logger.info("最终用户提示: \n" + user_prompt.replace("\n", "\\n"))

    if (response := await generate_ai_response(system_prompt, user_prompt)) is None:
        await UniMessage.text("AI 回复解析失败, 请重试").finish(reply_to=True)

    with contextlib.suppress(ActionFailed):
        await message_reaction("144")
    await UniMessage.text(response).finish(reply_to=ext.get_reply(msg_id) or True)
