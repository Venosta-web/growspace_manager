# Behavioral migrations preserve active irrigation semantics

Software upgrades may migrate stored structures but never silently change the meaning of an active Irrigation Recipe, operating limit, fallback, or actuator allocation. Before activation, a migration preserves and validates existing behavior, exports a recoverable configuration snapshot, and presents any unresolved semantic change for review. This slows migrations that could otherwise apply convenient new defaults, but prevents routine software maintenance from becoming an unreviewed agronomic change.
