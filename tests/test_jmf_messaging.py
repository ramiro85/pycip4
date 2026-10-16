"""Async tests for the JMF client/server messaging stack, plus JMF model
and MIME packaging coverage.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from aiohttp import web
from aiohttp.test_utils import TestServer

from pycip4.core.exceptions import JMFAckError, JMFMessageError, TransportError
from pycip4.core.types import JMFAcknowledgeCode
from pycip4.messaging.jmf_client import JMFClient
from pycip4.messaging.jmf_server import (
    JMFServer,
    known_devices_handler_factory,
    status_handler_factory,
)
from pycip4.models.jmf import (
    JMFAcknowledge,
    JMFEnvelope,
    JMFMessage,
    JMFResponse,
    build_acknowledge,
    build_command,
    build_query,
    build_response,
)

# -------------------------------------------------------------------------- #
# JMF model unit tests (no network)
# -------------------------------------------------------------------------- #


class TestJMFModels:
    def test_build_query_sets_type_and_id(self) -> None:
        query = build_query("KnownDevices")
        assert query.message_type == "KnownDevices"
        assert query.message_id is not None
        assert query.family.value == "Query"

    def test_envelope_wrap_and_unwrap(self) -> None:
        query = build_query("Status", DeviceID="Press-01")
        envelope = JMFEnvelope.wrap(query, sender_id="client-1")
        assert envelope.get_attr("SenderID") == "client-1"
        assert envelope.message is query
        assert envelope.require_message().get_attr("DeviceID") == "Press-01"

    def test_require_message_raises_on_empty_body(self) -> None:
        envelope = JMFEnvelope.create("JMF", Version="1.3")
        with pytest.raises(JMFMessageError):
            envelope.require_message()

    def test_build_response_copies_type_and_refid(self) -> None:
        query = build_query("KnownDevices")
        response = build_response(query, DeviceID="Press-01")
        assert response.message_type == "KnownDevices"
        assert response.get_attr("refID") == query.message_id
        assert response.return_code == 0

    def test_build_acknowledge_default_success(self) -> None:
        command = build_command("SubmitQueueEntry")
        ack = build_acknowledge(command)
        assert ack.return_code == JMFAcknowledgeCode.OK.value
        ack.raise_for_status()  # should not raise

    def test_acknowledge_raise_for_status_on_failure(self) -> None:
        command = build_command("SubmitQueueEntry")
        ack = build_acknowledge(command, return_code=101, text="Permission denied")
        with pytest.raises(JMFAckError) as exc_info:
            ack.raise_for_status()
        assert exc_info.value.return_code == 101
        assert exc_info.value.ack_text == "Permission denied"

    def test_round_trip_dispatches_to_query_subclass(self) -> None:
        envelope = JMFEnvelope.wrap(build_query("KnownDevices"))
        reparsed = JMFEnvelope.from_xml_string(envelope.to_xml_bytes())
        message = reparsed.require_message()
        assert message.message_type == "KnownDevices"
        assert type(message).__name__ == "JMFQuery"


# -------------------------------------------------------------------------- #
# Async server + client integration tests
# -------------------------------------------------------------------------- #


@pytest.fixture
def jmf_server() -> JMFServer:
    server = JMFServer(device_id="Press-01")
    server.on_query("KnownDevices")(
        known_devices_handler_factory("Press-01", "Idle", "DigitalPrinting")
    )
    server.on_query("Status")(status_handler_factory(lambda: {"DeviceStatus": "Running"}))

    @server.on_command("SubmitQueueEntry")
    async def submit_queue_entry(message: JMFMessage, request: web.Request) -> dict[str, str]:
        return {"QueueEntryID": "QE-001"}

    @server.on_command("Fail")
    async def always_fail(message: JMFMessage, request: web.Request) -> None:
        raise RuntimeError("boom")

    return server


@pytest_asyncio.fixture
async def running_server(jmf_server: JMFServer) -> AsyncIterator[str]:
    test_server = TestServer(jmf_server.app)
    await test_server.start_server()
    try:
        yield str(test_server.make_url("/jmf"))
    finally:
        await test_server.close()


@pytest_asyncio.fixture
async def jmf_client(running_server: str) -> AsyncIterator[JMFClient]:
    async with httpx.AsyncClient() as http:
        client = JMFClient(running_server, sender_id="test-client", http_client=http)
        yield client


class TestJMFServerClient:
    @pytest.mark.asyncio
    async def test_known_devices_query_returns_device_info(self, jmf_client: JMFClient) -> None:
        response = await jmf_client.query("KnownDevices")
        assert isinstance(response, JMFResponse)
        assert response.get_attr("DeviceID") == "Press-01"
        assert response.get_attr("DeviceStatus") == "Idle"

    @pytest.mark.asyncio
    async def test_status_query_uses_dynamic_provider(self, jmf_client: JMFClient) -> None:
        response = await jmf_client.query("Status")
        assert response.get_attr("DeviceStatus") == "Running"

    @pytest.mark.asyncio
    async def test_command_returns_acknowledge_with_payload(self, jmf_client: JMFClient) -> None:
        ack = await jmf_client.command("SubmitQueueEntry")
        assert isinstance(ack, JMFAcknowledge)
        assert ack.return_code == 0
        assert ack.get_attr("QueueEntryID") == "QE-001"

    @pytest.mark.asyncio
    async def test_unregistered_query_type_raises_ack_error(self, jmf_client: JMFClient) -> None:
        with pytest.raises(JMFAckError) as exc_info:
            await jmf_client.query("TotallyUnknownType")
        assert exc_info.value.return_code == JMFAcknowledgeCode.UNKNOWN_MESSAGE_TYPE.value

    @pytest.mark.asyncio
    async def test_handler_exception_is_caught_and_acknowledged_as_error(
        self, jmf_client: JMFClient
    ) -> None:
        ack = await jmf_client.command("Fail")
        assert ack.return_code == JMFAcknowledgeCode.GENERAL_ERROR.value

    @pytest.mark.asyncio
    async def test_signal_is_acknowledged(self, jmf_client: JMFClient) -> None:
        ack = await jmf_client.signal("Notification", Text="hello")
        assert ack.return_code == 0

    @pytest.mark.asyncio
    async def test_malformed_request_body_still_gets_jmf_response(
        self, running_server: str
    ) -> None:
        async with httpx.AsyncClient() as http:
            raw_response = await http.post(
                running_server,
                content=b"<NotValidJMF this is broken",
                headers={"Content-Type": "application/vnd.cip4-jmf+xml"},
            )
        assert raw_response.status_code == 200
        envelope = JMFEnvelope.from_xml_string(raw_response.content)
        message = envelope.require_message()
        assert message.tag == "Acknowledge"
        return_code = message.get_attr("ReturnCode")
        assert return_code is not None
        assert int(return_code) == JMFAcknowledgeCode.FORMAT_ERROR.value

    @pytest.mark.asyncio
    async def test_client_raises_transport_error_on_unreachable_endpoint(self) -> None:
        async with httpx.AsyncClient() as http:
            client = JMFClient("http://127.0.0.1:1/jmf", http_client=http, timeout=1.0)
            with pytest.raises(TransportError):
                await client.query("KnownDevices")


# -------------------------------------------------------------------------- #
# MIME multipart packaging tests
# -------------------------------------------------------------------------- #


class TestMimePackaging:
    def test_build_and_parse_round_trip(self) -> None:
        from pycip4.builder.jdf_builder import JDFBuilder
        from pycip4.utils.mime import build_mime_package, parse_mime_package

        jmf = JMFEnvelope.wrap(build_command("SubmitQueueEntry"))
        jdf = (
            JDFBuilder()
            .product(job_id="J1")
            .digital_printing_process()
            .with_media(dimension="210 297")
            .done()
            .build()
        )

        package = build_mime_package(
            jmf,
            jdf_parts=[jdf],
            binary_parts={"font1": (b"FAKEFONTDATA", "application/octet-stream")},
        )
        parts = parse_mime_package(package)

        content_types = {p.content_type for p in parts}
        assert "application/vnd.cip4-jmf+xml" in content_types
        assert "application/vnd.cip4-jdf+xml" in content_types
        assert "application/octet-stream" in content_types

        jmf_part = next(p for p in parts if p.content_type == "application/vnd.cip4-jmf+xml")
        model = jmf_part.as_model()
        assert isinstance(model, JMFEnvelope)
        assert model.require_message().message_type == "SubmitQueueEntry"

        binary_part = next(p for p in parts if p.content_type == "application/octet-stream")
        assert binary_part.payload == b"FAKEFONTDATA"
        assert binary_part.content_id == "font1"

    def test_as_model_rejects_non_xml_part(self) -> None:
        from pycip4.utils.mime import MIMEPackagingError, MIMEPart

        part = MIMEPart(content_type="application/octet-stream", content_id="x", payload=b"binary")
        with pytest.raises(MIMEPackagingError):
            part.as_model()
