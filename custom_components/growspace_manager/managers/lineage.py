"""Lineage tree construction and ancestry queries for the strain library."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import json
import logging
from typing import Any

import aiosqlite

from homeassistant.exceptions import ServiceValidationError

from ..exceptions import GrowspaceError

_LOGGER = logging.getLogger(__name__)

type StoredParent = dict[str, str]
type StoredParents = list[StoredParent]
type LineageNode = dict[str, Any]


def _collect_ancestors(
    node: dict[str, Any], depth: int = 1
) -> list[tuple[str, str | None, int]]:
    """Walk a lineage_tree node recursively, returning (name, url, depth) for every ancestor."""
    results: list[tuple[str, str | None, int]] = []
    for parent in node.get("parents", []):
        name = parent.get("name", "").strip()
        if name:
            results.append((name, parent.get("url"), depth))
            results.extend(_collect_ancestors(parent, depth + 1))
    return results


class StrainLineageManager:
    """Manages lineage tree construction and ancestry queries for the strain library."""

    def __init__(
        self,
        strains: dict[str, Any],
        db: aiosqlite.Connection | None,
        load_callback: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        """Initialize with the strains catalogue, DB handle and optional loader."""
        self._strains = strains
        self._db = db
        self._load_callback = load_callback
        self._lineage_cache: dict[str, LineageNode] = {}

    def invalidate_cache(self) -> None:
        """Clear the cached lineage trees."""
        self._lineage_cache.clear()

    def get_strain_lineage_tree(
        self,
        strain_name: str,
        _seen: frozenset[str] | None = None,
        _depth: int = 0,
    ) -> LineageNode:
        """Recursively resolve the full lineage tree for a strain from the in-memory cache.

        Reads StoredParents from self._strains (no DB I/O) and builds a nested LineageNode.
        Stops recursing when a strain is already in the current path (_seen) to prevent
        infinite loops, or when _depth >= 15.
        """
        if _seen is None:
            if strain_name in self._lineage_cache:
                return self._lineage_cache[strain_name]
            _seen = frozenset()

        strain_meta = self._strains.get(strain_name, {}).get("meta", {})
        node: LineageNode = {
            "name": strain_name,
            "source": "library",
            "parents": [],
            "generation": strain_meta.get("generation", ""),
        }

        if _depth >= 15 or strain_name in _seen:
            return node

        strain_data = self._strains.get(strain_name)
        if strain_data is None:
            return node

        parents = strain_data.get("meta", {}).get("lineage_tree") or []
        next_seen = _seen | {strain_name}

        for parent in parents[:2]:
            parent_name = parent.get("name", "")
            parent_phenotype = parent.get("phenotype") or None
            source = parent.get("source", "manual")
            if source == "library" and parent_name in self._strains:
                resolved = self.get_strain_lineage_tree(
                    parent_name, _seen=next_seen, _depth=_depth + 1
                )
                if parent_phenotype:
                    resolved["phenotype"] = parent_phenotype
            else:
                resolved = {"name": parent_name, "source": source, "parents": []}
                if parent_phenotype:
                    resolved["phenotype"] = parent_phenotype
            node["parents"].append(resolved)

        if _depth == 0:
            self._lineage_cache[strain_name] = node

        return node

    async def async_get_strains_by_ancestor(
        self, ancestor_name: str
    ) -> list[dict[str, Any]]:
        """Return all library strains that have ancestor_name anywhere in their lineage."""
        if self._db is None:
            return []
        async with self._db.execute(
            """
            SELECT s.strain_id, s.strain_name, s.breeder, sa.depth
            FROM strain_ancestry sa
            JOIN strains s ON sa.descendant_strain_id = s.strain_id
            WHERE sa.ancestor_name = ?
            ORDER BY sa.depth, s.strain_name
            """,
            (ancestor_name,),
        ) as cursor:
            return [dict(row) for row in await cursor.fetchall()]

    async def async_get_shared_ancestors(
        self, strain_ids: list[int]
    ) -> list[dict[str, Any]]:
        """Return ancestors common to ALL given strains, with the shallowest depth."""
        if self._db is None or not strain_ids:
            return []
        placeholders = ",".join("?" * len(strain_ids))
        async with self._db.execute(
            f"""
            SELECT ancestor_name, ancestor_url, MIN(depth) as closest_depth
            FROM strain_ancestry
            WHERE descendant_strain_id IN ({placeholders})
            GROUP BY ancestor_name
            HAVING COUNT(DISTINCT descendant_strain_id) = ?
            ORDER BY closest_depth, ancestor_name
            """,  # noqa: S608
            (*strain_ids, len(strain_ids)),
        ) as cursor:
            return [dict(row) for row in await cursor.fetchall()]

    async def _rebuild_strain_ancestry(self, strain_name: str) -> None:
        """Rebuild strain_ancestry rows for strain_name from the in-memory lineage cache."""
        if self._db is None:
            return
        cur = await self._db.execute(
            "SELECT strain_id FROM strains WHERE strain_name = ?", (strain_name,)
        )
        row = await cur.fetchone()
        if row is None:
            return
        strain_id = row[0]
        full_tree = self.get_strain_lineage_tree(strain_name)
        ancestors = _collect_ancestors(full_tree)
        await self._db.execute(
            "DELETE FROM strain_ancestry WHERE descendant_strain_id = ?", (strain_id,)
        )
        if ancestors:
            await self._db.executemany(
                "INSERT OR REPLACE INTO strain_ancestry"
                " (ancestor_name, descendant_strain_id, depth, ancestor_url)"
                " VALUES (?, ?, ?, ?)",
                [(name, strain_id, depth, url) for name, url, depth in ancestors],
            )
        await self._db.commit()

    async def update_strain_lineage_tree(
        self,
        strain_name: str,
        parents: StoredParents,
    ) -> str:
        """Store immediate parents for a strain and re-derive the flat lineage string."""
        if self._db is None:
            _LOGGER.warning("Database not connected, cannot update lineage tree")
            return ""

        parents = parents[:2]
        flat_lineage = " × ".join(p["name"] for p in parents)
        tree_json = json.dumps(parents)

        await self._db.execute(
            "UPDATE strains SET lineage_tree = ?, lineage = ? WHERE strain_name = ?",
            (tree_json, flat_lineage, strain_name),
        )
        await self._db.commit()
        if self._load_callback is not None:
            await self._load_callback()
        await self._rebuild_strain_ancestry(strain_name)
        _LOGGER.info("Updated lineage tree for strain '%s'", strain_name)
        return flat_lineage

    async def async_import_seedfinder_lineage_tree(
        self,
        root_strain_name: str,
        tree: dict[str, Any],
        scraper: Any | None = None,
    ) -> None:
        """Import a full multi-level seedfinder lineage tree."""
        if self._db is None:
            return

        lineage_by_node: dict[str, list[str]] = {}
        leaf_parent_urls: dict[str, str] = {}

        def _collect(node: dict[str, Any]) -> None:
            name = (node.get("name") or "").strip()
            if not name:
                return
            parents = node.get("parents") or []
            parent_names = [
                (p.get("name") or "").strip()
                for p in parents
                if (p.get("name") or "").strip()
            ]
            if parent_names:
                lineage_by_node[name] = parent_names[:2]
            for parent in parents:
                pname = (parent.get("name") or "").strip()
                purl = (parent.get("url") or "").strip()
                if pname and purl and not (parent.get("parents") or []):
                    leaf_parent_urls[pname] = purl
                _collect(parent)

        _collect(tree)

        if scraper and leaf_parent_urls:
            for pname, purl in leaf_parent_urls.items():
                if pname in lineage_by_node:
                    continue
                try:
                    parent_details = await scraper.async_get_strain_details(purl)
                    if parent_details and parent_details.get("lineage_tree"):
                        parent_tree = parent_details["lineage_tree"]
                        parent_tree.setdefault("name", pname)
                        _collect(parent_tree)
                        _LOGGER.debug(
                            "Fetched lineage for leaf parent '%s' from %s", pname, purl
                        )
                except (
                    AttributeError,
                    KeyError,
                    ValueError,
                    ServiceValidationError,
                    GrowspaceError,
                ):
                    _LOGGER.debug("Could not fetch lineage for '%s' at %s", pname, purl)

        if not lineage_by_node:
            return

        all_names: set[str] = set()
        for name, parent_names in lineage_by_node.items():
            all_names.add(name)
            all_names.update(parent_names)

        for ancestor_name in all_names:
            if ancestor_name == root_strain_name:
                continue
            await self._db.execute(
                "INSERT OR IGNORE INTO strains (strain_name, is_stub) VALUES (?, 1)",
                (ancestor_name,),
            )
            await self._db.execute(
                """
                INSERT OR IGNORE INTO phenotypes (strain_id, phenotype_name)
                SELECT strain_id, 'default' FROM strains WHERE strain_name = ?
                """,
                (ancestor_name,),
            )

        for name, parent_names in lineage_by_node.items():
            library_parents = [{"name": n, "source": "library"} for n in parent_names]
            flat_lineage = " × ".join(parent_names)
            await self._db.execute(
                "UPDATE strains SET lineage_tree = ?, lineage = ? WHERE strain_name = ?",
                (json.dumps(library_parents), flat_lineage, name),
            )

        await self._db.commit()
        if self._load_callback is not None:
            await self._load_callback()
        self._lineage_cache.clear()
        for name in lineage_by_node:
            await self._rebuild_strain_ancestry(name)
        _LOGGER.info(
            "Imported seedfinder lineage tree for '%s' (%d nodes)",
            root_strain_name,
            len(lineage_by_node),
        )

    async def async_update_strain_generation(
        self, strain_name: str, generation: str
    ) -> None:
        """Write the generation classification tag for a strain."""
        if self._db is None:
            _LOGGER.warning(
                "Database not connected, cannot update generation for '%s'", strain_name
            )
            return
        await self._db.execute(
            "UPDATE strains SET generation = ? WHERE strain_name = ?",
            (generation, strain_name),
        )
        await self._db.commit()
        if strain_name in self._strains:
            self._strains[strain_name].setdefault("meta", {})["generation"] = generation
        self._lineage_cache.clear()
        _LOGGER.debug("Set generation '%s' for strain '%s'", generation, strain_name)
