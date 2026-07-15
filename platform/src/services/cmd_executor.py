"""Custom command step executor."""
from __future__ import annotations
import asyncio
import base64
import logging
from typing import Any
from ..services import bridge_service

logger = logging.getLogger(__name__)


async def execute_command(steps: list[dict], params: dict[str, Any] = None) -> list[dict]:
    """Execute a sequence of command steps and return results."""
    params = params or {}
    results = []
    ctx: dict[str, Any] = {}  # shared context between steps

    for i, step in enumerate(steps):
        step_type = step.get("step_type", "")
        config = step.get("config", {})
        delay_ms = step.get("delay_ms", 0)
        on_error = step.get("on_error", "abort")

        # Resolve template params in config values
        resolved_config = _resolve_params(config, params, ctx)

        try:
            result = await _execute_step(step_type, resolved_config, ctx)
            results.append({"step": i + 1, "type": step_type, "success": True, "result": result})
        except Exception as e:
            logger.error(f"Step {i+1} ({step_type}) failed: {e}")
            results.append({"step": i + 1, "type": step_type, "success": False, "error": str(e)})
            if on_error == "abort":
                break
            # "continue" falls through

        # Inter-step delay
        if delay_ms > 0:
            await asyncio.sleep(delay_ms / 1000.0)

    return results


def _resolve_params(config: dict, params: dict, ctx: dict) -> dict:
    """Simple template resolution: {{param.key}} in string values."""
    resolved = {}
    for k, v in config.items():
        if isinstance(v, str) and v.startswith("{{") and v.endswith("}}"):
            key = v[2:-2].strip()
            if key.startswith("params."):
                resolved[k] = params.get(key[7:], v)
            elif key.startswith("ctx."):
                resolved[k] = ctx.get(key[4:], v)
            else:
                resolved[k] = v
        else:
            resolved[k] = v
    return resolved


async def _execute_step(step_type: str, config: dict, ctx: dict) -> Any:
    """Execute a single step."""
    if step_type == "gpio_config":
        ok = await bridge_service.gpio_config(
            config["gpio"], config.get("mode", 0),
            config.get("pull", 0), config.get("edge", 0),
        )
        return {"ack": ok}

    if step_type == "gpio_set":
        ok = await bridge_service.gpio_set(config["gpio"], config["value"])
        return {"ack": ok}

    if step_type == "gpio_get":
        value = await bridge_service.gpio_get(config["gpio"])
        ctx[f"gpio_{config['gpio']}"] = value
        return {"value": value}

    if step_type == "adc_sample":
        value = await bridge_service.adc_sample(config["gpio"], config.get("samples", 1))
        ctx[f"adc_{config['gpio']}"] = value
        return {"value": value}

    if step_type == "signal_tx":
        sig = [{"level": s["level"], "duration_us": s["duration_us"]} for s in config.get("signal", [])]
        ok = await bridge_service.signal_tx(
            config["gpio"],
            sig,
            config.get("delay_us", 0),
            config.get("carrier_hz", 0),
            config.get("duty_cycle", 0.5),
            config.get("repeat", 1),
            config.get("repeat_gap_us", 0),
        )
        return {"ack": ok}

    if step_type == "signal_rx":
        result = await bridge_service.signal_rx(config["gpio"], config.get("timeout_us", 1000000), config.get("max_edges", 100))
        return {"edges": result}

    if step_type == "signal_exchange":
        tx = [{"level": s["level"], "duration_us": s["duration_us"]} for s in config.get("tx_signal", [])]
        result = await bridge_service.signal_exchange(
            config["gpio"], tx, config.get("delay_us", 0),
            config.get("rx_total_us", 500000), config.get("rx_max_edges", 100),
            config.get("carrier_hz", 0), config.get("duty_cycle", 0.5),
        )
        return {"edges": result}

    if step_type == "uart_config":
        ok = await bridge_service.uart_config(
            config["uart_id"], config["baudrate"],
            config.get("tx_gpio", 1), config.get("rx_gpio", 3),
            config.get("data_bits", 8), config.get("parity", 0), config.get("stop_bits", 1),
        )
        return {"ack": ok}

    if step_type == "uart_send":
        data = config.get("data", "").encode(config.get("encoding", "utf-8"))
        if config.get("data_base64"):
            data = base64.b64decode(config["data_base64"])
        ok = await bridge_service.uart_send(config["uart_id"], data)
        return {"ack": ok}

    if step_type == "uart_read":
        result = await bridge_service.uart_read(config["uart_id"], config.get("length", 256))
        if result:
            return {"data_base64": base64.b64encode(result).decode()}
        return {"data_base64": ""}

    if step_type == "port_bind":
        ok = await bridge_service.port_bind(config["resource_type"], config["id"], config.get("owner_id", 0))
        return {"ack": ok}

    if step_type == "port_unbind":
        ok = await bridge_service.port_unbind(config["resource_type"], config["id"])
        return {"ack": ok}

    if step_type == "delay":
        ms = config.get("ms", 100)
        await asyncio.sleep(ms / 1000.0)
        return {"delayed_ms": ms}

    raise ValueError(f"Unknown step type: {step_type}")
