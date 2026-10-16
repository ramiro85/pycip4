"""Unit tests for the fluent JDF builder API and the underlying JDF model."""

from __future__ import annotations

import pytest

from pycip4.builder.jdf_builder import JDFBuilder
from pycip4.core.exceptions import BuilderError, JDFValidationError
from pycip4.core.types import JDFStatus, ResourceUsage
from pycip4.models.jdf import JDFNode, Media, ResourceLink, ResourcePool, RunList


class TestJDFBuilderBasics:
    """Tests for root creation and single-process ticket assembly."""

    def test_product_creates_root_with_expected_attributes(self) -> None:
        jdf = JDFBuilder().product(job_id="Job-42", descriptive_name="Brochure").build()

        assert isinstance(jdf, JDFNode)
        assert jdf.job_id == "Job-42"
        assert jdf.node_type == "Product"
        assert jdf.get_attr("DescriptiveName") == "Brochure"
        assert jdf.status == JDFStatus.WAITING

    def test_build_without_product_raises(self) -> None:
        with pytest.raises(BuilderError):
            JDFBuilder().build()

    def test_job_id_auto_generated_when_omitted(self) -> None:
        jdf = JDFBuilder().product().build()
        assert jdf.job_id is not None
        assert jdf.job_part_id is not None

    def test_digital_printing_process_creates_child_node(self) -> None:
        jdf = JDFBuilder().product(job_id="J1").digital_printing_process().done().build()

        children = jdf.child_nodes()
        assert len(children) == 1
        assert children[0].node_type == "DigitalPrinting"
        assert jdf.find_by_type("DigitalPrinting") is not None


class TestResourceAttachment:
    """Tests for resource pool / resource link pool wiring via the builder."""

    def test_with_media_adds_resource_and_link(self) -> None:
        jdf = (
            JDFBuilder()
            .product(job_id="J1")
            .digital_printing_process()
            .with_media(dimension="210 297", media_type="Paper", weight=90)
            .done()
            .build()
        )
        process = jdf.find_by_type("DigitalPrinting")
        assert process is not None

        pool = process.resource_pool
        assert isinstance(pool, ResourcePool)
        media_resources = [r for r in pool.resources() if r.tag == "Media"]
        assert len(media_resources) == 1
        media = media_resources[0]
        assert media.get_attr("Dimension") == "210 297"
        assert media.get_attr("MediaType") == "Paper"
        assert media.get_attr("Weight") == "90"
        assert media.resource_id is not None

        link_pool = process.resource_link_pool
        assert link_pool is not None
        links = link_pool.links()
        assert len(links) == 1
        assert links[0].tag == "MediaLink"
        assert links[0].usage == ResourceUsage.INPUT
        assert links[0].r_ref == media.resource_id

    def test_with_run_list_sets_url(self) -> None:
        jdf = (
            JDFBuilder()
            .product(job_id="J1")
            .digital_printing_process()
            .with_run_list(url="content.pdf")
            .done()
            .build()
        )
        process = jdf.find_by_type("DigitalPrinting")
        assert process is not None and process.resource_pool is not None
        run_lists = [r for r in process.resource_pool.resources() if r.tag == "RunList"]
        assert run_lists[0].get_attr("URL") == "content.pdf"

    def test_with_component_defaults_to_output_usage(self) -> None:
        jdf = (
            JDFBuilder()
            .product(job_id="J1")
            .digital_printing_process()
            .with_component(ComponentType="Sheet")
            .done()
            .build()
        )
        process = jdf.find_by_type("DigitalPrinting")
        assert process is not None and process.resource_link_pool is not None
        link = process.resource_link_pool.links()[0]
        assert link.tag == "ComponentLink"
        assert link.usage == ResourceUsage.OUTPUT

    def test_full_ticket_has_no_unresolved_links(self) -> None:
        jdf = (
            JDFBuilder()
            .product(job_id="Job-42", descriptive_name="Brochure run")
            .digital_printing_process()
            .with_media(dimension="210 297", media_type="Paper", weight=90)
            .with_run_list(url="run.pdf")
            .with_component(usage=ResourceUsage.OUTPUT, ComponentType="Sheet")
            .done()
            .build()
        )
        assert jdf.validate_links() == []


class TestMultiProcessAssembly:
    """Tests for multi-stage process trees (RIP -> Imposition -> DigitalPrinting)."""

    def test_sub_process_nests_under_parent(self) -> None:
        builder = JDFBuilder().product(job_id="J1")
        rip = builder.rip_process()
        imposition = rip.sub_process("Imposition")
        imposition.sub_process("DigitalPrinting")
        jdf = builder.build()

        rip_node = jdf.find_by_type("RIP")
        assert rip_node is not None
        imposition_node = rip_node.child_nodes()[0]
        assert imposition_node.node_type == "Imposition"
        digital_node = imposition_node.child_nodes()[0]
        assert digital_node.node_type == "DigitalPrinting"

    def test_multiple_top_level_processes(self) -> None:
        builder = JDFBuilder().product(job_id="J1")
        builder.rip_process().done()
        builder.cutting_process().done()
        jdf = builder.build()

        types = [child.node_type for child in jdf.child_nodes()]
        assert types == ["RIP", "Cutting"]


class TestResourceLinking:
    """Tests for lower-level JDFNode resource linking semantics and validation."""

    def test_link_resource_without_id_raises(self) -> None:
        node = JDFNode.create_root(job_id="J1")
        media = Media.create("Media")  # no ID set
        with pytest.raises(JDFValidationError):
            node.link_resource(media, ResourceUsage.INPUT)

    def test_add_resource_auto_assigns_id(self) -> None:
        node = JDFNode.create_root(job_id="J1")
        media = Media.create("Media")
        node.add_resource(media)
        assert media.resource_id is not None

    def test_find_resource_by_id_searches_descendants(self) -> None:
        root = JDFNode.create_root(job_id="J1", node_type="Product")
        child = JDFNode.create("JDF", Type="DigitalPrinting")
        root.add_child_node(child)
        media = Media.create("Media")
        child.add_resource(media)
        assert media.resource_id is not None

        found = root.find_resource_by_id(media.resource_id)
        assert found is media

    def test_validate_links_detects_dangling_rref(self) -> None:
        node = JDFNode.create_root(job_id="J1")
        node.ensure_resource_link_pool().add_child(
            ResourceLink.create("MediaLink", rRef="does-not-exist", Usage="Input")
        )
        problems = node.validate_links()
        assert len(problems) == 1
        assert "does-not-exist" in problems[0]

    def test_resolve_link_returns_resource_in_same_pool(self) -> None:
        node = JDFNode.create_root(job_id="J1")
        run_list = RunList.create("RunList")
        node.add_and_link_resource(run_list, ResourceUsage.INPUT)
        assert node.resource_link_pool is not None
        link = node.resource_link_pool.links()[0]
        assert node.resolve_link(link) is run_list


class TestSerializationRoundTrip:
    """Tests that a built JDF document round-trips through XML correctly."""

    def test_round_trip_preserves_structure(self) -> None:
        jdf = (
            JDFBuilder()
            .product(job_id="Job-99")
            .digital_printing_process()
            .with_media(dimension="210 297")
            .done()
            .build()
        )
        xml_bytes = jdf.to_xml_bytes()

        reparsed = JDFNode.from_xml_string(xml_bytes)
        assert reparsed.job_id == "Job-99"
        assert reparsed.find_by_type("DigitalPrinting") is not None
        assert reparsed.validate_links() == []

    def test_serialized_document_uses_jdf_namespace(self) -> None:
        jdf = JDFBuilder().product(job_id="J1").build()
        xml = jdf.to_xml_string()
        assert 'xmlns="http://www.CIP4.org/JDFSchema_1_1"' in xml
