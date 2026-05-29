# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Growspace Manager** is a Home Assistant custom integration for managing cannabis cultivation environments. It's a Gold-tier quality integration that provides plant tracking, environmental monitoring, irrigation control, and AI-powered assistance for cultivation.

**Key Integration Details:**

- Domain: `growspace_manager`
- Integration Type: Hub
- IoT Class: Local Push
- Quality Scale: Gold
- Single Config Entry: Yes
- Python: 3.14+

## Development Commands

### Testing

All tests should be run using the parent project's virtual environment at `/home/maxi/core/core/.venv` (Python 3.14+):

```bash
# Run all tests
/home/maxi/core/core/.venv/bin/pytest tests/ -q

# Run tests with coverage
/home/maxi/core/core/.venv/bin/pytest tests/ --cov=custom_components.growspace_manager --cov-report=term-missing -q

# Run specific test file
/home/maxi/core/core/.venv/bin/pytest tests/test_<module>.py -v

# Run tests matching a pattern
/home/maxi/core/core/.venv/bin/pytest tests/ -k "test_pattern" -v

# Update test snapshots (if used)
/home/maxi/core/core/.venv/bin/pytest tests/ --snapshot-update
# Always run tests again without --snapshot-update to verify
```

**CRITICAL:** After completing any task involving code changes, ALWAYS run the relevant tests to ensure no regressions. For bug fixes, run the related test file. For features, run all affected test files. Before marking work complete, run the full test suite.

### Code Quality

```bash
# Run all pre-commit hooks
pre-commit run --all-files

# Run ruff formatting and linting
ruff check custom_components/growspace_manager/
ruff format custom_components/growspace_manager/

# Run mypy type checking
mypy custom_components/growspace_manager/

# Run pylint (if needed)
pylint custom_components/growspace_manager/
```

### Coverage Workflow

```bash
# Establish coverage baseline
.venv/bin/pytest --cov=custom_components/growspace_manager --cov-report=term-missing tests/ > COVERAGE_LATEST.txt

# Identify gaps (files with < 100% coverage)
grep -v "100%" COVERAGE_LATEST.txt | grep -v "---" | grep -v "TOTAL" | sort -k4 -n

# Run coverage for specific file
.venv/bin/pytest --cov=custom_components/growspace_manager/PATH_TO_FILE --cov-report=term-missing tests/TEST_FILE.py
```

## Architecture Overview

### Core Components

The integration follows Home Assistant's standard architecture with several specialized subsystems:

**1. Main Integration (`__init__.py`)**

- Entry point for setup and teardown
- Initializes coordinator and subsystems
- Registers services and platforms

**2. Data Coordinator (`coordinator.py`)**

- Central data management using `DataUpdateCoordinator`
- Manages growspaces, plants, and environment configurations
- Handles state updates and persistence
- **Critical:** Pass `config_entry` parameter to coordinator - it's accepted and recommended

**3. Storage System**

- **Storage Manager (`storage_manager.py`)**: Handles JSON-based persistence
- **Data Access Layer (`data_access/`)**: Provides abstraction for data operations
- Multiple storage keys for different data domains:
  - `growspace_manager.config`: Growspaces and configurations
  - `growspace_manager.plants`: Plant data
  - `strain_library.db`: SQLite database for strain analytics

**4. Config Flow (`config_flow.py` + `config_handlers/`)**

- Multi-step configuration flow
- Config handlers organized by domain:
  - `growspace_config_handler.py`: Growspace management
  - `plant_config_handler.py`: Plant operations
  - `environment_config_handler.py`: Environmental sensors
  - `irrigation_config_handler.py`: Irrigation setup
  - `notification_config_handler.py`: Notification configuration
  - `ai_config_handler.py`: AI assistant settings
  - `strain_config_handler.py`: Strain library management

**5. Environmental Monitoring**

- **Bayesian Evaluator (`bayesian_evaluator.py`)**: Probability-based condition assessment
- **Binary Sensors (`binary_sensor.py`)**: Plant stress, mold risk, optimal conditions
- **Environment Analyzer (`environment_analyzer.py`)**: Contextual environment analysis

**6. Irrigation System**

- **Irrigation Coordinator (`irrigation_coordinator.py`)**: Schedule and execute watering
- **VWC Irrigation Coordinator (`vwc_irrigation_coordinator.py`)**: Volumetric water content based control
- **Dehumidifier Coordinator (`dehumidifier_coordinator.py`)**: VPD-based humidity control

**7. Entity Platforms**

- **Sensors (`sensor.py`)**: Growspace overview, plant sensors, strain library
- **Binary Sensors (`binary_sensor.py`)**: Environmental condition indicators
- **Switches (`switch.py`)**: Notification toggles
- **Calendar (`calendar.py`)**: Task scheduling

**8. Services (`services/` + `service_registration.py`)**

- Extensive service API for automation
- Organized by domain: growspace, plant, environment, irrigation, AI, strain library
- See `services.yaml` for complete service definitions

**9. WebSocket API (`websocket.py`)**

- Real-time updates for frontend
- Handles growspace and plant state synchronization
- Nutrient inventory management

**10. AI Integration**

- AI assistant for grow advice
- Strain recommendations
- Uses Home Assistant conversation agents (Anthropic, OpenAI, etc.)

### Data Models (`models.py`)

Key dataclasses:

- `GrowspaceConfig`: Growspace configuration and metadata
- `PlantData`: Individual plant tracking
- `EnvironmentConfig`: Sensor configuration
- `IrrigationConfig`: Watering schedules
- `DehumidifierConfig`: VPD/humidity targets

All models use `mashumaro` for serialization.

### Special Growspaces

The integration manages several canonical growspaces with fixed IDs:

- `dry`: For drying harvested plants
- `cure`: For curing dried plants
- `mother`: For mother plants
- `clone`: For clones
- `veg`: For vegetative growth

These are auto-created and should not be deleted. See `SPECIAL_GROWSPACES` in `const.py`.

### Event System

Uses custom event bus (`event_bus_pkg/`) for:

- Plant lifecycle events
- Environment changes
- Timeline entries for logbook integration

## Important Patterns

### Async Programming

- All I/O operations must be async
- Use `asyncio.gather` for concurrent operations, not loops with await
- Use `hass.async_add_executor_job` for blocking operations
- Background tasks should use `entry.async_on_unload` for cleanup

### Error Handling

- Use specific exceptions (`ServiceValidationError`, `HomeAssistantError`, `ConfigEntryNotReady`)
- Keep try blocks minimal - process data outside try/catch
- Bare exceptions only allowed in config flows and background tasks
- Always use `from` when raising exceptions

### Entity Naming

- Set `_attr_has_entity_name = True` on all entities
- Device info should include identifiers and connections
- Use translation keys for internationalization

### Coordinator Pattern

```python
class MyCoordinator(DataUpdateCoordinator[MyData]):
    def __init__(self, hass: HomeAssistant, client: MyClient, config_entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            logger=LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=5),
            config_entry=config_entry,  # Always pass this
        )
```

### Service Registration

- Register all services in `async_setup`, not `async_setup_entry`
- Validate config entry exists and is loaded before executing service
- Use schema validation from `schemas.py`

### Logging

- Use lazy logging: `_LOGGER.debug("Message with %s", variable)`
- No periods at end of messages
- No sensitive data in logs
- Log unavailability once, then log when recovered

## Testing Guidelines

### Test Structure

- Tests in `tests/` mirror component structure
- Use pytest fixtures from `conftest.py`
- Mock external dependencies
- Test async code with `asyncio_mode = auto`

### Common Fixtures

- `hass`: Home Assistant instance
- `mock_config_entry`: ConfigEntry with test data
- `coordinator`: Initialized coordinator
- `init_integration`: Fully set up integration

### Snapshot Testing

- Use snapshots for complex data structures
- Run with `--snapshot-update` to regenerate
- Always verify snapshots after updating

## Configuration Notes

### Environment Sensors

Required for Bayesian monitoring:

- Temperature sensor
- Humidity sensor
- VPD sensor

Optional:

- Light sensor (enables day/night logic)
- CO2 sensor
- Circulation fan
- Dehumidifier (for automated control)

### Irrigation

- Supports scheduled watering times
- Crop steering strategies (vegetative, generative, balanced)
- Automatic drainage after irrigation

### Dehumidifier Control

- VPD or humidity target selection
- Stage-specific targets (veg, early/mid/late flower, dry, cure)
- Day/night target variations
- Hysteresis to prevent short-cycling

## Development Workflow

1. **Make Changes**: Edit code in `custom_components/growspace_manager/`
2. **Run Tests**: Always run relevant tests after changes
3. **Check Coverage**: Ensure coverage doesn't decrease
4. **Run Linters**: Pre-commit hooks or manual ruff/mypy
5. **Verify**: Full test suite before marking complete

## Key Files to Know

- `coordinator.py`: Central data manager - most features touch this
- `models.py`: Data structures - understand these first
- `const.py`: All constants, enums, defaults
- `schemas.py`: Service schema definitions
- `serializers.py`: Data serialization for storage
- `config_handlers/`: Config flow step handlers
- `bayesian_evaluator.py`: Environmental condition logic
- `services/`: Service implementations by domain

## Common Pitfalls

1. **Don't access `hass.data` directly in tests** - use proper fixtures and integration setup
2. **Never make polling intervals user-configurable** - integration determines intervals
3. **Don't allow user-configurable config entry names** (except for helper integrations)
4. **Always validate config entry is loaded before service execution**
5. **Use the parent venv at `/home/maxi/core/core/.venv`**, not a local one
6. **Run tests after every code change** - don't wait until the end

## Refactoring Quick Reference

This section helps quickly identify anti-patterns and refactoring opportunities when reviewing code.

### Anti-Pattern Checklist

**God Object** - Class doing too many things:

- ❌ >1000 lines in a single file
- ❌ >50 methods in one class
- ❌ >10 distinct responsibilities
- ❌ 20+ passthrough/delegation methods
- 📍 Current: `coordinator.py` (1,384 lines, 86 methods)

**Tight Coupling** - Classes too dependent on each other:

- ❌ Direct coordinator attribute access (e.g., `self.coordinator.growspaces`)
- ❌ Circular dependencies between modules
- ❌ Classes needing entire objects for small pieces of data
- 📍 Current: `binary_sensor.py` accessing coordinator internals

**Bare Exception Blocks** - Catching all errors:

- ❌ `except Exception:` without specific types
- ❌ Swallowing errors without proper logging
- ❌ Losing error context in service calls
- 📍 Current: 96+ occurrences across service files

**Long Methods** - Functions doing too much:

- ❌ >50 lines in a single method
- ❌ >5 parameters
- ❌ Nested conditionals >3 levels deep
- 📍 Current: `environment_config_handler.py` (112-line methods)

**Duplicate Code** - Same logic in multiple places:

- ❌ Copy-paste patterns
- ❌ Similar logic in 3+ places
- ❌ Repeated validation boilerplate
- 📍 Current: Service handler patterns, ID resolution logic

### Pattern Recognition Rules

Quick "if you see X, consider Y" guide:

| If You See...                              | Consider...                    | Location              |
| ------------------------------------------ | ------------------------------ | --------------------- |
| Service with 20+ passthrough methods       | Facade/Adapter pattern         | coordinator.py:300+   |
| Multiple classes accessing `coordinator.X` | Extract to injected dependency | binary_sensor.py:400+ |
| Same validation in 5+ places               | Shared validator class         | services/             |
| `try/except Exception` in services         | Specific exception types       | services/\*.py        |
| 100+ line method                           | Extract Method refactoring     | config_handlers/      |
| Repeated ID resolution logic               | Shared utility module          | services/             |
| Deep nesting (>3 levels)                   | Guard clauses or extraction    | config_handlers/      |
| Classes with >10 dependencies              | Dependency grouping/facade     | coordinator.py:init   |

### Code Smell Indicators

| Smell                      | Indicator                                | Severity  | Quick Fix                  | Example Location             |
| -------------------------- | ---------------------------------------- | --------- | -------------------------- | ---------------------------- |
| **God Object**             | >1000 lines, 50+ methods                 | 🔴 High   | Extract services/managers  | coordinator.py               |
| **Feature Envy**           | Accesses other object's data 5+ times    | 🟡 Medium | Move method to owner       | binary_sensor.py:413-416     |
| **Shotgun Surgery**        | Change requires touching 5+ files        | 🔴 High   | Consolidate logic          | service handlers             |
| **Primitive Obsession**    | Using dicts/lists instead of dataclasses | 🟢 Low    | Introduce dataclass        | Already addressed            |
| **Long Parameter List**    | >5 parameters in constructor/method      | 🟡 Medium | Introduce parameter object | Some services                |
| **Duplicate Code**         | Identical blocks in 3+ places            | 🟡 Medium | Extract to utility         | services/                    |
| **Inappropriate Intimacy** | Classes too familiar with internals      | 🟡 Medium | Reduce coupling            | binary_sensor ↔ coordinator |

## Refactoring Playbook

Detailed guides for refactoring the top anti-patterns found in this codebase.

### 1. God Object - Coordinator Pattern

**Problem**: `coordinator.py` (1,384 lines, 86 methods)

**Identification**:

- File exceeds 1000 lines
- Class has 50+ methods
- Mixes multiple responsibilities: data persistence, business logic, sub-coordinator management, service delegation
- Many passthrough methods that just delegate to specialized services

**Why Problematic**:

- **Testing Complexity**: Hard to test in isolation, requires extensive mocking
- **Violation of SRP**: Single Responsibility Principle - class has too many reasons to change
- **Cognitive Overload**: Developers must understand entire system to modify any part
- **Merge Conflicts**: High-traffic file causes frequent git conflicts

**Current Examples** (coordinator.py):

```python
# 20+ passthrough methods like these:
async def async_add_plant(self, ...) -> str:
    """Add a plant - delegates to plant service."""
    return await self._plant_service.add_plant(...)

async def async_water_plant(self, ...) -> None:
    """Water a plant - delegates to watering service."""
    await self._watering_service.water_plant(...)

async def async_apply_ipm(self, ...) -> None:
    """Apply IPM - delegates to IPM service."""
    await self._ipm_service.apply_ipm(...)
```

**Refactoring Approach**:

1. **Extract Passthrough Methods** → Create ServiceFacade
   - Move all passthrough methods to a dedicated facade class
   - Coordinator keeps only core coordination logic

2. **Extract Initialization** → Create CoordinatorBuilder
   - Move 100+ lines of initialization to builder pattern
   - Simplifies testing and makes dependencies explicit

3. **Extract Sub-Coordinator Management** → Enhance SubsystemManager
   - Move irrigation/dehumidifier coordinator management
   - Let manager handle lifecycle completely

**Before** (coordinator.py, simplified):

```python
class GrowspaceCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, storage_manager, config_entry):
        # 100+ lines of initialization
        self._plant_service = PlantService(...)
        self._watering_service = WateringService(...)
        self._ipm_service = IPMService(...)
        # ... 10+ more services

    async def async_add_plant(self, ...):
        return await self._plant_service.add_plant(...)

    # ... 20+ more passthrough methods
    # ... 50+ actual coordinator methods
```

**After** (with ServiceFacade):

```python
class GrowspaceCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, storage_manager, config_entry):
        # Simplified initialization via builder
        self.services = ServiceFacade(self)  # Facade handles delegation
        # Only core coordinator state here

    # Remove passthrough methods
    # Keep only actual coordination logic
    async def async_commit(self): ...
    async def _async_update_data(self): ...
```

**Testing Strategy**:

- Test services independently without full coordinator
- Mock only what each service actually needs
- Test coordinator with service facade mocked

**Migration Path**:

1. Create `ServiceFacade` class in new file
2. Move passthrough methods to facade (one at a time)
3. Update callers to use `coordinator.services.add_plant()` instead
4. Once all moved, remove old methods
5. Tests should still pass at each step

---

### 2. Bare Exception Handling

**Problem**: 96+ occurrences of `except Exception` across service files

**Identification**:

```python
# ❌ Too broad
except Exception as err:
    _LOGGER.exception("Failed")
    raise ServiceValidationError(f"Failed: {err}") from err
```

**Why Problematic**:

- **Masks Bugs**: Catches programming errors (AttributeError, KeyError) that should fail fast
- **Loses Context**: Generic error messages don't tell users what went wrong
- **Makes Debugging Hard**: Root cause hidden behind generic wrapper
- **Violates HA Standards**: Should use specific exceptions except in config flows

**Current Examples**:

❌ **Bad** (services/ipm.py:51):

```python
try:
    preset = coordinator.nutrient_manager.get_ipm_preset(preset_id)
except Exception as err:
    raise ServiceValidationError(
        f"IPM preset '{preset_id}' not found"
    ) from err
```

**Refactoring Approach**:

1. **Identify Specific Exceptions**: What can actually be raised?
   - `KeyError` → Preset not found
   - `ValidationChangeError` → Invalid data
   - `asyncio.TimeoutError` → Device timeout

2. **Catch Specific First, Generic Last**:

   ```python
   except KeyError:
       # Handle missing key
   except ValidationChangeError:
       # Handle validation
   except Exception:  # Only if truly needed
       # Unexpected errors
   ```

3. **Use HA Exception Hierarchy**:
   - `ServiceValidationError` → User input errors
   - `HomeAssistantError` → Device/network errors
   - Let programming errors bubble up

✅ **Good** (refactored):

```python
try:
    preset = coordinator.nutrient_manager.get_ipm_preset(preset_id)
except KeyError as err:
    raise ServiceValidationError(
        f"IPM preset '{preset_id}' not found. "
        f"Available presets: {list(coordinator.nutrient_manager.ipm_presets.keys())}"
    ) from err
except ValidationChangeError as err:
    raise ServiceValidationError(
        f"Invalid IPM preset data: {err}"
    ) from err
# No generic Exception handler needed - let other errors bubble
```

**Exception Decision Tree**:

```
User provided invalid input?
  → ServiceValidationError (with translation_key if possible)

Device/network communication failed?
  → HomeAssistantError (user can retry)

Configuration invalid?
  → ConfigEntryError / ConfigEntryNotReady

Programming error (AttributeError, KeyError in internal code)?
  → Let it bubble (catch in tests, fix the bug)

Truly unexpected and need graceful degradation?
  → except Exception (ONLY in config flows & background tasks)
```

**Testing Strategy**:

- Test each specific exception path independently
- Verify error messages are helpful
- Ensure programming errors still fail tests (don't catch them)

---

### 3. Tight Coupling - Binary Sensors

**Problem**: `BayesianEnvironmentSensor` directly accesses coordinator internals

**Identification**:

```python
# ❌ Tight coupling
self.coordinator.growspaces
self.coordinator.get_growspace_plants()
self.coordinator.notification_manager
self.coordinator.strain_library
```

**Why Problematic**:

- **Hard to Test**: Must mock entire coordinator to test sensor logic
- **Prevents Reuse**: Can't use sensor logic in different contexts
- **Fragile**: Changes to coordinator break sensors
- **Hidden Dependencies**: Not clear what data sensor actually needs

**Current Example** (binary_sensor.py:411-416):

```python
for sensor in light_sensors:
    is_on, valid = self._check_light_sensor(sensor)
    if valid:
        any_valid = True
        if is_on:
            any_on = True
```

The sensor directly accesses `self.coordinator` throughout its logic, tightly coupling it to the coordinator's structure.

**Refactoring Approach**:

1. **Extract Sensor Logic** → Create Strategy Classes
2. **Inject Only Needed Dependencies** → Don't pass entire coordinator
3. **Use Repository Pattern** → Abstract data access

✅ **Good** (with dependency injection):

```python
class BayesianStressEvaluator:
    """Evaluates stress conditions - no coordinator dependency."""

    def __init__(
        self,
        get_growspace: Callable[[str], Growspace | None],
        get_plants: Callable[[str], list[Plant]],
        get_environment: Callable[[str], EnvironmentState | None],
    ):
        self._get_growspace = get_growspace
        self._get_plants = get_plants
        self._get_environment = get_environment

    def evaluate_stress(self, growspace_id: str) -> float:
        """Calculate stress probability - testable in isolation."""
        growspace = self._get_growspace(growspace_id)
        if not growspace:
            return 0.0

        plants = self._get_plants(growspace_id)
        environment = self._get_environment(growspace_id)
        # ... stress calculation logic
        return probability

# In binary_sensor.py
class BayesianEnvironmentSensor(CoordinatorEntity):
    def __init__(self, coordinator, growspace_id):
        self.evaluator = BayesianStressEvaluator(
            get_growspace=lambda gid: coordinator.growspaces.get(gid),
            get_plants=coordinator.get_growspace_plants,
            get_environment=coordinator.get_environment_state,
        )

    @property
    def is_on(self) -> bool:
        return self.evaluator.evaluate_stress(self.growspace_id) > 0.5
```

**Testing Strategy**:

- Test `BayesianStressEvaluator` with simple lambda functions (no coordinator needed)
- Mock only the three data access functions
- Sensor tests just verify evaluator is called correctly

---

### 4. Long Methods - Config Handlers

**Problem**: 112-line methods in `environment_config_handler.py`

**Identification**:

- Methods >50 lines
- Nested conditionals >3 levels deep
- Multiple responsibilities in one method
- Hard to understand control flow

**Why Problematic**:

- **Hard to Understand**: Cognitive load too high
- **Hard to Test**: Can't test individual pieces
- **Hard to Modify**: Fear of breaking unrelated logic
- **Duplication**: Repeated patterns can't be extracted

**Refactoring Approach**:

1. **Extract Method**: Break into smaller, named functions
2. **Extract Validation**: Create base class for common patterns
3. **Use Composition**: Separate data transformation

**Before** (environment_config_handler.py:84-196, simplified):

```python
async def async_step_configure_environment(self, user_input):
    # Validation (10 lines)
    if self.config_entry is None:
        return self.flow.async_abort(reason="setup_error")
    coordinator = self.config_entry.runtime_data
    if coordinator is None:
        return self.flow.async_abort(reason="setup_error")

    # Get growspace (5 lines)
    growspace_id = self.flow.context.get("growspace_id")
    growspace = coordinator.growspaces.get(growspace_id)

    # Handle form submission (50 lines)
    if user_input is not None:
        # Process irrigation tanks (15 lines)
        # Build schema (20 lines)
        # Validate inputs (15 lines)

    # Build default schema (30 lines)
    # Return form (10 lines)
```

**After** (with extraction):

```python
async def async_step_configure_environment(self, user_input):
    coordinator = self._validate_and_get_coordinator()
    growspace = self._get_current_growspace(coordinator)

    if user_input is not None:
        return await self._process_environment_submission(
            coordinator, growspace, user_input
        )

    return self._show_environment_form(growspace)

def _validate_and_get_coordinator(self):
    """Extract validation to reduce duplication."""
    if self.config_entry is None:
        raise AbortFlow("setup_error")
    coordinator = self.config_entry.runtime_data
    if coordinator is None:
        raise AbortFlow("setup_error")
    return coordinator

async def _process_environment_submission(self, coordinator, growspace, user_input):
    """Handle form submission - focused responsibility."""
    irrigation_tanks = self._transform_irrigation_tanks(user_input)
    validated_input = self._validate_environment_input(user_input)
    # ... update logic
    return self.flow.async_create_entry(title="", data={})

def _show_environment_form(self, growspace):
    """Build and show form - focused responsibility."""
    schema = self._build_environment_schema(growspace)
    return self.flow.async_show_form(step_id="configure_environment", data_schema=schema)
```

**Testing Strategy**:

- Test each extracted method independently
- Test main method as orchestration (mocking extracted methods)
- Easier to verify edge cases in small methods

---

### 5. Duplicate Code - Service Handlers

**Problem**: Repeated patterns across service files

**Identification**:

- Similar code blocks in 3+ files
- ID resolution logic duplicated
- Validation boilerplate repeated
- Error handling patterns copied

**Why Problematic**:

- **Inconsistency**: Each copy may handle things slightly differently
- **Maintenance Burden**: Bug fixes must be applied in multiple places
- **Bug Multiplication**: Bug in pattern gets copied everywhere

**Current Examples**:

Repeated in services/plant.py, services/growspace.py, services/irrigation.py:

```python
# ❌ Duplicated ID resolution
try:
    entity_registry = hass.data.get(er.DATA_REGISTRY)
    if entity_id and entity_id.startswith("sensor."):
        entity = entity_registry.async_get(entity_id)
        if entity and entity.unique_id:
            # Parse unique_id...
except Exception as e:
    _LOGGER.exception("Error")
```

**Refactoring Approach**:

1. **Extract to Shared Utility Module**: `services/utils.py`
2. **Create Base Service Class**: Common patterns
3. **Use Template Method Pattern**: Override specific parts

✅ **Good** (with extraction):

**services/utils.py** (new file):

```python
"""Shared utilities for service handlers."""

def resolve_entity_to_id(hass: HomeAssistant, entity_id: str) -> str | None:
    """Resolve entity_id to internal ID (plant_id or growspace_id).

    Args:
        hass: Home Assistant instance
        entity_id: Entity ID to resolve

    Returns:
        Resolved ID or None if not found

    Raises:
        ServiceValidationError: If entity not found
    """
    try:
        entity_registry = er.async_get(hass)
        entity = entity_registry.async_get(entity_id)
        if not entity or not entity.unique_id:
            raise ServiceValidationError(f"Entity {entity_id} not found")

        # Parse unique_id to extract plant_id or growspace_id
        parts = entity.unique_id.split("_")
        if len(parts) < 2:
            raise ServiceValidationError(f"Invalid entity unique_id: {entity.unique_id}")

        return parts[0]  # Return ID part
    except ServiceValidationError:
        raise
    except Exception as err:
        raise ServiceValidationError(
            f"Failed to resolve entity {entity_id}: {err}"
        ) from err


class BaseService:
    """Base class for domain services with common patterns."""

    def __init__(self, hass: HomeAssistant, repository: GrowspaceRepository):
        self.hass = hass
        self.repository = repository

    def _validate_growspace_exists(self, growspace_id: str) -> Growspace:
        """Common validation pattern."""
        growspace = self.repository.get_growspace(growspace_id)
        if not growspace:
            raise ServiceValidationError(f"Growspace {growspace_id} not found")
        return growspace

    def _validate_plant_exists(self, plant_id: str) -> Plant:
        """Common validation pattern."""
        plant = self.repository.get_plant(plant_id)
        if not plant:
            raise ServiceValidationError(f"Plant {plant_id} not found")
        return plant
```

**Using the utilities**:

```python
from .utils import resolve_entity_to_id, BaseService

class PlantService(BaseService):
    async def water_plant(self, plant_id: str, ...):
        plant = self._validate_plant_exists(plant_id)  # Shared method
        # ... watering logic
```

**Testing Strategy**:

- Test shared utilities thoroughly once
- Service tests just verify utilities are called correctly
- Reduces test duplication

## Design Patterns in Use

Catalog of design patterns currently implemented and opportunities for new patterns.

### Patterns Already Implemented

#### Coordinator Pattern

**What it is**: DataUpdateCoordinator manages centralized data and notifies entities of changes

**Why we use it**: Home Assistant standard for efficient entity updates, prevents polling

**Where to find it**:

- `coordinator.py:67` - GrowspaceCoordinator class
- `irrigation_coordinator.py` - IrrigationCoordinator
- `vwc_irrigation_coordinator.py` - VWCIrrigationCoordinator
- `dehumidifier_coordinator.py` - DehumidifierCoordinator

**How to use it**:

```python
class MyCoordinator(DataUpdateCoordinator[MyData]):
    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            logger=LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=5),
            config_entry=config_entry,
        )

    async def _async_update_data(self) -> MyData:
        """Fetch data from source."""
        return await self._fetch_data()
```

**When to apply it**: Any time you need to manage shared state that multiple entities need to display

---

#### Service Locator Pattern

**What it is**: Centralized registry to locate the correct coordinator instance

**Why we use it**: Support multiple config entries (multi-instance support)

**Where to find it**:

- `service_coordinator_locator.py:15` - ServiceCoordinatorLocator class

**How to use it**:

```python
locator = ServiceCoordinatorLocator(hass)
coordinator = locator.get_coordinator_for_growspace(growspace_id)
# or
coordinator = locator.get_coordinator_for_plant(plant_id)
```

**When to apply it**: When services need to route to correct coordinator based on entity ID

---

#### Repository Pattern

**What it is**: Abstraction layer for data access, separating business logic from data storage

**Why we use it**: Encapsulates data access, makes testing easier, reduces coordinator responsibility

**Where to find it**:

- `data_access/growspace_repository.py:15` - GrowspaceRepository class

**How to use it**:

```python
class GrowspaceRepository:
    def get_growspace(self, growspace_id: str) -> Growspace | None:
        return self.growspaces.get(growspace_id)

    def add_growspace(self, growspace: Growspace) -> None:
        self.growspaces[growspace.id] = growspace

# Usage
repository = GrowspaceRepository(data_dict)
growspace = repository.get_growspace("tent1")
```

**When to apply it**: When you need clean separation between data access and business logic

---

#### Service Layer Pattern

**What it is**: Domain logic separated into dedicated service classes

**Why we use it**: Reduces coordinator complexity, improves testability, clear responsibility boundaries

**Where to find it**:

- `services/growspace_service.py:45` - GrowspaceService
- `services/plant_service.py:45` - PlantService
- `services/watering_service.py` - WateringService
- `services/training_service.py` - TrainingService
- `services/ipm_service.py` - IPMService

**How to use it**:

```python
class PlantService:
    def __init__(
        self,
        hass: HomeAssistant,
        repository: GrowspaceRepository,
        validator: GrowspaceValidator,
        save_callback: Callable,
        lock: asyncio.Lock,
    ):
        self.hass = hass
        self.repository = repository
        self.validator = validator
        self._save_callback = save_callback
        self._lock = lock

    async def add_plant(self, ...) -> str:
        """Business logic for adding a plant."""
        async with self._lock:
            # Validate
            # Create plant
            # Save
            await self._save_callback()
        return plant_id
```

**When to apply it**: When domain logic doesn't belong in coordinator or entities

---

#### Event Bus Pattern

**What it is**: Pub/sub system for domain events, decouples event producers from consumers

**Why we use it**: Integrates with HA logbook, allows loose coupling of components

**Where to find it**:

- `event_bus_pkg/event_bus.py:10` - GrowspaceEventBus
- `events.py` - Event type constants and helper functions

**How to use it**:

```python
# Publishing events
await async_fire_plant_event(
    hass,
    EVENT_PLANT_ADDED,
    plant_id=plant.id,
    growspace_id=growspace_id,
    details={"strain": plant.strain_name},
)

# HA logbook automatically consumes these events
```

**When to apply it**: When you need to notify other parts of system without direct coupling

---

#### Strategy Pattern

**What it is**: Encapsulates algorithms, making them interchangeable

**Why we use it**: Different irrigation strategies (time-based vs VWC-based), different evaluation strategies

**Where to find it**:

- `irrigation_coordinator.py` - Time-based strategy
- `vwc_irrigation_coordinator.py` - VWC-based strategy
- `strategies/stress.py` - Stress evaluation strategy
- `strategies/mold.py` - Mold evaluation strategy
- `strategies/optimal.py` - Optimal conditions strategy

**How to use it**:

```python
# Base strategy
class EvaluatorStrategy(ABC):
    @abstractmethod
    def evaluate(self, environment: EnvironmentState, ...) -> float:
        """Calculate probability."""

# Concrete strategies
class StressEvaluatorStrategy(EvaluatorStrategy):
    def evaluate(self, environment, ...) -> float:
        # Stress-specific logic
        return probability

# Usage
strategy = StressEvaluatorStrategy()
probability = strategy.evaluate(environment, plants)
```

**When to apply it**: When you have multiple algorithms for the same problem (irrigation, evaluation, etc.)

---

#### Manager Pattern

**What it is**: Dedicated classes to manage specific concerns or subsystems

**Why we use it**: Delegate complex subsystem management, reduce coordinator size

**Where to find it**:

- `managers/nutrient.py:20` - NutrientManager (manages presets and inventory)
- `managers/subsystem.py:20` - SubsystemManager (manages sub-coordinators)

**How to use it**:

```python
class NutrientManager:
    def __init__(self):
        self.nutrient_presets: dict[str, NutrientPreset] = {}
        self.ipm_presets: dict[str, IPMPreset] = {}

    def get_nutrient_preset(self, preset_id: str) -> NutrientPreset:
        """Manage nutrient preset retrieval."""
        return self.nutrient_presets[preset_id]

# Usage in coordinator
self.nutrient_manager = NutrientManager()
preset = self.nutrient_manager.get_nutrient_preset("bloom_boost")
```

**When to apply it**: When a coordinator needs to manage a complex subsystem with its own lifecycle

---

### Pattern Opportunities

Patterns that could improve the codebase if applied:

#### Facade Pattern

**Current Problem**: Coordinator has 20+ passthrough methods that just delegate to services

**Pattern Solution**: Create a ServiceFacade that groups related service methods

**Implementation Sketch**:

```python
class ServiceFacade:
    """Unified interface to all domain services."""

    def __init__(self, coordinator):
        self._coordinator = coordinator
        # Initialize all services
        self.plants = PlantServiceFacade(coordinator._plant_service)
        self.growspaces = GrowspaceServiceFacade(coordinator._growspace_service)
        self.watering = WateringServiceFacade(coordinator._watering_service)

# Usage
coordinator.services.plants.add(...)
coordinator.services.watering.water(...)
```

**Migration Path**:

1. Create `ServiceFacade` class
2. Move passthrough methods to facade
3. Update callers: `coordinator.async_add_plant()` → `coordinator.services.plants.add()`
4. Remove old passthrough methods

**Benefits**: Reduces coordinator from 1,384 lines to ~800 lines, clearer API

---

#### Builder Pattern

**Current Problem**: Coordinator `__init__` has 100+ lines of initialization logic

**Pattern Solution**: Use builder to construct coordinator with all dependencies

**Implementation Sketch**:

```python
class CoordinatorBuilder:
    """Builds GrowspaceCoordinator with all dependencies."""

    def __init__(self, hass: HomeAssistant, storage_manager: StorageManager):
        self.hass = hass
        self.storage_manager = storage_manager

    async def build(self, config_entry: ConfigEntry) -> GrowspaceCoordinator:
        """Build coordinator with all dependencies."""
        # Load data
        data = await self.storage_manager.async_load()

        # Create repository
        repository = GrowspaceRepository(data)

        # Create coordinator
        coordinator = GrowspaceCoordinator(
            hass=self.hass,
            repository=repository,
            config_entry=config_entry,
        )

        # Initialize services
        await self._initialize_services(coordinator)

        return coordinator

# Usage
builder = CoordinatorBuilder(hass, storage_manager)
coordinator = await builder.build(config_entry)
```

**Migration Path**:

1. Create `CoordinatorBuilder` class
2. Move initialization logic to builder methods
3. Update `async_setup_entry` to use builder
4. Simplify coordinator `__init__`

**Benefits**: Easier testing (mock builder), clearer initialization flow

---

#### Template Method Pattern

**Current Problem**: Service handlers have repeated boilerplate (validation, locking, error handling)

**Pattern Solution**: Base class with template method, subclasses override specific steps

**Implementation Sketch**:

```python
class BaseServiceHandler(ABC):
    """Template for service execution."""

    async def execute(self, **kwargs) -> Any:
        """Template method - defines execution flow."""
        async with self._lock:
            self._validate_inputs(**kwargs)
            result = await self._perform_operation(**kwargs)
            await self._save_changes()
            self._fire_events(result)
            return result

    @abstractmethod
    async def _perform_operation(self, **kwargs) -> Any:
        """Override in subclass."""

    def _validate_inputs(self, **kwargs) -> None:
        """Default validation - can override."""
        pass

# Concrete implementation
class AddPlantHandler(BaseServiceHandler):
    async def _perform_operation(self, growspace_id, strain, position):
        plant = Plant(...)
        self.repository.add_plant(plant)
        return plant.id
```

**Migration Path**:

1. Create `BaseServiceHandler` with template method
2. Convert one service to use template (e.g., PlantService)
3. Test thoroughly
4. Migrate other services one at a time

**Benefits**: Eliminates duplicate boilerplate, ensures consistent patterns

---

#### Chain of Responsibility Pattern

**Current Problem**: Validation logic scattered across services and validator class

**Pattern Solution**: Chain of validators, each responsible for one validation rule

**Implementation Sketch**:

```python
class ValidationHandler(ABC):
    def __init__(self, next_handler=None):
        self._next = next_handler

    def validate(self, context: ValidationContext) -> None:
        self._check(context)
        if self._next:
            self._next.validate(context)

    @abstractmethod
    def _check(self, context: ValidationContext) -> None:
        pass

class PositionBoundsValidator(ValidationHandler):
    def _check(self, context):
        if context.position not in range(context.growspace.grid_size):
            raise ServiceValidationError("Position out of bounds")

class PositionOccupiedValidator(ValidationHandler):
    def _check(self, context):
        if context.repository.is_position_occupied(context.position):
            raise ServiceValidationError("Position already occupied")

# Build chain
validator = PositionBoundsValidator(
    next_handler=PositionOccupiedValidator(
        next_handler=PlantStageValidator()
    )
)

# Use chain
validator.validate(ValidationContext(...))
```

**Migration Path**:

1. Create `ValidationHandler` base class
2. Extract validation rules to individual handlers
3. Build validation chains in services
4. Deprecate monolithic validator methods

**Benefits**: Single Responsibility, easily add/remove validation rules

---

#### Observer Pattern (Enhanced)

**Current Problem**: Entity updates only through coordinator's `async_set_updated_data`

**Pattern Solution**: Direct observer registration for fine-grained updates

**Implementation Sketch**:

```python
class EntityObserver(ABC):
    @abstractmethod
    async def on_entity_updated(self, entity_id: str, data: Any) -> None:
        pass

class EntityPublisher:
    def __init__(self):
        self._observers: dict[str, list[EntityObserver]] = {}

    def subscribe(self, entity_id: str, observer: EntityObserver) -> None:
        self._observers.setdefault(entity_id, []).append(observer)

    async def notify(self, entity_id: str, data: Any) -> None:
        for observer in self._observers.get(entity_id, []):
            await observer.on_entity_updated(entity_id, data)

# Usage - reduce full coordinator updates
await publisher.notify("plant.tomato_1", plant_data)
```

**Migration Path**:

1. Create `EntityPublisher` in coordinator
2. Add observer interface for entities
3. Migrate high-frequency updates to use publisher
4. Keep coordinator updates for full refreshes

**Benefits**: Reduces unnecessary entity updates, improves performance

## Architectural Decision Guidelines

Decision frameworks for common architectural choices in this codebase.

### When to Extract a Service

**Decision Tree**:

```
Does this logic belong to a specific domain?
├─ YES: Is it used by multiple components?
│  ├─ YES: Create domain service in services/
│  └─ NO: Keep in single component (don't over-abstract)
└─ NO: What kind of logic is it?
   ├─ Coordination logic → Keep in coordinator
   ├─ Data access logic → Add to repository
   ├─ Presentation logic → Add to view_model_builder
   ├─ Validation logic → Add to validator
   └─ Utility logic → Create in utils/
```

**Examples**:

✅ **Extract to Service**:

- Plant lifecycle management (multiple components use it)
- Watering operations (complex domain logic)
- IPM application (distinct domain concern)

❌ **Don't Extract**:

- Simple data transformation used once
- Coordinator-specific state management
- UI-specific formatting

**Rule of Three**: Only extract when you need it in 3+ places, or it's complex enough to deserve isolation.

---

### Dependency Injection Strategy

**What to Inject** ✅:

- **Data Access**: Repository, database connections
- **Validators**: Domain validators, schema validators
- **Managers**: Subsystem managers, external service clients
- **Callbacks**: Save callbacks, notification callbacks
- **Locks**: For thread safety

**What NOT to Inject** ❌:

- **Entire coordinator**: Inject only what you need from it
- **HomeAssistant object**: Unless service actually needs hass capabilities
- **Storage manager**: Use callbacks instead of direct storage access
- **Entity registry**: Pass data, not registry

**Constructor Patterns**:

✅ **Good** (explicit dependencies):

```python
class PlantService:
    def __init__(
        self,
        hass: HomeAssistant,  # Needed for event firing
        repository: GrowspaceRepository,  # Data access
        validator: GrowspaceValidator,  # Validation
        save_callback: Callable,  # Persistence
        lock: asyncio.Lock,  # Thread safety
    ):
        self.hass = hass
        self.repository = repository
        self.validator = validator
        self._save_callback = save_callback
        self._lock = lock
```

❌ **Bad** (too many dependencies):

```python
class PlantService:
    def __init__(self, coordinator: GrowspaceCoordinator):
        # Now dependent on entire coordinator structure
        self.coordinator = coordinator
```

**Callbacks vs Direct Dependencies**:

Use **callbacks** when:

- Operation triggers side effect in another component
- You don't want reverse dependency
- Example: `save_callback()` to trigger persistence

Use **direct dependencies** when:

- You need to query/command the dependency
- Clear ownership relationship
- Example: `repository.get_plant(id)` for data access

---

### Error Handling Strategy

**Decision Matrix**:

| Scenario                            | Exception Type                                   | Translation Key? | Example                     |
| ----------------------------------- | ------------------------------------------------ | ---------------- | --------------------------- |
| User provided invalid input         | `ServiceValidationError`                         | Yes (Gold tier)  | Invalid plant position      |
| Required data not found             | `ServiceValidationError`                         | Yes              | Plant ID not found          |
| Device/network communication failed | `HomeAssistantError`                             | Optional         | Failed to connect to sensor |
| Configuration is invalid            | `ConfigEntryError`                               | No               | Malformed config data       |
| Temporary setup failure             | `ConfigEntryNotReady`                            | No               | Device offline during setup |
| Programming error                   | **Let it bubble**                                | No               | AttributeError, KeyError    |
| Truly unexpected                    | `Exception` (config flows/background tasks only) | No               | Unknown error               |

**Error Message Guidelines**:

✅ **Good Error Messages**:

```python
# Specific, actionable
raise ServiceValidationError(
    f"Plant position {position} is out of bounds. "
    f"Valid positions: 0-{growspace.grid_size - 1}"
)

# With translation key (Gold tier)
raise ServiceValidationError(
    translation_domain=DOMAIN,
    translation_key="plant_position_out_of_bounds",
    translation_placeholders={
        "position": position,
        "max_position": growspace.grid_size - 1,
    },
)
```

❌ **Bad Error Messages**:

```python
# Vague, not actionable
raise ServiceValidationError("Invalid position")

# Too technical for users
raise ServiceValidationError(
    f"Position {position} exceeds grid.shape[0] * grid.shape[1]"
)
```

**Exception Chaining**:

Always use `from` to preserve traceback:

```python
try:
    data = await api.fetch()
except ApiError as err:
    raise HomeAssistantError("Failed to fetch data") from err
    #                                                   ^^^^^^^^
```

**When to Catch vs Let Bubble**:

✅ **Catch** when:

- You can handle it meaningfully
- You need to transform it for user
- You can provide context

❌ **Let bubble** when:

- Programming error (fix the bug)
- No meaningful handling possible
- Already specific enough

---

### Testing Principles

**Test Through Public Interfaces**:

✅ **Good**:

```python
async def test_add_plant(coordinator):
    """Test through public API."""
    plant_id = await coordinator.services.plants.add(
        growspace_id="tent1",
        strain="OG Kush",
        position=0,
    )
    assert plant_id in coordinator.plants
```

❌ **Bad**:

```python
async def test_add_plant(coordinator):
    """Testing internals."""
    plant = Plant(id="123", ...)
    coordinator._plant_service._repository.plants["123"] = plant
    # Fragile - breaks if internals change
```

**Mock at Service Boundaries**:

✅ **Good**:

```python
@pytest.fixture
def mock_repository():
    """Mock data access layer."""
    repo = Mock(spec=GrowspaceRepository)
    repo.get_growspace.return_value = Growspace(...)
    return repo

async def test_service(mock_repository):
    service = PlantService(hass, mock_repository, ...)
    # Test service with mocked data access
```

❌ **Bad**:

```python
async def test_service(coordinator):
    """Mock internal implementation details."""
    with patch.object(coordinator._plant_service, '_some_internal_method'):
        # Too tied to implementation
```

**Fixture Organization**:

Use pytest fixtures for common setups:

```python
@pytest.fixture
async def coordinator(hass, mock_config_entry):
    """Fully initialized coordinator."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    return mock_config_entry.runtime_data

@pytest.fixture
def mock_growspace():
    """Reusable test growspace."""
    return Growspace(
        id="test_tent",
        name="Test Tent",
        grid_size=10,
        # ... other fields
    )
```

**Coverage Goals**:

- **New code**: Aim for >95% coverage
- **Refactored code**: Maintain or improve existing coverage
- **Integration tests**: Test happy path + major error paths
- **Unit tests**: Test edge cases in isolated components

**Test Naming Convention**:

```python
async def test_<action>_<condition>_<expected_result>():
    """Test that <action> under <condition> results in <expected_result>."""
    # Example:
    async def test_add_plant_invalid_position_raises_error():
    async def test_water_plant_success_updates_last_watered():
    async def test_get_growspace_not_found_returns_none():
```

**Snapshot Testing**:

Use snapshots for complex data structures:

```python
async def test_growspace_data_structure(coordinator, snapshot):
    """Verify growspace data structure."""
    growspace = coordinator.growspaces["tent1"]
    assert growspace.to_dict() == snapshot
```

After updating snapshots with `--snapshot-update`, **always run tests again without the flag** to verify.

---

### Code Organization Guidelines

**Module Size Limits**:

- **Files**: Target <500 lines (warning at 800, refactor at 1000+)
- **Classes**: Target <300 lines (warning at 500, refactor at 800+)
- **Methods**: Target <50 lines (warning at 80, refactor at 100+)

**When to Split a Module**:

**Split when**:

- File exceeds 800 lines
- Multiple distinct responsibilities
- Some code rarely used together
- Clear organizational boundary exists

**Example**: `services/plant.py` could split into:

- `services/plant/crud.py` - Create, read, update, delete
- `services/plant/lifecycle.py` - Stage transitions, harvesting
- `services/plant/cloning.py` - Clone operations

**Don't split when**:

- Code is cohesive and < 500 lines
- Would create one-method files
- Split creates more complexity than it removes

**Import Organization**:

Follow ruff/isort conventions:

```python
"""Module docstring."""

from __future__ import annotations  # Always first

# Standard library (alphabetical)
import asyncio
from datetime import date, timedelta
import logging
from typing import Any

# Third-party (alphabetical)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

# Local (relative imports, alphabetical)
from .const import DOMAIN, PlantStage
from .models import Growspace, Plant
from .repository import GrowspaceRepository
```

**File Naming**:

- `snake_case` for all Python files
- Match class name when file contains single primary class
- Use descriptive names: `irrigation_coordinator.py` not `ic.py`

## Home Assistant Integration Standards

This integration follows Home Assistant's development standards. Key requirements for Gold tier:

- Device registry with proper device info
- Diagnostic data collection
- Entity translations
- Config flow with error handling
- Unique IDs for all entities
- Async-first architecture
- Comprehensive test coverage (target: >95%)
