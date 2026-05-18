"""ServiceContext and BaseService for the Growspace Manager integration."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import GrowspaceEvent


@dataclass
class ServiceContext:
    """Orchestration wiring shared by all services and managers.

    Bundles the four callbacks that every mutating service needs, so they
    can be constructed once in the coordinator and passed as a single
    dependency rather than four separate positional arguments.
    """

    save_callback: Callable[[], Awaitable[None]]
    lock: asyncio.Lock
    add_event: Callable[[str, GrowspaceEvent], None]
    invalidate_cache: Callable[[str | None], None]


class BaseService:
    """Base class for all services and managers that mutate growspace data."""

    def __init__(self, ctx: ServiceContext) -> None:
        self._ctx = ctx

    async def _save(self) -> None:
        await self._ctx.save_callback()

    def _emit(self, growspace_id: str, event: GrowspaceEvent) -> None:
        self._ctx.add_event(growspace_id, event)

    def _invalidate(self, growspace_id: str | None = None) -> None:
        self._ctx.invalidate_cache(growspace_id)

    @property
    def _lock(self) -> asyncio.Lock:
        return self._ctx.lock
