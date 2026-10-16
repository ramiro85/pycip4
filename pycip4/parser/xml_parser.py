"""Safe, fast XML parsing of CIP4 documents into pycip4 model instances.

Two entry points cover the two real-world shapes consumers need:

* :class:`CIP4Parser` -- parse a complete, in-memory document (string,
  bytes, file path, or open binary stream) into the right root model
  (:class:`~pycip4.models.jdf.JDFNode`, :class:`~pycip4.models.jmf.JMFEnvelope`,
  or :class:`~pycip4.models.xjdf.XJDFNode`), auto-detected from the root
  element's tag/namespace.
* :func:`iter_parse_jdf_nodes` -- a streaming, constant-memory walk over a
  *huge* JDF file using ``lxml.etree.iterparse``, yielding each ``JDF``
  process node as it closes and immediately freeing it from memory. This
  is the recommended path for multi-hundred-MB job tickets where loading
  the full tree would be wasteful or impossible.

Security note:
    All parsing disables network access and entity resolution
    (``resolve_entities=False``, ``no_network=True``) to avoid XXE and SSRF
    via maliciously crafted documents -- CIP4 documents routinely arrive
    from third-party MIS/workflow systems and must be treated as untrusted
    input.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO

from lxml import etree

from pycip4.core.exceptions import XMLParsingError
from pycip4.core.types import JDF_NAMESPACE, XJDF_NAMESPACE
from pycip4.models.base import CIP4Element
from pycip4.models.jdf import JDFNode
from pycip4.models.jmf import JMFEnvelope
from pycip4.models.xjdf import XJDFNode

#: Root tag -> model class, keyed by (namespace, local_tag).
_ROOT_DISPATCH: dict[tuple[str, str], type[CIP4Element]] = {
    (JDF_NAMESPACE, "JDF"): JDFNode,
    (JDF_NAMESPACE, "JMF"): JMFEnvelope,
    (XJDF_NAMESPACE, "XJDF"): XJDFNode,
}


def _safe_parser(*, huge_tree: bool = False) -> etree.XMLParser:
    """Build an ``lxml`` parser hardened against XXE/SSRF/entity-expansion."""
    return etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        huge_tree=huge_tree,
        load_dtd=False,
        dtd_validation=False,
    )


def _split_qname(tag: str) -> tuple[str | None, str]:
    namespace, _, local = tag.rpartition("}")
    return (namespace.lstrip("{") or None, local)


class CIP4Parser:
    """Parses complete CIP4 documents (JDF, JMF, or XJDF) into pycip4 models.

    The format is auto-detected from the root element -- callers do not
    need to know in advance whether a byte stream holds a JDF job ticket, a
    JMF message, or an XJDF product, which matters for generic ingestion
    pipelines (e.g. a MIME multipart handler that receives mixed payloads).

    Example:
        >>> parser = CIP4Parser()
        >>> node = parser.parse_string("<JDF xmlns='http://www.CIP4.org/JDFSchema_1_1' "
        ...                             "JobID='J1' Type='Product'/>")
        >>> node.job_id
        'J1'
    """

    def __init__(self, *, huge_tree: bool = False) -> None:
        """Args:
        huge_tree: Disable ``lxml``'s default ~10MB/depth protections for
            trusted, very large documents. Leave ``False`` for untrusted
            input.
        """
        self._huge_tree = huge_tree

    def parse_string(self, xml: str) -> CIP4Element:
        """Parse an XML string into the appropriate root model."""
        return self.parse_bytes(xml.encode("utf-8"))

    def parse_bytes(self, xml: bytes) -> CIP4Element:
        """Parse raw XML bytes into the appropriate root model.

        Raises:
            XMLParsingError: On malformed XML or an unrecognized root element.
        """
        try:
            root = etree.fromstring(xml, parser=_safe_parser(huge_tree=self._huge_tree))
        except etree.XMLSyntaxError as exc:
            raise XMLParsingError(f"Malformed CIP4 XML document: {exc}") from exc
        return self._dispatch(root)

    def parse_file(self, path: str | Path) -> CIP4Element:
        """Parse a CIP4 document from a file path."""
        file_path = Path(path)
        try:
            tree = etree.parse(str(file_path), parser=_safe_parser(huge_tree=self._huge_tree))
        except etree.XMLSyntaxError as exc:
            raise XMLParsingError(f"Malformed CIP4 XML document at {file_path}: {exc}") from exc
        return self._dispatch(tree.getroot())

    def parse_stream(self, stream: BinaryIO) -> CIP4Element:
        """Parse a CIP4 document from an open binary stream."""
        try:
            tree = etree.parse(stream, parser=_safe_parser(huge_tree=self._huge_tree))
        except etree.XMLSyntaxError as exc:
            raise XMLParsingError(f"Malformed CIP4 XML document in stream: {exc}") from exc
        return self._dispatch(tree.getroot())

    @staticmethod
    def _dispatch(root: etree._Element) -> CIP4Element:
        namespace, local_tag = _split_qname(root.tag)
        model_cls = _ROOT_DISPATCH.get((namespace or "", local_tag))
        if model_cls is None:
            raise XMLParsingError(
                f"Unrecognized CIP4 root element <{local_tag}> in namespace {namespace!r}; "
                "expected JDF, JMF, or XJDF.",
                context={"tag": local_tag, "namespace": namespace},
            )
        return model_cls.from_xml_element(root)


def iter_parse_jdf_nodes(
    source: str | Path | BinaryIO, *, tag: str = "JDF"
) -> Iterator[JDFNode]:
    """Stream-parse a (potentially huge) JDF file, yielding one node per match.

    Uses ``lxml.etree.iterparse`` so memory usage stays bounded regardless
    of overall document size: each matched element is converted to a
    :class:`~pycip4.models.jdf.JDFNode` as soon as it closes, then
    immediately cleared (and its now-empty ancestors pruned) to release the
    underlying ``lxml`` nodes.

    Args:
        source: File path or open binary stream to read from.
        tag: Local element name to stream-match (default: every ``JDF``
            process node, including nested ones -- pass a more specific
            value, e.g. combined with post-filtering on ``node_type``, to
            narrow further).

    Yields:
        One :class:`~pycip4.models.jdf.JDFNode` per matched element, in
        document order. Note that because nested ``JDF`` nodes are matched
        too, a yielded node's own ``children`` still contain its (already
        fully parsed) descendants -- only elements that have *closed* are
        emitted, so no node is yielded before its subtree is complete.

    Raises:
        XMLParsingError: On malformed XML encountered mid-stream.
    """
    qualified_tag = f"{{{JDF_NAMESPACE}}}{tag}"
    context = etree.iterparse(
        source,
        events=("end",),
        tag=qualified_tag,
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        dtd_validation=False,
        huge_tree=True,
    )
    try:
        for _event, element in context:
            yield JDFNode.from_xml_element(element)
            # Free this element's subtree and any now-dangling siblings that
            # precede it, keeping peak memory bounded for very deep/wide trees.
            element.clear(keep_tail=True)
            parent = element.getparent()
            if parent is not None:
                while element.getprevious() is not None:
                    del parent[0]
    except etree.XMLSyntaxError as exc:
        raise XMLParsingError(f"Malformed XML encountered during streaming parse: {exc}") from exc
    finally:
        del context
