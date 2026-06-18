from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

FEATURE_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True, slots=True)
class AcRoomBinding:
    gpio: int
    protocol: str = "tcl"


ROOM_BINDINGS: dict[str, AcRoomBinding] = {
    # "living_room": AcRoomBinding(
    #     gpio=5,
    # ),
    "bedroom": AcRoomBinding(
        gpio=4,
    ),
}
