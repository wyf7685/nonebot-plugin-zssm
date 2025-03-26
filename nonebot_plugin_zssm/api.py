import json

import httpx


class APIError(Exception):
    """基础API异常类"""

    def __init__(self, message: str, code: int | None = None):
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}" if code else message)


class AsyncChatClient:
    def __init__(
        self,
        endpoint: str,
        api_key: str,
        timeout: int = 120,
    ):
        """
        初始化异步聊天客户端

        :param endpoint: API端点
        :param api_key: API密钥
        :param timeout: 请求超时时间
        """
        self.endpoint = endpoint
        self.api_key = api_key
        self.base_url = endpoint
        self.timeout = timeout
        self._client = httpx.AsyncClient()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        await self.close()

    async def close(self):
        """关闭客户端"""
        await self._client.aclose()

    def _build_headers(self) -> dict[str, str]:
        """构建请求头"""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def create(self, model: str, messages: list, *, stream: bool = False, **kwargs):
        """
        创建聊天请求

        :param model: 使用的模型名称
        :param messages: 消息列表
        :param stream: 是否使用流式响应
        :return: 生成器或字典
        """
        url = f"{self.base_url}/chat/completions"

        # 构建基础请求参数
        payload = {"model": model, "messages": messages, "stream": stream, **kwargs}

        # 发送请求
        response = await self._client.post(url, headers=self._build_headers(), json=payload, timeout=self.timeout)

        if response.status_code != 200:
            try:
                error_data = response.json()
                raise APIError(
                    error_data.get("message", "Unknown error"),
                    code=error_data.get("code", response.status_code),
                )
            except json.JSONDecodeError:
                raise APIError(f"HTTP Error {response.status_code}", code=response.status_code) from None
        return response

    async def stream_response(self, response: httpx.Response):
        self.content = ""
        async for chunk in response.aiter_lines():
            if not chunk.strip() or chunk.startswith(": ping"):
                continue
            try:
                if chunk.startswith("data: "):
                    data: dict = json.loads(chunk[6:])
                    if data["finish_reason"] == "stop":
                        self.content += data["choices"][0]["delta"]["content"]
                    yield data
            except json.JSONDecodeError:
                continue

    async def non_stream_response(self, response: httpx.Response):
        return response.json()
