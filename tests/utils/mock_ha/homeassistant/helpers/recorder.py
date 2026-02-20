from homeassistant.core import HomeAssistant


class Recorder:
    async def async_add_executor_job(self, target):
        return target()


def get_instance(hass: HomeAssistant | None = None):
    return Recorder()
