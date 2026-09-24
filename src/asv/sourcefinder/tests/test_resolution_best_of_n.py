"""Tier 0.3 §4.4 — resolution keeps the *best* candidate, not the first.

Before Tier 0, ``download_with_resolution`` returned on the first candidate
that fetched. Adding a content gate on top of that would have been strictly
harmful: candidate 1 is typically a publisher landing page, which fetches fine,
gets refused as ``abstract_only``, and the full-text mirror at candidate 2 is
never tried — converting a fake pass into an abstention while leaving real
evidence on the table.

These tests pin the replacement behaviour, including the disk hygiene that
comes with it (per-candidate filenames, non-winners deleted).
"""

from pathlib import Path

import pytest

from asv.core.verdicts import ContentQuality
from asv.sourcefinder.text_downloader import TextDownloader

pytestmark = pytest.mark.unit


LANDING_PAGE = (
    "Oncolytic herpes simplex virus vectors\n\nAbstract\n"
    + ("A summary of the field and its open questions. " * 20)
    + "\n\nReferences\n"
    + "".join(f"{i}. Author A, Author B. A title here. J Virol 201{i % 10}; 9{i % 10}: 1{i}20.\n"
             for i in range(1, 40))
)

FULL_TEXT = (
    "Introduction\n" + ("Framing prose. " * 200)
    + "\n\nMaterials and Methods\n" + ("Method prose. " * 200)
    + "\n\nResults\n" + ("Result prose with numbers. " * 200)
    + "\n\nDiscussion\n" + ("Discussion prose. " * 200)
)

PAYWALL = (
    "Access this article\nThis is a preview of subscription content, log in via "
    "an institution to check access.\nBuy this article\nUSD 39.95\n"
    + ("Subscribe and save. " * 10)
)


class FakeFinder:
    """Stands in for AcademicPaperFinder."""

    def __init__(self, urls):
        self.urls = urls
        self.browser_searcher = None

    def find_urls(self, raw_citation_text, known_doi=None):
        return list(self.urls)


def _downloader(tmp_path, pages, urls):
    """A TextDownloader whose network layer serves ``pages`` (url -> text)."""
    dl = TextDownloader(output_dir=str(tmp_path))
    dl._paper_finder = FakeFinder(urls)
    fetched = []

    def fake_download(url, citation_id, *, filename_suffix=""):
        fetched.append(url)
        body = pages.get(url)
        if body is None:
            return {
                'downloaded': False, 'format': None, 'path': None,
                'text_content': None, 'content_quality': None,
                'content_signals': None, 'judgeable': False, 'error': '403 Forbidden',
            }
        return dl._process_bytes(
            body.encode("utf-8"), url, citation_id, "text/html",
            filename_suffix=filename_suffix,
        )

    dl.download = fake_download  # type: ignore[method-assign]
    dl.fetched = fetched         # type: ignore[attr-defined]
    return dl


def test_full_text_beats_an_earlier_abstract(tmp_path):
    """The exact scenario that makes 0.3 harmful without 0.3 §4.4."""
    urls = ["https://www.nature.com/landing", "https://europepmc.org/full"]
    dl = _downloader(tmp_path, {urls[0]: LANDING_PAGE, urls[1]: FULL_TEXT}, urls)

    result = dl.download_with_resolution(None, "42", "Some reference text")

    assert result['winning_url'] == urls[1]
    assert result['content_quality'] == ContentQuality.FULL_TEXT
    assert result['judgeable'] is True
    assert len(result['attempts']) == 2


def test_stops_as_soon_as_full_text_is_found(tmp_path):
    """Nothing beats full text, so the cascade must not keep fetching."""
    urls = ["https://europepmc.org/full", "https://www.nature.com/landing", "https://other/x"]
    dl = _downloader(tmp_path, {u: FULL_TEXT for u in urls}, urls)

    dl.download_with_resolution(None, "42", "ref")

    assert dl.fetched == [urls[0]], "should not fetch past the first full text"


def test_all_candidates_abstract_returns_best_but_not_judgeable(tmp_path):
    urls = ["https://a/paywall", "https://b/landing"]
    dl = _downloader(tmp_path, {urls[0]: PAYWALL, urls[1]: LANDING_PAGE}, urls)

    result = dl.download_with_resolution(None, "42", "ref")

    # abstract_only outranks paywall_interstitial, so the landing page wins —
    # but the batch is still not judgeable.
    assert result['downloaded'] is True
    assert result['judgeable'] is False
    assert result['content_quality'] == ContentQuality.ABSTRACT_ONLY
    assert result['winning_url'] == urls[1]


def test_only_the_winning_file_is_left_on_disk(tmp_path):
    urls = ["https://www.nature.com/landing", "https://europepmc.org/full"]
    dl = _downloader(tmp_path, {urls[0]: LANDING_PAGE, urls[1]: FULL_TEXT}, urls)

    result = dl.download_with_resolution(None, "42", "ref")

    files = sorted(p.name for p in Path(tmp_path).iterdir() if p.is_file())
    assert len(files) == 1, f"superseded candidates left behind: {files}"
    assert Path(result['path']).name == files[0]


def test_every_attempt_records_its_content_quality(tmp_path):
    """Turns the manifest into the calibration corpus for the classifier
    instead of a dead-end log."""
    urls = ["https://a/paywall", "https://b/landing", "https://c/full"]
    dl = _downloader(
        tmp_path, {urls[0]: PAYWALL, urls[1]: LANDING_PAGE, urls[2]: FULL_TEXT}, urls,
    )

    result = dl.download_with_resolution(None, "42", "ref")

    qualities = [a['content_quality'] for a in result['attempts']]
    assert qualities == [
        ContentQuality.PAYWALL_INTERSTITIAL,
        ContentQuality.ABSTRACT_ONLY,
        ContentQuality.FULL_TEXT,
    ]


def test_failed_fetches_do_not_stop_the_cascade(tmp_path):
    urls = ["https://dead/1", "https://dead/2", "https://europepmc.org/full"]
    dl = _downloader(tmp_path, {urls[2]: FULL_TEXT}, urls)

    result = dl.download_with_resolution(None, "42", "ref")

    assert result['winning_url'] == urls[2]
    assert [a['downloaded'] for a in result['attempts']] == [False, False, True]


def test_total_failure_reports_honestly(tmp_path):
    urls = ["https://dead/1", "https://dead/2"]
    dl = _downloader(tmp_path, {}, urls)

    result = dl.download_with_resolution(None, "42", "ref")

    assert result['downloaded'] is False
    assert result['judgeable'] is False
    assert result['winning_url'] is None
    assert result['error']
    assert len(result['attempts']) == 2


def test_candidate_cap_is_respected(tmp_path):
    from asv.sourcefinder.config import MAX_CANDIDATES_PER_BATCH

    urls = [f"https://dead/{i}" for i in range(MAX_CANDIDATES_PER_BATCH + 5)]
    dl = _downloader(tmp_path, {}, urls)

    dl.download_with_resolution(None, "42", "ref")

    assert len(dl.fetched) == MAX_CANDIDATES_PER_BATCH


def test_direct_url_is_tried_first_and_can_be_beaten(tmp_path):
    from asv.core.models import CitationDetails

    direct = "https://publisher/landing"
    oa = "https://europepmc.org/full"
    dl = _downloader(tmp_path, {direct: LANDING_PAGE, oa: FULL_TEXT}, [oa])

    result = dl.download_with_resolution(
        CitationDetails(url=direct, raw_text="ref"), "42", "ref",
    )

    assert dl.fetched[0] == direct
    assert result['winning_url'] == oa
    assert result['attempts'][0]['source'] == 'direct'
    assert result['attempts'][1]['source'] == 'open_access'
