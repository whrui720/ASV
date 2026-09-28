"""Union-then-rank resolution, JATS extraction, and EZproxy — F1, §6, §7.

The measured failure these pin: 32 of 51 citation batches had exactly one
candidate URL, because the resolver's cascade guarded every step with
``if not candidates``. One publisher 403 then killed the batch even when a PMC
mirror existed. The ranking is the fix, so the ranking is what is tested —
kind order, dedupe, and the fact that a repository mirror cannot be shadowed by
whichever resolver happened to answer first.
"""

import pytest

from asv.core.verdicts import ContentQuality
from asv.sourcefinder.content_quality import assess_content
from asv.sourcefinder.fulltext_apis import (
    KIND_RANK,
    SourceCandidate,
    classify,
    clean_doi,
    extract_doi,
    normalise_url,
    rank_and_dedupe,
)
from asv.sourcefinder.reference_text import normalise_reference
from asv.sourcefinder.text_downloader import TextDownloader, ezproxy_url

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------

def test_full_text_xml_outranks_everything_else():
    pool = [
        SourceCandidate("https://www.nature.com/articles/x", "unpaywall", "publisher_landing"),
        SourceCandidate("https://publisher.example/x.pdf", "crossref", "publisher_pdf"),
        SourceCandidate("https://www.ebi.ac.uk/europepmc/webservices/rest/PMC1/fullTextXML",
                        "europepmc_fulltext", "fulltext_xml"),
        SourceCandidate("https://repo.example/x.pdf", "unpaywall", "repository_pdf"),
    ]

    ranked = rank_and_dedupe(pool)

    assert [c.kind for c in ranked] == [
        "fulltext_xml", "repository_pdf", "publisher_pdf", "publisher_landing",
    ]


def test_answer_order_does_not_beat_kind_order():
    """The whole point of F1: Unpaywall answering first must not shadow the
    Europe PMC mirror that answered second."""
    pool = [
        SourceCandidate("https://journals.asm.org/doi/10.1/2", "unpaywall", "publisher_landing"),
        SourceCandidate("https://www.ebi.ac.uk/europepmc/webservices/rest/PMC9/fullTextXML",
                        "europepmc_fulltext", "fulltext_xml"),
    ]

    assert rank_and_dedupe(pool)[0].source == "europepmc_fulltext"


def test_duplicate_urls_keep_their_best_kind():
    url = "https://repo.example/paper.pdf"
    pool = [
        SourceCandidate(url, "crossref", "publisher_landing"),
        SourceCandidate(url + "/", "unpaywall", "repository_pdf"),
    ]

    ranked = rank_and_dedupe(pool)

    assert len(ranked) == 1
    assert ranked[0].kind == "repository_pdf"


def test_non_http_candidates_are_dropped():
    pool = [
        SourceCandidate("ftp://old.example/x.pdf", "crossref", "repository_pdf"),
        SourceCandidate("", "crossref", "repository_pdf"),
        SourceCandidate("https://ok.example/x", "crossref", "publisher_landing"),
    ]

    assert [c.url for c in rank_and_dedupe(pool)] == ["https://ok.example/x"]


def test_limit_keeps_the_best(tmp_path=None):
    pool = [SourceCandidate(f"https://x.example/{i}", "s", "publisher_landing") for i in range(10)]
    pool.append(SourceCandidate("https://repo.example/a.pdf", "s", "repository_pdf"))

    ranked = rank_and_dedupe(pool, limit=3)

    assert len(ranked) == 3
    assert ranked[0].kind == "repository_pdf"


def test_every_kind_has_a_rank():
    for kind in ("fulltext_xml", "repository_pdf", "repository_landing",
                 "publisher_pdf", "publisher_landing", "search_guess"):
        assert kind in KIND_RANK


def test_classify_uses_host_type_when_the_api_supplies_one():
    # An institutional repository on an unfamiliar host is still a repository
    # when Unpaywall or OpenAlex says so.
    assert classify("https://eprints.unknown.ac.uk/1/a.pdf", is_pdf=True,
                    host_type="repository") == "repository_pdf"
    assert classify("https://eprints.unknown.ac.uk/1/a.pdf", is_pdf=True) == "publisher_pdf"


def test_known_repository_hosts_are_recognised_without_a_hint():
    assert classify("https://arxiv.org/pdf/2101.1", is_pdf=True) == "repository_pdf"
    assert classify("https://www.ebi.ac.uk/x", is_pdf=False) == "repository_landing"


def test_url_normalisation_is_case_and_slash_insensitive():
    assert normalise_url("HTTPS://Example.ORG/a/") == normalise_url("https://example.org/a")
    assert normalise_url("https://x.org/a#frag") == normalise_url("https://x.org/a")


# ---------------------------------------------------------------------------
# DOI handling
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("https://doi.org/10.1038/sj.gt.3301885", "10.1038/sj.gt.3301885"),
    ("http://dx.doi.org/10.1/2", "10.1/2"),
    ("10.1089/104454902762053864.", "10.1089/104454902762053864"),
    (None, None),
    ("", None),
])
def test_clean_doi(raw, expected):
    assert clean_doi(raw) == expected


def test_extract_doi_stops_at_punctuation():
    assert extract_doi("see doi:10.1038/sj.gt.3301885, and also") == "10.1038/sj.gt.3301885"
    assert extract_doi("no identifier here") is None


# ---------------------------------------------------------------------------
# Reference repair (F8)
# ---------------------------------------------------------------------------

def test_reference_repair_splits_run_together_fields():
    out = normalise_reference(
        "Burton EA, Fink DJ, Glorioso JC.Gene delivery using herpes simplex "
        "virus vectors.DNA Cell Biol2002;21: 915�936."
    )

    assert "JC. Gene delivery" in out
    assert "vectors. DNA Cell Biol 2002" in out
    assert "915-936" in out
    assert "�" not in out


def test_reference_repair_leaves_mccase_names_alone():
    out = normalise_reference("Harrison's Principles of Internal Medicine.McGraw-Hill, 1980")
    assert "McGraw-Hill" in out
    assert "Mc Graw" not in out


def test_reference_repair_does_not_touch_dois():
    out = normalise_reference("A paper. Gene Therapy2002;9: 584. doi:10.1038/sj.gt.3301885")
    assert "10.1038/sj.gt.3301885" in out


def test_reference_repair_is_idempotent_and_safe_on_clean_input():
    clean = "Smith J, Jones A. A clean reference. J Virol 1999; 73: 2181-2189."
    assert normalise_reference(clean) == clean


def test_mojibake_is_undone():
    assert "Harrison's" in normalise_reference("Harrisonâ€™s Principles")


# ---------------------------------------------------------------------------
# JATS / XML extraction (§6 Tier 1 — the payoff of adding Europe PMC)
# ---------------------------------------------------------------------------

JATS = """<?xml version="1.0"?>
<article>
  <front><journal-meta><journal-title>J Test</journal-title></journal-meta>
    <article-meta><article-title>Oncolytic HSV in glioma</article-title>
      <abstract><p>We tested the thing.</p></abstract>
    </article-meta>
  </front>
  <body>
    <sec><title>Introduction</title><p>%s</p></sec>
    <sec><title>Materials and Methods</title><p>%s</p></sec>
    <sec><title>Results</title><p>Tumour volume fell by 62%% (p&lt;0.01).</p></sec>
    <sec><title>Discussion</title><p>%s</p></sec>
  </body>
  <back><ref-list><ref><p>Should not appear: SENTINEL_REFERENCE</p></ref></ref-list></back>
</article>
""" % ("Framing prose. " * 200, "Method prose. " * 200, "Discussion prose. " * 200)


def _downloader(tmp_path):
    return TextDownloader(output_dir=str(tmp_path))


def test_xml_is_detected_from_magic_bytes(tmp_path):
    dl = _downloader(tmp_path)
    assert dl._detect_format("https://x/y", "", b"<?xml version='1.0'?><article>") == "xml"
    assert dl._detect_format("https://x/y", "application/xml", b"") == "xml"
    # The Europe PMC route has no extension, so the URL hint carries it.
    assert dl._detect_format(
        "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC1/fullTextXML", "", b""
    ) == "xml"


def test_xml_is_not_mistaken_for_html(tmp_path):
    """JATS reaching the HTML extractor would keep the metadata soup and lose
    the section structure the content gate keys off."""
    dl = _downloader(tmp_path)
    assert dl._detect_format("https://x/y.pdf", "text/html", b"%PDF-1.4") == "pdf"
    assert dl._detect_format("https://x/y", "", b"<!doctype html><html>") == "html"


def test_jats_extraction_keeps_headings_and_drops_the_bibliography(tmp_path):
    text = _downloader(tmp_path)._extract_xml_text(JATS)

    assert "Oncolytic HSV in glioma" in text
    assert "Tumour volume fell by 62%" in text
    assert "SENTINEL_REFERENCE" not in text, "ref-list must not pollute retrieval"
    for heading in ("Introduction", "Materials and Methods", "Results", "Discussion"):
        assert f"\n{heading}" in text, f"{heading} must survive as its own line"


def test_extracted_jats_passes_the_content_gate_as_full_text(tmp_path):
    """End to end: the whole reason Europe PMC is the top-ranked source."""
    text = _downloader(tmp_path)._extract_xml_text(JATS)

    assessment = assess_content(text, file_format="xml", url="https://www.ebi.ac.uk/x")

    assert assessment.quality == ContentQuality.FULL_TEXT
    assert assessment.judgeable is True


def test_non_jats_xml_falls_back_to_all_text(tmp_path):
    text = _downloader(tmp_path)._extract_xml_text(
        '<?xml version="1.0"?><error><message>Not found</message></error>'
    )
    assert "Not found" in text


# ---------------------------------------------------------------------------
# EZproxy (§7)
# ---------------------------------------------------------------------------

def test_ezproxy_rewrites_a_publisher_host():
    assert ezproxy_url(
        "https://www.sciencedirect.com/science/article/pii/X", "proxy.lib.umich.edu"
    ) == "https://www-sciencedirect-com.proxy.lib.umich.edu/science/article/pii/X"


def test_ezproxy_preserves_the_path_and_query():
    out = ezproxy_url("https://journals.asm.org/doi/10.1128/jvi.1?x=2", "p.edu")
    assert out.endswith("/doi/10.1128/jvi.1?x=2")


def test_ezproxy_is_off_without_a_configured_host():
    assert ezproxy_url("https://cell.com/x", "") is None


def test_ezproxy_skips_what_it_cannot_help():
    """Proxying an open-access aggregator spends the run's proxy budget on a
    host that was never behind the library's subscription."""
    assert ezproxy_url("https://www.ebi.ac.uk/europepmc/x", "p.edu") is None
    assert ezproxy_url("https://arxiv.org/pdf/1", "p.edu") is None
    assert ezproxy_url("https://doi.org/10.1/2", "p.edu") is None


def test_ezproxy_does_not_double_proxy():
    already = "https://www-cell-com.p.edu/x"
    assert ezproxy_url(already, "p.edu") is None


# ---------------------------------------------------------------------------
# HTML extraction — the content root is chosen before the cleanup runs
# ---------------------------------------------------------------------------

# Nature's real page shape. The wrapper's layout class contains "sidebar", and
# the old extractor's junk-class filter matched it *before* choosing a content
# root — decomposing an ancestor of the article and turning 284KB of
# successfully fetched page into zero characters, reported as a failed download.
NATURE_SHAPED = """
<html><body class="article-page">
  <div id="content" class="c-article-main u-container eds-l-with-sidebar">
    <main class="c-article-main-column js-main-column">
      <article>
        <div class="c-article-body">
          <h2>Abstract</h2><p>%s</p>
          <h2>Results</h2><p>The tumour shrank by 62%%.</p>
        </div>
        <div class="c-article-related-content">Similar content being viewed by others</div>
        <div class="js-cookie-banner">We use cookies</div>
      </article>
    </main>
  </div>
</body></html>
""" % ("Abstract prose. " * 100)


def test_a_layout_class_on_an_ancestor_cannot_delete_the_article(tmp_path):
    text = _downloader(tmp_path)._extract_html_text(NATURE_SHAPED)

    assert "The tumour shrank by 62%" in text
    assert len(text) > 1000, "content root was deleted by an ancestor's layout class"


def test_chrome_inside_the_content_root_is_still_stripped(tmp_path):
    text = _downloader(tmp_path)._extract_html_text(NATURE_SHAPED)

    assert "Similar content being viewed by others" not in text
    assert "We use cookies" not in text


def test_cleanup_never_returns_less_than_it_started_with(tmp_path):
    """Backstop for selectors we have not seen: a noisy document is
    recoverable, an empty one is reported as a failed fetch."""
    hostile = (
        '<html><body><main class="nav-sidebar-promo-banner">'
        "<p>" + ("Real article prose. " * 200) + "</p>"
        "</main></body></html>"
    )

    text = _downloader(tmp_path)._extract_html_text(hostile)

    assert "Real article prose." in text


def test_europepmc_website_urls_are_rerouted_to_the_rest_mirror():
    """europepmc.org is behind a Cloudflare challenge that 403s every scripted
    request; www.ebi.ac.uk serves the same article as JATS. A resolver handing
    us the website URL has the right article and the wrong door."""
    pool = [SourceCandidate(
        "https://europepmc.org/articles/PMC33479?pdf=render", "openalex", "repository_pdf",
    )]

    ranked = rank_and_dedupe(pool)

    assert len(ranked) == 1
    assert ranked[0].url == (
        "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC33479/fullTextXML"
    )
    assert ranked[0].kind == "fulltext_xml"


def test_unroutable_europepmc_urls_are_dropped_not_kept():
    pool = [
        SourceCandidate("https://europepmc.org/search?query=x", "openalex", "repository_landing"),
        SourceCandidate("https://ok.example/a.pdf", "crossref", "repository_pdf"),
    ]

    assert [c.url for c in rank_and_dedupe(pool)] == ["https://ok.example/a.pdf"]


# ---------------------------------------------------------------------------
# Title verification on search hits
# ---------------------------------------------------------------------------

def test_title_match_accepts_a_lost_subtitle():
    from asv.sourcefinder.fulltext_apis import title_matches
    assert title_matches(
        "Anatomy of herpes simplex virus DNA",
        "Anatomy of herpes simplex virus DNA. XII. Accumulation of head-to-tail concatemers",
    )


def test_title_match_rejects_an_unrelated_top_hit():
    """A title search always returns its best row. Accepting it unchecked is how
    a 1982 Cell reference acquires the DOI of an unrelated review — and from
    there the wrong DOI reaches Unpaywall, Crossref and the TDM endpoints, and a
    claim is judged against the wrong paper behind a resolvable source URL."""
    from asv.sourcefinder.fulltext_apis import title_matches
    assert not title_matches(
        "Structure and role of the herpes simplex virus DNA termini",
        "Machine learning approaches to protein folding prediction",
    )


def test_title_match_needs_both_sides():
    from asv.sourcefinder.fulltext_apis import title_matches
    assert not title_matches(None, "Something")
    assert not title_matches("Something", None)
    assert not title_matches("", "")
