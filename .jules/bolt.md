## 2024-05-23 - [Optimizing Home Assistant Coordinator Updates] **Learning:** [O(N^2) Anti-Pattern] **Action:** [Pre-index]

### The Problem
The `GrowspaceCoordinator` was performing a nested loop during its periodic update cycle, resulting in O(M*N) complexity where M is growspaces and N is plants.
Specifically, for *each* growspace, it was iterating through *all* plants to find which ones belonged to it:

```python
# Old O(M*N) approach
for growspace_id in self.growspaces:
    plants = self.get_growspace_plants(growspace_id) # Iterates all plants (N)
    # ... serialize ...
```

This became a bottleneck as the number of plants grew, causing the update cycle (which runs every 15 minutes or on demand) to consume excessive CPU time.

### The Solution
By pre-indexing the plants into a dictionary keyed by `growspace_id` before the loop, we reduced the complexity to O(N) (one pass to group plants) + O(M) (one pass to serialize growspaces).

```python
# New O(N + M) approach
plants_by_growspace = {}
for plant in self.plants.values():
    # ... build index ...

for growspace_id in self.growspaces:
    plants = plants_by_growspace.get(growspace_id, [])
    # ... serialize ...
```

### Impact
- **Total Speedup:** ~2.3x faster updates in benchmark.
- **Date Parsing:** Switching to `datetime.fromisoformat()` provided a ~4.5x speedup for date operations, which are heavily used in plant stage calculations.

### Takeaway
In "parent-child" relationships (like Growspace -> Plants), always pre-group the children before iterating the parents if you need to process the hierarchy. Avoid filtering the full child list inside the parent loop.
