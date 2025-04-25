import re
import time

from nonebot import logger
from nonebot.compat import type_validate_json
from pydantic import BaseModel

from ..api import AsyncChatClient
from ..config import plugin_config

config = plugin_config.text


class LLMResponse(BaseModel):
    """LLM响应模型"""

    output: str
    block: bool = False
    keyword: str | list[str] | None = None


def extract_output_safe(data: str) -> LLMResponse | None:
    # 尝试清理Markdown代码块
    try:
        markdown_pattern = r"^```\w*\s*|\s*```$"
        data = re.sub(markdown_pattern, "", data.strip())
    except Exception as e:
        logger.warning(f"清理Markdown格式失败: {e}")

    # 记录原始内容用于调试
    logger.debug(f"尝试解析JSON: {data}")

    # 防御性解析，尝试修复常见问题
    if data.startswith("```json") and data.endswith("```"):
        data = data[7:-3].strip()

    # 截取可能的JSON部分
    data = data[data.find("{") : data.rfind("}") + 1]

    try:
        return type_validate_json(LLMResponse, data)
    except ValueError:
        logger.exception(f"LLM 响应解析失败: {data}")
        return None


def truncate_chunk(chunk: str) -> str:
    return f"{chunk[:20]}...{len(chunk) - 40}...{chunk[-20:]}" if len(chunk) > 60 else chunk


async def generate_ai_response(system_prompt: str, user_prompt: str) -> str | None:
    """生成AI响应

    Args:
        system_prompt: 系统提示词
        user_prompt: 用户提示词

    Returns:
        Optional[str]: AI生成的响应, 失败时返回None
    """
    if not config.token:
        return None

    try:
        last_time = time.time()
        last_chunk = ""
        i = 0
        async with AsyncChatClient(config) as client:
            async for chunk in client.stream_create(
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ):
                i += 1
                last_chunk = chunk
                if time.time() - last_time > 5:
                    last_time = time.time()
                    logger.info(f"AI响应进度: {i}, {truncate_chunk(last_chunk)}")

        logger.info(f"AI响应完成: {i}\n{truncate_chunk(last_chunk)}")

        if not (data := client.content):
            logger.error("AI返回内容为空")
            return None

        if (llm_output := extract_output_safe(data)) is None:
            logger.error(f"AI响应格式异常: \n{data}")
            return None

        if llm_output.block:
            return "（抱歉, 我现在还不会这个）"

        return (
            f"关键词：{' | '.join(keywords) if isinstance(keywords, list) else keywords}\n\n"
            if (keywords := llm_output.keyword)
            else ""
        ) + llm_output.output

    except Exception as e:
        logger.error(f"生成AI响应失败: {e}")
        return None
