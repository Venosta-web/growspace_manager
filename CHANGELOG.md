# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.4] - 2026-01-16

### Added
- Bayesian inference engine for environmental stress and mold risk detection
- AI-powered Grow Master assistant with configurable personalities
- Strain analytics tracking (yield, potency, quality metrics)
- Integrated Pest Management (IPM) system with treatment presets
- Smart irrigation strategies including crop steering
- Dehumidifier automation with stage-specific thresholds
- Nutrient inventory management and tracking
- Timeline event system for plant lifecycle documentation
- Task calendar for scheduled notifications
- WebSocket API for real-time frontend communication
- Comprehensive test suite (99% coverage, 1341 tests)

### Fixed
- Critical `NameError` in `evaluator_strategy.py` preventing test execution
- Import ordering in config handlers

### Changed
- Achieved Gold Quality Scale compliance
- Enhanced type hints across all modules (Python 3.13+)
- Improved error handling in config flows
- Optimized Bayesian probability calculations

### Security
- Input sanitization via Voluptuous schemas
- Safe parsing with `ast.literal_eval` only
- No eval() or exec() usage
- Pathlib for file operations

## [Unreleased]

### Planned
- Additional environment sensor integrations
- Enhanced AI model training capabilities
- Multi-user support
- Cloud backup integration
