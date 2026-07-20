"""Request-shape tests for DHT11 signal exchange."""
import ast
from pathlib import Path


def test_signal_exchange_uses_exact_capture():
    source = (
        Path(__file__).parents[1] / "custom_components" / "rose" / "client.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    method = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "signal_exchange"
    )
    constants = {node.value for node in ast.walk(method) if isinstance(node, ast.Constant)}
    assert "/api/v1/gpio/" in constants
    assert "exact" in constants
    assert "rx_total_us" in constants
    assert "rx_max_edges" in constants