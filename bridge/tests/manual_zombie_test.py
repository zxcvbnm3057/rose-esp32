"""
Reproduces the zombie-server cross-fixture port leak.

This script mimics what happens when test_reconnect.py's session-scoped
server is torn down and a subsequent test module creates a new server on
the same port (e.g. test_signal.py).

Run:   python tests/manual_zombie_test.py
"""

import socket
import threading
import time
import sys
import os

# Allow importing bridge from parent directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ..src import IoTAgentClient

CYCLES = 5
WAIT_CONNECT = 60  # seconds to wait for ESP32 on first connection


def can_bind(port: int) -> bool:
    """Check whether port is free."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("0.0.0.0", port))
        s.close()
        return True
    except OSError:
        return False


def dump_threads(label: str) -> None:
    print(f"\n--- {label} ---")
    for t in threading.enumerate():
        print(f"  {t.name:35s} alive={t.is_alive()} daemon={t.daemon}")
    print(f"  Port 8080 free: {can_bind(8080)}")


def main() -> None:
    print("=" * 60)
    print("Zombie Server Cross-Fixture Test")
    print(f"Cycles: {CYCLES}")
    print("=" * 60)

    # ---- Phase 1: initial connection ----
    print("\n[Phase 1] Creating first server (like session fixture)...")
    c1 = IoTAgentClient()
    c1.start()
    if not c1.wait_for_connection(timeout=WAIT_CONNECT):
        print("SKIP: No ESP32 connected.  Is the device online?")
        c1.stop()
        return
    print("  Connected.")

    dump_threads("Before first stop()")

    # ---- Phase 2: stop + immediate rebind, N times ----
    for cycle in range(1, CYCLES + 1):
        print(f"\n[Phase 2.{cycle}] Stopping server...")
        c1.stop()
        time.sleep(0.2)  # tiny gap to let OS release

        dump_threads(f"After stop() — cycle {cycle}")

        if not can_bind(8080):
            print(f"  *** FAIL: port 8080 STILL OCCUPIED after stop()!  ZOMBIE DETECTED ***")
            # Wait a bit longer to see if it eventually releases
            for extra in range(1, 11):
                time.sleep(1.0)
                if can_bind(8080):
                    print(f"  Port freed after {extra + 0.2:.1f}s")
                    break
            else:
                print("  Port STILL occupied after 10s — DEFINITIVE ZOMBIE")
                return 1

        # Create new server + connect
        print(f"  Port 8080 free — creating new server...")
        c1 = IoTAgentClient()
        c1.start()
        if not c1.wait_for_connection(timeout=30):
            print(f"  *** FAIL: ESP32 did not reconnect within 30s after cycle {cycle} ***")
            c1.stop()
            return 1
        print(f"  Reconnected — cycle {cycle} OK")

    # ---- Phase 3: clean shutdown ----
    print("\n[Phase 3] Final cleanup...")
    c1.stop()
    time.sleep(0.5)
    dump_threads("After final stop()")

    if can_bind(8080):
        print("\n*** ALL CHECKS PASSED — no zombie detected ***")
    else:
        print("\n*** FAIL: port still occupied after final stop() ***")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
