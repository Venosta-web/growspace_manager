"""Memory-only supply claims; decisions and pump effects belong to the controller."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


@dataclass(frozen=True)
class SupplyClaim:
    """A zone is due, without a composed shot. Manual requests are independent."""

    zone_id: str
    due_at: datetime
    source: Literal["schedule", "steering", "manual", "fallback"]
    sequence: int

    def as_dict(self) -> dict[str, str]:
        """Return the card's claim wire form."""
        return {
            "zone_id": self.zone_id,
            "due_at": self.due_at.isoformat(),
            "source": self.source,
        }


class SupplyQueue:
    """FIFO by due minute, zone order for ties, with manual FIFO at the front."""

    def __init__(self) -> None:
        """Begin with no requests or service history."""
        self._claims: list[SupplyClaim] = []
        self._turns: dict[str, tuple[datetime, int]] = {}
        self._sequence = 0

    def contains(self, zone_id: str) -> bool:
        """Whether the zone already has an automatic claim."""
        return any(c.zone_id == zone_id and c.source != "manual" for c in self._claims)

    def claim(
        self,
        zone_id: str,
        due_at: datetime,
        source: Literal["schedule", "steering", "manual", "fallback"],
    ) -> SupplyClaim | None:
        """Admit one automatic claim per zone, or an independent manual run."""
        if source != "manual" and self.contains(zone_id):
            return None
        claim = SupplyClaim(
            zone_id, due_at.replace(second=0, microsecond=0), source, self._sequence
        )
        self._sequence += 1
        self._claims.append(claim)
        return claim

    def ordered(self, zone_order: tuple[str, ...]) -> tuple[SupplyClaim, ...]:
        """Return claims in service order, without releasing any."""
        ranks = {zone: index for index, zone in enumerate(zone_order)}
        return tuple(
            sorted(
                self._claims,
                key=lambda c: (
                    0 if c.source == "manual" else 1,
                    c.sequence if c.source == "manual" else c.due_at,
                    self._turn(c),
                    ranks.get(c.zone_id, len(ranks)),
                    c.sequence,
                ),
            )
        )

    def _turn(self, claim: SupplyClaim) -> int:
        """Place a rejoining zone behind peers still due in the same minute."""
        minute, turn = self._turns.get(claim.zone_id, (claim.due_at, 0))
        return turn if minute == claim.due_at else 0

    def release(self, zone_order: tuple[str, ...]) -> SupplyClaim | None:
        """Release the head whenever the controller's supply is free."""
        claims = self.ordered(zone_order)
        if not claims:
            return None
        head = claims[0]
        self._claims.remove(head)
        if head.source != "manual":
            self._turns[head.zone_id] = (head.due_at, self._turn(head) + 1)
        return head

    def clear(self) -> None:
        """Drop pending requests on teardown; nothing is replayed."""
        self._claims.clear()
        self._turns.clear()
