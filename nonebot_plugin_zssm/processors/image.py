import base64
import ssl
import time
from io import BytesIO
from typing import Any

import httpx
from nonebot import logger
from nonebot_plugin_alconna.uniseg import Image
from PIL import Image as PILImage

from ..api import AsyncChatClient
from ..config import plugin_config
from ..constant import IMAGE_PROMPT

config = plugin_config.vl


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
            response = (await client.get(url, timeout=30.0)).raise_for_status()
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


def _completion_msg(image_url: str) -> dict[str, Any]:
    return {
        "role": "user",
        "content": [
            {"type": "image_url", "image_url": {"url": image_url}},
            {"type": "text", "text": IMAGE_PROMPT},
        ],
    }


def truncate_chunk(chunk: str) -> str:
    return f"{chunk[:20]}...{len(chunk) - 40}...{chunk[-20:]}" if len(chunk) > 60 else chunk


async def process_image(image: Image) -> str | None:
    """处理图片内容, 返回图片描述

    Args:
        image: 图片对象

    Returns:
        Optional[str]: 图片描述内容, 失败时返回None
    """
    if not image.url or not config.token:
        return None

    logger.info(f"处理图片: {image.url}")
    last_time = time.time()
    last_chunk = ""
    i = 0

    try:
        message_content = [
            {"type": "image_url", "image_url": {"url": await url_to_base64(image.url)}},
            {"type": "text", "text": IMAGE_PROMPT},
        ]

        async with AsyncChatClient(config) as client:
            async for chunk in client.stream_create({"role": "user", "content": message_content}):
                i += 1
                last_chunk = chunk
                if time.time() - last_time > 5:
                    last_time = time.time()
                    logger.info(f"图片处理进度: {i}, {truncate_chunk(last_chunk)}")

    except Exception as e:
        logger.error(f"图片处理失败: {e}")
        return None
    else:
        logger.info(f"图片处理完成: {i}, {last_chunk}")
        return client.content
