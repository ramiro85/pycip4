"""Asynchronous JMF message responder (HTTP server).

CIP4 devices and MIS systems exchange JMF over plain HTTP(S) POST: the
caller POSTs a ``<JMF><Body><Query .../></Body></JMF>`` envelope with
content-type ``application/vnd.cip4-jmf+xml`` to a well-known endpoint, and
the responder answers synchronously with a ``<JMF><Body><Response .../>``
envelope of the same content-type.

:class:`JMFServer` implements that contract on top of ``aiohttp.web`` with
a small, registry-based dispatch so handlers for specific JMF ``Type``
values (``KnownDevices``, ``Status``, ...) can be registered without the
server core knowing about any of them -- the same extensibility philosophy
as the model layer's :data:`~pycip4.models.base.NODE_REGISTRY`.

Example:
    >>> server = JMFServer(device_id="Press-01")
    >>> @server.on_query("KnownDevices")
    ... async def known_devices(message, request):
    ...     return {"DeviceID": "Press-01", "DeviceStatus": "Idle"}
    >>> isinstance(server.app, object)
    True
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any
from xml.sax.saxutils import quoteattr

from aiohttp import web

from pycip4.core.exceptions import JMFMessageError
from pycip4.core.types import JMF_NAMESPACE, MIME_TYPE_JMF, JMFAcknowledgeCode
from pycip4.models.jmf import (
    JMFCommand,
    JMFEnvelope,
    JMFMessage,
    JMFQuery,
    build_acknowledge,
    build_response,
)

logger = logging.getLogger("pycip4.messaging.jmf_server")

#: A handler receives the parsed message and the raw ``aiohttp`` request,
#: and returns either a plain ``dict`` of response attributes, a fully
#: built :class:`~pycip4.models.jmf.JMFMessage` to use verbatim as the
#: ``Response``/``Acknowledge`` payload, or ``None`` for an attribute-free
#: (bare) response.
QueryHandler = Callable[[JMFMessage, web.Request], Awaitable[dict[str, Any] | JMFMessage | None]]
CommandHandler = QueryHandler


class JMFServer:
    """Async JMF responder exposing a single HTTP(S) endpoint.

    Handlers are registered per ``(family, Type)`` via :meth:`on_query` /
    :meth:`on_command` decorators. Unregistered but well-formed messages are
    acknowledged with :data:`JMFAcknowledgeCode.UNKNOWN_MESSAGE_TYPE`
    rather than raising, matching JMF's "always acknowledge" contract.

    Attributes:
        device_id: Identifies this responder in outgoing message attributes
            where applicable (not mandated by JMF, but conventional).
    """

    def __init__(self, *, device_id: str | None = None, path: str = "/jmf") -> None:
        self.device_id = device_id
        self._path = path
        self._query_handlers: dict[str, QueryHandler] = {}
        self._command_handlers: dict[str, CommandHandler] = {}
        self._app = web.Application()
        self._app.router.add_post(self._path, self._handle_request)

    # ------------------------------------------------------------------ #
    # Handler registration
    # ------------------------------------------------------------------ #

    def on_query(self, message_type: str) -> Callable[[QueryHandler], QueryHandler]:
        """Decorator registering an ``async def`` handler for a ``Query`` ``Type``.

        Example:
            >>> server = JMFServer()
            >>> @server.on_query("Status")
            ... async def status(message, request):
            ...     return {"DeviceStatus": "Idle"}
        """

        def decorator(handler: QueryHandler) -> QueryHandler:
            self._query_handlers[message_type] = handler
            return handler

        return decorator

    def on_command(self, message_type: str) -> Callable[[CommandHandler], CommandHandler]:
        """Decorator registering an ``async def`` handler for a ``Command`` ``Type``."""

        def decorator(handler: CommandHandler) -> CommandHandler:
            self._command_handlers[message_type] = handler
            return handler

        return decorator

    # ------------------------------------------------------------------ #
    # Request handling
    # ------------------------------------------------------------------ #

    async def _handle_request(self, request: web.Request) -> web.Response:
        body = await request.read()
        try:
            envelope = JMFEnvelope.from_xml_string(body)
            message = envelope.require_message()
        except Exception as exc:  # malformed input must still get a JMF-shaped reply
            logger.warning("Rejecting malformed JMF request: %s", exc)
            return self._error_response(exc)

        try:
            reply_envelope = await self._dispatch(message, request)
        except Exception:
            logger.exception("JMF handler raised for message Type=%s", message.message_type)
            ack = build_acknowledge(
                message,
                return_code=JMFAcknowledgeCode.GENERAL_ERROR.value,
                text="Internal error processing request",
            )
            reply_envelope = JMFEnvelope.wrap(ack, sender_id=self.device_id)

        return web.Response(
            body=reply_envelope.to_xml_bytes(),
            content_type=MIME_TYPE_JMF,
            charset="utf-8",
        )

    async def _dispatch(self, message: JMFMessage, request: web.Request) -> JMFEnvelope:
        message_type = message.message_type or ""

        if isinstance(message, JMFQuery):
            handler = self._query_handlers.get(message_type)
            if handler is None:
                ack = build_acknowledge(
                    message,
                    return_code=JMFAcknowledgeCode.UNKNOWN_MESSAGE_TYPE.value,
                    text=f"No handler registered for Query Type={message_type!r}",
                )
                return JMFEnvelope.wrap(ack, sender_id=self.device_id)
            result = await handler(message, request)
            response = self._build_response(message, result)
            return JMFEnvelope.wrap(response, sender_id=self.device_id)

        if isinstance(message, JMFCommand):
            handler = self._command_handlers.get(message_type)
            if handler is None:
                ack = build_acknowledge(
                    message,
                    return_code=JMFAcknowledgeCode.UNKNOWN_MESSAGE_TYPE.value,
                    text=f"No handler registered for Command Type={message_type!r}",
                )
                return JMFEnvelope.wrap(ack, sender_id=self.device_id)
            result = await handler(message, request)
            # Commands acknowledge immediately; any payload becomes attributes
            # on the Acknowledge itself (simple synchronous command model).
            attrs = result if isinstance(result, dict) else {}
            ack = build_acknowledge(message, return_code=JMFAcknowledgeCode.OK.value)
            for key, value in attrs.items():
                ack.set_attr(key, value)
            return JMFEnvelope.wrap(ack, sender_id=self.device_id)

        # Signals and other families: acknowledge receipt only.
        ack = build_acknowledge(message, return_code=JMFAcknowledgeCode.OK.value)
        return JMFEnvelope.wrap(ack, sender_id=self.device_id)

    @staticmethod
    def _build_response(
        message: JMFMessage, result: dict[str, Any] | JMFMessage | None
    ) -> JMFMessage:
        if isinstance(result, JMFMessage):
            # Caller supplied a fully-built Response/Acknowledge message.
            return result
        response = build_response(message)
        for key, value in (result or {}).items():
            response.set_attr(key, value)
        return response

    @staticmethod
    def _error_response(exc: Exception) -> web.Response:
        # Best-effort JMF-shaped error when the inbound envelope itself is
        # unparsable -- we cannot correlate a refID, so ReturnCode/Text are
        # all we can offer.
        error_xml = (
            f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<JMF xmlns={quoteattr(JMF_NAMESPACE)} Version="1.3">'
            f"<Body><Acknowledge Type=\"Unknown\" "
            f'ReturnCode="{JMFAcknowledgeCode.FORMAT_ERROR.value}" '
            f"Text={quoteattr(str(JMFMessageError(str(exc))))}/></Body></JMF>"
        )
        return web.Response(
            body=error_xml.encode("utf-8"),
            content_type=MIME_TYPE_JMF,
            charset="utf-8",
            status=200,  # JMF errors are reported in-band, not via HTTP status
        )

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    @property
    def app(self) -> web.Application:
        """The underlying ``aiohttp.web.Application`` (for test clients, TLS
        context injection, or mounting alongside other routes).
        """
        return self._app

    def run(self, *, host: str = "0.0.0.0", port: int = 8080, **kwargs: Any) -> None:
        """Run the server with ``aiohttp``'s blocking event-loop runner.

        For embedding inside an existing asyncio application instead, use
        an ``aiohttp.web.AppRunner`` against :attr:`app` directly.
        """
        web.run_app(self._app, host=host, port=port, **kwargs)


def known_devices_handler_factory(
    device_id: str, device_status: str = "Idle", device_type: str = "Press"
) -> QueryHandler:
    """Build a ready-to-register ``KnownDevices`` query handler.

    Example:
        >>> server = JMFServer(device_id="Press-01")
        >>> server.on_query("KnownDevices")(
        ...     known_devices_handler_factory("Press-01", "Idle", "DigitalPrinting")
        ... )  # doctest: +ELLIPSIS
        <function known_devices_handler_factory...
    """

    async def handler(message: JMFMessage, request: web.Request) -> dict[str, Any]:
        return {"DeviceID": device_id, "DeviceStatus": device_status, "DeviceType": device_type}

    return handler


def status_handler_factory(status_provider: Callable[[], dict[str, Any]]) -> QueryHandler:
    """Build a ``Status`` query handler backed by a user-supplied callback
    that returns the current device/job status as a flat attribute dict.
    """

    async def handler(message: JMFMessage, request: web.Request) -> dict[str, Any]:
        return status_provider()

    return handler
