"""ASGI middlewares for the MCP Gateway."""

from typing import Any

from starlette.types import Message, Receive, Scope, Send

_HTTP_RESPONSE_START = "http.response.start"


class PayloadTooLargeError(RuntimeError):
    """Raised when the request body exceeds the maximum allowed size."""


class MaxBodySizeMiddleware:
    def __init__(self, app: Any, max_size_bytes: int):
        self.app = app
        self.max_size_bytes = max_size_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self._should_handle(scope):
            await self.app(scope, receive, send)
            return

        response_started = False

        async def wrapped_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == _HTTP_RESPONSE_START:
                response_started = True
            await send(message)

        # Check for duplicate Content-Length headers to prevent request smuggling
        content_lengths = [v for k, v in scope["headers"] if k.lower() == b"content-length"]
        if len(content_lengths) > 1:
            await self._send_400(wrapped_send)
            return

        headers = dict(scope["headers"])
        if b"content-length" in headers:
            handled = await self._handle_content_length(
                headers=headers,
                wrapped_send=wrapped_send,
                scope=scope,
                receive=receive,
                response_started_ref=lambda: response_started,
            )
            if handled:
                return
        else:
            handled = await self._handle_no_content_length(
                scope=scope,
                receive=receive,
                wrapped_send=wrapped_send,
                response_started_ref=lambda: response_started,
            )
            if handled:
                return

    def _should_handle(self, scope: Scope) -> bool:
        return scope["type"] == "http" and scope["method"] in (
            "POST",
            "PUT",
            "PATCH",
            "DELETE",
        )

    async def _handle_content_length(
        self,
        *,
        headers: dict[bytes, bytes],
        wrapped_send: Any,
        scope: Scope,
        receive: Receive,
        response_started_ref: Any,
    ) -> bool:
        """Fast path when Content-Length header is present.

        Returns ``True`` if the request was fully handled and the caller
        should return, ``False`` if the caller should continue processing.
        """
        try:
            content_length = int(headers[b"content-length"])
        except ValueError:
            await self._send_400(wrapped_send)
            return True

        if content_length < 0:
            await self._send_400(wrapped_send)
            return True

        if content_length > self.max_size_bytes:
            await self._send_413(wrapped_send)
            return True

        count = 0

        async def wrapped_receive() -> Message:
            nonlocal count
            message = await receive()
            if message["type"] == "http.request":
                body = message.get("body", b"")
                count += len(body)
                if count > self.max_size_bytes:
                    raise PayloadTooLargeError()
            return message

        try:
            await self.app(scope, wrapped_receive, wrapped_send)
        except PayloadTooLargeError:
            if not response_started_ref():
                await self._send_413(wrapped_send)
                return True
            raise

        return True

    async def _handle_no_content_length(
        self,
        *,
        scope: Scope,
        receive: Receive,
        wrapped_send: Any,
        response_started_ref: Any,
    ) -> bool:
        """Robust path when Content-Length header is absent.

        Eagerly reads and buffers up to *max_size_bytes* + 1 bytes to
        enforce the limit even if the application never reads the body.

        Returns ``True`` if the request was fully handled and the caller
        should return.
        """
        buffered_messages: list[Message] = []
        count = 0
        while True:
            message = await receive()
            buffered_messages.append(message)
            if message["type"] == "http.request":
                body = message.get("body", b"")
                count += len(body)
                if count > self.max_size_bytes:
                    if not response_started_ref():
                        await self._send_413(wrapped_send)
                    return True
                if not message.get("more_body", False):
                    break
            elif message["type"] == "http.disconnect":
                break

        async def buffered_receive() -> Message:
            if buffered_messages:
                return buffered_messages.pop(0)
            return await receive()

        await self.app(scope, buffered_receive, wrapped_send)
        return True

    async def _send_400(self, send: Send) -> None:
        await send(
            {
                "type": _HTTP_RESPONSE_START,
                "status": 400,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": b'{"error": "invalid_request"}',
            }
        )

    async def _send_413(self, send: Send) -> None:
        await send(
            {
                "type": _HTTP_RESPONSE_START,
                "status": 413,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": b'{"error": "payload_too_large"}',
            }
        )
