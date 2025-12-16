import sys
import os

sys.path.append("/home/maxi/core/core/vendor/growspace_manager")
from custom_components.growspace_manager.const import (
    ADD_PLANT_SCHEMA,
    UPDATE_PLANT_SCHEMA,
    _PLANT_DATE_FIELDS,
    _PLANT_DAYS_FIELDS,
    DATE_FIELDS,
    PLANT_STAGES,
)
import voluptuous as vol

print("Import successful")
print("DATE_FIELDS:", len(DATE_FIELDS))
print("_PLANT_DATE_FIELDS:", len(_PLANT_DATE_FIELDS))
print("_PLANT_DAYS_FIELDS:", len(_PLANT_DAYS_FIELDS))

# Test ADD_PLANT_SCHEMA
try:
    res = ADD_PLANT_SCHEMA(
        {
            "growspace_id": "test",
            "strain": "Test",
            "row": 1,
            "col": 1,
            "seedling_start": "2023-01-01",
        }
    )
    print("ADD_PLANT_SCHEMA passed")
except Exception as e:
    print("ADD_PLANT_SCHEMA failed:", e)

# Test UPDATE_PLANT_SCHEMA
try:
    res = UPDATE_PLANT_SCHEMA(
        {"plant_id": "p1", "seedling_days": "10", "veg_start": "2023-02-01"}
    )
    print("UPDATE_PLANT_SCHEMA passed")
except Exception as e:
    print("UPDATE_PLANT_SCHEMA failed:", e)
