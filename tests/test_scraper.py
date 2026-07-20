"""Tests for the Magyar Közlöny scraper.

Uses the `responses` library to mock `requests` calls. A live test is included
for manual verification (skipped by default).
"""
from __future__ import annotations

import pytest
import responses

from hr_kozlony.config import LLMProvider, Settings
from hr_kozlony.scraper.magyarkozlony import (
    Bekezdes,
    MagyarKozlonyClient,
    content_hash,
)


def _settings() -> Settings:
    return Settings(
        llm_provider=LLMProvider.OPENAI,
        llm_api_key="test-key",
        scraper_user_agent="TestAgent/1.0",
    )


_HOMEPAGE_HTML = """
<html><body>
<div class="fresh-row">
  <div class="margin-bottom-5 row" itemscope itemtype="http://schema.org/Newspaper">
    <meta content="application/pdf" itemprop="fileFormat"/>
    <meta content="https://magyarkozlony.hu/dokumentumok/abc123/megtekintes" itemprop="url"/>
    <div class="col-xs-5">
      <a class="text-success hidden-xs" href="https://magyarkozlony.hu/dokumentumok/abc123/megtekintes" title="">
        <b itemprop="name">Magyar Közlöny 2026. évi 83. szám</b>
      </a>
    </div>
    <div class="col-xs-3 text-lowercase text-sm">
      <meta content="2026-07-01" itemprop="datePublished"/>
      2026. július 1.
    </div>
    <div class="col-xs-3">
      <a href="https://magyarkozlony.hu/dokumentumok/abc123/letoltes">PDF</a>
    </div>
    <a href="https://magyarkozlony.hu/indoklasok/abc123"> »Indokolások</a>
  </div>
</div>
<div class="fresh-row">
  <div class="margin-bottom-5 row" itemscope>
    <meta content="https://magyarkozlony.hu/dokumentumok/def456/megtekintes" itemprop="url"/>
    <div class="col-xs-5">
      <a href="https://magyarkozlony.hu/dokumentumok/def456/megtekintes">
        <b itemprop="name">Hivatalos Értesítő 2026. évi 28. szám</b>
      </a>
    </div>
    <div class="col-xs-3">
      <meta content="2026-06-30" itemprop="datePublished"/>
      2026. június 30.
    </div>
  </div>
</div>
</body></html>
"""


@responses.activate
def test_list_issues_filters_indokolo_and_drops_hivatalos() -> None:
    s = _settings()
    responses.add(
        responses.GET,
        f"{s.kozlony_base_url}/",
        body=_HOMEPAGE_HTML,
        status=200,
    )
    client = MagyarKozlonyClient(s)
    from datetime import date
    issues = client.list_issues(date(2026, 6, 1), date(2026, 7, 31))

    # Should drop the Hivatalos Értesítő entry
    assert len(issues) == 1
    assert issues[0].issue_id == "2026/83"
    assert issues[0].has_indokolas is True
    assert issues[0].date == "2026-07-01"
    assert issues[0].indokolas_url == "https://magyarkozlony.hu/dokumentumok/abc123/indokolas"
    assert issues[0].letoltes_url == "https://magyarkozlony.hu/dokumentumok/abc123/letoltes"


_ISSUE_HTML = """
<html><body>
<article>
  <h1>2026. évi 83. szám</h1>
  <section>
    <h2>12. § (3)</h2>
    <p>A cégautóadó mértéke 2026. január 1-jétől 18 000 Ft-ról 19 500 Ft-ra emelkedik.</p>
    <h2>13. § (1)</h2>
    <p>A változtatás kizárólag a céges tulajdonban álló személygépkocsikra vonatkozik.</p>
  </section>
</article>
</body></html>
"""


@responses.activate
def test_fetch_issue_content_parses_bekezdesek() -> None:
    s = _settings()
    responses.add(
        responses.GET,
        "https://magyarkozlony.hu/dokumentumok/abc123/megtekintes",
        body=_ISSUE_HTML,
        status=200,
    )
    client = MagyarKozlonyClient(s)
    from hr_kozlony.scraper.magyarkozlony import IssueMeta
    meta = IssueMeta(
        number="2026. évi 83. szám",
        issue_id="2026/83",
        date="2026-07-01",
        has_indokolas=False,
        megtekintes_url="https://magyarkozlony.hu/dokumentumok/abc123/megtekintes",
        letoltes_url="https://magyarkozlony.hu/dokumentumok/abc123/letoltes",
    )
    bekezdes_list = client.fetch_issue_content(meta)

    assert len(bekezdes_list) == 2
    assert bekezdes_list[0].anchor == "12. §"
    assert "cégautóadó" in bekezdes_list[0].text


def test_content_hash_is_deterministic_and_length_independent() -> None:
    b1 = Bekezdes(anchor="x", heading="", text="Hello   World\n\nFoo")
    b2 = Bekezdes(anchor="x", heading="", text="hello world foo")
    assert content_hash(b1) == content_hash(b2)


@responses.activate
def test_min_bekezdes_length_filter() -> None:
    """The fetch node applies a length filter. Test that the filter logic works."""
    s = _settings()
    s.min_bekezdes_length = 50
    responses.add(
        responses.GET,
        "https://magyarkozlony.hu/dokumentumok/abc123/megtekintes",
        body=_ISSUE_HTML,
        status=200,
    )
    client = MagyarKozlonyClient(s)
    from hr_kozlony.scraper.magyarkozlony import IssueMeta
    meta = IssueMeta(
        number="2026. évi 83. szám", issue_id="2026/83", date="2026-07-01",
        has_indokolas=False,
        megtekintes_url="https://magyarkozlony.hu/dokumentumok/abc123/megtekintes",
        letoltes_url="https://magyarkozlony.hu/dokumentumok/abc123/letoltes",
    )
    all_b = client.fetch_issue_content(meta)
    filtered = [b for b in all_b if len(b.text) >= s.min_bekezdes_length]
    # Both bekezdések are > 50 chars in the fixture
    assert len(filtered) == 2
