import json
import re
import time

from nonebot import logger
from nonebot.compat import type_validate_json
from pydantic import BaseModel

from ..api import AsyncChatClient
from ..config import plugin_config
from ..constant import AUDIT_SYSTEM_PROMPT, AUDIT_USER_PROMPT

config = plugin_config.text
config_check = plugin_config.check


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
        logger.opt(exception=e).warning("清理Markdown格式失败")

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


async def check_prompt_leakage(response: str, system_prompt: str) -> str:
    """检查AI响应是否泄露了system prompt

    Args:
        response: AI的响应内容
        system_prompt: 原始系统提示词

    Returns:
        tuple[bool, str]: (是否泄露, 审查后的响应)
    """
    if config_check is None:
        # 如果没有配置审查API Token，则跳过审查
        logger.warning("未配置审查API Token，跳过system prompt泄露检查")
        return response

    try:
        prompt = AUDIT_USER_PROMPT.format(
            system_prompt=system_prompt,
            response=response,
        )

        logger.info(f"开始审查AI响应: {config_check.name}")
        async with AsyncChatClient(config_check) as client:
            audit_response = await client.create(
                {"role": "system", "content": AUDIT_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            )

            if not audit_response or "choices" not in audit_response:
                logger.error("审查AI返回内容为空或格式错误")
                return response

            audit_content: str = audit_response["choices"][0]["message"]["content"]

            try:
                audit_result: dict[str, object] = json.loads(re.sub(r"^```\w*\s*|\s*```$", "", audit_content.strip()))
                logger.info(f"审查结果: {audit_result}")
            except json.JSONDecodeError:
                logger.exception("审查结果JSON解析失败")
                logger.debug(f"原始审查内容: {audit_content}")
                return response

            if audit_result.get("leaked", False):
                logger.warning("检测到 system prompt 泄露，已替换响应")
                return "（抱歉，我现在还不会这个）"
            return response

    except Exception:
        logger.exception("检查prompt泄露失败")
        return response


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

        if (llm_resp := extract_output_safe(data)) is None:
            logger.error(f"AI响应格式异常: \n{data}")
            return None

        if llm_resp.block:
            return "（抱歉, 我现在还不会这个）"

        output = await check_prompt_leakage(llm_resp.output, system_prompt)

        return (
            f"关键词：{' | '.join(keywords) if isinstance(keywords, list) else keywords}\n\n" if (keywords := llm_resp.keyword) else ""
        ) + output

    except Exception as e:
        logger.opt(exception=e).error("生成AI响应失败")
        return None
