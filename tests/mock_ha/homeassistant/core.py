class HomeAssistant:
    def __init__(self):
        self.data = {}
        self.services = ServiceRegistry()
        self.states = StateMachine()

    def async_create_task(self, target):
        pass

class ServiceRegistry:
    async def async_call(self, domain, service, service_data, blocking=False):
        pass

class StateMachine:
    def get(self, entity_id):
        return None

class Context:
    pass

class State:
    def __init__(self, entity_id, state, last_updated=None):
        self.entity_id = entity_id
        self.state = state
        self.last_updated = last_updated

def callback(func):
    return func
