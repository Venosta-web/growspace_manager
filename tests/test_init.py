async def test_setup_unload_entry(mock_hass, coordinator):
    """Test initializing and unloading the coordinator (integration setup)."""
    # Simulate adding a growspace entry
    growspace_id = await coordinator.async_add_growspace("Tent 2", 3, 3, None)
    assert growspace_id in coordinator.growspaces

    # Simulate unloading
    await coordinator.async_remove_growspace(growspace_id)
    assert growspace_id not in coordinator.growspaces
