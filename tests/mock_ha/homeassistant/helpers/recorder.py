class Recorder:
    async def async_add_executor_job(self, target):
        return target()

def get_instance(hass):
    return Recorder()
