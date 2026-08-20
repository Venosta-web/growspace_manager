## 2024-05-23 - [Optimizing Home Assistant Coordinator Updates] **Learning:** [O(N^2) Anti-Pattern] **Action:** [Pre-index]

### The Problem

The `GrowspaceCoordinator` was performing a nested loop during its periodic update cycle, resulting in O(M*N) complexity where M is growspaces and N is plants.
Specifically, for *each* growspace, it was iterating through *all\* plants to find which ones belonged to it:

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

---

## 2026-01-07 - [Single-Pass Statistics in Chart Rendering]

**Learning:** [Avoid Multiple Iterations]  
**Action:** [Combine min/max/sum in one loop]

### The Problem

In `growspace-env-chart.ts`, the `_computeGraphSeries` function was calculating min, max, and sum using 3 separate array operations:

```typescript
// Old O(3n) approach - iterates array 3 times
let min = Math.min(...dataPoints.map((d) => d.value)); // O(n) + spread
let max = Math.max(...dataPoints.map((d) => d.value)); // O(n) + spread
const sum = dataPoints.reduce((acc, curr) => acc + curr.value, 0); // O(n)
```

The spread operator also has a risk of stack overflow for very large arrays.

### The Solution

Combined all three calculations into a single loop:

```typescript
// New O(n) approach - single pass
let min = dataPoints[0].value;
let max = dataPoints[0].value;
let sum = 0;
for (let i = 0; i < dataPoints.length; i++) {
  const val = dataPoints[i].value;
  if (val < min) min = val;
  if (val > max) max = val;
  sum += val;
}
```

### Impact

- **Theoretical speedup:** ~3x fewer iterations for min/max/sum
- **Memory safety:** Eliminates spread operator stack overflow risk for large datasets
- **Real-world benefit:** More noticeable on 7-day graphs with many data points

### Takeaway

When computing multiple aggregate statistics (min, max, sum, count), always combine them into a single loop. Avoid `Math.min(...array)` for potentially large arrays.
