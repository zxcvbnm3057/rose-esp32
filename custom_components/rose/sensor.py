"""Signal-backed Rose sensor entities."""
from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator, UpdateFailed

from .client import RoseApiError
from .const import DOMAIN, SUBENTRY_TYPE_SENSOR, configured_subentries
from .protocols.dht11 import DHT11_START_SIGNAL, Dht11DecodeError, decode_dht11_signal

LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    runtime = hass.data[DOMAIN][entry.entry_id]
    for subentry_id, key, config in configured_subentries(entry, SUBENTRY_TYPE_SENSOR):
        if config.get("model") != "dht11":
            continue
        coordinator = RoseDht11Coordinator(hass, runtime["client"], config)
        async_add_entities(
            [
                RoseDht11Sensor(coordinator, key, config, "temperature"),
                RoseDht11Sensor(coordinator, key, config, "humidity"),
            ],
            config_subentry_id=subentry_id,
        )
        entry.async_create_background_task(
            hass,
            coordinator.async_request_refresh(),
            f"Refresh Rose DHT11 GPIO {config['gpio']}",
        )


class RoseDht11Coordinator(DataUpdateCoordinator[dict[str, float]]):
    def __init__(self, hass, client, config: dict) -> None:
        super().__init__(
            hass,
            logger=LOGGER,
            name=f"Rose DHT11 GPIO {config['gpio']}",
            update_interval=timedelta(seconds=10),
        )
        self._client = client
        self._gpio = int(config["gpio"])

    async def _async_update_data(self) -> dict[str, float]:
        try:
            edges = await self._client.signal_exchange(
                self._gpio,
                DHT11_START_SIGNAL,
                rx_total_us=10_000,
                rx_max_edges=100,
            )
            temperature, humidity = decode_dht11_signal(edges)
        except (RoseApiError, Dht11DecodeError, KeyError, TypeError, ValueError) as exc:
            raise UpdateFailed(str(exc)) from exc
        return {"temperature": temperature, "humidity": humidity}


class RoseDht11Sensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, key: str, config: dict, measurement: str) -> None:
        super().__init__(coordinator)
        self._key = key
        self._config = config
        self._measurement = measurement
        self._attr_translation_key = measurement
        self._attr_unique_id = f"rose_sensor_{key}_{measurement}"
        if measurement == "temperature":
            self._attr_device_class = SensorDeviceClass.TEMPERATURE
            self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        else:
            self._attr_device_class = SensorDeviceClass.HUMIDITY
            self._attr_native_unit_of_measurement = PERCENTAGE

    @property
    def native_value(self):
        return self.coordinator.data.get(self._measurement) if self.coordinator.data else None

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, f"sensor_{self._key}")},
            "name": self._config.get("name", "DHT11"),
            "manufacturer": "Rose",
            "model": "DHT11",
            "via_device": (DOMAIN, "platform"),
        }