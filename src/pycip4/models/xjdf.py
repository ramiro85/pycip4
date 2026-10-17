"""XJDF (Exchange JDF 2.0+) flat document model.

XJDF deliberately abandons JDF's nested process-tree shape in favor of a
flat ``Product``/``Set``/``Parameter``/``Resource`` model:

* A single ``XJDF`` root carries one or more ``Product`` declarations
  (the "what to make") plus flat ``ResourceSet``/``Resource``/``Set``
  elements (the "what to make it with/from") -- there is no recursive
  process tree and no ``ResourceLinkPool`` indirection.
* ``Parameter`` resources (e.g. ``DigitalPrintingParams``) replace JDF's
  process-specific intent resources with simplified, usage-scoped sets.

Per the task's architectural requirement, this module is kept entirely
separate from :mod:`pycip4.models.jdf` -- the two formats share only the
generic :class:`~pycip4.models.base.CIP4Element` plumbing, not domain
accessors, since conflating "tree node" and "flat product" semantics is
exactly the mistake CIP4 designed XJDF to avoid.
"""

from __future__ import annotations

from typing import Self

from pycip4.core.types import XJDF_NAMESPACE
from pycip4.models.base import CIP4Element, CIP4Node, generate_id, register_node


class XJDFElement(CIP4Element):
    """Base for all XJDF elements; pins the namespace to XJDF 2.x."""

    XML_NAMESPACE = XJDF_NAMESPACE
    namespace: str | None = XJDF_NAMESPACE


@register_node("Product", namespace=XJDF_NAMESPACE)
class Product(XJDFElement):
    """An XJDF ``Product``: one deliverable item of the job (flat, no
    process-tree nesting -- a job with N distinct end products simply
    declares N ``Product`` elements).
    """

    XML_TAG = "Product"

    @property
    def product_id(self) -> str | None:
        return self.get_attr("ID")

    @property
    def amount(self) -> float | None:
        raw = self.get_attr("Amount")
        return float(raw) if raw is not None else None


@register_node("Resource", namespace=XJDF_NAMESPACE)
class XJDFResource(XJDFElement):
    """A flat XJDF resource (e.g. ``Media``, ``RunList``) -- note that unlike
    JDF, the *element tag itself* in XJDF is typically the resource name
    (``<Media .../>``) nested under a typed ``ResourceSet``, not a generic
    ``<Resource>`` tag; this class exists for resources that genuinely use
    the generic form and as the common base for resource-set members.
    """


@register_node("ResourceSet", namespace=XJDF_NAMESPACE)
class ResourceSet(XJDFElement):
    """Groups one resource's ``Input``/``Output`` usage occurrences.

    Attributes:
        Name: The resource type name (e.g. ``"Media"``, ``"RunList"``).
        Usage: ``"Input"`` or ``"Output"``, shared by all contained
            resource occurrences (XJDF collapses JDF's per-link ``Usage``
            into one usage per set).
    """

    XML_TAG = "ResourceSet"

    @property
    def name(self) -> str | None:
        return self.get_attr("Name")

    @property
    def usage(self) -> str | None:
        return self.get_attr("Usage")

    def add_resource(self, tag: str, **attributes: str) -> Self:
        """Add a concrete resource occurrence element to this set."""
        element = XJDFElement.create(tag, **attributes)
        self.add_child(element)
        return self


@register_node("Parameter", namespace=XJDF_NAMESPACE)
class Parameter(XJDFElement):
    """A flat XJDF ``Parameter`` resource (process configuration, replacing
    JDF's per-process intent resources).
    """

    XML_TAG = "Parameter"


@register_node("Set", namespace=XJDF_NAMESPACE)
class Set(XJDFElement):
    """An XJDF ``Set``: groups ``Parameter``/``ResourceSet`` elements under
    a named process usage (e.g. the ``DigitalPrinting`` set).
    """

    XML_TAG = "Set"

    @property
    def set_type(self) -> str | None:
        return self.get_attr("Type")


@register_node("XJDF", namespace=XJDF_NAMESPACE)
class XJDFNode(CIP4Node):
    """The root ``XJDF`` element: flat container for ``Product``,
    ``ResourceSet``, ``Set``, and ``Parameter`` declarations.
    """

    XML_TAG = "XJDF"
    XML_NAMESPACE = XJDF_NAMESPACE
    namespace: str | None = XJDF_NAMESPACE

    @classmethod
    def create_root(
        cls,
        *,
        job_id: str | None = None,
        job_part_id: str | None = None,
        node_type: str = "Product",
        version: str = "2.1",
    ) -> Self:
        """Create a new root ``XJDF`` element with mandatory root attributes."""
        return cls.create(
            "XJDF",
            JobID=job_id or generate_id("Job"),
            JobPartID=job_part_id or generate_id("JP"),
            Types=node_type,
            Version=version,
        )

    @property
    def job_id(self) -> str | None:
        return self.get_attr("JobID")

    @property
    def types(self) -> list[str]:
        raw = self.get_attr("Types")
        return raw.split() if raw else []

    def products(self) -> list[Product]:
        """Return every ``Product`` declared directly under this root."""
        return [c for c in self.children if isinstance(c, Product)]

    def add_product(self, product: Product) -> Self:
        if product.product_id is None:
            product.set_attr("ID", generate_id("P"))
        self.add_child(product)
        return self

    def resource_sets(self) -> list[ResourceSet]:
        return [c for c in self.children if isinstance(c, ResourceSet)]

    def add_resource_set(self, resource_set: ResourceSet) -> Self:
        self.add_child(resource_set)
        return self

    def sets(self) -> list[Set]:
        return [c for c in self.children if isinstance(c, Set)]

    def add_set(self, set_: Set) -> Self:
        self.add_child(set_)
        return self
