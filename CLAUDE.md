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
- Python: 3.13+

## Development Commands

### Testing

All tests should be run using the parent project's virtual environment at `/home/maxi/core/core/.venv` (Python 3.13+):

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

## Home Assistant Integration Standards

This integration follows Home Assistant's development standards. Key requirements for Gold tier:
- Device registry with proper device info
- Diagnostic data collection
- Entity translations
- Config flow with error handling
- Unique IDs for all entities
- Async-first architecture
- Comprehensive test coverage (target: >95%)
