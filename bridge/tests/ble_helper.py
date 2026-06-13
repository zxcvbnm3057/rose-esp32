"""
BLE test helper -- uses the PC Bluetooth adapter to interact with
the ESP32 BLE peripheral, enabling end-to-end BLE event tests.

Scanning/GATT uses bleak. Pairing uses the Windows Runtime (winrt)
custom-pairing API so the firmware-generated PIN can be injected
programmatically (no Windows PIN dialog), keeping tests fully automated.

Requires: Windows Bluetooth ON (Settings > Bluetooth & devices)
          bleak  (scanning / connect)
          winrt  (programmatic PIN pairing -- Windows only)
"""

import asyncio
import logging
from typing import Optional

from bleak import BleakScanner, BleakClient

logger = logging.getLogger(__name__)

ESP32_BLE_NAME = "ESP32-IoT"

# winrt is Windows-only; import lazily/guarded so the module still loads
# (and non-pairing helpers stay usable) on other platforms.
try:
    from winrt.windows.devices.bluetooth import BluetoothLEDevice
    from winrt.windows.devices.enumeration import (
        DeviceInformationCustomPairing,
        DevicePairingKinds,
    )
    _WINRT_OK = True
except Exception as _winrt_err:  # noqa: BLE001
    _WINRT_OK = False
    _WINRT_IMPORT_ERROR = _winrt_err



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

    # ── Automated PIN pairing via winrt (no system dialog) ────────────

    @staticmethod
    def winrt_available() -> bool:
        """True if the Windows Runtime pairing API is importable."""
        return _WINRT_OK

    @staticmethod
    def _addr_to_int(addr: str) -> int:
        return int(addr.replace(":", "").replace("-", ""), 16)

    def pair_with_pin(self, pin: str, timeout: float = 20.0) -> bool:
        """Pair with the ESP32 using a firmware-provided PIN, fully unattended.

        Uses winrt custom pairing: clears any stale bond, starts the
        ProvidePin ceremony, and injects ``pin`` via accept_with_pin so no
        Windows PIN dialog appears. Returns True if pairing succeeded
        (status Paired / AlreadyPaired).
        """
        if not self._WINRT_OK_OR_LOG():
            return False
        if not self._address:
            logger.error("No address; call scan_for_device() first")
            return False
        return asyncio.run(self._pair_with_pin_async(pin, timeout))

    @staticmethod
    def _WINRT_OK_OR_LOG() -> bool:
        if not _WINRT_OK:
            logger.error("winrt unavailable: %s", _WINRT_IMPORT_ERROR)
        return _WINRT_OK

    async def _pair_with_pin_async(self, pin: str, timeout: float) -> bool:
        bt_int = self._addr_to_int(self._address)
        le = await BluetoothLEDevice.from_bluetooth_address_async(bt_int)
        if le is None:
            logger.error("from_bluetooth_address returned None for %s", self._address)
            return False
        pairing = le.device_information.pairing

        # Clear any stale bond so the firmware (RAM key store) and Windows
        # agree to run a fresh ceremony.
        if pairing.is_paired:
            await pairing.unpair_async()

        custom: DeviceInformationCustomPairing = pairing.custom

        def _on_requested(_sender, args):
            deferral = args.get_deferral()
            try:
                if args.pairing_kind == DevicePairingKinds.PROVIDE_PIN:
                    args.accept_with_pin(pin)
                else:
                    args.accept()
            finally:
                deferral.complete()

        token = custom.add_pairing_requested(_on_requested)
        try:
            # status 19 (Failed) shows up intermittently when a fresh pairing
            # ceremony starts before the BLE stack has fully recovered from a
            # prior cycle. Retry a couple of times (re-unpairing first) so the
            # automated suite stays reliable without manual intervention.
            max_attempts = 3
            for attempt in range(1, max_attempts + 1):
                result = await asyncio.wait_for(
                    custom.pair_async(DevicePairingKinds.PROVIDE_PIN),
                    timeout=timeout,
                )
                status = int(result.status)
                # 0 = Paired, 3 = AlreadyPaired
                if status in (0, 3):
                    self._connected = True
                    logger.info(
                        "Paired with %s (status=%d, attempt=%d)",
                        self._address, status, attempt,
                    )
                    return True
                logger.warning(
                    "Pair failed status=%d (attempt %d/%d)",
                    status, attempt, max_attempts,
                )
                if attempt < max_attempts:
                    # Drop any half-formed bond and let the stack settle.
                    if pairing.is_paired:
                        await pairing.unpair_async()
                    await asyncio.sleep(2.0)
            return False
        except Exception as e:  # noqa: BLE001
            logger.error("pair_with_pin error: %s", e)
            return False
        finally:
            custom.remove_pairing_requested(token)

    def unpair(self) -> bool:
        """Remove the Windows bond for the ESP32 (cleanup between tests)."""
        if not _WINRT_OK or not self._address:
            return False
        return asyncio.run(self._unpair_async())

    async def _unpair_async(self) -> bool:
        try:
            bt_int = self._addr_to_int(self._address)
            le = await BluetoothLEDevice.from_bluetooth_address_async(bt_int)
            if le is None:
                return False
            await le.device_information.pairing.unpair_async()
            self._connected = False
            return True
        except Exception as e:  # noqa: BLE001
            logger.error("unpair error: %s", e)
            return False

    def cleanup(self) -> None:
        if self._client and self._connected:
            try:
                asyncio.run(self._client.disconnect())
            except Exception:
                pass
        # Best-effort: drop any bond so re-runs start clean.
        if _WINRT_OK and self._address:
            try:
                asyncio.run(self._unpair_async())
            except Exception:
                pass
        self._client = None
        self._connected = False
