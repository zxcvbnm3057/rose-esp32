"""
IoT Agent Bridge - Python Driver for ESP32 IoT Agent

This module provides a complete Python implementation for communicating with
the ESP32 IoT Agent hardware proxy. It includes TCP server functionality,
command dispatching, event handling, and comprehensive testing utilities.

Features:
- TCP server for ESP32 client connections
- Full command set support (GPIO, UART, BLE, etc.)
- Event-driven architecture
- Type-safe implementation with full type annotations
- Comprehensive test suite
"""

from .protocol import *
from .server import IoTAgentServer
from .commands import CommandDispatcher
from .events import EventHandler
from .client import IoTAgentClient

__version__ = "1.0.0"
__all__ = [
    "IoTAgentServer",
    "CommandDispatcher",
    "EventHandler",
    "IoTAgentClient",
    # Protocol constants
    "MSG_TYPE_CMD", "MSG_TYPE_ACK", "MSG_TYPE_EVENT", "MSG_TYPE_ERROR",
    "CMD_GPIO_CONFIG", "CMD_GPIO_SET", "CMD_GPIO_GET",
    "EVENT_CMD_ACK", "EVENT_GPIO_VALUE",
    # And all other constants from protocol
]