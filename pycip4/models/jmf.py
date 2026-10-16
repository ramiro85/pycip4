"""JMF (Job Messaging Format) document model.

A JMF document is a thin envelope (``<JMF>``) wrapping exactly one
``<Body>`` which, in turn, contains exactly one message element whose tag
names the JMF *family* (``Query``, ``Command``, ``Response``, ``Signal``,
``Acknowledge``) and whose ``Type`` attribute names the concrete message
(``KnownDevices``, ``Status``, ``SubmitQueueEntry``, ...).

This module models that envelope/body/message shape explicitly rather than
reusing the generic JDF tree model, since JMF messaging semantics (request
IDs, acknowledge return codes, device identity) are meaningfully different
from JDF's resource/process graph.
"""

from __future__ import annotations

from typing import Self

from pycip4.core.exceptions import JMFAckError, JMFMessageError
from pycip4.core.types import JMFAcknowledgeCode, JMFMessageFamily
from pycip4.models.base import CIP4Element, CIP4Node, generate_id, register_node


class JMFMessage(CIP4Element):
    """One JMF message element (``Query``, ``Command``, ``Response``,
    ``Signal``, or ``Acknowledge``).

    Attributes are accessed via the generic :meth:`get_attr`/:meth:`set_attr`
    inherited from :class:`CIP4Element`; this class adds JMF-specific typed
    convenience properties on top.
    """

    @property
    def message_type(self) -> str | None:
        """The ``Type`` attribute, e.g. ``"KnownDevices"`` or ``"Status"``."""
        return self.get_attr("Type")

    @property
    def message_id(self) -> str | None:
        """The ``ID`` attribute, used to correlate Query/Command with their
        eventual Response/Acknowledge.
        """
        return self.get_attr("ID")

    @property
    def family(self) -> JMFMessageFamily:
        """The message family, derived from this element's tag name."""
        return JMFMessageFamily(self.tag)


@register_node("Query")
class JMFQuery(JMFMessage):
    """A JMF ``Query`` message: request for current state (no side effects)."""

    XML_TAG = "Query"


@register_node("Command")
class JMFCommand(JMFMessage):
    """A JMF ``Command`` message: request to change device/job state."""

    XML_TAG = "Command"


@register_node("Signal")
class JMFSignal(JMFMessage):
    """A JMF ``Signal`` message: unsolicited notification of a state change."""

    XML_TAG = "Signal"


@register_node("Response")
class JMFResponse(JMFMessage):
    """A JMF ``Response`` message: the reply payload to a ``Query`` or the
    successful result of a ``Command``.
    """

    XML_TAG = "Response"

    @property
    def return_code(self) -> int | None:
        raw = self.get_attr("ReturnCode")
        return int(raw) if raw is not None else None


@register_node("Acknowledge")
class JMFAcknowledge(JMFMessage):
    """A JMF ``Acknowledge`` message: immediate receipt confirmation,
    carrying a ``ReturnCode`` (``0`` = success).
    """

    XML_TAG = "Acknowledge"

    @property
    def return_code(self) -> int:
        raw = self.get_attr("ReturnCode")
        return int(raw) if raw is not None else JMFAcknowledgeCode.OK.value

    def raise_for_status(self) -> None:
        """Raise :class:`JMFAckError` if this acknowledge reports failure.

        Example:
            >>> ack = JMFAcknowledge.create("Acknowledge", ReturnCode="0")
            >>> ack.raise_for_status()  # no-op, ReturnCode == 0
        """
        if self.return_code != JMFAcknowledgeCode.OK.value:
            raise JMFAckError(
                f"JMF command/query was not acknowledged successfully "
                f"(ReturnCode={self.return_code})",
                return_code=self.return_code,
                ack_text=self.get_attr("Text"),
            )


@register_node("JMF")
class JMFEnvelope(CIP4Node):
    """The root ``JMF`` envelope element.

    Exactly one ``Body`` child wraps exactly one message element in
    practice (CIP4 permits multiple, pycip4's builders emit one per
    envelope, matching the overwhelming majority of real-world usage).
    """

    XML_TAG = "JMF"

    @classmethod
    def wrap(
        cls, message: JMFMessage, *, version: str = "1.3", sender_id: str | None = None
    ) -> Self:
        """Wrap a single message element in a new ``JMF``/``Body`` envelope.

        Args:
            message: The ``Query``/``Command``/``Response``/``Signal``/
                ``Acknowledge`` element to wrap.
            version: JMF schema ``Version``.
            sender_id: Optional ``SenderID`` identifying the originating
                device/application.

        Returns:
            A complete, ready-to-serialize ``JMF`` envelope.
        """
        envelope = cls.create("JMF", Version=version)
        if sender_id:
            envelope.set_attr("SenderID", sender_id)
        body = CIP4Element.create("Body")
        body.add_child(message)
        envelope.add_child(body)
        return envelope

    @property
    def body(self) -> CIP4Element | None:
        return self.find_first("Body")

    @property
    def message(self) -> JMFMessage | None:
        """The single wrapped message element, if present."""
        body = self.body
        if body is None or not body.children:
            return None
        child = body.children[0]
        return child if isinstance(child, JMFMessage) else None

    def require_message(self) -> JMFMessage:
        """Like :attr:`message`, but raises if the envelope is malformed.

        Raises:
            JMFMessageError: If there is no ``Body`` or no message inside it.
        """
        message = self.message
        if message is None:
            raise JMFMessageError("JMF envelope has no Body/message element")
        return message


def build_query(
    message_type: str, *, message_id: str | None = None, **attributes: str
) -> JMFQuery:
    """Construct a ``Query`` message of the given ``Type``.

    Args:
        message_type: JMF ``Type`` value, e.g. ``"KnownDevices"``.
        message_id: Correlation ``ID``; auto-generated if omitted.
        **attributes: Additional attributes/parameters for the query.

    Returns:
        A new, unwrapped ``JMFQuery`` element (combine with
        :meth:`JMFEnvelope.wrap` to produce a sendable envelope).
    """
    return JMFQuery.create(
        "Query", Type=message_type, ID=message_id or generate_id("Q"), **attributes
    )


def build_command(
    message_type: str, *, message_id: str | None = None, **attributes: str
) -> JMFCommand:
    """Construct a ``Command`` message of the given ``Type``."""
    return JMFCommand.create(
        "Command", Type=message_type, ID=message_id or generate_id("C"), **attributes
    )


def build_signal(
    message_type: str, *, message_id: str | None = None, **attributes: str
) -> JMFSignal:
    """Construct a ``Signal`` message of the given ``Type``."""
    return JMFSignal.create(
        "Signal", Type=message_type, ID=message_id or generate_id("S"), **attributes
    )


def build_response(
    request: JMFMessage,
    *,
    return_code: int = JMFAcknowledgeCode.OK.value,
    **attributes: str,
) -> JMFResponse:
    """Construct a ``Response`` message correlated to an incoming request.

    Args:
        request: The ``Query`` or ``Command`` being responded to; its
            ``Type`` and correlation ``ID`` (as ``refID``) are copied over.
        return_code: ``0`` for success, non-zero for a domain-specific error.
        **attributes: Additional response payload attributes.
    """
    response = JMFResponse.create(
        "Response",
        Type=request.message_type or "",
        refID=request.message_id or "",
        ReturnCode=str(return_code),
    )
    for key, value in attributes.items():
        response.set_attr(key, value)
    return response


def build_acknowledge(
    request: JMFMessage,
    *,
    return_code: int = JMFAcknowledgeCode.OK.value,
    text: str | None = None,
) -> JMFAcknowledge:
    """Construct an ``Acknowledge`` message correlated to an incoming request."""
    ack = JMFAcknowledge.create(
        "Acknowledge",
        Type=request.message_type or "",
        refID=request.message_id or "",
        ReturnCode=str(return_code),
    )
    if text:
        ack.set_attr("Text", text)
    return ack
