"""
BLE test helper -- uses the PC Bluetooth adapter to interact with
the ESP32 BLE peripheral, enabling end-to-end BLE event tests.

Requires: Windows Bluetooth ON (Settings > Bluetooth & devices)
          bleak library
"""

import asyncio
import logging
from typing import Optional

from bleak import BleakScanner, BleakClient

logger = logging.getLogger(__name__)

ESP32_BLE_NAME = "ESP32-IoT"


class BleTestHelper:
    """PC-side BLE central that connects to the ESP32 peripheral."""

    def __init__(self, target_name: str = ESP32_BLE_NAME,
                 scan_timeout: float = 8.0) -> None:
        self.target_name = target_name
        self.scan_timeout = scan_timeout
        self._address: Optional[str] = None
        self._client: Optional[BleakClient] = None
        self._connected = False

    def scan_for_device(self) -> Optional[str]:
        """Scan for ESP32 BLE device; returns address or None."""
        return asyncio.run(self._scan_async())

    async def _scan_async(self) -> Optional[str]:
        logger.info(
            "Scanning for '%s' (%ss)...",
            self.target_name, self.scan_timeout
        )
        devices = await BleakScanner.discover(
            timeout=self.scan_timeout, return_adv=True
        )
        for addr, (device, adv_data) in devices.items():
            name = adv_data.local_name or device.name or ""
            if self.target_name.lower() in name.lower():
                self._address = device.address
                logger.info(
                    "Found %s at %s (RSSI=%sdBm)",
                    name, device.address, adv_data.rssi
                )
                return self._address

        found = [
            f"{adv.local_name or d.name or '?'}({d.address})"
            for d, adv in (
                (devices[a][0], devices[a][1]) for a in devices
            )
        ]
        logger.warning(
            "'%s' not in %s devices: %s",
            self.target_name, len(devices), ", ".join(found)
        )
        return None

    def get_address(self) -> Optional[str]:
        return self._address

    def connect(self, timeout: float = 15.0) -> bool:
        """Connect to scanned ESP32. Returns True on success."""
        if not self._address:
            logger.error("No address; call scan_for_device() first")
            return False
        return asyncio.run(self._connect_async(timeout))

    async def _connect_async(self, timeout: float) -> bool:
        try:
            self._client = BleakClient(self._address, timeout=timeout)
            await self._client.connect()
            self._connected = self._client.is_connected
            if self._connected:
                logger.info("Connected to %s", self._address)
            return self._connected
        except Exception as e:
            logger.error("Connect failed: %s", e)
            self._connected = False
            return False

    def disconnect(self) -> bool:
        return asyncio.run(self._disconnect_async())

    async def _disconnect_async(self) -> bool:
        if not self._client:
            return False
        try:
            await self._client.disconnect()
            self._connected = False
            logger.info("Disconnected")
            return True
        except Exception as e:
            logger.error("Disconnect error: %s", e)
            return False

    @property
    def is_connected(self) -> bool:
        return self._connected

    def cleanup(self) -> None:
        if self._client and self._connected:
            try:
                asyncio.run(self._client.disconnect())
            except Exception:
                pass
        self._client = None
        self._connected = False
