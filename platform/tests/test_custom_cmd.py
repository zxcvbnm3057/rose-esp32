"""Test custom command CRUD + execution."""
import pytest


@pytest.mark.anyio
async def test_list_empty(client, mock_bridge):
    """List commands — may contain items from previous runs in real mode."""
    res = await client.get("/api/v1/cmds")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert isinstance(data["data"]["commands"], list)


@pytest.mark.anyio
async def test_create_and_list(client, mock_bridge):
    import time
    slug = f"toggle-relay-{int(time.time() * 1000)}"
    res = await client.post("/api/v1/cmds", json={
        "slug": slug,
        "name": "切换继电器",
        "description": "翻转 GPIO5 3次",
        "icon": "🔌",
        "steps": [
            {"step_type": "gpio_set", "config": {"gpio": 5, "value": 1}, "delay_ms": 100, "on_error": "abort"},
            {"step_type": "gpio_set", "config": {"gpio": 5, "value": 0}, "delay_ms": 100, "on_error": "abort"},
        ],
    })
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["data"]["slug"] == slug
    assert data["data"]["step_count"] == 2
    assert data["data"]["external_url"] == f"/cmd/{slug}"

    # List — verify the new command appears
    res2 = await client.get("/api/v1/cmds")
    cmds = res2.json()["data"]["commands"]
    assert any(c["slug"] == slug for c in cmds), f"Created cmd '{slug}' not found in list"


@pytest.mark.anyio
async def test_create_duplicate_slug(client, mock_bridge):
    await client.post("/api/v1/cmds", json={
        "slug": "dup", "name": "dup", "steps": [],
    })
    res = await client.post("/api/v1/cmds", json={
        "slug": "dup", "name": "dup2", "steps": [],
    })
    assert res.status_code == 409


@pytest.mark.anyio
async def test_get_by_slug(client, mock_bridge):
    await client.post("/api/v1/cmds", json={
        "slug": "my-cmd", "name": "My", "steps": [],
    })
    res = await client.get("/api/v1/cmds/my-cmd")
    assert res.status_code == 200
    assert res.json()["data"]["slug"] == "my-cmd"


@pytest.mark.anyio
async def test_get_not_found(client, mock_bridge):
    res = await client.get("/api/v1/cmds/nonexistent")
    assert res.status_code == 404


@pytest.mark.anyio
async def test_update(client, mock_bridge):
    await client.post("/api/v1/cmds", json={
        "slug": "upd", "name": "Old", "steps": [],
    })
    res = await client.put("/api/v1/cmds/upd", json={
        "name": "New Name",
        "enabled": False,
    })
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["name"] == "New Name"
    assert data["enabled"] is False


@pytest.mark.anyio
async def test_delete(client, mock_bridge):
    await client.post("/api/v1/cmds", json={
        "slug": "del-me", "name": "Delete Me", "steps": [],
    })
    res = await client.delete("/api/v1/cmds/del-me")
    assert res.status_code == 200
    # Verify gone
    res2 = await client.get("/api/v1/cmds/del-me")
    assert res2.status_code == 404


@pytest.mark.anyio
async def test_execute(client, mock_bridge):
    await client.post("/api/v1/cmds", json={
        "slug": "exec-test",
        "name": "Exec",
        "steps": [
            {"step_type": "gpio_set", "config": {"gpio": 5, "value": 1}, "delay_ms": 0, "on_error": "abort"},
            {"step_type": "gpio_set", "config": {"gpio": 5, "value": 0}, "delay_ms": 0, "on_error": "abort"},
        ],
    })
    res = await client.post("/api/v1/cmds/exec-test/execute", json={"params": {}})
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["data"]["steps_executed"] == 2
    assert len(data["data"]["results"]) == 2
    assert data["data"]["results"][0]["success"] is True


@pytest.mark.anyio
async def test_execute_disabled(client, mock_bridge):
    await client.post("/api/v1/cmds", json={
        "slug": "disabled-cmd", "name": "Disabled", "steps": [],
    })
    # Disable it
    await client.put("/api/v1/cmds/disabled-cmd", json={"enabled": False})
    # Try execute
    res = await client.post("/api/v1/cmds/disabled-cmd/execute")
    assert res.status_code == 200
    assert res.json()["success"] is False
    assert "disabled" in res.json()["error"].lower()


@pytest.mark.anyio
async def test_public_cmd_url(client, mock_bridge):
    """The /cmd/{slug} endpoint should work same as execute."""
    await client.post("/api/v1/cmds", json={
        "slug": "public-test",
        "name": "Public",
        "steps": [
            {"step_type": "gpio_set", "config": {"gpio": 5, "value": 1}, "delay_ms": 0, "on_error": "abort"},
        ],
    })
    res = await client.post("/cmd/public-test")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["data"]["slug"] == "public-test"
    assert data["data"]["steps_executed"] == 1


@pytest.mark.anyio
async def test_update_steps(client, mock_bridge):
    """Update command steps and verify they changed."""
    await client.post("/api/v1/cmds", json={
        "slug": "step-upd", "name": "StepUpd",
        "steps": [{"step_type": "gpio_set", "config": {"gpio": 5, "value": 1}, "delay_ms": 0, "on_error": "abort"}],
    })
    res = await client.put("/api/v1/cmds/step-upd", json={
        "steps": [
            {"step_type": "gpio_set", "config": {"gpio": 5, "value": 0}, "delay_ms": 0, "on_error": "abort"},
            {"step_type": "delay", "config": {"ms": 500}, "delay_ms": 0, "on_error": "abort"},
        ],
    })
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["step_count"] == 2
    assert data["steps"][0]["step_type"] == "gpio_set"
    assert data["steps"][1]["step_type"] == "delay"


@pytest.mark.anyio
async def test_update_not_found(client, mock_bridge):
    res = await client.put("/api/v1/cmds/no-such", json={"name": "X"})
    assert res.status_code == 404


@pytest.mark.anyio
async def test_execute_not_found(client, mock_bridge):
    res = await client.post("/api/v1/cmds/no-such/execute")
    assert res.status_code == 404
