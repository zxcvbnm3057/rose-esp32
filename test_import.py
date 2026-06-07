#!/usr/bin/env python3
"""Test script to verify bridge imports."""

try:
    import sys
    sys.path.insert(0, '.')
    import bridge
    print("Bridge import successful")
    print(f"Bridge version: {bridge.__version__}")
    print(f"Available classes: {dir(bridge)}")
except Exception as e:
    print(f"Import error: {e}")
    import traceback
    traceback.print_exc()