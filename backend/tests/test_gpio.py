"""Test GPIO endpoints — works with both mock and real device."""
import pytest


@pytest.mark.anyio
async def test_gpio_config(client, mock_bridge, is_real):
    # Ensure clean state: unbind first, then configure
    if is_real:
        await client.post("/api/v1/port/unbind", json={"resource_type": 0, "id": 5})
    res = await client.post("/api/v1/gpio/5/config", json={
        "mode": 1, "pull": 2, "edge": 0,
    })
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["data"]["gpio"] == 5
    assert data["data"]["mode"] == 1


@pytest.mark.anyio
async def test_gpio_config_reserved_pin(client, mock_bridge):
    res = await client.post("/api/v1/gpio/8/config", json={"mode": 1})
    assert res.status_code == 403
    assert "reserved" in res.json()["error"].lower()


@pytest.mark.anyio
async def test_gpio_set(client, mock_bridge, is_real):
    # Configure OUTPUT first, then set value
    if is_real:
        await client.post("/api/v1/port/unbind", json={"resource_type": 0, "id": 5})
        await client.post("/api/v1/gpio/5/config", json={"mode": 1})
    res = await client.post("/api/v1/gpio/5/set", json={"value": 1})
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["data"]["value"] == 1


@pytest.mark.anyio
async def test_gpio_get(client, mock_bridge, is_real):
    res = await client.get("/api/v1/gpio/5/get")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["data"]["gpio"] == 5
    assert "value" in data["data"]
    if not is_real:
        assert data["data"]["value"] == 0


@pytest.mark.anyio
async def test_gpio_adc(client, mock_bridge, is_real):
    res = await client.post("/api/v1/gpio/2/adc", json={"samples": 4})
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert "voltage_mv" in data["data"]
    if is_real:
        assert 0 <= data["data"]["value"] <= 4095
    else:
        assert data["data"]["value"] == 2048


@pytest.mark.anyio
async def test_gpio_invalid_mode(client, mock_bridge):
    res = await client.post("/api/v1/gpio/5/config", json={"mode": 99})
    assert res.status_code == 422


@pytest.mark.anyio
async def test_gpio_set_invalid_value(client, mock_bridge):
    res = await client.post("/api/v1/gpio/5/set", json={"value": 2})
    assert res.status_code == 422
