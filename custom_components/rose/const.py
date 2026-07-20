"""Constants for the Rose integration."""

DOMAIN = "rose"
CONF_PLATFORM_URL = "platform_url"
CONF_KEY = "key"
CONF_BLE_DEVICES = "ble_devices"
SUBENTRY_TYPE_CLIMATE = "climate"
SUBENTRY_TYPE_LIGHT = "light"
DEFAULT_NAME = "Rose Platform"
EVENT_BLE_PRESENCE = "rose_ble_presence"
PLATFORMS = ["binary_sensor", "climate", "device_tracker", "light", "number", "switch"]

CLIMATE_PROTOCOL_NAMES = {
	"tcl": "TCL TAC09CHSD 112-bit infrared",
}


def climate_protocol_name(config: dict) -> str:
	"""Return the display name for a configured climate protocol."""
	protocol = config.get("protocol", "tcl")
	return CLIMATE_PROTOCOL_NAMES.get(protocol, protocol)


def configured_subentries(entry, subentry_type: str):
	"""Return configured device subentries of one type."""
	for subentry_id, subentry in entry.subentries.items():
		if subentry.subentry_type != subentry_type:
			continue
		config = dict(subentry.data)
		yield subentry_id, config[CONF_KEY], config
