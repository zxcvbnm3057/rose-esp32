"""Constants for the Rose integration."""

DOMAIN = "rose"
CONF_PLATFORM_URL = "platform_url"
CONF_CLIMATES = "climates"
CONF_LIGHTS = "lights"
DEFAULT_NAME = "Rose Platform"
EVENT_BLE_PRESENCE = "rose_ble_presence"
PLATFORMS = ["binary_sensor", "climate", "device_tracker", "light"]


def configured_devices(entry, key: str) -> dict:
	"""Return devices managed by the integration options UI."""
	return entry.options.get(key, {})
