"""Abstract base classes for every CIP4 XML node (JDF, JMF, and XJDF alike).

Design notes:
    CIP4 documents are, structurally, just deeply nested XML elements with
    attribute bags and typed children. Rather than hand-writing a Pydantic
    model per resource (there are hundreds across the JDF spec), pycip4
    models the *generic* XML node shape once in :class:`CIP4Element` and
    layers strongly-typed, ergonomic accessors on top in the format-specific
    modules (:mod:`pycip4.models.jdf`, :mod:`pycip4.models.jmf`,
    :mod:`pycip4.models.xjdf`).

    :class:`CIP4Element` is intentionally ``lxml``-agnostic in its stored
    state (plain ``dict``/``list``/``str`` -- no live ``lxml`` references are
    held past the parse/serialize boundary) so instances are cheap to copy,
    hash-stable, and trivially (de)serializable via ``pydantic``.

    Extensibility (custom resources, dynamic intents, vendor namespaces) is
    handled by the :data:`NODE_REGISTRY`: format parsers consult it to decide
    which Python subclass should represent a given ``(namespace, tag)`` pair,
    falling back to :class:`CIP4Element` for anything unregistered. This
    keeps the core free of ``if tag == "...":`` ladders and lets consumers
    register proprietary vendor extensions without monkey-patching.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any, ClassVar, Self, cast
from uuid import uuid4

from lxml import etree
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from pycip4.core.exceptions import RegistryError, XMLParsingError
from pycip4.core.types import JDF_NAMESPACE, XSI_NAMESPACE

# --------------------------------------------------------------------------
# Extensibility registry
# --------------------------------------------------------------------------

#: Maps ``(namespace_uri, local_tag_name)`` -> the :class:`CIP4Element`
#: subclass that should represent elements of that shape. Populated via
#: :func:`register_node`. Consumers may register proprietary vendor
#: namespaces/tags without touching library internals.
NODE_REGISTRY: dict[tuple[str | None, str], type[CIP4Element]] = {}

#: Maps ``(namespace_uri, tag_suffix)`` -> the :class:`CIP4Element` subclass
#: that should represent any element whose tag *ends with* that suffix and
#: has no exact match in :data:`NODE_REGISTRY`. This covers CIP4's
#: naming-convention-based families -- most importantly every
#: ``{ResourceName}Link`` element (``MediaLink``, ``RunListLink``,
#: ``ColorantControlLink``, ...), which cannot be enumerated exhaustively
#: since custom/dynamic resources mint new link tags freely. Populated via
#: :func:`register_suffix_node`.
NODE_SUFFIX_REGISTRY: dict[tuple[str | None, str], type[CIP4Element]] = {}


def register_suffix_node(
    suffix: str, *, namespace: str | None = JDF_NAMESPACE
) -> Any:
    """Class decorator registering a fallback class for a tag *suffix*.

    Used for CIP4's naming-convention families where the set of concrete
    tags is open-ended (e.g. every resource type ``Foo`` has a
    corresponding ``FooLink`` element) rather than a fixed vocabulary.
    Exact :func:`register_node` matches always take priority over a suffix
    match in :func:`resolve_node_class`.

    Args:
        suffix: Tag suffix to match, e.g. ``"Link"``.
        namespace: Namespace URI the suffix is registered under.
    """

    def decorator(cls: type[CIP4Element]) -> type[CIP4Element]:
        NODE_SUFFIX_REGISTRY[(namespace, suffix)] = cls
        return cls

    return decorator


def register_node(
    tag: str, *, namespace: str | None = JDF_NAMESPACE
) -> Any:
    """Class decorator that registers a :class:`CIP4Element` subclass.

    Enables the parser (:mod:`pycip4.parser.xml_parser`) to materialize the
    correct strongly-typed Python class for a given XML element, including
    for custom resources, dynamic intents, or proprietary vendor extensions
    defined entirely outside of pycip4's core.

    Args:
        tag: The local (namespace-stripped) XML element name, e.g.
            ``"Media"`` or ``"MyVendor:CustomResource"``.
        namespace: The namespace URI the tag is registered under. Defaults
            to the standard JDF/JMF namespace.

    Returns:
        A decorator that registers and returns the class unchanged.

    Raises:
        RegistryError: If a different class is already registered for the
            same ``(namespace, tag)`` pair.

    Example:
        >>> @register_node("CustomResource", namespace="urn:example:vendor")
        ... class CustomResource(CIP4Element):
        ...     pass
    """

    def decorator(cls: type[CIP4Element]) -> type[CIP4Element]:
        key = (namespace, tag)
        existing = NODE_REGISTRY.get(key)
        if existing is not None and existing is not cls:
            raise RegistryError(
                f"Node tag {tag!r} in namespace {namespace!r} is already "
                f"registered to {existing.__name__}",
                context={"tag": tag, "namespace": namespace},
            )
        NODE_REGISTRY[key] = cls
        return cls

    return decorator


def resolve_node_class(tag: str, namespace: str | None) -> type[CIP4Element]:
    """Look up the best-matching registered class for an XML element.

    Resolution order: an exact ``(namespace, tag)`` match in
    :data:`NODE_REGISTRY`, then the longest matching suffix in
    :data:`NODE_SUFFIX_REGISTRY` (covering open-ended families like
    ``*Link``), finally falling back to :class:`CIP4Element` -- this is
    what allows unknown or future CIP4 elements, and arbitrary vendor
    extensions, to always parse successfully.
    """
    exact = NODE_REGISTRY.get((namespace, tag))
    if exact is not None:
        return exact

    best_match: type[CIP4Element] | None = None
    best_length = -1
    for (suffix_namespace, suffix), cls in NODE_SUFFIX_REGISTRY.items():
        if suffix_namespace == namespace and tag.endswith(suffix) and len(suffix) > best_length:
            best_match = cls
            best_length = len(suffix)
    return best_match or CIP4Element


def generate_id(prefix: str = "ID") -> str:
    """Generate a spec-compliant unique ID for JDF/JMF ``ID``-typed attributes.

    CIP4 IDs must be valid XML ``NMTOKEN``s; a hyphenated UUID is not legal
    (digits/hyphens cannot lead and colons are reserved), so this produces a
    letter-prefixed, hyphen-free token instead.
    """
    return f"{prefix}{uuid4().hex}"


class CIP4Element(BaseModel):
    """Generic, format-agnostic representation of one CIP4 XML element.

    This is the structural backbone for JDF, JMF, and XJDF nodes alike: an
    element is a tag name scoped to a namespace, an attribute bag, ordered
    child elements, and optional text content.

    Attributes:
        tag: Local (namespace-stripped) element name, e.g. ``"JDF"``.
        namespace: Namespace URI this element belongs to, or ``None``.
        attributes: Ordered mapping of attribute name -> string value.
            CIP4 attribute values are always serialized as strings in XML;
            typed accessors in subclasses convert to/from richer Python
            types (``int``, ``float``, ``datetime``, enums, ...).
        children: Ordered list of child elements.
        text: Direct text content of the element, if any (most CIP4
            elements are attribute-only and leave this ``None``).
    """

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        arbitrary_types_allowed=False,
    )

    #: Overridable in subclasses to pin the element to a fixed tag name.
    XML_TAG: ClassVar[str | None] = None
    #: Overridable in subclasses to pin the element to a fixed namespace.
    XML_NAMESPACE: ClassVar[str | None] = JDF_NAMESPACE

    tag: str
    namespace: str | None = JDF_NAMESPACE
    attributes: dict[str, str] = Field(default_factory=dict)
    children: list[CIP4Element] = Field(default_factory=list)
    text: str | None = None

    _source_line: int | None = PrivateAttr(default=None)

    # ---------------------------------------------------------------- #
    # Construction helpers
    # ---------------------------------------------------------------- #

    @classmethod
    def create(cls, tag: str | None = None, /, **attributes: str) -> Self:
        """Fluent constructor: ``Element.create("Media", Dimension="...")``.

        Args:
            tag: Element tag name. Required unless the subclass defines a
                fixed :attr:`XML_TAG`.
            **attributes: Initial attribute name/value pairs.

        Returns:
            A new, childless element instance.
        """
        resolved_tag = tag or cls.XML_TAG
        if resolved_tag is None:
            raise ValueError(f"{cls.__name__} requires an explicit tag")
        return cls(tag=resolved_tag, namespace=cls.XML_NAMESPACE, attributes=dict(attributes))

    # ---------------------------------------------------------------- #
    # Attribute access (fluent, chainable)
    # ---------------------------------------------------------------- #

    def get_attr(self, name: str, default: str | None = None) -> str | None:
        """Return the raw string value of an attribute, or ``default``."""
        return self.attributes.get(name, default)

    def set_attr(self, name: str, value: Any) -> Self:
        """Set an attribute, coercing ``value`` to its XML string form.

        Returns ``self`` to allow fluent chaining:
        ``node.set_attr("Status", "Waiting").set_attr("JobID", "123")``.
        """
        if value is None:
            self.attributes.pop(name, None)
        else:
            self.attributes[name] = value.value if hasattr(value, "value") else str(value)
        return self

    def __getitem__(self, name: str) -> str | None:
        return self.get_attr(name)

    def __setitem__(self, name: str, value: Any) -> None:
        self.set_attr(name, value)

    # ---------------------------------------------------------------- #
    # Child/tree navigation
    # ---------------------------------------------------------------- #

    def add_child(self, child: CIP4Element) -> Self:
        """Append a child element and return ``self`` for chaining."""
        self.children.append(child)
        return self

    def extend_children(self, children: Iterator[CIP4Element]) -> Self:
        """Append several children at once and return ``self`` for chaining."""
        self.children.extend(children)
        return self

    def find_children(self, tag: str) -> list[CIP4Element]:
        """Return all direct children whose tag matches ``tag``."""
        return [c for c in self.children if c.tag == tag]

    def find_first(self, tag: str) -> CIP4Element | None:
        """Return the first direct child whose tag matches ``tag``, if any."""
        for child in self.children:
            if child.tag == tag:
                return child
        return None

    def iter_descendants(self) -> Iterator[CIP4Element]:
        """Depth-first iterate over every descendant (not including ``self``)."""
        for child in self.children:
            yield child
            yield from child.iter_descendants()

    def find_descendants(self, tag: str) -> list[CIP4Element]:
        """Return every descendant (at any depth) whose tag matches ``tag``."""
        return [node for node in self.iter_descendants() if node.tag == tag]

    # ---------------------------------------------------------------- #
    # XML (de)serialization
    # ---------------------------------------------------------------- #

    def to_xml_element(self) -> etree._Element:
        """Serialize this node (and its subtree) into an ``lxml`` element.

        Returns:
            A freshly constructed ``lxml.etree._Element``, fully detached
            from any source document.
        """
        qname = f"{{{self.namespace}}}{self.tag}" if self.namespace else self.tag
        nsmap = {None: self.namespace, "xsi": XSI_NAMESPACE} if self.namespace else None
        # lxml-stubs under-types `nsmap` as Mapping[str, str]; a `None` key
        # (the default-namespace binding) is valid and required at runtime.
        element = etree.Element(qname, nsmap=cast("Mapping[str, str] | None", nsmap))
        for name, value in self.attributes.items():
            element.set(name, value)
        if self.text is not None:
            element.text = self.text
        for child in self.children:
            element.append(child.to_xml_element())
        return element

    def to_xml_bytes(self, *, pretty_print: bool = True, xml_declaration: bool = True) -> bytes:
        """Serialize to a complete, encoded XML document.

        Args:
            pretty_print: Indent output for human readability.
            xml_declaration: Prepend an ``<?xml version="1.0" ...?>`` header.

        Returns:
            UTF-8 encoded XML bytes.
        """
        element = self.to_xml_element()
        top_nsmap = {None: self.namespace, "xsi": XSI_NAMESPACE} if self.namespace else None
        etree.cleanup_namespaces(
            element,
            top_nsmap=cast("Mapping[str, str] | None", top_nsmap),
            keep_ns_prefixes=["xsi"],
        )
        return etree.tostring(
            element,
            pretty_print=pretty_print,
            xml_declaration=xml_declaration,
            encoding="UTF-8",
        )

    def to_xml_string(self, *, pretty_print: bool = True) -> str:
        """Serialize to an XML string (no XML declaration, UTF-8 decoded)."""
        return self.to_xml_bytes(pretty_print=pretty_print, xml_declaration=False).decode("utf-8")

    @classmethod
    def from_xml_element(cls, element: etree._Element) -> Self:
        """Build a (subclass-dispatched) node tree from a parsed ``lxml`` element.

        Child elements are recursively materialized through
        :func:`resolve_node_class`, so registered specialized subclasses
        (e.g. a strongly-typed ``Media`` resource) are produced automatically
        wherever they appear in the tree, with unregistered elements falling
        back to plain :class:`CIP4Element` instances.

        Args:
            element: A parsed ``lxml`` element (comments/PIs are skipped).

        Returns:
            A new node instance of ``cls`` (or, if ``cls`` is a fixed-tag
            subclass that does not match ``element``, of the resolved
            registry class -- callers that need exact-type dispatch should
            prefer calling this on :class:`CIP4Element` itself or via
            :mod:`pycip4.parser.xml_parser`).

        Raises:
            XMLParsingError: If ``element`` is not a well-formed element node.
        """
        if not isinstance(element.tag, str):
            raise XMLParsingError(
                "Cannot build a CIP4Element from a non-element XML node "
                "(comment or processing instruction)",
            )

        raw_namespace, _, local_tag = element.tag.rpartition("}")
        namespace: str | None = raw_namespace.lstrip("{") or None

        target_cls = cls if cls is not CIP4Element else resolve_node_class(local_tag, namespace)

        children = [
            CIP4Element.from_xml_element(child)
            for child in element
            if isinstance(child.tag, str)
        ]
        text = element.text.strip() if element.text and element.text.strip() else None

        instance = target_cls(
            tag=local_tag,
            namespace=namespace,
            attributes={str(k): str(v) for k, v in element.attrib.items()},
            children=children,
            text=text,
        )
        # lxml-stubs mistypes `sourceline` as a bare `...` assignment rather
        # than `int | None`, so an explicit cast is needed here.
        instance._source_line = cast("int | None", element.sourceline)
        # target_cls is a (possibly more specific, registry-resolved) subclass
        # of CIP4Element, not necessarily `cls`/`Self` as far as the type
        # checker can tell from a runtime-computed class.
        return cast(Self, instance)

    @classmethod
    def from_xml_string(cls, xml: str | bytes) -> Self:
        """Parse an XML string/bytes directly into a node tree.

        Raises:
            XMLParsingError: On malformed XML.
        """
        try:
            parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
            root = etree.fromstring(
                xml.encode("utf-8") if isinstance(xml, str) else xml, parser=parser
            )
        except etree.XMLSyntaxError as exc:
            raise XMLParsingError(f"Malformed XML: {exc}") from exc
        return cls.from_xml_element(root)

    # ---------------------------------------------------------------- #
    # XPath convenience
    # ---------------------------------------------------------------- #

    def xpath(self, expression: str, **extra_namespaces: str) -> list[Any]:
        """Run an XPath query against this node's serialized XML form.

        The default prefix ``jdf`` is bound to this node's namespace (if
        any) so queries can be written as ``node.xpath("//jdf:Media")``
        without the caller needing to know the raw namespace URI.

        Args:
            expression: XPath 1.0 expression (``lxml`` engine).
            **extra_namespaces: Additional prefix=uri bindings.

        Returns:
            The raw ``lxml`` XPath result (list of elements, strings, or
            numbers depending on the expression).
        """
        element = self.to_xml_element()
        namespaces = {"jdf": self.namespace} if self.namespace else {}
        namespaces.update(extra_namespaces)
        return cast(list[Any], element.xpath(expression, namespaces=namespaces))

    # ---------------------------------------------------------------- #
    # Misc dunder ergonomics
    # ---------------------------------------------------------------- #

    def __repr__(self) -> str:
        attrs_preview = ", ".join(f"{k}={v!r}" for k, v in list(self.attributes.items())[:3])
        return f"{self.__class__.__name__}(tag={self.tag!r}, {attrs_preview})"


CIP4Element.model_rebuild()


class CIP4Node(CIP4Element):
    """Marker base class for *document-root-capable* CIP4 nodes.

    Format-specific root types (``JDFNode``, ``JMFMessage``, ``XJDFNode``)
    subclass this rather than :class:`CIP4Element` directly, so type checkers
    and the parser's top-level dispatch (:mod:`pycip4.parser.xml_parser`) can
    distinguish "a thing that can be the root of a document" from "a generic
    attribute-bag element nested somewhere inside one".
    """
