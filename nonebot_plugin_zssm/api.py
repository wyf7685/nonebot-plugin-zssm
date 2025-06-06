import json
from typing import Any, AsyncGenerator, NoReturn, Self, TypedDict

import httpx
from nonebot.log import logger

from .config import LLMConfig


class APIError(Exception):
    """基础API异常类"""

    def __init__(self, message: str, code: int | None = None):
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}" if code else message)


class CompletionMessage(TypedDict):
    role: str
    content: str | list[dict[str, Any]]


class AsyncChatClient:
    config: LLMConfig
    content: str
    reasoning_content: str

    def __init__(self, config: LLMConfig, timeout: int = 120) -> None:
        self.config = config
        self.timeout = timeout
        self._client = httpx.AsyncClient()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    def _build_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.config.token}",
            "Content-Type": "application/json",
        }

    async def create(self, *messages: CompletionMessage, **kwargs: Any) -> dict:
        """发起非流式请求并返回解析后的响应"""
        url = f"{self.config.endpoint}/chat/completions"
        payload = {"model": self.config.name, "messages": [*messages], "stream": False, **kwargs}

        response = await self._client.post(
            url,
            headers=self._build_headers(),
            json=payload,
            timeout=self.timeout,
        )

        if response.status_code != 200:
            self._handle_error(response)

        return response.json()

    async def stream_create(self, *messages: CompletionMessage, **kwargs: Any) -> AsyncGenerator[str, None]:
        """发起流式请求并返回异步生成器"""
        url = f"{self.config.endpoint}/chat/completions"
        payload = {"model": self.config.name, "messages": [*messages], "stream": True, **kwargs}
        self.content = ""
        self.reasoning_content = ""

        async with self._client.stream(
            "POST",
            url,
            headers=self._build_headers(),
            json=payload,
            timeout=self.timeout,
        ) as resp:
            if resp.status_code != 200:
                await resp.aread()
                self._handle_error(resp)

            async for chunk in resp.aiter_lines():
                if (data := self._parse_stream_chunk(chunk)) is None:
                    continue

                # 更新内容
                reasoning_content, content = data
                self.reasoning_content += reasoning_content
                self.content += content
                yield self.reasoning_content + self.content

    def _parse_stream_chunk(self, chunk: str) -> tuple[str, str] | None:
        if not chunk.startswith("data:") or (data_str := chunk[6:].strip()) == "[DONE]":
            return None

        try:
            data: dict[str, Any] = json.loads(data_str)
        except json.JSONDecodeError:
            logger.error(f"Failed to parse stream chunk: {chunk}")
            return None

        choice: dict[str, dict] = data["choices"][0]
        delta: dict[str, str] = choice.get("delta", {})
        return delta.get("reasoning_content") or "", delta.get("content") or ""

    def _handle_error(self, response: httpx.Response) -> NoReturn:
        """统一错误处理"""
        try:
            error_data: dict = response.json()
            message = error_data.get("message", "Unknown error")
            code = error_data.get("code", response.status_code)
        except Exception:
            message = f"HTTP Error {response.status_code}"
            code = response.status_code
        raise APIError(message, code)
