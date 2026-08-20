
from custom_components.growspace_manager.managers.strain_analytics import (
    StrainAnalyticsManager,
)

STRAINS_WITH_HARVESTS = {
    "OG Kush": {
        "meta": {"breeder": "DNA Genetics"},
        "phenotypes": {
            "Pheno1": {
                "harvests": [
                    {"veg_days": 30, "flower_days": 60, "dry_weight": 80.0, "wet_weight": 300.0},
                    {"veg_days": 28, "flower_days": 63, "dry_weight": 90.0, "wet_weight": 320.0},
                ]
            }
        },
    }
}


STRAINS_NO_HARVESTS = {
    "White Widow": {
        "meta": {},
        "phenotypes": {"Pheno A": {"harvests": []}},
    }
}


def test_compute_zero_harvests_returns_zeros() -> None:
    manager = StrainAnalyticsManager(STRAINS_NO_HARVESTS)
    result = manager.compute()

    strain = result["strains"]["White Widow"]
    assert strain["analytics"]["total_harvests"] == 0
    assert strain["analytics"]["avg_veg_days"] == 0
    assert strain["analytics"]["avg_flower_days"] == 0
    assert "avg_dry_weight" not in strain["phenotypes"]["Pheno A"]


def test_compute_caches_result() -> None:
    manager = StrainAnalyticsManager(STRAINS_WITH_HARVESTS)
    first = manager.compute()
    second = manager.compute()
    assert first is second


def test_invalidate_clears_cache() -> None:
    manager = StrainAnalyticsManager(STRAINS_WITH_HARVESTS)
    first = manager.compute()
    manager.invalidate()
    second = manager.compute()
    assert first is not second


def test_compute_returns_correct_averages() -> None:
    manager = StrainAnalyticsManager(STRAINS_WITH_HARVESTS)
    result = manager.compute()

    strain = result["strains"]["OG Kush"]
    assert strain["analytics"]["total_harvests"] == 2
    assert strain["analytics"]["avg_veg_days"] == 29
    assert strain["analytics"]["avg_flower_days"] == 62
    assert strain["phenotypes"]["Pheno1"]["avg_dry_weight"] == 85.0
    assert "OG Kush" in result["strain_list"]
