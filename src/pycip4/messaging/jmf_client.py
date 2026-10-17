"""Asynchronous JMF client for sending Query/Command/Signal messages.

Complements :mod:`pycip4.messaging.jmf_server`: where the server answers
inbound JMF HTTP POSTs, :class:`JMFClient` originates them -- e.g. an MIS
polling a press's device status, or a workflow controller submitting a
queue entry to a digital front-end.
"""

from __future__ import annotations

from types import TracebackType
from typing import Any, Self

import httpx

from pycip4.core.exceptions import JMFMessageError, TransportError
from pycip4.core.types import MIME_TYPE_JMF
from pycip4.models.jmf import (
    JMFAcknowledge,
    JMFEnvelope,
    JMFMessage,
    JMFResponse,
    build_command,
    build_query,
    build_signal,
)


class JMFClient:
    """Async HTTP(S) client for sending JMF messages to a CIP4 device/controller.

    Example:
        >>> async def example() -> None:  # doctest: +SKIP
        ...     async with JMFClient("https://press.local/jmf") as client:
        ...         response = await client.query("KnownDevices")
        ...         print(response.get_attr("DeviceID"))
    """

    def __init__(
        self,
        endpoint: str,
        *,
        sender_id: str | None = None,
        timeout: float = 30.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        """Args:
        endpoint: Full URL of the target JMF endpoint.
        sender_id: Identifies this client as ``SenderID`` on outgoing envelopes.
        timeout: Per-request timeout, in seconds.
        http_client: Inject a pre-configured ``httpx.AsyncClient`` (for
            connection pooling shared across multiple ``JMFClient``s, custom
            TLS settings, or test transports). A private client is created
            and owned by this instance otherwise.
        """
        self._endpoint = endpoint
        self._sender_id = sender_id
        self._owns_client = http_client is None
        self._http = http_client or httpx.AsyncClient(timeout=timeout)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the underlying HTTP client, if owned by this instance."""
        if self._owns_client:
            await self._http.aclose()

    # ------------------------------------------------------------------ #
    # High-level message senders
    # ------------------------------------------------------------------ #

    async def query(self, message_type: str, **attributes: str) -> JMFResponse:
        """Send a ``Query`` and return the parsed ``Response``.

        Args:
            message_type: JMF ``Type``, e.g. ``"KnownDevices"`` or ``"Status"``.
            **attributes: Additional query attributes/parameters.

        Returns:
            The ``Response`` message from the reply envelope.

        Raises:
            JMFMessageError: If the reply envelope has no ``Response``
                (e.g. the responder returned an ``Acknowledge`` error
                instead -- callers that must also handle the
                error-acknowledge case should use :meth:`send` directly).
            TransportError: On a network-level failure.
        """
        message = build_query(message_type, **attributes)
        reply = await self.send(message)
        if isinstance(reply, JMFResponse):
            return reply
        if isinstance(reply, JMFAcknowledge):
            reply.raise_for_status()
        raise JMFMessageError(
            f"Expected a Response to Query Type={message_type!r}, got {reply.tag}"
        )

    async def command(self, message_type: str, **attributes: str) -> JMFAcknowledge:
        """Send a ``Command`` and return the parsed ``Acknowledge``.

        Raises:
            TransportError: On a network-level failure.
        """
        message = build_command(message_type, **attributes)
        reply = await self.send(message)
        if isinstance(reply, JMFAcknowledge):
            return reply
        raise JMFMessageError(
            f"Expected an Acknowledge to Command Type={message_type!r}, got {reply.tag}"
        )

    async def signal(self, message_type: str, **attributes: str) -> JMFAcknowledge:
        """Send a ``Signal`` (fire-and-forget notification) and return its
        receipt ``Acknowledge``.
        """
        message = build_signal(message_type, **attributes)
        reply = await self.send(message)
        if isinstance(reply, JMFAcknowledge):
            return reply
        raise JMFMessageError(
            f"Expected an Acknowledge to Signal Type={message_type!r}, got {reply.tag}"
        )

    # ------------------------------------------------------------------ #
    # Low-level envelope transport
    # ------------------------------------------------------------------ #

    async def send(self, message: JMFMessage) -> JMFMessage:
        """Wrap ``message`` in a ``JMF`` envelope, POST it, and return the
        single reply message element (``Response`` or ``Acknowledge``).

        Raises:
            TransportError: On connection failure, timeout, or non-2xx HTTP
                status.
            JMFMessageError: If the reply body is not a well-formed JMF
                envelope.
        """
        envelope = JMFEnvelope.wrap(message, sender_id=self._sender_id)
        try:
            http_response = await self._http.post(
                self._endpoint,
                content=envelope.to_xml_bytes(),
                headers={"Content-Type": MIME_TYPE_JMF},
            )
            http_response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise TransportError(
                f"JMF endpoint returned HTTP {exc.response.status_code}",
                context={"endpoint": self._endpoint, "body": exc.response.text[:500]},
            ) from exc
        except httpx.HTTPError as exc:
            raise TransportError(
                f"Failed to reach JMF endpoint {self._endpoint}: {exc}"
            ) from exc

        try:
            reply_envelope = JMFEnvelope.from_xml_string(http_response.content)
            return reply_envelope.require_message()
        except Exception as exc:
            raise JMFMessageError(f"Malformed JMF reply from {self._endpoint}: {exc}") from exc


async def query_known_devices(endpoint: str, **attributes: Any) -> JMFResponse:
    """One-shot convenience: query ``KnownDevices`` without managing a client."""
    async with JMFClient(endpoint) as client:
        return await client.query("KnownDevices", **{k: str(v) for k, v in attributes.items()})


async def query_status(endpoint: str, **attributes: Any) -> JMFResponse:
    """One-shot convenience: query ``Status`` without managing a client."""
    async with JMFClient(endpoint) as client:
        return await client.query("Status", **{k: str(v) for k, v in attributes.items()})
