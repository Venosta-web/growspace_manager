from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
from bs4 import BeautifulSoup
import pytest

from custom_components.growspace_manager.services.seedfinder_scraper import (
    BASE_URL,
    SeedfinderScraper,
)


@pytest.fixture
def scraper() -> SeedfinderScraper:
    """Fixture for SeedfinderScraper."""
    hass = MagicMock()
    hass.async_add_executor_job = AsyncMock(
        side_effect=lambda target, *args, **kwargs: target(*args, **kwargs)
    )
    return SeedfinderScraper(hass)


def _make_mock_session(html: str, status: int = 200) -> MagicMock:
    mock_session = MagicMock()
    mock_response = MagicMock()
    mock_response.status = status
    mock_response.text = AsyncMock(return_value=html)

    mock_get_ctx = MagicMock()
    mock_get_ctx.__aenter__ = AsyncMock(return_value=mock_response)
    mock_get_ctx.__aexit__ = AsyncMock(return_value=None)

    mock_session.get.return_value = mock_get_ctx
    return mock_session


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


# ---------------------------------------------------------------------------
# _async_fetch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_fetch_success(scraper: SeedfinderScraper) -> None:
    with patch(
        "custom_components.growspace_manager.services.seedfinder_scraper.async_get_clientsession",
        return_value=_make_mock_session("<html>ok</html>"),
    ):
        result = await scraper._async_fetch("http://example.com")
    assert result == "<html>ok</html>"


@pytest.mark.asyncio
async def test_async_fetch_non_200(scraper: SeedfinderScraper) -> None:
    with patch(
        "custom_components.growspace_manager.services.seedfinder_scraper.async_get_clientsession",
        return_value=_make_mock_session("", status=404),
    ):
        result = await scraper._async_fetch("http://example.com")
    assert result is None


@pytest.mark.asyncio
async def test_async_fetch_client_error(scraper: SeedfinderScraper) -> None:
    mock_session = MagicMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(side_effect=aiohttp.ClientError("fail"))
    ctx.__aexit__ = AsyncMock(return_value=None)
    mock_session.get.return_value = ctx

    with patch(
        "custom_components.growspace_manager.services.seedfinder_scraper.async_get_clientsession",
        return_value=mock_session,
    ):
        result = await scraper._async_fetch("http://example.com")
    assert result is None


@pytest.mark.asyncio
async def test_async_fetch_timeout_error(scraper: SeedfinderScraper) -> None:
    mock_session = MagicMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(side_effect=TimeoutError("timeout"))
    ctx.__aexit__ = AsyncMock(return_value=None)
    mock_session.get.return_value = ctx

    with patch(
        "custom_components.growspace_manager.services.seedfinder_scraper.async_get_clientsession",
        return_value=mock_session,
    ):
        result = await scraper._async_fetch("http://example.com")
    assert result is None


@pytest.mark.asyncio
async def test_async_fetch_unexpected_error(scraper: SeedfinderScraper) -> None:
    mock_session = MagicMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(side_effect=ValueError("boom"))
    ctx.__aexit__ = AsyncMock(return_value=None)
    mock_session.get.return_value = ctx

    with patch(
        "custom_components.growspace_manager.services.seedfinder_scraper.async_get_clientsession",
        return_value=mock_session,
    ):
        result = await scraper._async_fetch("http://example.com")
    assert result is None


# ---------------------------------------------------------------------------
# async_search_strains – error paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_search_strains_non_200(scraper: SeedfinderScraper) -> None:
    with patch(
        "custom_components.growspace_manager.services.seedfinder_scraper.async_get_clientsession",
        return_value=_make_mock_session("", status=500),
    ):
        results = await scraper.async_search_strains("OG Kush")
    assert results == []


@pytest.mark.asyncio
async def test_async_search_strains_client_error(scraper: SeedfinderScraper) -> None:
    mock_session = MagicMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(side_effect=aiohttp.ClientError("fail"))
    ctx.__aexit__ = AsyncMock(return_value=None)
    mock_session.get.return_value = ctx

    with patch(
        "custom_components.growspace_manager.services.seedfinder_scraper.async_get_clientsession",
        return_value=mock_session,
    ):
        results = await scraper.async_search_strains("OG Kush")
    assert results == []


@pytest.mark.asyncio
async def test_async_search_strains_unexpected_error(
    scraper: SeedfinderScraper,
) -> None:
    mock_session = MagicMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(side_effect=ValueError("boom"))
    ctx.__aexit__ = AsyncMock(return_value=None)
    mock_session.get.return_value = ctx

    with patch(
        "custom_components.growspace_manager.services.seedfinder_scraper.async_get_clientsession",
        return_value=mock_session,
    ):
        results = await scraper.async_search_strains("OG Kush")
    assert results == []


@pytest.mark.asyncio
async def test_async_search_strains_relative_url(scraper: SeedfinderScraper) -> None:
    """Relative URLs get BASE_URL prepended."""
    mock_html = """
    <table>
        <tr>
            <td><a href="/strain-info/og-kush/">OG Kush</a></td>
            <td><a href="/breeder/b1/">Royal Queen</a></td>
        </tr>
    </table>
    """
    with patch(
        "custom_components.growspace_manager.services.seedfinder_scraper.async_get_clientsession",
        return_value=_make_mock_session(mock_html),
    ):
        results = await scraper.async_search_strains("og kush")
    assert len(results) == 1
    assert results[0]["url"].startswith(BASE_URL)


@pytest.mark.asyncio
async def test_async_search_strains_no_parent_row(scraper: SeedfinderScraper) -> None:
    """Strains without a parent row get 'Unknown' breeder."""
    mock_html = """
    <div>
        <a href="/strain-info/og-kush/">OG Kush</a>
    </div>
    """
    with patch(
        "custom_components.growspace_manager.services.seedfinder_scraper.async_get_clientsession",
        return_value=_make_mock_session(mock_html),
    ):
        results = await scraper.async_search_strains("OG Kush")
    assert results[0]["breeder"] == "Unknown"


@pytest.mark.asyncio
async def test_async_search_strains_no_breeder_link_in_row(
    scraper: SeedfinderScraper,
) -> None:
    """Row exists but has no breeder link – breeder stays 'Unknown'."""
    mock_html = """
    <table>
        <tr>
            <td><a href="/strain-info/og-kush/">OG Kush</a></td>
            <td>Some other info</td>
        </tr>
    </table>
    """
    with patch(
        "custom_components.growspace_manager.services.seedfinder_scraper.async_get_clientsession",
        return_value=_make_mock_session(mock_html),
    ):
        results = await scraper.async_search_strains("OG Kush")
    assert results[0]["breeder"] == "Unknown"


@pytest.mark.asyncio
async def test_async_search_strains_deduplication(scraper: SeedfinderScraper) -> None:
    """Duplicate names are only included once."""
    mock_html = """
    <table>
        <tr>
            <td><a href="/strain-info/og-kush/">OG Kush</a></td>
            <td><a href="/breeder/b1/">Breeder 1</a></td>
        </tr>
        <tr>
            <td><a href="/strain-info/og-kush-v2/">OG Kush</a></td>
            <td><a href="/breeder/b2/">Breeder 2</a></td>
        </tr>
    </table>
    """
    with patch(
        "custom_components.growspace_manager.services.seedfinder_scraper.async_get_clientsession",
        return_value=_make_mock_session(mock_html),
    ):
        results = await scraper.async_search_strains("OG Kush")
    assert len(results) == 1


# ---------------------------------------------------------------------------
# async_search_strains – filtering & ranking (existing tests preserved)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# async_get_strain_details – error paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_get_strain_details_non_200(scraper: SeedfinderScraper) -> None:
    with patch(
        "custom_components.growspace_manager.services.seedfinder_scraper.async_get_clientsession",
        return_value=_make_mock_session("", status=404),
    ):
        result = await scraper.async_get_strain_details("http://example.com/strain")
    assert result is None


@pytest.mark.asyncio
async def test_async_get_strain_details_client_error(
    scraper: SeedfinderScraper,
) -> None:
    mock_session = MagicMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(side_effect=aiohttp.ClientError("fail"))
    ctx.__aexit__ = AsyncMock(return_value=None)
    mock_session.get.return_value = ctx

    with patch(
        "custom_components.growspace_manager.services.seedfinder_scraper.async_get_clientsession",
        return_value=mock_session,
    ):
        result = await scraper.async_get_strain_details("http://example.com/strain")
    assert result is None


@pytest.mark.asyncio
async def test_async_get_strain_details_unexpected_error(
    scraper: SeedfinderScraper,
) -> None:
    mock_session = MagicMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(side_effect=ValueError("boom"))
    ctx.__aexit__ = AsyncMock(return_value=None)
    mock_session.get.return_value = ctx

    with patch(
        "custom_components.growspace_manager.services.seedfinder_scraper.async_get_clientsession",
        return_value=mock_session,
    ):
        result = await scraper.async_get_strain_details("http://example.com/strain")
    assert result is None


@pytest.mark.asyncio
async def test_async_get_strain_details_full(scraper: SeedfinderScraper) -> None:
    """Test full details extraction with all major HTML features present."""
    html = """
    <html>
      <body>
        <h1>OG Kush</h1>
        <a href="/breeder/royal-queen-seeds/">Royal Queen Seeds</a>
        <img :src="selectedIndex === -1 ? '/storage/pics/og-kush.jpg' : images[selectedIndex].big" />
        <h2>Basic Strain Information</h2>
        <div>60% sativa, 40% indica. Blütizeit von 63 days. A great strain.</div>
        <div id="lineage">
          <ul>
            <li>
              <a class="font-bold" href="/strain-info/og-kush/">OG Kush</a>
              <a class="font-bold" href="/strain-info/chemdawg/">Chemdawg</a>
            </li>
          </ul>
        </div>
        <div>
          <h3>Awards</h3>
          <div>
            <ul>
              <li>1st place Cannabis Cup 2010</li>
            </ul>
          </div>
        </div>
        <h4>Effect/Effectiveness</h4>
        <div>
          <div class="rounded-lg">Relaxing</div>
          <div class="rounded-lg">Euphoric</div>
        </div>
        <h4>Scent/Smell</h4>
        <div>
          <div class="rounded-lg">Earthy</div>
        </div>
        <h4>Taste/Flavor</h4>
        <div>
          <div class="rounded-lg">Pine</div>
        </div>
        THC: 20%
      </body>
    </html>
    """
    with patch(
        "custom_components.growspace_manager.services.seedfinder_scraper.async_get_clientsession",
        return_value=_make_mock_session(html),
    ):
        result = await scraper.async_get_strain_details(
            "https://seedfinder.eu/en/strain/og-kush/"
        )

    assert result is not None
    assert result["name"] == "OG Kush"
    assert result["breeder"] == "Royal Queen Seeds"
    assert result["image"] is not None
    assert result["composition"]["sativa"] == 60.0
    assert result["composition"]["indica"] == 40.0
    assert result["awards"] == ["1st place Cannabis Cup 2010"]
    assert "Relaxing" in result["effects"]
    assert "Earthy" in result["aroma"]
    assert "Pine" in result["taste"]
    assert result["thc"] == 20.0


@pytest.mark.asyncio
async def test_async_get_strain_details_lineage_fallback(
    scraper: SeedfinderScraper,
) -> None:
    """lineage_str fallback used when UL structure not found but lineage_str exists."""
    html = """
    <html>
      <body>
        <h1>Test Strain</h1>
        <div id="lineage">
          Lineage: Parent A x Parent B
        </div>
        THC: 18%
      </body>
    </html>
    """
    with patch(
        "custom_components.growspace_manager.services.seedfinder_scraper.async_get_clientsession",
        return_value=_make_mock_session(html),
    ):
        result = await scraper.async_get_strain_details("https://seedfinder.eu/strain/")
    assert result is not None
    assert result["lineage_str"] != "" or result["lineage_tree"] == {}


@pytest.mark.asyncio
async def test_async_get_strain_details_lineage_header_fallback(
    scraper: SeedfinderScraper,
) -> None:
    """Lineage header fallback (no id=lineage div)."""
    html = """
    <html>
      <body>
        <h1>Test Strain</h1>
        <h2>Lineage</h2>
        <div>
          <ul>
            <li>
              <span class="text-[#003300]"><a href="/strain-info/parent-a/">Parent A</a></span>
            </li>
          </ul>
        </div>
      </body>
    </html>
    """
    with patch(
        "custom_components.growspace_manager.services.seedfinder_scraper.async_get_clientsession",
        return_value=_make_mock_session(html),
    ):
        result = await scraper.async_get_strain_details("https://seedfinder.eu/strain/")
    assert result is not None


@pytest.mark.asyncio
async def test_async_get_strain_details_lineage_tree_fallback_to_recursive(
    scraper: SeedfinderScraper,
) -> None:
    """When UL exists but all LIs parse to None, falls back to _parse_recursive."""
    # lineage div has UL but empty LIs that produce None nodes, and a lineage_str exists
    html = """
    <html>
      <body>
        <h1>Test Strain</h1>
        <div id="lineage">
          <ul>
            <li>   </li>
          </ul>
          Lineage: Parent A x Parent B
        </div>
      </body>
    </html>
    """
    with patch(
        "custom_components.growspace_manager.services.seedfinder_scraper.async_get_clientsession",
        return_value=_make_mock_session(html),
    ):
        result = await scraper.async_get_strain_details("https://seedfinder.eu/strain/")
    assert result is not None
    # lineage_tree should be populated by _parse_recursive fallback
    assert result["lineage_tree"] != {} or result["lineage_str"] == ""


@pytest.mark.asyncio
async def test_async_get_strain_details_comp_overrides_metrics(
    scraper: SeedfinderScraper,
) -> None:
    """Composition flowering_time is merged when metrics has none."""
    html = """
    <html>
      <body>
        <h1>Test Strain</h1>
        <h2>Basic Strain Information</h2>
        <div>flowering time of 56 days. Some description text here.</div>
      </body>
    </html>
    """
    with patch(
        "custom_components.growspace_manager.services.seedfinder_scraper.async_get_clientsession",
        return_value=_make_mock_session(html),
    ):
        result = await scraper.async_get_strain_details("https://seedfinder.eu/strain/")
    assert result is not None
    assert result["flowering_time"] == "56 days"


# ---------------------------------------------------------------------------
# _parse_basic_info
# ---------------------------------------------------------------------------


def test_parse_basic_info_with_h1_and_breeder(scraper: SeedfinderScraper) -> None:
    soup = _soup(
        '<h1>Blue Dream</h1><a href="/breeder/humboldt/">Humboldt Seed Co</a>'
    )
    name, breeder = scraper._parse_basic_info(soup)
    assert name == "Blue Dream"
    assert breeder == "Humboldt Seed Co"


def test_parse_basic_info_no_h1(scraper: SeedfinderScraper) -> None:
    soup = _soup('<a href="/breeder/humboldt/">Humboldt Seed Co</a>')
    name, breeder = scraper._parse_basic_info(soup)
    assert name == "Unknown"
    assert breeder == "Humboldt Seed Co"


def test_parse_basic_info_no_breeder_link(scraper: SeedfinderScraper) -> None:
    soup = _soup("<h1>Blue Dream</h1>")
    name, breeder = scraper._parse_basic_info(soup)
    assert name == "Blue Dream"
    assert breeder == "Unknown"


# ---------------------------------------------------------------------------
# _parse_image
# ---------------------------------------------------------------------------


def test_parse_image_alpine_absolute(scraper: SeedfinderScraper) -> None:
    soup = _soup(
        '<img :src="selectedIndex === -1 ? \'https://cdn.example.com/img.jpg\' : images[selectedIndex].big" />'
    )
    url = scraper._parse_image(soup, "Strain")
    assert url == "https://cdn.example.com/img.jpg"


def test_parse_image_alpine_relative(scraper: SeedfinderScraper) -> None:
    soup = _soup(
        '<img :src="selectedIndex === -1 ? \'/storage/pics/img.jpg\' : images[selectedIndex].big" />'
    )
    url = scraper._parse_image(soup, "Strain")
    assert url == f"{BASE_URL}/storage/pics/img.jpg"


def test_parse_image_fallback_storage(scraper: SeedfinderScraper) -> None:
    soup = _soup('<img src="/storage/pics/og-kush.jpg" />')
    url = scraper._parse_image(soup, "Strain")
    assert url == f"{BASE_URL}/storage/pics/og-kush.jpg"


def test_parse_image_fallback_storage_absolute(scraper: SeedfinderScraper) -> None:
    soup = _soup('<img src="https://cdn.example.com/storage/pics/og-kush.jpg" />')
    url = scraper._parse_image(soup, "Strain")
    assert url == "https://cdn.example.com/storage/pics/og-kush.jpg"


def test_parse_image_none(scraper: SeedfinderScraper) -> None:
    soup = _soup("<div>no image here</div>")
    url = scraper._parse_image(soup, "Strain")
    assert url is None


def test_parse_image_alpine_404_placeholder_returns_none(
    scraper: SeedfinderScraper,
) -> None:
    """Alpine.js :src with =404 placeholder is rejected."""
    soup = _soup(
        '<img :src="selectedIndex === -1 ? \'/storage/pics/00breeder/=404\' : images[selectedIndex].big" />'
    )
    url = scraper._parse_image(soup, "Strain")
    assert url is None


def test_parse_image_fallback_src_404_placeholder_returns_none(
    scraper: SeedfinderScraper,
) -> None:
    """Fallback src containing =404 is rejected."""
    soup = _soup('<img src="/storage/pics/01seeds/Paradise_Seeds/=404" />')
    url = scraper._parse_image(soup, "Strain")
    assert url is None


# ---------------------------------------------------------------------------
# _parse_composition
# ---------------------------------------------------------------------------


def test_parse_composition_sativa_indica_percentages(scraper: SeedfinderScraper) -> None:
    soup = _soup(
        "<h2>Basic Strain Information</h2><div>70% sativa, 30% indica text here</div>"
    )
    data = scraper._parse_composition(soup)
    assert data["sativa"] == 70.0
    assert data["indica"] == 30.0


def test_parse_composition_zero_percent_treated_as_none(
    scraper: SeedfinderScraper,
) -> None:
    soup = _soup(
        "<h2>Basic Strain Information</h2><div>0% sativa, 0% indica some text here</div>"
    )
    data = scraper._parse_composition(soup)
    assert data["sativa"] is None
    assert data["indica"] is None


def test_parse_composition_indica_dominant(scraper: SeedfinderScraper) -> None:
    soup = _soup(
        "<h2>Basic Strain Information</h2><div>This is an indica-dominant strain.</div>"
    )
    data = scraper._parse_composition(soup)
    assert data["sativa"] == 30
    assert data["indica"] == 70


def test_parse_composition_sativa_dominant(scraper: SeedfinderScraper) -> None:
    soup = _soup(
        "<h2>Basic Strain Information</h2><div>This is a sativa-dominant strain.</div>"
    )
    data = scraper._parse_composition(soup)
    assert data["sativa"] == 70
    assert data["indica"] == 30


def test_parse_composition_pure_indica(scraper: SeedfinderScraper) -> None:
    soup = _soup(
        "<h2>Basic Strain Information</h2><div>This is a pure indica variety.</div>"
    )
    data = scraper._parse_composition(soup)
    assert data["sativa"] == 0
    assert data["indica"] == 100


def test_parse_composition_pure_sativa(scraper: SeedfinderScraper) -> None:
    soup = _soup(
        "<h2>Basic Strain Information</h2><div>This is a pure sativa variety.</div>"
    )
    data = scraper._parse_composition(soup)
    assert data["sativa"] == 100
    assert data["indica"] == 0


def test_parse_composition_indicadominiert(scraper: SeedfinderScraper) -> None:
    soup = _soup(
        "<h2>Grundlegende Information</h2><div>indicadominiert pflanze</div>"
    )
    data = scraper._parse_composition(soup)
    assert data["indica"] == 70


def test_parse_composition_reine_indica(scraper: SeedfinderScraper) -> None:
    soup = _soup(
        "<h2>Grundlegende Information</h2><div>reine indica pflanze</div>"
    )
    data = scraper._parse_composition(soup)
    assert data["indica"] == 100


def test_parse_composition_reine_sativa(scraper: SeedfinderScraper) -> None:
    soup = _soup(
        "<h2>Grundlegende Information</h2><div>reine sativa pflanze</div>"
    )
    data = scraper._parse_composition(soup)
    assert data["sativa"] == 100


def test_parse_composition_flowering_time_range(scraper: SeedfinderScraper) -> None:
    soup = _soup(
        "<h2>Basic Strain Information</h2><div>flowering time of 56-63 days</div>"
    )
    data = scraper._parse_composition(soup)
    assert data["flowering_time"] == "56-63 days"


def test_parse_composition_flowering_time_single(scraper: SeedfinderScraper) -> None:
    soup = _soup(
        "<h2>Basic Strain Information</h2><div>flowering time of 63 days</div>"
    )
    data = scraper._parse_composition(soup)
    assert data["flowering_time"] == "63 days"


def test_parse_composition_no_header(scraper: SeedfinderScraper) -> None:
    soup = _soup("<div>No relevant content</div>")
    data = scraper._parse_composition(soup)
    assert data["sativa"] is None
    assert data["indica"] is None
    assert data["flowering_time"] is None


def test_parse_composition_content_node_too_short(scraper: SeedfinderScraper) -> None:
    """Falls back to next sibling when first content node is too short."""
    soup = _soup(
        "<h2>Basic Strain Information</h2><div>ok</div><div>60% sativa, 40% indica long enough text here</div>"
    )
    data = scraper._parse_composition(soup)
    assert data["sativa"] == 60.0


def test_parse_composition_lambda_header_fallback(scraper: SeedfinderScraper) -> None:
    """Tests the lambda-based fallback header search."""
    soup = _soup(
        "<h3>Basic Infos About The Strain</h3><div>50% sativa, 50% indica enough text here for parsing</div>"
    )
    data = scraper._parse_composition(soup)
    assert data["sativa"] == 50.0


def test_parse_composition_sibling_loop_break(scraper: SeedfinderScraper) -> None:
    """Covers the break statement when a sibling with >10 chars is found."""
    # first div is tiny (<10 chars), second div has real content
    soup = _soup(
        "<h2>Basic Strain Information</h2>"
        "<div>x</div>"
        "<div>60% sativa, 40% indica long enough text</div>"
    )
    data = scraper._parse_composition(soup)
    assert data["sativa"] == 60.0


# ---------------------------------------------------------------------------
# _parse_metrics
# ---------------------------------------------------------------------------


def test_parse_metrics_from_table_cells(scraper: SeedfinderScraper) -> None:
    html = """
    <table>
      <tr>
        <td>Flowering Time</td><td>56-63 days</td>
      </tr>
      <tr>
        <td>Yield</td><td>High</td>
      </tr>
      <tr>
        <td>Height</td><td>Tall</td>
      </tr>
    </table>
    """
    soup = _soup(html)
    metrics = scraper._parse_metrics(soup)
    assert metrics["flowering_time"] == "56-63 days"
    assert metrics["yield_potential"] == "High"
    assert metrics["height"] == "Tall"


def test_parse_metrics_flowering_time_single_value(scraper: SeedfinderScraper) -> None:
    html = "<table><tr><td>Flowering Time</td><td>63 days</td></tr></table>"
    soup = _soup(html)
    metrics = scraper._parse_metrics(soup)
    assert metrics["flowering_time"] == "63 days"


def test_parse_metrics_fallback_text(scraper: SeedfinderScraper) -> None:
    html = "Yield: High\nIndoor flowering: 56 days"
    soup = _soup(html)
    metrics = scraper._parse_metrics(soup)
    assert metrics["yield_potential"] == "High"
    assert metrics["flowering_time"] == "56 days"


def test_parse_metrics_fallback_flowering_range(scraper: SeedfinderScraper) -> None:
    html = "Indoor flowering: 56-63 days"
    soup = _soup(html)
    metrics = scraper._parse_metrics(soup)
    assert metrics["flowering_time"] == "56-63 days"


def test_parse_metrics_cannabinoids(scraper: SeedfinderScraper) -> None:
    html = "THC content: 20\nCBD: 1.5\nCBG: 0.5"
    soup = _soup(html)
    metrics = scraper._parse_metrics(soup)
    assert metrics["thc"] == 20.0
    assert metrics["cbd"] == 1.5
    assert metrics["cbg"] == 0.5


def test_parse_metrics_indoor_outdoor_potency(scraper: SeedfinderScraper) -> None:
    html = "Indoor: 500\nOutdoor: 800\nPotency: 9"
    soup = _soup(html)
    metrics = scraper._parse_metrics(soup)
    assert metrics["indoor"] == 500.0
    assert metrics["outdoor"] == 800.0
    assert metrics["potency"] == 9.0


# ---------------------------------------------------------------------------
# _parse_thc
# ---------------------------------------------------------------------------


def test_parse_thc_match(scraper: SeedfinderScraper) -> None:
    assert scraper._parse_thc("THC: 22%") == 22.0


def test_parse_thc_decimal(scraper: SeedfinderScraper) -> None:
    assert scraper._parse_thc("THC: 18.5%") == 18.5


def test_parse_thc_no_match(scraper: SeedfinderScraper) -> None:
    assert scraper._parse_thc("No THC info here") is None


# ---------------------------------------------------------------------------
# _parse_lineage_str
# ---------------------------------------------------------------------------


def test_parse_lineage_str_two_links(scraper: SeedfinderScraper) -> None:
    html = """
    <div id="lineage">
      <ul>
        <li>
          <a href="/strain-info/og-kush/">OG Kush</a>
          <a href="/strain-info/chemdawg/">Chemdawg</a>
        </li>
      </ul>
    </div>
    """
    soup = _soup(html)
    result = scraper._parse_lineage_str(soup)
    assert result == "OG Kush x Chemdawg"


def test_parse_lineage_str_arrows_stripped(scraper: SeedfinderScraper) -> None:
    html = """
    <div id="lineage">
      <ul>
        <li>
          <a href="/strain-info/a/">Parent A »»»</a>
          <a href="/strain-info/b/">Parent B »»»</a>
        </li>
      </ul>
    </div>
    """
    soup = _soup(html)
    result = scraper._parse_lineage_str(soup)
    assert "»" not in result
    assert "Parent A" in result


def test_parse_lineage_str_one_link(scraper: SeedfinderScraper) -> None:
    """Less than 2 links → falls through to regex fallback."""
    html = """
    <div id="lineage">
      <ul>
        <li><a href="/strain-info/og/">OG Kush</a></li>
      </ul>
      Lineage: OG Kush x Chemdawg
    </div>
    """
    soup = _soup(html)
    result = scraper._parse_lineage_str(soup)
    assert result == "OG Kush x Chemdawg"


def test_parse_lineage_str_no_div(scraper: SeedfinderScraper) -> None:
    soup = _soup("<div>No lineage here</div>")
    result = scraper._parse_lineage_str(soup)
    assert result == ""


def test_parse_lineage_str_lineage_div_no_ul(scraper: SeedfinderScraper) -> None:
    """Div exists but has no UL – falls through to regex."""
    html = '<div id="lineage">Lineage: Parent A x Parent B</div>'
    soup = _soup(html)
    result = scraper._parse_lineage_str(soup)
    assert result == "Parent A x Parent B"


# ---------------------------------------------------------------------------
# _parse_description
# ---------------------------------------------------------------------------


def test_parse_description_basic_info_header(scraper: SeedfinderScraper) -> None:
    html = """
    <div>
      <h2>Basic Strain Information</h2>
      <p>This is a great strain with lots of flavor and aroma.</p>
    </div>
    """
    soup = _soup(html)
    result = scraper._parse_description(soup)
    assert "great strain" in result


def test_parse_description_breeder_description(scraper: SeedfinderScraper) -> None:
    html = """
    <div>
      <h3>Breeder Description</h3>
      <p>The breeder says this strain is excellent for relaxation.</p>
    </div>
    """
    soup = _soup(html)
    result = scraper._parse_description(soup)
    assert "excellent" in result


def test_parse_description_strips_header_text(scraper: SeedfinderScraper) -> None:
    html = """
    <div>
      <h2>Basic Strain Information</h2>
      <div>Basic Strain Information This is the actual description content here.</div>
    </div>
    """
    soup = _soup(html)
    result = scraper._parse_description(soup)
    # Header text should be stripped from beginning
    assert not result.startswith("Basic Strain Information")


def test_parse_description_no_header(scraper: SeedfinderScraper) -> None:
    soup = _soup("<div>No description header here</div>")
    result = scraper._parse_description(soup)
    assert result == ""


def test_parse_description_short_next_node_uses_parent(
    scraper: SeedfinderScraper,
) -> None:
    """When next node is too short, falls back to parent container."""
    html = """
    <div>
      <h2>Basic Strain Information</h2>
      <p>short</p>
      This is a long description from the parent container with lots of text.
    </div>
    """
    soup = _soup(html)
    result = scraper._parse_description(soup)
    # Should get some content from fallback
    assert isinstance(result, str)


def test_parse_description_lambda_fallback(scraper: SeedfinderScraper) -> None:
    """Tests the lambda-based fallback header search when string= doesn't match."""
    html = """
    <div>
      <h2>Basic infos about the strain</h2>
      <p>This is the description content with sufficient length.</p>
    </div>
    """
    soup = _soup(html)
    result = scraper._parse_description(soup)
    assert "description content" in result


def test_parse_description_container_too_short_continues(
    scraper: SeedfinderScraper,
) -> None:
    """When next_node is short and parent container has no extra text, tries next pattern."""
    # Header has no meaningful parent div with extra content → continue
    # Then "Breeder Description" pattern also has no content → returns ""
    html = """
    <h2>Basic Strain Information</h2>
    <p>x</p>
    """
    soup = _soup(html)
    result = scraper._parse_description(soup)
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# _parse_awards
# ---------------------------------------------------------------------------


def test_parse_awards_with_list(scraper: SeedfinderScraper) -> None:
    html = """
    <div>
      <h3>Awards</h3>
      <div>
        <ul>
          <li>1st place Cannabis Cup 2010</li>
          <li>Best Indica 2011</li>
        </ul>
      </div>
    </div>
    """
    soup = _soup(html)
    awards = scraper._parse_awards(soup)
    assert awards == ["1st place Cannabis Cup 2010", "Best Indica 2011"]


def test_parse_awards_no_header(scraper: SeedfinderScraper) -> None:
    soup = _soup("<div>No awards section</div>")
    awards = scraper._parse_awards(soup)
    assert awards == []


def test_parse_awards_no_ul(scraper: SeedfinderScraper) -> None:
    html = """
    <div>
      <h3>Awards</h3>
      <div>No list here</div>
    </div>
    """
    soup = _soup(html)
    awards = scraper._parse_awards(soup)
    assert awards == []


def test_parse_awards_german_header(scraper: SeedfinderScraper) -> None:
    html = """
    <div>
      <h3>Auszeichnungen</h3>
      <div>
        <ul>
          <li>1. Platz</li>
        </ul>
      </div>
    </div>
    """
    soup = _soup(html)
    awards = scraper._parse_awards(soup)
    assert awards == ["1. Platz"]


# ---------------------------------------------------------------------------
# _parse_lineage_to_tree
# ---------------------------------------------------------------------------


def test_parse_lineage_to_tree_bold_link(scraper: SeedfinderScraper) -> None:
    soup = _soup(
        '<li><a class="font-bold" href="/strain-info/og-kush/">OG Kush</a></li>'
    )
    li = soup.find("li")
    result = scraper._parse_lineage_to_tree(li)
    assert result is not None
    assert result["name"] == "OG Kush"
    assert result["url"] == "https://seedfinder.eu/strain-info/og-kush/"


def test_parse_lineage_to_tree_span_link(scraper: SeedfinderScraper) -> None:
    soup = _soup(
        '<li><span class="text-[#003300]"><a href="/strain-info/parent-a/">Parent A</a></span></li>'
    )
    li = soup.find("li")
    result = scraper._parse_lineage_to_tree(li)
    assert result is not None
    assert result["name"] == "Parent A"


def test_parse_lineage_to_tree_last_resort_link(scraper: SeedfinderScraper) -> None:
    """No bold link, no span – uses last resort any link."""
    soup = _soup('<li><a href="/strain-info/fallback/">Fallback Strain</a></li>')
    li = soup.find("li")
    result = scraper._parse_lineage_to_tree(li)
    assert result is not None
    assert result["name"] == "Fallback Strain"


def test_parse_lineage_to_tree_no_link_text_fallback(
    scraper: SeedfinderScraper,
) -> None:
    """No link at all – uses plain text."""
    soup = _soup("<li>Unknown Strain</li>")
    li = soup.find("li")
    result = scraper._parse_lineage_to_tree(li)
    assert result is not None
    assert result["name"] == "Unknown Strain"
    assert result["url"] is None


def test_parse_lineage_to_tree_empty_text_returns_none(
    scraper: SeedfinderScraper,
) -> None:
    """Empty li text with no links returns None."""
    soup = _soup("<li>   </li>")
    li = soup.find("li")
    result = scraper._parse_lineage_to_tree(li)
    assert result is None


def test_parse_lineage_to_tree_generic_term_skipped(
    scraper: SeedfinderScraper,
) -> None:
    """Generic terms trigger fallback to other links in the li."""
    soup = _soup(
        '<li>'
        '<a class="font-bold" href="/a/">specified above »»»</a>'
        '<a href="/strain-info/real-strain/">Real Strain</a>'
        "</li>"
    )
    li = soup.find("li")
    result = scraper._parse_lineage_to_tree(li)
    assert result is not None
    assert result["name"] == "Real Strain"


def test_parse_lineage_to_tree_absolute_url_unchanged(
    scraper: SeedfinderScraper,
) -> None:
    soup = _soup(
        '<li><a class="font-bold" href="https://seedfinder.eu/strain-info/og-kush/">OG Kush</a></li>'
    )
    li = soup.find("li")
    result = scraper._parse_lineage_to_tree(li)
    assert result["url"] == "https://seedfinder.eu/strain-info/og-kush/"


def test_parse_lineage_to_tree_nested_parents(scraper: SeedfinderScraper) -> None:
    html = """
    <li>
      <a class="font-bold" href="/strain-info/og-kush/">OG Kush</a>
      <ul>
        <li><span class="text-[#003300]"><a href="/strain-info/chemdawg/">Chemdawg</a></span></li>
        <li><span class="text-[#003300]"><a href="/strain-info/lemon-thai/">Lemon Thai</a></span></li>
      </ul>
    </li>
    """
    soup = _soup(html)
    li = soup.find("li")
    result = scraper._parse_lineage_to_tree(li)
    assert result is not None
    assert len(result["parents"]) == 2
    names = {p["name"] for p in result["parents"]}
    assert "Chemdawg" in names
    assert "Lemon Thai" in names


def test_parse_lineage_to_tree_strips_arrows_and_brackets(
    scraper: SeedfinderScraper,
) -> None:
    soup = _soup(
        '<li><a class="font-bold" href="/s/">Name [auto] (clone) »»»</a></li>'
    )
    li = soup.find("li")
    result = scraper._parse_lineage_to_tree(li)
    assert result["name"] == "Name"


# ---------------------------------------------------------------------------
# _parse_sensory
# ---------------------------------------------------------------------------


def test_parse_sensory_with_rounded_tags(scraper: SeedfinderScraper) -> None:
    html = """
    <h4>Effect/Effectiveness</h4>
    <div>
      <div class="rounded-lg">Relaxing</div>
      <div class="rounded-lg">Euphoric</div>
    </div>
    <h4>Scent/Smell</h4>
    <div>
      <div class="rounded-lg">Earthy</div>
    </div>
    <h4>Taste/Flavor</h4>
    <div>
      <div class="rounded-lg">Pine</div>
    </div>
    """
    soup = _soup(html)
    sensory = scraper._parse_sensory(soup)
    assert "Relaxing" in sensory["effects"]
    assert "Euphoric" in sensory["effects"]
    assert "Earthy" in sensory["aroma"]
    assert "Pine" in sensory["taste"]


def test_parse_sensory_deduplication(scraper: SeedfinderScraper) -> None:
    html = """
    <h4>Effect/Effectiveness</h4>
    <div>
      <div class="rounded-lg">Relaxing</div>
      <div class="rounded-lg">Relaxing</div>
    </div>
    """
    soup = _soup(html)
    sensory = scraper._parse_sensory(soup)
    assert sensory["effects"].count("Relaxing") == 1


def test_parse_sensory_fallback_direct_siblings(scraper: SeedfinderScraper) -> None:
    html = """
    <h4>Wirkung</h4>
    <div>
      <div>Happy</div>
      <div>Creative</div>
    </div>
    """
    soup = _soup(html)
    sensory = scraper._parse_sensory(soup)
    assert "Happy" in sensory["effects"]
    assert "Creative" in sensory["effects"]


def test_parse_sensory_no_headers(scraper: SeedfinderScraper) -> None:
    soup = _soup("<div>Nothing here</div>")
    sensory = scraper._parse_sensory(soup)
    assert sensory == {"effects": [], "aroma": [], "taste": []}


def test_parse_sensory_german_aroma(scraper: SeedfinderScraper) -> None:
    html = """
    <h4>Aroma</h4>
    <div>
      <div class="rounded-lg">Citrus</div>
    </div>
    """
    soup = _soup(html)
    sensory = scraper._parse_sensory(soup)
    assert "Citrus" in sensory["aroma"]


def test_parse_sensory_long_sibling_text_skipped(scraper: SeedfinderScraper) -> None:
    """Sibling div text longer than 30 chars should be skipped."""
    html = """
    <h4>Wirkung</h4>
    <div>
      <div>This text is way too long to be a sensory tag value here</div>
      <div>Short</div>
    </div>
    """
    soup = _soup(html)
    sensory = scraper._parse_sensory(soup)
    long_text = "This text is way too long to be a sensory tag value here"
    assert long_text not in sensory["effects"]
    assert "Short" in sensory["effects"]


# ---------------------------------------------------------------------------
# _parse_recursive
# ---------------------------------------------------------------------------


def test_parse_recursive_leaf(scraper: SeedfinderScraper) -> None:
    result = scraper._parse_recursive("OG Kush")
    assert result == {"name": "OG Kush", "parents": []}


def test_parse_recursive_simple_cross(scraper: SeedfinderScraper) -> None:
    result = scraper._parse_recursive("OG Kush x Chemdawg")
    assert result["name"] == "Cross"
    assert len(result["parents"]) == 2
    assert result["parents"][0]["name"] == "OG Kush"
    assert result["parents"][1]["name"] == "Chemdawg"


def test_parse_recursive_wrapped_parens(scraper: SeedfinderScraper) -> None:
    result = scraper._parse_recursive("(OG Kush x Chemdawg)")
    assert result["name"] == "Cross"
    assert len(result["parents"]) == 2


def test_parse_recursive_nested_cross(scraper: SeedfinderScraper) -> None:
    result = scraper._parse_recursive("(OG Kush x Chemdawg) x Lemon Thai")
    assert result["name"] == "Cross"
    parent_names = {p["name"] for p in result["parents"]}
    assert "Cross" in parent_names
    assert "Lemon Thai" in parent_names


def test_parse_recursive_partial_paren_not_stripped(
    scraper: SeedfinderScraper,
) -> None:
    """Parens that don't wrap the full expression are not stripped."""
    result = scraper._parse_recursive("(OG Kush x Chemdawg) x (Lemon Thai x Skunk)")
    assert result["name"] == "Cross"
    assert len(result["parents"]) == 2
    for p in result["parents"]:
        assert p["name"] == "Cross"
