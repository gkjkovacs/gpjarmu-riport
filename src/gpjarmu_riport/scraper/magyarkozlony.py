"""
Magyar Közlöny scraper.

Discovers issues in a date range from https://magyarkozlony.hu, fetches
the per-issue 'megtekintes' (online) HTML, and parses it into
Bekezdes (paragraph) units. Falls back to 'letoltes' (PDF) if HTML is unavailable.
"""

from __future__ import annotations

import hashlib
import logging
import re
import tempfile
from dataclasses import dataclass, field
from datetime import date, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from ..config import Settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class IssueMeta:
    number: str              # e.g. "2026. évi 83. szám"
    issue_id: str            # e.g. "2026/83"
    date: str                # ISO YYYY-MM-DD
    has_indokolas: bool
    megtekintes_url: str
    letoltes_url: str
    indokolas_url: Optional[str] = None


@dataclass
class Bekezdes:
    anchor: str
    heading: str
    text: str
    has_indokolas: bool = False
    indokolas_url: Optional[str] = None
    indokolas_text: str = ""


# ---------------------------------------------------------------------------
# Date / number parsing
# ---------------------------------------------------------------------------

_HU_MONTHS = {
    "január": 1, "február": 2, "március": 3, "április": 4, "május": 5, "június": 6,
    "július": 7, "augusztus": 8, "szeptember": 9, "október": 10,
    "november": 11, "december": 12, "decemebr": 12,
}

_RE_ISSUE = re.compile(r"(\d{4})\.\s*évi\s+(\d+)\.\s*szám")
_RE_DATE_HU = re.compile(
    r"(\d{4})\.\s*(január|február|március|április|május|június|július|"
    r"augusztus|szeptember|október|november|decemebr|december)\s*(\d{1,2})\.?",
    re.IGNORECASE,
)


def _parse_hu_date(text: str) -> Optional[str]:
    m = _RE_DATE_HU.search(text)
    if not m:
        return None
    y, mo_name, d = m.group(1), m.group(2).lower(), int(m.group(3))
    mo = _HU_MONTHS.get(mo_name)
    if not mo:
        return None
    try:
        return date(int(y), mo, d).isoformat()
    except ValueError:
        return None


_RE_ANCHOR = re.compile(
    r"(\d{1,3})\.\s*§|\b([IVX]{1,5})\.\s*(?:fejezet|cím|alcím|rész)\b|\(([1-9]\d?)\)",
)


def _infer_anchor(heading: str) -> Optional[str]:
    m = _RE_ANCHOR.search(heading)
    if not m:
        return None
    if m.group(1):
        return f"{m.group(1)}. §"
    if m.group(2):
        return f"{m.group(2)}. fejezet"
    if m.group(3):
        return f"({m.group(3)})"
    return None


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

class MagyarKozlonyClient:
    """HTTP client for magyarkozlony.hu."""

    def __init__(self, settings: Settings):
        self.base_url = settings.kozlony_base_url.rstrip("/")
        self.timeout = settings.scraper_timeout
        self.user_agent = settings.scraper_user_agent
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "hu,en;q=0.5",
        })

    def get(self, url: str) -> str:
        """Fetch URL, return text. Raises on non-2xx."""
        resp = self.session.get(url, timeout=self.timeout)
        resp.raise_for_status()
        # The site sometimes serves ISO-8859-2 — let requests detect.
        if resp.encoding and resp.encoding.lower() in ("iso-8859-2", "latin-2"):
            return resp.content.decode("iso-8859-2", errors="replace")
        return resp.text

    # -- Issue discovery --

    def list_issues(self, start: date, end: date, max_pages: int = 20) -> list[IssueMeta]:
        """
        Discover Magyar Közlöny issues published within [start, end].
        Filters out Hivatalos Értesítő. Paginates the homepage.
        """
        found: dict[str, IssueMeta] = {}
        for page in range(1, max_pages + 1):
            url = f"{self.base_url}/?page={page}" if page > 1 else self.base_url
            try:
                html = self.get(url)
            except requests.RequestException as e:
                logger.warning("Page %d fetch failed: %s", page, e)
                break

            for issue in self._parse_issue_list(html):
                if "Hivatalos Értesítő" in issue.number or "Hivatalos Értesítő" in issue.date:
                    continue
                issue_date = date.fromisoformat(issue.date)
                if not (start <= issue_date <= end):
                    if issue_date < start and page > 1:
                        return sorted(
                            found.values(),
                            key=lambda i: (i.date, i.issue_id),
                            reverse=True,
                        )
                    continue
                found[issue.issue_id] = issue

            if "/dokumentumok/" not in html:
                break

        return sorted(found.values(), key=lambda i: (i.date, i.issue_id), reverse=True)

    def _parse_issue_list(self, html: str) -> list[IssueMeta]:
        """
        Parse the homepage issue table.

        Expected structure (best-effort):
          <tr>
            <td><a href="/dokumentumok/{hash}/megtekintes">2026. évi 83. szám</a></td>
            <td>2026. július 1.</td>
            <td>Indokolás</td>
          </tr>
        """
        soup = BeautifulSoup(html, "lxml")
        results: list[IssueMeta] = []
        for row in soup.find_all("tr"):
            link = row.find("a", href=re.compile(r"/dokumentumok/.+/megtekintes"))
            if not link:
                continue
            number_raw = link.get_text(strip=True)

            # Drop Hivatalos Értesítő rows early — they appear in the same table
            cells = row.find_all("td")
            if any("Hivatalos Értesítő" in c.get_text() for c in cells):
                continue
            if "Hivatalos Értesítő" in number_raw:
                continue

            num_match = _RE_ISSUE.search(number_raw)
            if not num_match:
                continue
            year, seq = num_match.group(1), num_match.group(2)
            issue_id = f"{year}/{seq}"

            # Date is in the next <td>
            if len(cells) < 2:
                continue
            iso_date = _parse_hu_date(cells[1].get_text(" ", strip=True))
            if not iso_date:
                continue

            megtekintes_url = urljoin(self.base_url, link["href"])
            letoltes_url = megtekintes_url.replace("/megtekintes", "/letoltes")
            has_ind = len(cells) >= 3 and cells[2].get_text(strip=True)
            indokolas_url = (
                megtekintes_url.replace("/megtekintes", "/indokolas") if has_ind else None
            )

            results.append(IssueMeta(
                number=number_raw,
                issue_id=issue_id,
                date=iso_date,
                has_indokolas=bool(has_ind),
                megtekintes_url=megtekintes_url,
                letoltes_url=letoltes_url,
                indokolas_url=indokolas_url,
            ))
        return results

    # -- Per-issue content --

    def fetch_issue_content(self, meta: IssueMeta) -> list[Bekezdes]:
        """
        Fetch the per-issue 'megtekintes' HTML and parse it into Bekezdes units.
        Attaches indokolás text if present.
        """
        try:
            html = self.get(meta.megtekintes_url)
            bekezdes_list = self._parse_issue_html(html)
        except requests.RequestException as e:
            logger.warning("megtekintes fetch failed for %s: %s — trying PDF", meta.issue_id, e)
            return self.fetch_issue_pdf(meta)

        # Fetch indokolás if present
        if meta.has_indokolas and meta.indokolas_url:
            try:
                ind_html = self.get(meta.indokolas_url)
                ind_bekezdes = self._parse_issue_html(ind_html)
                if ind_bekezdes:
                    global_ind = ind_bekezdes[0].text
                    for b in bekezdes_list:
                        b.has_indokolas = True
                        b.indokolas_url = meta.indokolas_url
                        b.indokolas_text = global_ind
            except requests.RequestException as e:
                logger.debug("indokolás fetch failed for %s: %s", meta.issue_id, e)

        return bekezdes_list

    def _parse_issue_html(self, html: str) -> list[Bekezdes]:
        soup = BeautifulSoup(html, "lxml")
        # Walk through headings and grab the paragraphs that follow.
        out: list[Bekezdes] = []
        current_heading = ""
        current_text: list[str] = []
        current_anchor: Optional[str] = None

        for elem in soup.find_all(["h1", "h2", "h3", "h4", "p", "div"]):
            if elem.name in ("h1", "h2", "h3", "h4"):
                if current_text and "".join(current_text).strip():
                    out.append(self._build_bekezdes(
                        current_heading, current_anchor, "".join(current_text)
                    ))
                current_heading = elem.get_text(" ", strip=True)
                current_anchor = _infer_anchor(current_heading)
                current_text = []
            else:
                cls = " ".join(elem.get("class", []))
                if elem.name == "p" or "bekezdes" in cls:
                    txt = elem.get_text(" ", strip=True)
                    if txt:
                        current_text.append(txt)

        if current_text and "".join(current_text).strip():
            out.append(self._build_bekezdes(
                current_heading, current_anchor, "".join(current_text)
            ))
        return out

    def _build_bekezdes(
        self, heading: str, anchor: Optional[str], text: str
    ) -> Bekezdes:
        return Bekezdes(
            anchor=anchor or heading[:40] or "ismeretlen",
            heading=heading,
            text=text,
        )

    def fetch_issue_pdf(self, meta: IssueMeta) -> list[Bekezdes]:
        """Fallback: download the PDF, extract text with pdfplumber, split on blank lines."""
        try:
            import pdfplumber
        except ImportError as e:
            raise ImportError("pdfplumber is required for PDF fallback.") from e

        resp = self.session.get(meta.letoltes_url, timeout=self.timeout)
        resp.raise_for_status()
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as fh:
            fh.write(resp.content)
            pdf_path = fh.name

        chunks: list[Bekezdes] = []
        with pdfplumber.open(pdf_path) as pdf:
            full_text = "\n\n".join((p.extract_text() or "") for p in pdf.pages)

        for i, chunk in enumerate(full_text.split("\n\n"), start=1):
            chunk = chunk.strip()
            if len(chunk) < 30:
                continue
            anchor = _infer_anchor(chunk) or f"p{i}"
            chunks.append(Bekezdes(anchor=anchor, heading="", text=chunk))
        return chunks


# ---------------------------------------------------------------------------
# Hashing helper
# ---------------------------------------------------------------------------

def content_hash(b: Bekezdes) -> str:
    norm = re.sub(r"\s+", " ", b.text.lower()).strip()
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


__all__ = [
    "MagyarKozlonyClient",
    "IssueMeta",
    "Bekezdes",
    "content_hash",
]
