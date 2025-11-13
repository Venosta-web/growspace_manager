## `GEMINI.MD`: Your AI Teammate for Home Assistant Development

This document outlines the development standards and workflows for creating integrations for Home Assistant, a Python-based home automation application. Use this guide with `gemini-cli` to ensure your contributions meet our quality standards.

### Integration Quality Scale

Home Assistant employs an Integration Quality Scale to maintain code quality and a consistent user experience. This scale is divided into four tiers, each with a specific set of rules.

- **Bronze**: The essential foundation for any integration. All Bronze rules are mandatory.
- **Silver**: Introduces enhanced functionality and robustness.
- **Gold**: Encompasses advanced features for a polished integration.
- **Platinum**: The highest standard, reserved for exemplary integrations.

**Applying the Rules:**

1.  **Check `manifest.json`**: The `"quality_scale"` key in this file determines the integration's target quality level.
2.  **Bronze is Mandatory**: Any integration with a defined quality scale must adhere to all Bronze rules.
3.  **Tiered Progression**: An integration must meet all the requirements of the tiers below its target level. For example, a Gold integration must satisfy all Bronze and Silver rules.
4.  **Track Your Progress**: Use the `quality_scale.yaml` file within your integration's directory to monitor your compliance with each rule. Mark rules as `done`, `exempt` (with a clear reason), or `todo`.

### Core Development Principles

**Code Review:**

When reviewing code, please **do not** comment on:

- **Missing imports**: Our static analysis tools will catch these.
- **Code formatting**: `ruff` is our designated formatting tool and will handle this automatically.

**Python Standards:**

- **Version**: Your code must be compatible with Python 3.13 and newer.
- **Modern Python**: We encourage the use of the latest Python features, including:
  - Pattern matching
  - Comprehensive type hints
  - F-strings for all string formatting
  - Dataclasses
  - The walrus operator (`:=`)

**Strict Typing (Platinum Requirement):**

- Provide type hints for all functions, methods, and variables.
- For custom config entry types using `runtime_data`, define them as follows:
  ```python
  type MyIntegrationConfigEntry = ConfigEntry[MyClient]
  ```
- Ensure any libraries you introduce include a `py.typed` file for PEP-561 compliance.

### Writing and Documentation

- **Language**: All code, comments, and documentation must be in American English.
- **Tone**: Maintain a friendly and informative tone.
- **Perspective**: Use the second-person ("you" and "your") in user-facing messages.
- **Clarity**: Write with non-native English speakers in mind.
- **Formatting**:
  - Use backticks for file paths, filenames, variable names, and field entries.
  - Use sentence case for all titles and messages.
  - Avoid abbreviations where possible.

### Asynchronous Programming

All I/O operations must be asynchronous.

**Best Practices:**

- Avoid using `sleep` in loops.
- Use `asyncio.gather` for concurrent await operations in a loop.
- Eliminate all blocking calls.
- Group executor jobs when feasible, as switching between the event loop and the executor is resource-intensive.

**Async Dependencies (Platinum Requirement):**

- All dependencies must be fully `asyncio`-compatible.

**WebSession Injection (Platinum Requirement):**

- Support passing `websession` to dependencies.
  ```python
  client = MyClient(entry.data[CONF_HOST], async_get_clientsession(hass))
  ```
- For cookie handling, use `async_create_clientsession` for `aiohttp` or `create_async_httpx_client` for `httpx`.

### Error and Exception Handling

- **Specificity is Key**: Always choose the most specific exception type available.
- **Keep `try` blocks minimal**: Only wrap the code that can throw an exception.
- **Avoid bare `except:` clauses** except in specific, documented cases like background tasks and config flows to ensure robustness.

### Logging

- **Format**:
  - Do not end log messages with a period.
  - The integration name and domain are added automatically.
  - Never log sensitive data such as API keys, tokens, or passwords.
- **Lazy Logging**: Use lazy logging to avoid performance issues.
  ```python
  _LOGGER.debug("Log message with data: %s", data_variable)
  ```

For a comprehensive guide to all development standards, please refer to the detailed documentation in the `.gemini-guidelines` directory of this repository.

---
