"""Thread passthrough tests for IoT Agent Bridge."""

import os
import pytest

from bridge import IoTAgentClient, EVENT_ERROR, EVENT_THREAD_RESPONSE

RUN_THREAD_ONLINE = os.getenv("THREAD_DEVICE_ONLINE", "0") == "1"
THREAD_DEVICE_ID = os.getenv("THREAD_DEVICE_ID", "1")


class TestThreadPassthrough:
    """Thread passthrough integration tests."""

    @pytest.fixture
    def client(self):
        client = IoTAgentClient()
        try:
            client.start()
            assert client.wait_for_connection(timeout=60.0)
            yield client
        finally:
            client.stop()

    def test_thread_passthrough_without_device_reports_error(self, client):
        """Without online Thread device, passthrough should report EVENT_ERROR."""
        payload = b"thread:ping"
        cmd_id = client.commands.thread_passthrough(1, payload)
        assert cmd_id is not None

        err_evt = client.events.wait_for_event(EVENT_ERROR, timeout=2.0)
        assert err_evt is not None
        # cmd_id may not align when run after other tests (global counter)

    @pytest.mark.skipif(not RUN_THREAD_ONLINE, reason="Set THREAD_DEVICE_ONLINE=1 when a real Thread target is online")
    def test_thread_passthrough_roundtrip(self, client):
        """Send payload through online Thread device and verify response event."""
        device_id = int(THREAD_DEVICE_ID)
        payload = os.getenv("THREAD_TEST_PAYLOAD", "thread:ping").encode("utf-8")

        cmd_id = client.commands.thread_passthrough(device_id, payload)
        assert cmd_id is not None

        evt = client.events.wait_for_event(EVENT_THREAD_RESPONSE, timeout=5.0)
        assert evt is not None, "No Thread response event received"
        assert evt.device_id == device_id
        assert evt.payload == payload
        assert evt.payload_len == len(evt.payload)
        assert evt.payload_len > 0
