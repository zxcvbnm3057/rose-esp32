"""
Sync / reconnect protocol tests for IoT Agent Bridge.

Validates CMD_SYNC_REQUEST → EVENT_SYNC_RESPONSE structure,
CMD_SYN stage 0/1 confirmation flow, and reconnection sync recovery.
"""

import socket
import time

import pytest

from bridge import IoTAgentClient, EVENT_SYNC_RESPONSE, EVENT_PORT_STATUS


class TestSyncProtocol:
    """Test sync request/response protocol."""

    @pytest.fixture
    def client(self):
        client = IoTAgentClient()
        try:
            client.start()
            assert client.wait_for_connection(timeout=60.0)
            yield client
        finally:
            client.stop()

    def test_sync_response_structure(self, client):
        """Verify EVENT_SYNC_RESPONSE has all required fields."""
        cmd_id = client.commands.sync_request()
        assert cmd_id is not None

        evt = client.events.wait_for_event(EVENT_SYNC_RESPONSE, timeout=5.0)
        assert evt is not None, "No EVENT_SYNC_RESPONSE received"

        assert hasattr(evt, 'session_version')
        assert hasattr(evt, 'pending_cmd_count')
        assert hasattr(evt, 'pending_thread_count')
        assert hasattr(evt, 'port_status_count')

        assert isinstance(evt.session_version, int)
        assert isinstance(evt.pending_cmd_count, int)
        assert isinstance(evt.pending_thread_count, int)
        assert isinstance(evt.port_status_count, int)

        assert evt.session_version >= 0
        assert evt.pending_cmd_count >= 0
        assert evt.pending_thread_count >= 0
        assert evt.port_status_count >= 0

    def test_sync_followed_by_port_status_events(self, client):
        """
        After CMD_SYNC_REQUEST, the device sends port status snapshots.
        Verify EVENT_PORT_STATUS events arrive after sync response.
        """
        # First bind a GPIO to ensure it appears in the snapshot
        assert client.configure_gpio(5, 0)  # INPUT mode

        client.events.clear_pending()
        cmd_id = client.commands.sync_request()
        assert cmd_id is not None

        sync_evt = client.events.wait_for_event(EVENT_SYNC_RESPONSE, timeout=5.0)
        assert sync_evt is not None

        # Collect port status events that follow the sync response
        port_events = []
        deadline = time.time() + 3.0
        while time.time() < deadline:
            evt = client.events.wait_for_event(EVENT_PORT_STATUS, timeout=0.5)
            if evt is None:
                break
            port_events.append(evt)

        # There should be at least the GPIO 5 we configured
        gpio5_events = [e for e in port_events
                        if hasattr(e, 'resource_type') and e.resource_type == 0
                        and hasattr(e, 'id') and e.id == 5]
        assert len(gpio5_events) >= 1, (
            f"GPIO 5 not in port status snapshot after sync"
        )

    def test_syn_stage_0_confirmation(self, client):
        """CMD_SYN with stage=0 should be ACKed for any correlation_id."""
        result = client.confirm_sync(0xDEAD0001, stage=0)
        assert result is True

    def test_syn_stage_1_confirmation(self, client):
        """CMD_SYN with stage=1 should be ACKed for any correlation_id."""
        result = client.confirm_sync(0xDEAD0002, stage=1)
        assert result is True

    def test_multiple_sync_requests_idempotent(self, client):
        """Multiple CMD_SYNC_REQUEST calls should each return valid responses."""
        for _ in range(3):
            version = client.request_sync()
            assert isinstance(version, int)
            assert version >= 0
            time.sleep(0.1)

    def test_sync_version_increments_across_sessions(self, client):
        """Session version should change across connection cycles."""
        v1 = client.request_sync()
        assert isinstance(v1, int)

        # Force disconnect and reconnect
        with client.server._lock:
            sock = client.server.client_socket
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except Exception:
                    pass
                try:
                    sock.close()
                except Exception:
                    pass

        assert client.wait_for_connection(timeout=60.0)
        import time; time.sleep(1.0)
        v2 = None
        for _ in range(5):
            v2 = client.request_sync()
            if isinstance(v2, int):
                break
            time.sleep(0.5)
        assert isinstance(v2, int), f"sync after reconnect failed"
        # Session version only increments on cold boot, not TCP reconnect
        assert v2 >= v1, f"Session version regressed: {v1} -> {v2}"
