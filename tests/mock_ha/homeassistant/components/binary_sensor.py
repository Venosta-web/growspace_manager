class BinarySensorEntity:
    def __init__(self):
        self.hass = None
        self.entity_id = None
        self._attr_unique_id = None
        self._attr_name = None
        self._attr_device_info = None
        self._attr_should_poll = False
    
    def async_write_ha_state(self):
        pass
    
    def async_on_remove(self, func):
        pass
