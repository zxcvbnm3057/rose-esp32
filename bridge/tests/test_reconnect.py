"""
Reconnect / sync-recovery integration tests.
"""

import socket
import threading
import time

import pytest

from ..src import IoTAgentClient


@pytest.fixture
def client() -> IoTAgentClient:
    client = IoTAgentClient(host='0.0.0.0', port=8080)
    client.start()
    try:
        if not client.wait_for_connection(timeout=60.0):
            pytest.skip('No ESP32 IoT Agent connected to real bridge on 0.0.0.0:8080')
        yield client
    finally:
        client.stop()


def test_real_device_sync_request_returns_session_version(client: IoTAgentClient) -> None:
    session_version = client.request_sync()
    assert isinstance(session_version, int)
    assert session_version >= 0


def test_real_device_reconnect_recovers_sync_state(client: IoTAgentClient) -> None:
    first_version = client.request_sync()
    assert isinstance(first_version, int)

    if client.server.client_socket is not None:
        try:
            client.server.client_socket.close()
        except Exception:
            pass

    start = time.time()
    was_disconnected = False
    while time.time() - start < 30.0:
        if not client.server.is_connected():
            was_disconnected = True
            break
        time.sleep(0.05)
    assert was_disconnected, "server never reported disconnected after socket close"
    assert client.wait_for_connection(timeout=60.0)

    second_version = client.request_sync()
    assert isinstance(second_version, int)


def test_real_device_sync_request_after_connection_drop_returns_none_and_recovers(client: IoTAgentClient) -> None:
    """request_sync during a connection drop must not hang, and recovery must work."""

    def force_disconnect() -> None:
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

    # Tear down the socket *before* the request so that send_command fails.
    force_disconnect()

    # The ESP32 may reconnect in the background; the important thing is
    # that request_sync does not hang and returns in a timely fashion.
    result = client.request_sync()
    # Outcome depends on timing: None if the socket was still closed,
    # or an int if the firmware re-sent a queued response after reconnect.
    assert result is None or isinstance(result, int), f"unexpected result: {result!r}"

    # Now explicitly wait for a working connection and verify recovery.
    assert client.wait_for_connection(timeout=60.0), "device did not reconnect within 60s"
    recovered_version = client.request_sync()
    assert isinstance(recovered_version, int), f"recovery sync failed: {recovered_version!r}"


def test_real_device_confirm_sync_returns_true(client: IoTAgentClient) -> None:
    result = client.confirm_sync(0x12345678, stage=0)
    assert result is True
