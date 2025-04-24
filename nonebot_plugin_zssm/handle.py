import random
import re
from typing import Annotated

import httpx
from arclet.alconna import AllParam
from nonebot import logger
from nonebot.internal.adapter import Bot, Event
from nonebot.params import Depends
from nonebot_plugin_alconna import Alconna, Args, Match, on_alconna
from nonebot_plugin_alconna.builtins.extensions.reply import ReplyRecordExtension
from nonebot_plugin_alconna.builtins.uniseg.market_face import MarketFace
from nonebot_plugin_alconna.uniseg import Image, MsgId, Reference, Reply, UniMessage, message_reaction

from .config import plugin_config
from .constant import SYSTEM_PROMPT_RAW
from .processors.ai import generate_ai_response
from .processors.image import process_image
from .processors.pdf import process_pdf
from .processors.web import process_web_page

# 从文件加载系统提示词
PATTERN_URL = re.compile(r"\b(?:https?):\/\/[^\s\/?#]+[^\s]*\b")
PATTERN_PDF = re.compile(r"\b(?:https?):\/\/[^\s\/?#]+[^\s]*\.pdf\b")


async def extract_reply(msg_id: MsgId, ext: ReplyRecordExtension) -> Reply | None:
    return ext.get_reply(msg_id)


MsgReply = Annotated[Reply | None, Depends(extract_reply)]


async def extract_reply_content(
    msg_id: MsgId,
    reply: MsgReply,
    event: Event,
) -> tuple[str, list[Image]]:
    if reply is None:
        return "", []

    if not (raw := reply.msg):
        await UniMessage.text("上一条消息内容为空").finish(reply_to=Reply(msg_id))

    if isinstance(raw, str):
        raw = event.get_message().__class__(raw)

    msg = UniMessage.generate_sync(message=raw)
    display = ""
    for seg in msg:
        if isinstance(seg, Image):
            display += f"[图片 {hash(seg.url)}]"
        elif isinstance(seg, Reference):
            await UniMessage.text("不支持引用消息").finish(reply_to=Reply(msg_id))
        elif isinstance(seg, MarketFace):
            await UniMessage.text("不支持商城表情").finish(reply_to=Reply(msg_id))
        else:
            display += str(seg)

    return f"<type: text>\n{display}\n</type: text>", msg[Image]


ReplyContent = Annotated[tuple[str, list[Image]], Depends(extract_reply_content)]


async def extract_param_content(content: Match[UniMessage], reply: MsgReply) -> tuple[str, list[Image]]:
    if not content.available:
        return "", []

    display = ""
    for seg in content.result:
        if isinstance(seg, Image):
            display += f"[图片 {hash(seg.url)}]"
        display += str(seg)

    type_ = "interest" if reply is not None else "text"
    return f"<type: {type_}>\n{display}\n</type: {type_}>", content.result[Image]


ParamContent = Annotated[tuple[str, list[Image]], Depends(extract_param_content)]


async def process_images(image_list: list[Image], msg_id: str):
    for image in image_list:
        image_content = await process_image(image)
        if not image_content:
            await UniMessage.text("图片识别失败").finish(reply_to=Reply(msg_id))
        yield f"\n<type: image, id: {hash(image.url)}>\n{image_content}\n</type: image, id: {hash(image.url)}>"


async def process_url(url: str, msg_id: str) -> str:
    logger.info(f"处理URL: {url}")

    # 尝试检测链接内容类型
    try:
        async with httpx.AsyncClient() as client:
            head_response = await client.head(url, follow_redirects=True)
            content_type = head_response.headers.get("Content-Type", "").lower()
            is_pdf = bool(PATTERN_PDF.match(url)) or "application/pdf" in content_type
            logger.info(f"链接内容类型: {content_type} - {head_response.url}")
    except Exception:
        # 如果HEAD请求失败，使用URL后缀判断
        is_pdf = bool(PATTERN_PDF.match(url))

    if is_pdf:
        # 处理PDF链接
        await UniMessage.text("正在尝试处理PDF文件").send(reply_to=Reply(msg_id))
        if pdf_content := await process_pdf(url):
            return f"\n<type: pdf, url: {url}>\n{pdf_content}\n</type: pdf>"

        await UniMessage.text("无法处理PDF文件，请检查文件是否有效且大小合适").finish(reply_to=Reply(msg_id))

    # 处理普通网页链接
    await UniMessage.text("正在尝试打开链接").send(reply_to=Reply(msg_id))

    if page_content := await process_web_page(url):
        return f"\n<type: web_page, url: {url}>\n{page_content}\n</type: web_page>"
    if pdf_content := await process_pdf(url):
        return f"\n<type: pdf, url: {url}>\n{pdf_content}\n</type: pdf>"

    await UniMessage.text("无法获取页面内容").finish(reply_to=Reply(msg_id))


zssm = on_alconna(
    Alconna("zssm", Args["content?", AllParam]),
    extensions=[ReplyRecordExtension()],
)


@zssm.handle()
async def check_config(msg_id: MsgId):
    # 验证API配置
    if not plugin_config.text.token or not plugin_config.vl.token:
        await UniMessage.text("未配置 Api Key, 暂时无法使用").finish(reply_to=Reply(msg_id))


@zssm.handle()
async def handle(
    bot: Bot,
    event: Event,
    msg_id: MsgId,
    reply_content: ReplyContent,
    param_content: ParamContent,
) -> None:
    user_prompt = reply_content[0] + param_content[0]
    image_list = reply_content[1] + param_content[1]
    if not user_prompt and not image_list:
        await UniMessage.text("请回复或输入内容").finish(reply_to=Reply(msg_id))

    await message_reaction("424", msg_id, event, bot)

    # 处理图片, 最多2张
    if len(image_list) > 2:
        await UniMessage.text("图片数量超过限制, 最多 2 张").finish(reply_to=Reply(msg_id))

    async for image_content in process_images(image_list, msg_id):
        user_prompt += image_content

    # 处理URL和PDF
    if msg_urls := PATTERN_URL.findall(str(user_prompt)):
        # 尝试处理第一个链接
        user_prompt += await process_url(msg_urls[0], msg_id)

    # 如果处理了URL/PDF或图片, 更新反应
    if msg_urls or image_list:
        await message_reaction("314", msg_id, event, bot)

    # 准备最终的提示词
    random_number = str(random.randint(10000000, 99999999))  # noqa: S311
    system_prompt = SYSTEM_PROMPT_RAW + random_number
    user_prompt = f"<random number: {random_number}>\n{user_prompt}\n</random number: {random_number}>"
    logger.info("最终用户提示: \n" + user_prompt.replace("\n", "\\n"))

    # 生成AI响应
    if (response := await generate_ai_response(system_prompt, user_prompt)) is None:
        await UniMessage.text("AI 回复解析失败, 请重试").finish(reply_to=Reply(msg_id))

    await message_reaction("144", msg_id, event, bot)
    await UniMessage.text(response).finish(reply_to=Reply(msg_id))
