from __future__ import annotations

from typing import Any


class StrainAnalyticsManager:
    def __init__(self, strains: dict[str, Any]) -> None:
        self._strains = strains
        self._cache: dict[str, Any] | None = None

    def invalidate(self) -> None:
        self._cache = None

    def compute(self) -> dict[str, Any]:
        if self._cache is not None:
            return self._cache

        analytics_data: dict[str, Any] = {}

        for strain_name, strain_data in self._strains.items():
            phenotypes = strain_data.get("phenotypes", {})
            strain_harvests: list[dict[str, Any]] = []
            pheno_analytics: dict[str, Any] = {}

            for pheno_name, pheno_data in phenotypes.items():
                harvests = pheno_data.get("harvests", [])
                strain_harvests.extend(harvests)
                num = len(harvests)
                if num:
                    total_veg = sum(h.get("veg_days", 0) for h in harvests)
                    total_flower = sum(h.get("flower_days", 0) for h in harvests)
                    dry_weights = [
                        h["dry_weight"]
                        for h in harvests
                        if h.get("dry_weight") is not None
                    ]
                    wet_weights = [
                        h["wet_weight"]
                        for h in harvests
                        if h.get("wet_weight") is not None
                    ]
                    stats: dict[str, Any] = {
                        "avg_veg_days": round(total_veg / num),
                        "avg_flower_days": round(total_flower / num),
                        "total_harvests": num,
                    }
                    if dry_weights:
                        stats["avg_dry_weight"] = round(
                            sum(dry_weights) / len(dry_weights), 1
                        )
                        stats["total_dry_yield"] = round(sum(dry_weights), 1)
                    if wet_weights:
                        stats["avg_wet_weight"] = round(
                            sum(wet_weights) / len(wet_weights), 1
                        )
                else:
                    stats = {
                        "avg_veg_days": 0,
                        "avg_flower_days": 0,
                        "total_harvests": 0,
                    }
                pheno_meta = {
                    k: v
                    for k, v in pheno_data.items()
                    if k not in ["harvests", "description", "image_path", "image_crop_meta"]
                }
                pheno_analytics[pheno_name] = {**stats, **pheno_meta}

            num_strain_harvests = len(strain_harvests)
            if num_strain_harvests:
                strain_avg_veg = round(
                    sum(h.get("veg_days", 0) for h in strain_harvests) / num_strain_harvests
                )
                strain_avg_flower = round(
                    sum(h.get("flower_days", 0) for h in strain_harvests) / num_strain_harvests
                )
            else:
                strain_avg_veg = 0
                strain_avg_flower = 0

            analytics_data[strain_name] = {
                "meta": strain_data.get("meta", {}),
                "analytics": {
                    "avg_veg_days": strain_avg_veg,
                    "avg_flower_days": strain_avg_flower,
                    "total_harvests": num_strain_harvests,
                },
                "phenotypes": pheno_analytics,
            }

        self._cache = {
            "strains": analytics_data,
            "strain_list": list(self._strains.keys()),
        }
        return self._cache
