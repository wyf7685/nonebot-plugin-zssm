import tempfile
from io import BytesIO

import fitz  # PyMuPDF
import httpx
from nonebot import logger

from ..config import plugin_config

config = plugin_config.pdf


async def download_pdf(url: str) -> BytesIO | None:
    """下载PDF文件

    Args:
        url: PDF文件URL

    Returns:
        BytesIO | None: PDF文件的BytesIO对象, 失败时返回None
    """
    buffer = BytesIO()
    total_size = 0

    try:
        async with (
            httpx.AsyncClient() as client,
            client.stream("GET", url, timeout=60.0, follow_redirects=True) as resp,
        ):
            async for chunk in resp.raise_for_status().aiter_bytes(4096):
                total_size += len(chunk)
                if total_size > config.max_size:
                    logger.error(f"PDF文件过大: {total_size / 1024 / 1024:.2f}MB, 超过{config.max_size / 1024 / 1024:.2f}MB限制")
                    return None

                buffer.write(chunk)

    except httpx.HTTPError as e:
        logger.error(f"下载PDF失败: {url}, 错误: {e}")
        return None
    else:
        buffer.seek(0)
        return buffer


async def process_pdf(url: str) -> str | None:
    """处理PDF内容

    Args:
        url: PDF文件URL

    Returns:
        Optional[str]: PDF内容文本, 失败时返回None
    """
    # 下载PDF
    if (pdf_buffer := await download_pdf(url)) is None:
        return None

    try:
        # 创建临时文件
        with tempfile.NamedTemporaryFile(suffix=".pdf") as temp_file:
            temp_file.write(pdf_buffer.getvalue())
            with fitz.open(temp_file.name) as doc:
                # 检查页数
                if len(doc) > (max_pages := config.max_pages):
                    logger.info(f"PDF页数过多: {len(doc)}, 将只处理前{max_pages}页")
                    page_count = max_pages
                else:
                    page_count = len(doc)

                # 提取文本
                full_text = "\n".join(doc.load_page(page_num).get_textpage().extractText() for page_num in range(page_count))

                # 如果文本太长，截取前N个字符
                if len(full_text) > (max_chars := config.max_chars):
                    logger.info(f"PDF内容过长，已截取前{max_chars}个字符，原长度: {len(full_text)}")
                    full_text = full_text[:max_chars] + "\n...[内容过长已截断]"

                return full_text

    except Exception as e:
        logger.error(f"处理PDF失败: {url}, 错误: {e}")
        return None
