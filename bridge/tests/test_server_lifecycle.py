"""
Server lifecycle / port-leak (zombie) tests — no hardware required.

Automated replacement for the manual `manual_zombie_test.py` script. These
tests verify that IoTAgentServer / IoTAgentClient release the listening port
on stop() and can be re-created on the same port across many cycles without
leaking a "zombie" listener or accept thread.

Unlike the hardware fixtures these do NOT wait for a real ESP32 to connect;
they only exercise the server socket lifecycle, so they run anywhere.
"""

import socket
import time

from ..src import IoTAgentClient
from ..src.server import IoTAgentServer

TEST_PORT = 18080  # high port unlikely to collide with the real bridge (8080)


def _port_is_free(port: int, host: str = "0.0.0.0") -> bool:
    """Return True if we can bind the port right now (i.e. it is free)."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        probe.close()


def _wait_port_free(port: int, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _port_is_free(port):
            return True
        time.sleep(0.05)
    return _port_is_free(port)


def test_server_start_stop_releases_port():
    """A single start()/stop() must leave the listening port free."""
    server = IoTAgentServer(host="0.0.0.0", port=TEST_PORT)
    server.start()
    try:
        # While running the port must NOT be bindable by anyone else.
        assert not _port_is_free(TEST_PORT), "port should be occupied while server runs"
    finally:
        server.stop()

    assert _wait_port_free(TEST_PORT), "port still occupied after stop() — zombie listener"


def test_server_rebind_cycles_no_zombie():
    """Repeated stop()+recreate on the same port must never leak a zombie."""
    cycles = 5
    server = IoTAgentServer(host="0.0.0.0", port=TEST_PORT)
    server.start()
    try:
        for cycle in range(cycles):
            server.stop()
            assert _wait_port_free(TEST_PORT), (
                f"port 8080-equivalent still occupied after stop() on cycle {cycle}"
            )
            # Re-create on the same port — would raise OSError if the old
            # listener were still bound (the zombie bug this guards against).
            server = IoTAgentServer(host="0.0.0.0", port=TEST_PORT)
            server.start()
    finally:
        server.stop()
    assert _wait_port_free(TEST_PORT)


def test_server_stop_joins_accept_thread():
    """stop() must not leave the server loop thread running (no daemon leak)."""
    server = IoTAgentServer(host="0.0.0.0", port=TEST_PORT)
    server.start()
    time.sleep(0.1)  # allow the server loop thread to spin up
    loop_thread = server._server_thread
    assert loop_thread is not None and loop_thread.is_alive()

    server.stop()

    # The server loop thread must terminate promptly after stop().
    loop_thread.join(timeout=3.0)
    assert not loop_thread.is_alive(), "server loop thread still alive after stop()"


def test_client_start_stop_releases_port():
    """IoTAgentClient (the high-level wrapper) must release its port too."""
    client = IoTAgentClient(host="0.0.0.0", port=TEST_PORT)
    client.start()
    try:
        assert not _port_is_free(TEST_PORT)
        assert client.is_connected() is False  # no device, but server is up
    finally:
        client.stop()
    assert _wait_port_free(TEST_PORT), "client did not release port on stop()"


def test_double_stop_is_safe():
    """Calling stop() twice must not raise and must leave the port free."""
    client = IoTAgentClient(host="0.0.0.0", port=TEST_PORT)
    client.start()
    client.stop()
    client.stop()  # second stop must be a no-op, not an error
    assert _wait_port_free(TEST_PORT)
