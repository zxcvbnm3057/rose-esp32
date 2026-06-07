"""
TCP Server for IoT Agent communication.

This module implements a TCP server that handles connections from ESP32 IoT Agent
devices, processes incoming events, and sends commands.
"""

import socket
import select
import threading
import time
import struct
import logging
from typing import Optional, Callable, Dict, Any
from .protocol import MessageFrame, MSG_TYPE_CMD, MSG_TYPE_EVENT, MSG_TYPE_ACK

logger = logging.getLogger(__name__)

class IoTAgentServer:
    """TCP Server for ESP32 IoT Agent connections."""

    def __init__(self, host: str = '0.0.0.0', port: int = 8080) -> None:
        self.host = host
        self.port = port
        self.server_socket: Optional[socket.socket] = None
        self.client_socket: Optional[socket.socket] = None
        self.client_address: Optional[tuple] = None
        self.running = False
        self.connected = False
        self.event_callback: Optional[Callable[[MessageFrame], None]] = None
        self._server_thread: Optional[threading.Thread] = None
        self._client_thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()
        # Socket pair for cross-thread wake-up: writing to _wake_w unblocks
        # select() in _server_loop so stop() can interrupt it on Windows.
        self._wake_r, self._wake_w = socket.socketpair()

    def set_event_callback(self, callback: Callable[[MessageFrame], None]) -> None:
        """Set callback for handling incoming events."""
        self.event_callback = callback

    def start(self) -> None:
        """Start the TCP server."""
        if self.running:
            return

        self.running = True
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # Retry bind — a previous server instance thread may not have released
        # the port yet even though stop() was called.
        for attempt in range(100):
            try:
                self.server_socket.bind((self.host, self.port))
                break
            except OSError:
                if attempt == 99:
                    raise
                time.sleep(0.2)
        self.server_socket.listen(1)

        self._server_thread = threading.Thread(target=self._server_loop, daemon=True)
        self._server_thread.start()

        logger.info(f"IoT Agent Server started on {self.host}:{self.port}")

    def stop(self) -> None:
        """Stop the TCP server."""
        self.running = False
        # Wake up the server loop via socketpair so it exits select() promptly.
        try:
            self._wake_w.send(b'x')
        except:
            pass

        with self._lock:
            if self.client_socket:
                try:
                    self.client_socket.shutdown(socket.SHUT_RDWR)
                except:
                    pass
                try:
                    self.client_socket.close()
                except:
                    pass
                self.client_socket = None
                self.connected = False

        # Wait for server thread to exit FIRST — closing server_socket while
        # the thread is in select() on it will hang on Windows.
        if self._server_thread and self._server_thread.is_alive():
            self._server_thread.join(timeout=5.0)
            if self._server_thread.is_alive():
                logger.warning("Server thread did not exit within 5s")

        if self.server_socket:
            try:
                self.server_socket.close()
            except:
                pass
            self.server_socket = None

        # Close the wake-up socketpair
        try:
            self._wake_r.close()
        except:
            pass
        try:
            self._wake_w.close()
        except:
            pass

        logger.info("IoT Agent Server stopped")

    def send_command(self, frame: MessageFrame) -> bool:
        """Send a command frame to the connected client."""
        with self._lock:
            if not self.connected or not self.client_socket:
                logger.warning("No client connected")
                return False

            try:
                data = frame.to_bytes()
                self.client_socket.sendall(data)
                logger.debug(f"Sent command: type={frame.msg_type}, cmd_id={frame.cmd_id}")
                return True
            except Exception as e:
                logger.error(f"Failed to send command: {e}")
                self._handle_disconnect()
                return False

    def is_connected(self) -> bool:
        """Check if a client is connected."""
        return self.connected

    def _server_loop(self) -> None:
        """Main server loop accepting connections."""
        while self.running:
            try:
                r, _, _ = select.select([self.server_socket, self._wake_r], [], [], 0.5)
                if self._wake_r in r:
                    # Drain the wake byte and exit
                    try:
                        self._wake_r.recv(1)
                    except:
                        pass
                    break
                if self.server_socket not in r:
                    continue
                # select() said readable but accept() may still block on
                # Windows; use a timeout to stay responsive to stop().
                self.server_socket.settimeout(0.5)
                try:
                    client_sock, addr = self.server_socket.accept()
                except socket.timeout:
                    continue
            except (OSError, select.error):
                break
            except Exception as e:
                logger.error(f"Server error: {e}")
                time.sleep(1.0)
                continue

            logger.info(f"Client connected from {addr}")

            with self._lock:
                if self.client_socket:
                    try:
                        self.client_socket.close()
                    except:
                        pass

                self.client_socket = client_sock
                self.client_address = addr
                self.connected = True

            # Start client handler thread
            self._client_thread = threading.Thread(target=self._client_handler, args=(client_sock,), daemon=True)
            self._client_thread.start()

    def _client_handler(self, client_sock: socket.socket) -> None:
        """Handle communication with connected client."""
        buffer = b''
        client_sock.settimeout(1.0)  # Prevent indefinite blocking after stop()

        while self.running:
            try:
                data = client_sock.recv(1024)
                if not data:
                    # Client disconnected
                    break

                buffer += data

                # Process complete messages
                while len(buffer) >= 8:  # Minimum header size
                    try:
                        # Peek at header to get message length
                        header = buffer[:8]
                        version, msg_type, length, cmd_id, crc = struct.unpack('<BBHHH', header)
                        if length > 4096 or length < 0:
                            raise ValueError(f"Invalid payload length: {length}")

                        total_size = 8 + length
                        if len(buffer) < total_size:
                            break  # Wait for more data

                        # Extract full message
                        msg_data = buffer[:total_size]
                        buffer = buffer[total_size:]

                        # Parse message
                        frame = MessageFrame.from_bytes(msg_data)
                        logger.debug(f"Received frame: type={frame.msg_type}, cmd_id={frame.cmd_id}, len={frame.length}, payload_len={len(frame.payload)}")
                        if frame.msg_type == MSG_TYPE_EVENT:
                            if self.event_callback:
                                self.event_callback(frame)
                        elif frame.msg_type == MSG_TYPE_CMD:
                            logger.warning("Received CMD from client - unexpected")
                        elif frame.msg_type == MSG_TYPE_ACK:
                            logger.debug(f"Received ACK for cmd_id {frame.cmd_id}")
                        else:
                            logger.warning(f"Unknown message type: {frame.msg_type}")

                    except Exception as e:
                        logger.error(f"Error parsing message: {e}")
                        # Skip invalid data - find next potential header
                        buffer = buffer[1:]
                        continue

            except socket.timeout:
                continue  # Normal — just checking self.running periodically
            except Exception as e:
                logger.error(f"Client handler error: {e}")
                break

        self._handle_disconnect(client_sock)

    def _handle_disconnect(self, client_sock: Optional[socket.socket] = None) -> None:
        """Handle client disconnection."""
        with self._lock:
            if client_sock is None:
                client_sock = self.client_socket

            if client_sock:
                try:
                    client_sock.close()
                except:
                    pass

                if self.client_socket is client_sock:
                    self.client_socket = None
                    self.connected = False
                    logger.info("Client disconnected")
                else:
                    logger.info("Client handler disconnected stale socket")