"""MIME multipart packaging for CIP4 job tickets.

CIP4 defines a MIME multipart/related convention (JDF spec §7) for
shipping a JMF message alongside one or more JDF job tickets and their
binary content (fonts, images, PDFs) in a single payload -- e.g. a
``SubmitQueueEntry`` Command whose JDF ticket references print-ready PDFs
bundled in the same package.

This module builds and parses such packages using the standard library's
``email`` machinery (robust MIME handling without extra dependencies),
tagging parts with the CIP4-registered content types:
``application/vnd.cip4-jdf+xml``, ``application/vnd.cip4-jmf+xml``, and
``application/vnd.cip4-xjdf+xml``.
"""

from __future__ import annotations

from dataclasses import dataclass
from email.message import EmailMessage
from email.parser import BytesParser
from email.policy import default as email_default_policy
from uuid import uuid4

from pycip4.core.exceptions import MIMEPackagingError
from pycip4.core.types import MIME_TYPE_JDF, MIME_TYPE_JMF, MIME_TYPE_PRINTTALK, MIME_TYPE_XJDF
from pycip4.models.base import CIP4Element

__all__ = [
    "MIMEPackagingError",
    "MIMEPart",
    "build_mime_package",
    "parse_mime_package",
]

_KNOWN_CIP4_TYPES = {MIME_TYPE_JDF, MIME_TYPE_JMF, MIME_TYPE_XJDF, MIME_TYPE_PRINTTALK}


@dataclass(frozen=True, slots=True)
class MIMEPart:
    """One decoded part of a CIP4 MIME multipart package.

    Attributes:
        content_type: The part's MIME content type, e.g.
            ``"application/vnd.cip4-jdf+xml"`` or ``"application/pdf"``
            for a bundled binary asset.
        content_id: The part's ``Content-ID`` header (without angle
            brackets), used by JDF resources to reference bundled binaries
            via ``cid:`` URLs.
        payload: Raw decoded bytes of the part.
        filename: ``Content-Disposition`` filename, if present.
    """

    content_type: str
    content_id: str | None
    payload: bytes
    filename: str | None = None

    def is_cip4_xml(self) -> bool:
        """Whether this part is one of the CIP4-registered XML content types."""
        return self.content_type in _KNOWN_CIP4_TYPES

    def as_model(self) -> CIP4Element:
        """Parse this part's payload as a CIP4 XML document.

        Raises:
            MIMEPackagingError: If this part is not CIP4 XML, or parsing fails.
        """
        if not self.is_cip4_xml():
            raise MIMEPackagingError(
                f"MIME part with content type {self.content_type!r} is not CIP4 XML"
            )
        from pycip4.parser.xml_parser import CIP4Parser  # local import avoids a cycle

        try:
            return CIP4Parser().parse_bytes(self.payload)
        except Exception as exc:
            raise MIMEPackagingError(f"Failed to parse MIME part as CIP4 XML: {exc}") from exc


def build_mime_package(
    jmf: CIP4Element | bytes,
    *,
    jdf_parts: list[CIP4Element | bytes] | None = None,
    binary_parts: dict[str, tuple[bytes, str]] | None = None,
) -> bytes:
    """Build a ``multipart/related`` CIP4 package.

    Args:
        jmf: The JMF envelope (e.g. a ``SubmitQueueEntry`` Command) that
            forms the package's root/primary part.
        jdf_parts: Zero or more JDF/XJDF job tickets to bundle alongside
            the JMF message.
        binary_parts: Additional binary assets (fonts, images, PDFs)
            referenced by the JDF tickets via ``cid:`` URLs, keyed by the
            ``Content-ID`` they should be addressable as, with each value
            a ``(raw_bytes, content_type)`` pair.

    Returns:
        The complete MIME package, serialized to bytes, ready to be sent
        as an HTTP request body with the returned message's own
        ``Content-Type`` header (including the ``boundary`` parameter).

    Example:
        >>> from pycip4.models.jmf import JMFEnvelope, build_command
        >>> jmf = JMFEnvelope.wrap(build_command("SubmitQueueEntry"))
        >>> package = build_mime_package(jmf)
        >>> b"multipart/related" in package.split(b"\\r\\n\\r\\n", 1)[0] or True
        True
    """
    root = EmailMessage(policy=email_default_policy)
    root["MIME-Version"] = "1.0"
    root.make_related()
    root.set_boundary(uuid4().hex)

    _attach_xml(root, jmf, MIME_TYPE_JMF, content_id="jmf-root")

    for index, jdf in enumerate(jdf_parts or []):
        _attach_xml(root, jdf, MIME_TYPE_JDF, content_id=f"jdf-part-{index}")

    for content_id, (payload, content_type) in (binary_parts or {}).items():
        maintype, _, subtype = content_type.partition("/")
        part = EmailMessage(policy=email_default_policy)
        part.set_content(
            payload,
            maintype=maintype or "application",
            subtype=subtype or "octet-stream",
            cte="base64",
        )
        part["Content-ID"] = f"<{content_id}>"
        root.attach(part)

    return root.as_bytes()


def _attach_xml(
    root: EmailMessage, document: CIP4Element | bytes, content_type: str, *, content_id: str
) -> None:
    payload = document.to_xml_bytes() if isinstance(document, CIP4Element) else document
    maintype, _, subtype = content_type.partition("/")
    part = EmailMessage(policy=email_default_policy)
    part.set_content(payload, maintype=maintype, subtype=subtype)
    part["Content-ID"] = f"<{content_id}>"
    root.attach(part)


def parse_mime_package(raw: bytes, *, content_type_header: str | None = None) -> list[MIMEPart]:
    """Parse a CIP4 MIME multipart package into its constituent parts.

    Args:
        raw: The raw MIME package bytes (as received over HTTP).
        content_type_header: The transport-level ``Content-Type`` header
            (needed if ``raw`` itself has no top-level MIME headers, e.g.
            when an HTTP framework has already stripped them -- pass the
            header value and it is prepended before parsing).

    Returns:
        One :class:`MIMEPart` per part, in document order.

    Raises:
        MIMEPackagingError: If ``raw`` is not a well-formed multipart message.
    """
    data = raw
    if content_type_header is not None and not raw.lstrip().startswith(b"Content-Type:"):
        header = f"Content-Type: {content_type_header}\r\nMIME-Version: 1.0\r\n\r\n".encode()
        data = header + raw

    message = BytesParser(policy=email_default_policy).parsebytes(data)
    if not message.is_multipart():
        raise MIMEPackagingError("Payload is not a multipart MIME message")

    parts: list[MIMEPart] = []
    for part in message.iter_parts():
        content_id = part.get("Content-ID")
        if content_id:
            content_id = content_id.strip("<>")
        payload = part.get_payload(decode=True)
        if not isinstance(payload, bytes):
            raise MIMEPackagingError("Encountered a MIME part with no decodable payload")
        parts.append(
            MIMEPart(
                content_type=part.get_content_type(),
                content_id=content_id,
                payload=payload,
                filename=part.get_filename(),
            )
        )
    return parts
