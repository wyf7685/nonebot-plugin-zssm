import contextlib
import tempfile
from collections.abc import AsyncGenerator

import fitz  # PyMuPDF
import httpx
from nonebot import logger

from ..config import plugin_config

config = plugin_config.pdf


@contextlib.asynccontextmanager
async def _download_pdf(url: str) -> AsyncGenerator[str | None]:
    with tempfile.NamedTemporaryFile(suffix=".pdf") as temp:
        try:
            async with (
                httpx.AsyncClient() as client,
                client.stream("GET", url, timeout=60.0, follow_redirects=True) as resp,
            ):
                async for chunk in resp.raise_for_status().aiter_bytes(64 * 1024):  # 64KB
                    temp.write(chunk)
                    if temp.tell() > config.max_size:
                        logger.error(f"PDF文件过大: {temp.tell() / 1024 / 1024:.2f}MB, 超过{config.max_size / 1024 / 1024:.2f}MB限制")
                        yield None
                        return

        except httpx.HTTPError:
            logger.exception(f"下载PDF失败: {url}")
            yield None
        else:
            temp.flush()
            temp.seek(0)
            yield temp.name


async def process_pdf(url: str) -> str | None:
    """处理PDF内容

    Args:
        url: PDF文件URL

    Returns:
        Optional[str]: PDF内容文本, 失败时返回None
    """

    async with _download_pdf(url) as filename:
        if filename is None:
            return None

        try:
            with fitz.open(filename) as doc:
                # 检查页数
                if len(doc) > (max_pages := config.max_pages):
                    logger.info(f"PDF页数过多: {len(doc)}, 将只处理前{max_pages}页")
                    page_count = max_pages
                else:
                    page_count = len(doc)

                # 提取文本
                full_text = "\n".join(doc.load_page(page_num).get_textpage().extractText() for page_num in range(page_count))

        except Exception:
            logger.exception(f"处理PDF失败: {url}")
            return None

    # 如果文本太长，截取前N个字符
    if len(full_text) > (max_chars := config.max_chars):
        logger.info(f"PDF内容过长，已截取前{max_chars}个字符，原长度: {len(full_text)}")
        full_text = full_text[:max_chars] + "\n...[内容过长已截断]"

    return full_text
