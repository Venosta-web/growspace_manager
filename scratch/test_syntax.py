from collections.abc import Mapping
from typing import Any
class EventType[_DataT: Mapping[str, Any] = Mapping[str, Any]](str):
    pass
print('Success')
