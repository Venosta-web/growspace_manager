from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.services.seedfinder_scraper import (
    SeedfinderScraper,
)


@pytest.fixture
def scraper() -> SeedfinderScraper:
    """Fixture for SeedfinderScraper."""
    return SeedfinderScraper(MagicMock())


def _make_mock_session(html: str) -> MagicMock:
    mock_session = MagicMock()
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.text = AsyncMock(return_value=html)

    mock_get_ctx = MagicMock()
    mock_get_ctx.__aenter__ = AsyncMock(return_value=mock_response)
    mock_get_ctx.__aexit__ = AsyncMock(return_value=None)

    mock_session.get.return_value = mock_get_ctx
    return mock_session


@pytest.mark.asyncio
async def test_async_search_strains_filtering(scraper: SeedfinderScraper) -> None:
    """Test that async_search_strains correctly filters blacklisted breeders."""
    mock_html = """
    <table>
        <tr>
            <td><a href="/strain-info/strain1/">Strain 1</a></td>
            <td><a href="/breeder/breeder1/">Breeder 1</a></td>
        </tr>
        <tr>
            <td><a href="/strain-info/strain2/">Strain 2</a></td>
            <td><a href="/breeder/breeder2/">Breeder 2</a></td>
        </tr>
    </table>
    """

    with patch(
        "custom_components.growspace_manager.services.seedfinder_scraper.async_get_clientsession",
        return_value=_make_mock_session(mock_html),
    ):
        results = await scraper.async_search_strains("query")
        assert len(results) == 2
        assert results[0]["breeder"] == "Breeder 1"
        assert results[1]["breeder"] == "Breeder 2"

    with patch(
        "custom_components.growspace_manager.services.seedfinder_scraper.async_get_clientsession",
        return_value=_make_mock_session(mock_html),
    ):
        results = await scraper.async_search_strains("query", blacklist=["Breeder 1"])
        assert len(results) == 1
        assert results[0]["breeder"] == "Breeder 2"
        assert results[0]["name"] == "Strain 2"


@pytest.mark.asyncio
async def test_async_search_strains_ranking(scraper: SeedfinderScraper) -> None:
    """Test that exact and prefix matches are ranked before substring matches."""
    mock_html = """
    <table>
        <tr>
            <td><a href="/strain-info/alien-gelato/">Alien Gelato</a></td>
            <td><a href="/breeder/b1/">Breeder 1</a></td>
        </tr>
        <tr>
            <td><a href="/strain-info/gelato-41/">Gelato #41</a></td>
            <td><a href="/breeder/b2/">Breeder 2</a></td>
        </tr>
        <tr>
            <td><a href="/strain-info/gelato/">Gelato</a></td>
            <td><a href="/breeder/b3/">Breeder 3</a></td>
        </tr>
    </table>
    """

    with patch(
        "custom_components.growspace_manager.services.seedfinder_scraper.async_get_clientsession",
        return_value=_make_mock_session(mock_html),
    ):
        results = await scraper.async_search_strains("Gelato")
        assert len(results) == 3
        assert results[0]["name"] == "Gelato"
        assert results[1]["name"] == "Gelato #41"
        assert results[2]["name"] == "Alien Gelato"
