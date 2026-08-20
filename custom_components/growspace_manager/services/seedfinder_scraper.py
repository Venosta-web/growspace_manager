"""Seedfinder scraper for Growspace Manager."""

import logging
import re
from typing import Any

import aiohttp
from bs4 import BeautifulSoup, Tag

from custom_components.growspace_manager.exceptions import GrowspaceError
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://seedfinder.eu"
SEARCH_URL = f"{BASE_URL}/en/search/results/"


def _attr_str(tag: Tag, name: str) -> str | None:
    """Return a bs4 tag attribute as a plain string.

    bs4 types multi-valued attributes (e.g. class) as AttributeValueList; the
    attributes scraped here (href, src, x-data, :src) are always single
    strings in practice, so collapse that case defensively instead of
    assuming it away.
    """
    value = tag.get(name)
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(value)
    return None


class SeedfinderScraper:
    """Scraper for Seedfinder."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize."""
        self.hass = hass

    async def _async_fetch(self, url: str) -> str | None:
        """Fetch HTML content from a URL."""
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=15)
            ) as response:
                if response.status == 403:
                    _LOGGER.warning(
                        "Seedfinder fetch blocked (403) — the site is behind bot "
                        "protection (Cloudflare). Automated access is not possible"
                    )
                    raise ServiceValidationError(
                        "Seedfinder is temporarily unavailable: the site is currently "
                        "blocking automated access. Try again later or add the strain manually."
                    )
                if response.status != 200:
                    _LOGGER.error("Error fetching %s: %s", url, response.status)
                    return None
                return await response.text()
        except (aiohttp.ClientError, TimeoutError) as err:
            _LOGGER.error("Network error fetching %s: %s", url, err)
            return None
        except (
            AttributeError,
            KeyError,
            ValueError,
            GrowspaceError,
        ) as err:
            _LOGGER.error("Unexpected error fetching %s: %s", url, err)
            return None

    async def async_search_strains(
        self, query: str, blacklist: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """Search for strains on Seedfinder."""
        session = async_get_clientsession(self.hass)
        params = {"search": query}

        try:
            async with session.get(
                SEARCH_URL, params=params, timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status == 403:
                    _LOGGER.warning(
                        "Seedfinder search blocked (403) — the site is behind bot "
                        "protection (Cloudflare). Automated access is not possible"
                    )
                    raise ServiceValidationError(
                        "Seedfinder is temporarily unavailable: the site is currently "
                        "blocking automated access. Try again later or add the strain manually."
                    )
                if response.status != 200:
                    _LOGGER.error("Error searching Seedfinder: %s", response.status)
                    return []

                html = await response.text()
                soup = await self.hass.async_add_executor_job(
                    BeautifulSoup, html, "html.parser"
                )

                results: list[dict[str, Any]] = []
                # Search results are typically in a table or list
                # Based on inspection, we look for links containing /strain-info/
                for link in soup.find_all("a", href=re.compile(r"/strain-info/")):
                    name = link.text.strip()
                    url = _attr_str(link, "href")
                    if not url:
                        continue
                    if not url.startswith("http"):
                        url = BASE_URL + url

                    # Try to find breeder info nearby (usually in the same row)
                    parent_row = link.find_parent("tr")
                    breeder = "Unknown"
                    if parent_row:
                        cells = parent_row.find_all("td")
                        if len(cells) > 1:
                            # Breeder is often in the second or third cell
                            breeder_link = parent_row.find(
                                "a", href=re.compile(r"/breeder/")
                            )
                            if breeder_link:
                                breeder = breeder_link.text.strip()

                    # Filter out blacklisted breeders
                    if blacklist and breeder in blacklist:
                        _LOGGER.debug(
                            "Skipping strain %s from blacklisted breeder %s",
                            name,
                            breeder,
                        )
                        continue

                    if name and url and name not in [r["name"] for r in results]:
                        results.append({"name": name, "breeder": breeder, "url": url})

                query_lower = query.lower()

                def _rank(result: dict) -> int:
                    name_lower = result["name"].lower()
                    if name_lower == query_lower:
                        return 0
                    if name_lower.startswith(query_lower):
                        return 1
                    return 2

                results.sort(key=_rank)
                return results

        except (aiohttp.ClientError, TimeoutError) as err:
            _LOGGER.error("Network error searching Seedfinder: %s", err)
            return []
        except (
            AttributeError,
            KeyError,
            ValueError,
            GrowspaceError,
        ) as err:
            _LOGGER.error("Unexpected error searching Seedfinder: %s", err)
            return []

    async def async_get_strain_details(self, url: str) -> dict[str, Any] | None:
        """Get strain details from Seedfinder."""
        session = async_get_clientsession(self.hass)

        try:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status != 200:
                    _LOGGER.error(
                        "Error fetching Seedfinder details: %s", response.status
                    )
                    return None

                html = await response.text()
                soup = await self.hass.async_add_executor_job(
                    BeautifulSoup, html, "html.parser"
                )

                # Extract info using helper methods
                name, breeder = self._parse_basic_info(soup)
                image_urls = self._parse_images(soup)
                comp_data = self._parse_composition(soup)
                metrics = self._parse_metrics(soup)

                # Merge composition metrics with table metrics
                if comp_data.get("flowering_time") and not metrics.get(
                    "flowering_time"
                ):
                    metrics["flowering_time"] = comp_data["flowering_time"]

                thc = metrics.get("thc") or self._parse_thc(html)
                lineage_str = self._parse_lineage_str(soup)
                description = self._parse_description(soup)
                awards = self._parse_awards(soup)
                sensory = self._parse_sensory(soup)

                # Extract Lineage Tree
                lineage_tree = {}
                # Try finding by ID first, then by common containers
                lineage_div = soup.find("div", id="lineage")
                if not lineage_div:
                    # Fallback: look for a div that contains "Lineage" or "Abstammung"
                    lineage_header = soup.find(
                        ["h2", "h3"],
                        string=re.compile(r"Lineage|Abstammung", re.IGNORECASE),
                    )
                    if lineage_header:
                        lineage_div = lineage_header.find_next("div")

                if lineage_div:
                    # Seedfinder lineage is usually in a UL
                    root_ul = lineage_div.find("ul")
                    if root_ul:
                        root_li = root_ul.find("li", recursive=False)
                        if root_li:
                            lineage_tree = self._parse_lineage_to_tree(root_li) or {}

                        if not lineage_tree and lineage_str:
                            # Fallback to string parsing if UL structure not found
                            parts = lineage_str.split(" \u00bb\u00bb\u00bb ")
                            core_lineage = parts[-1] if parts else lineage_str
                            lineage_tree = self._parse_recursive(core_lineage)

                return {
                    "name": name,
                    "breeder": breeder,
                    "type": "Hybrid",
                    "composition": {
                        "sativa": comp_data["sativa"],
                        "indica": comp_data["indica"],
                    },
                    "flowering_time": metrics.get("flowering_time"),
                    "lineage_str": lineage_str,
                    "description": description,
                    "images": image_urls,
                    "yield_potential": metrics.get("yield_potential"),
                    "height": metrics.get("height"),
                    "thc": thc,
                    "cbd": metrics.get("cbd"),
                    "cbg": metrics.get("cbg"),
                    "awards": awards,
                    "lineage_tree": lineage_tree,
                    "effects": sensory.get("effects", []),
                    "aroma": sensory.get("aroma", []),
                    "taste": sensory.get("taste", []),
                }

        except (aiohttp.ClientError, TimeoutError) as err:
            _LOGGER.error("Network error fetching Seedfinder details: %s", err)
            return None
        except (
            AttributeError,
            KeyError,
            ValueError,
            ServiceValidationError,
            GrowspaceError,
        ) as err:
            _LOGGER.error("Unexpected error fetching Seedfinder details: %s", err)
            return None

    def _parse_basic_info(self, soup: BeautifulSoup) -> tuple[str, str]:
        """Extract name and breeder."""
        title_tag = soup.find("h1")
        name = title_tag.text.strip() if title_tag else "Unknown"

        breeder = "Unknown"
        breeder_link = soup.find("a", href=re.compile(r"/breeder/"))
        if breeder_link:
            breeder = breeder_link.text.strip()

        return name, breeder

    _MAX_GALLERY_IMAGES = 10

    def _parse_images(self, soup: BeautifulSoup) -> list[str]:
        """Extract gallery image URLs, capped at 10.

        Tries three strategies in order:
        1. Alpine.js x-data JSON gallery (newer Seedfinder pages).
        2. Plain <img src="/storage/pics/galerie/..."> tags (older pages).
        3. Single-image fallback via _parse_image.
        """
        # Strategy 1: Alpine.js x-data (supports both JSON and JS object literal syntax)
        for tag in soup.find_all(lambda t: t.has_attr("x-data")):
            x_data_raw = _attr_str(tag, "x-data") or ""
            urls = []
            for match in re.finditer(r'"?big"?:\s*["\']([^"\']+)["\']', x_data_raw):
                url = match.group(1)
                if not url or "=404" in url:
                    continue
                if not url.startswith("http"):
                    url = BASE_URL + url
                if url not in urls:
                    urls.append(url)
                if len(urls) >= self._MAX_GALLERY_IMAGES:
                    break
            if urls:
                return urls

        # Strategy 2: plain galerie img tags (e.g. Sunset Paradise)
        seen: set[str] = set()
        galerie_urls: list[str] = []
        for img in soup.find_all("img", src=re.compile(r"/storage/pics/galerie/")):
            url = _attr_str(img, "src")
            if not url or "=404" in url:
                continue
            if not url.startswith("http"):
                url = BASE_URL + url
            if url not in seen:
                seen.add(url)
                galerie_urls.append(url)
            if len(galerie_urls) >= self._MAX_GALLERY_IMAGES:
                break
        if galerie_urls:
            return galerie_urls

        # Strategy 3: single-image fallback
        single = self._parse_image(soup, "")
        return [single] if single else []

    def _parse_image(self, soup: BeautifulSoup, name: str) -> str | None:
        """Extract primary strain image."""
        # Prefer the official breeder image embedded in the Alpine.js :src binding.
        # The expression is: selectedIndex === -1 ? 'URL' : images[selectedIndex].big
        alpine_img = soup.find("img", attrs={":src": True})
        if alpine_img:
            src_expr = _attr_str(alpine_img, ":src") or ""
            match = re.search(r"selectedIndex === -1 \? '([^']+)'", src_expr)
            if match:
                image_url = match.group(1)
                if "=404" in image_url:
                    return None
                if not image_url.startswith("http"):
                    image_url = BASE_URL + image_url
                return image_url

        # Fallback: first gallery image with a real src attribute
        img_tag = soup.find("img", src=re.compile(r"/storage/pics/"))
        if img_tag:
            image_url = _attr_str(img_tag, "src")
            if not image_url or "=404" in image_url:
                return None
            if not image_url.startswith("http"):
                image_url = BASE_URL + image_url
            return image_url
        return None

    def _parse_composition(self, soup: BeautifulSoup) -> dict[str, Any]:
        """Extract sativa/indica percentages and any embedded metrics."""
        # Use more flexible header search
        basic_info_h2 = soup.find(
            ["h2", "h3"],
            string=re.compile(
                r"Basic .* Information|Grundlegende Information", re.IGNORECASE
            ),
        )

        if not basic_info_h2:
            basic_info_h2 = soup.find(
                lambda tag: (
                    tag.name in ["h2", "h3"]
                    and ("Basic" in tag.text or "Grundlegende" in tag.text)
                )
            )

        data: dict[str, Any] = {
            "sativa": None,
            "indica": None,
            "flowering_time": None,
            "yield": None,
        }
        if not basic_info_h2:
            return data

        # Look for the first paragraph or div after the header that contains text
        content_node = basic_info_h2.find_next(["p", "div"])
        if not content_node or len(content_node.get_text()) < 10:
            for sibling in basic_info_h2.find_next_siblings(["p", "div"]):
                if len(sibling.get_text()) > 10:
                    content_node = sibling
                    break

        if not content_node:
            return data

        text = content_node.get_text()

        # Sativa/Indica percentages
        sativa_match = re.search(r"(\d+(?:\.\d+)?)\s*%\s*sativa", text, re.IGNORECASE)
        indica_match = re.search(r"(\d+(?:\.\d+)?)\s*%\s*indica", text, re.IGNORECASE)
        if sativa_match and indica_match:
            data["sativa"] = float(sativa_match.group(1))
            data["indica"] = float(indica_match.group(1))
            # If both are reported as 0%, treat as unknown
            if data["sativa"] == 0 and data["indica"] == 0:
                data["sativa"] = data["indica"] = None
        # Fallback for German descriptive terms
        elif "indicadominiert" in text.lower() or "indica-dominant" in text.lower():
            data["sativa"], data["indica"] = 30, 70
        elif "sativadominiert" in text.lower() or "sativa-dominant" in text.lower():
            data["sativa"], data["indica"] = 70, 30
        elif "reine indica" in text.lower() or "pure indica" in text.lower():
            data["sativa"], data["indica"] = 0, 100
        elif "reine sativa" in text.lower() or "pure sativa" in text.lower():
            data["sativa"], data["indica"] = 100, 0

        # Embedded flowering time in paragraph: "Blütezeit von ±58" or "flowering time of 60 days"
        flow_match = re.search(
            r"(?:flowering time of|bl\u00fctizeit von)\s*(?:\u00b1|~|&plusmn;)?\s*(\d+)(?:\s*-\s*(\d+))?",
            text,
            re.IGNORECASE,
        )
        if flow_match:
            if flow_match.group(2):
                data["flowering_time"] = (
                    f"{flow_match.group(1)}-{flow_match.group(2)} days"
                )
            else:
                data["flowering_time"] = f"{flow_match.group(1)} days"

        return data

    def _parse_metrics(self, soup: BeautifulSoup) -> dict[str, Any]:
        """Extract metrics like yield, height, and cannabinoids."""
        metrics: dict[str, Any] = {}

        # Use anchored patterns so we only match label text nodes, not prose containing these words
        # Flowering time
        flowering_header = soup.find(
            string=re.compile(
                r"^(?:Flowering Time|Bl\u00fctizeit|Bl\u00fctedauer)$", re.IGNORECASE
            )
        )
        if flowering_header:
            container = flowering_header.find_parent(["div", "td", "tr"])
            if container:
                val_node = container.find_next_sibling(["div", "td"])
                if val_node:
                    val_text = val_node.get_text().strip()
                    days_match = re.search(r"(\d+)\s*-\s*(\d+)", val_text)
                    if days_match:
                        metrics["flowering_time"] = (
                            f"{days_match.group(1)}-{days_match.group(2)} days"
                        )
                    else:
                        metrics["flowering_time"] = val_text

        # Yield
        yield_header = soup.find(
            string=re.compile(r"^(?:Yield|Ertrag|Ertragspotenzial)$", re.IGNORECASE)
        )
        if yield_header:
            container = yield_header.find_parent(["div", "td", "tr"])
            if container:
                val_node = container.find_next_sibling(["div", "td"])
                if val_node:
                    metrics["yield_potential"] = val_node.get_text().strip()

        # Height \u2014 anchored to avoid matching "height" in user comments
        height_header = soup.find(
            string=re.compile(r"^(?:Height|H\u00f6he)$", re.IGNORECASE)
        )
        if height_header:
            container = height_header.find_parent(["div", "td", "tr"])
            if container:
                val_node = container.find_next_sibling(["div", "td"])
                if val_node:
                    metrics["height"] = val_node.get_text().strip()

        # Fallback: search general text for yield/flowering if still missing
        full_text = soup.get_text()
        if not metrics.get("yield_potential"):
            yield_match = re.search(
                r"(?:Yield|Ertrag):\s*(\w+)", full_text, re.IGNORECASE
            )
            if yield_match:
                metrics["yield_potential"] = yield_match.group(1)

        if not metrics.get("flowering_time"):
            flow_match = re.search(
                r"(?:Indoor flowering|Bl\u00fctezeits?):\s*(\d+)(?:\s*-\s*(\d+))?\s*(?:days|tage)",
                full_text,
                re.IGNORECASE,
            )
            if flow_match:
                if flow_match.group(2):
                    metrics["flowering_time"] = (
                        f"{flow_match.group(1)}-{flow_match.group(2)} days"
                    )
                else:
                    metrics["flowering_time"] = f"{flow_match.group(1)} days"

        for keyword, pattern in [
            ("indoor", r"Indoor:\s*(\d+(?:\.\d+)?)"),
            ("outdoor", r"Outdoor:\s*(\d+(?:\.\d+)?)"),
            ("potency", r"(?:Potency|Potenz):\s*(\d+(?:\.\d+)?)"),
        ]:
            match = re.search(pattern, full_text, re.IGNORECASE)
            if match:
                metrics[keyword.lower()] = float(match.group(1))

        # THC/CBD/CBG
        for keyword in ["THC", "CBD", "CBG"]:
            pattern = rf"{keyword}\s*(?:content)?\s*:\s*(?:.*?\(?over\s+)?([\d.]+)"
            match = re.search(pattern, full_text, re.IGNORECASE)
            if match:
                metrics[keyword.lower()] = float(match.group(1))

        return metrics

    def _parse_thc(self, html: str) -> float | None:
        """Extract THC percentage from raw HTML."""
        thc_match = re.search(r"THC:\s*(\d+(?:\.\d)?)%", html)
        return float(thc_match.group(1)) if thc_match else None

    def _parse_lineage_str(self, soup: BeautifulSoup) -> str:
        """Extract flat lineage string."""
        lineage_div = soup.find("div", id="lineage")
        if lineage_div:
            # Try to find the summary text "A x B"
            # Look for the first list item that contains an "x" and multiple links
            root_ul = lineage_div.find("ul")
            if root_ul:
                root_li = root_ul.find("li")
                if root_li:
                    links = root_li.find_all("a", recursive=False)
                    if len(links) >= 2:
                        names = [
                            link.get_text(strip=True)
                            .replace(" \u00bb\u00bb\u00bb", "")
                            .replace("\u00bb\u00bb\u00bb", "")
                            .strip()
                            for link in links
                        ]
                        return " x ".join(names)

            # Fallback to regex on text
            lineage_text = lineage_div.get_text()
            lineage_match = re.search(
                r"(?:Lineage|Abstammung):\s*(.*)", lineage_text, re.IGNORECASE
            )
            if lineage_match:
                return lineage_match.group(1).strip()
        return ""

    def _parse_description(self, soup: BeautifulSoup) -> str:
        """Extract breeder description."""
        patterns = [
            r"Basic .* Information",
            r"Basic infos?",
            r"Breeder Description",
            r"Grundlegende Information",
        ]
        for pattern in patterns:
            # Look for headers that CONTAIN the pattern
            header = soup.find(
                ["h2", "h3", "h4"], string=re.compile(pattern, re.IGNORECASE)
            )
            if not header:
                # Try finding by text if string match fails
                header = soup.find(
                    lambda tag, p=pattern: (
                        tag.name in ["h2", "h3", "h4"]
                        and bool(re.search(p, tag.get_text(), re.IGNORECASE))
                    )
                )
            if header:
                # Prefer the immediate next content node over the parent container,
                # since the container often includes navigation and unrelated sections.
                next_node = header.find_next(["p", "div"])
                if next_node and len(next_node.get_text()) > 20:
                    text = next_node.get_text(separator="\n", strip=True)
                else:
                    container = header.find_parent("div")
                    if (
                        container
                        and len(container.get_text()) > len(header.get_text()) + 20
                    ):
                        text = container.get_text(separator="\n", strip=True)
                    else:
                        continue

                # Clean up
                text = re.sub(
                    rf"^{re.escape(header.get_text())}", "", text, flags=re.IGNORECASE
                ).strip()
                text = re.sub(r"\[\d+\]", "", text)
                text = re.sub(r"\n{3,}", "\n\n", text)
                return text.strip()
        return ""

    def _parse_awards(self, soup: BeautifulSoup) -> list[str]:
        """Extract awards list."""
        awards = []
        awards_h3 = soup.find(
            ["h2", "h3"], string=re.compile(r"Awards|Auszeichnungen", re.IGNORECASE)
        )
        if awards_h3:
            # Scope to the parent section to avoid jumping into unrelated ULs (e.g. lineage tree)
            section = awards_h3.find_parent("div")
            awards_list = section.find("ul") if section else None
            if awards_list:
                awards = [li.get_text().strip() for li in awards_list.find_all("li")]
        return awards

    def _parse_lineage_to_tree(self, li: Tag) -> dict[str, Any] | None:
        """Recursive helper to parse lineage tree from UL/LI structure."""
        # The root li has a direct bold link (the strain itself); child lis wrap the
        # strain link in a colored span. Direct-child plain links are »»» derivation
        # indicators and must not be used as the strain name.
        main_link = li.find("a", class_=re.compile(r"font-bold"), recursive=False)
        if not main_link:
            strain_span = li.find("span", class_=re.compile(r"text-\[#003300\]"))
            if strain_span:
                main_link = strain_span.find("a")

        if not main_link:
            # Last resort: any link that is not inside a nested ul
            nested_ul = li.find("ul")
            for link in li.find_all("a"):
                if nested_ul is None or link.find_parent("ul") is not nested_ul:
                    main_link = link
                    break

        if not main_link:
            # Fallback to text if no link is found
            text = li.get_text(strip=True).split("\u00bb\u00bb\u00bb")[0].strip()
            if not text:
                return None
            name = text
            url = None
        else:
            name = (
                main_link.get_text()
                .strip()
                .replace(" \u00bb\u00bb\u00bb", "")
                .replace("\u00bb\u00bb\u00bb", "")
            )
            url = _attr_str(main_link, "href")

        # Clean up name
        name = re.sub(r"\s*\[.*?\]", "", name)
        name = re.sub(r"\s*\(.*?\)", "", name)
        name = name.replace("\u00bb\u00bb\u00bb", "").strip()

        # If the name is too generic (e.g. "specified above", "probably"), try to find a better one in the same li
        generic_terms = [
            "specified above",
            "probably",
            "unknown",
            "oben angegeben",
            "unbekannt",
            "wahrscheinlich",
        ]
        if any(x in name.lower() for x in generic_terms):
            links = li.find_all("a")
            for link in links:
                l_text = link.get_text(strip=True)
                if not any(x in l_text.lower() for x in generic_terms):
                    name = (
                        l_text.replace(" \u00bb\u00bb\u00bb", "")
                        .replace("\u00bb\u00bb\u00bb", "")
                        .strip()
                    )
                    url = _attr_str(link, "href")
                    break

        if url and url.startswith("/"):
            url = f"https://seedfinder.eu{url}"

        node: dict[str, Any] = {"name": name, "url": url, "parents": []}

        # Look for nested UL which contains the parents
        nested_ul = li.find("ul")
        if nested_ul:
            # We want to find the NEXT level of LIs.
            # find_all with recursive=False ensures we only take the direct children of THIS ul.
            for nested_li in nested_ul.find_all("li", recursive=False):
                parent_node = self._parse_lineage_to_tree(nested_li)
                if parent_node:
                    node["parents"].append(parent_node)

        return node

    def _parse_sensory(self, soup: BeautifulSoup) -> dict[str, list[str]]:
        """Extract sensory data from Degustation section."""
        sensory: dict[str, list[str]] = {"effects": [], "aroma": [], "taste": []}

        sensory_map = {
            "effects": ["Effect/Effectiveness", "Wirkung", "Wirksamkeit"],
            "aroma": ["Scent/Smell", "Aroma", "Geruch"],
            "taste": ["Taste/Flavor", "Geschmack", "Schmecken"],
        }

        for key, headers in sensory_map.items():
            for header_text in headers:
                # Use recursive search and check text content
                header_node = soup.find(
                    lambda tag, ht=header_text: (
                        tag.name in ["h2", "h3", "h4"]
                        and ht.lower() in tag.get_text().lower()
                    )
                )
                if header_node:
                    # Look for rounded-lg divs or primary color badges in siblings
                    container = header_node.find_next("div")
                    if container:
                        # Values are in rounded-lg divs or similar
                        tags = container.find_all(
                            "div", class_=re.compile(r"rounded-lg|bg-primary|badge")
                        )
                        if not tags:
                            # Try finding direct siblings that look like tags
                            for sibling in container.find_all("div", recursive=False):
                                val = sibling.get_text().strip()
                                if val and len(val) < 30:
                                    sensory[key].append(val)
                        else:
                            for tag in tags:
                                val = tag.get_text().strip()
                                if val and val not in sensory[key]:
                                    sensory[key].append(val)
                    break
        return sensory

    def _parse_recursive(self, lineage: str) -> dict[str, Any]:
        """Recursively parse lineage string."""
        lineage = lineage.strip()

        if lineage.startswith("(") and lineage.endswith(")"):
            balance = 0
            is_wrapped = True
            for i, char in enumerate(lineage):
                if char == "(":
                    balance += 1
                elif char == ")":
                    balance -= 1
                if balance == 0 and i < len(lineage) - 1:
                    is_wrapped = False
                    break
            if is_wrapped:
                return self._parse_recursive(lineage[1:-1])

        split_idx = -1
        balance = 0
        for i in range(len(lineage) - 3):
            char = lineage[i]
            if char == "(":
                balance += 1
            elif char == ")":
                balance -= 1

            if balance == 0 and lineage[i : i + 3] == " x ":
                split_idx = i
                break

        if split_idx != -1:
            parent1_str = lineage[:split_idx].strip()
            parent2_str = lineage[split_idx + 3 :].strip()

            return {
                "name": "Cross",
                "parents": [
                    self._parse_recursive(parent1_str),
                    self._parse_recursive(parent2_str),
                ],
            }

        return {"name": lineage, "parents": []}
