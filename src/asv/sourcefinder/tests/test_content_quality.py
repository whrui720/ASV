"""Tier 0.3 — is this fetched text admissible as evidence?

In the reference run (``runs/hsv_cancer__20260706_192057``), 10 of 16
"successful" downloads were publisher landing pages: an abstract plus a
reference list. They cleared the 200-character floor comfortably and RAG then
searched a document that could not contain the evidence.

The unsafe direction here is classifying an abstract as full text — that
produces a confident verdict off a page that never had the answer. The safe
direction is the reverse: a false abstention costs recall, shows up in the
checkable-rate metric, and never becomes a false accusation. These tests pin
the unsafe direction at zero.
"""

import pytest

from asv.core.verdicts import ContentQuality
from asv.sourcefinder.content_quality import assess_content

pytestmark = pytest.mark.unit


FULL_TEXT = """
Herpes simplex virus vectors for cancer therapy

Abstract
We review oncolytic HSV vectors and their clinical development.

Introduction
Herpes simplex virus type 1 is a neurotropic double-stranded DNA virus with a
genome of approximately 152 kb. Interest in HSV-1 as an oncolytic agent dates
to the early 1990s, when the first attenuated mutants were described.
""" + ("Additional background prose about viral genetics and tropism. " * 120) + """

Materials and Methods
Vero cells were maintained in DMEM supplemented with 10% fetal calf serum.
Viral titres were determined by plaque assay in triplicate.
""" + ("Detailed methodological description of the assays performed. " * 120) + """

Results
Viral titres peaked at 24 hours post-infection, reaching 6.2 log10 PFU/ml.
""" + ("Further results prose describing the observed effects in detail. " * 120) + """

Discussion
These findings are consistent with earlier reports in murine models.
""" + ("Discussion of limitations and comparison to prior work. " * 120) + """

References
1. Smith AB, Jones CD. Oncolytic viruses. J Virol 2019; 93: 1120.
2. Brown EF. HSV latency. Cell 2020; 181: 55.
"""


NATURE_LANDING_PAGE = """
Oncolytic herpes simplex virus vectors in solid tumours

Abstract
Oncolytic virotherapy has emerged as a promising modality for the treatment of
solid tumours. Here we review the current clinical landscape, the engineering
strategies used to attenuate neurovirulence while preserving replication in
tumour cells, and the outstanding questions facing the field. We discuss
combination approaches with checkpoint blockade and the regulatory pathway
followed by the first approved agents.

Similar content being viewed by others

References
1. Martuza RL, Malick A, Markert JM. Experimental therapy of human glioma. Science 1991; 252: 854.
2. Mineta T, Rabkin SD, Yazaki T. Attenuated multi-mutated herpes simplex virus-1. Nat Med 1995; 1: 938.
3. Andtbacka RH, Kaufman HL, Collichio F. Talimogene laherparepvec improves survival. J Clin Oncol 2015; 33: 2780.
4. Liu BL, Robinson M, Han ZQ. ICP34.5 deleted herpes simplex virus. Gene Ther 2003; 10: 292.
5. Todo T, Martuza RL, Rabkin SD. Oncolytic herpes simplex virus vector. Proc Natl Acad Sci 2001; 98: 6396.
6. Hu JC, Coffin RS, Davis CJ. A phase I study of OncoVEX. Clin Cancer Res 2006; 12: 6737.
7. Kaufman HL, Kohlhapp FJ, Zloza A. Oncolytic viruses: a new class. Nat Rev Drug Discov 2015; 14: 642.
8. Chiocca EA, Rabkin SD. Oncolytic viruses and their application. Cancer Immunol Res 2014; 2: 295.
9. Peters C, Rabkin SD. Designing herpes viruses as oncolytics. Mol Ther Oncolytics 2015; 2: 15010.
10. Nguyen HM, Saha D. The current state of oncolytic HSV. Front Oncol 2021; 11: 617.

Author information

Rights and permissions

About this article
"""


SPRINGER_PAYWALL = """
Gene delivery using herpes simplex virus vectors

Abstract
This is a preview of subscription content, log in via an institution to check access.

Access this article
Log in via an institution
Subscribe and save
Buy this article
Price includes VAT (United Kingdom)
USD 39.95
Instant access to the full article PDF.
Rent this article via DeepDyve
"""


ABSTRACT_PDF = """
Gene delivery using herpes simplex virus vectors

Burton EA, Bai Q, Goins WF, Glorioso JC

Abstract
Herpes simplex virus type 1 (HSV-1) is a human neurotropic virus that has been
extensively engineered as a gene delivery vector. This review summarises vector
design, the biology underlying neuronal tropism, and progress toward clinical
application in chronic pain and neurodegenerative disease.

Keywords: gene therapy, HSV-1, vector, neuron
"""


ERROR_PAGE = "Error 403: Forbidden."


def test_full_text_article_is_judgeable():
    a = assess_content(FULL_TEXT, file_format="html", page_count=12)
    assert a.quality == ContentQuality.FULL_TEXT
    assert a.judgeable
    assert a.signals["imrad_count"] >= 3


def test_nature_landing_page_is_abstract_only():
    """The exact failure the reference run hit nine times."""
    a = assess_content(NATURE_LANDING_PAGE, file_format="html")
    assert a.quality == ContentQuality.ABSTRACT_ONLY
    assert not a.judgeable
    assert a.signals["imrad_count"] < 2


def test_springer_subscription_preview_is_a_paywall():
    a = assess_content(SPRINGER_PAYWALL, file_format="html")
    assert a.quality == ContentQuality.PAYWALL_INTERSTITIAL
    assert not a.judgeable
    assert a.signals["paywall_phrases"]


def test_short_abstract_pdf_is_abstract_only():
    a = assess_content(ABSTRACT_PDF, file_format="pdf", page_count=1)
    assert a.quality == ContentQuality.ABSTRACT_ONLY


def test_error_page_is_rejected():
    a = assess_content(ERROR_PAGE, file_format="html")
    assert a.quality == ContentQuality.REJECTED


def test_empty_text_is_rejected():
    assert assess_content("").quality == ContentQuality.REJECTED
    assert assess_content(None).quality == ContentQuality.REJECTED


def test_unknown_content_defaults_to_abstention():
    """The default must be the abstaining class. An unknown page that is really
    full text costs recall; an unknown landing page judged as full text costs a
    false accusation, which VALUE_PROPOSITION.md §10 rates critical."""
    ambiguous = "Some prose about a topic. " * 300  # long, no structure, no wall
    a = assess_content(ambiguous, file_format="html")
    assert a.quality == ContentQuality.ABSTRACT_ONLY
    assert not a.judgeable


def test_short_letter_with_strong_structure_still_counts_as_full_text():
    """Letters and brief communications are short but complete. Three IMRaD
    headings is enough on its own — otherwise the length floor would throw away
    an entire legitimate article class."""
    letter = (
        "Introduction\nBrief framing of the problem and why it matters to the "
        "field, with reference to the two prior reports.\n\n"
        "Methods\nCells were cultured and infected under standard conditions, "
        "and titres were determined by plaque assay in triplicate.\n\n"
        "Results\nTitres peaked at 24 hours, reaching 6.2 log10 PFU/ml, a "
        "significant increase over the parental strain.\n\n"
        "Discussion\nThe effect is consistent with the proposed mechanism, "
        "though the sample is small and confined to a single cell line.\n"
    )
    assert assess_content(letter, file_format="pdf", page_count=2).quality == \
        ContentQuality.FULL_TEXT


def test_signals_are_recorded_for_every_assessment():
    """A mis-tuned threshold has to be diagnosable without re-fetching, so the
    inputs are persisted on the manifest alongside the verdict."""
    a = assess_content(NATURE_LANDING_PAGE, file_format="html", url="https://www.nature.com/x")
    for key in (
        "usable_chars", "imrad_count", "imrad_sections", "reference_line_fraction",
        "paywall_phrases", "has_abstract_marker", "format", "url",
    ):
        assert key in a.signals
    assert a.reason


def test_numbered_section_headings_are_recognised():
    """Many journals number their sections; the heading test must survive it."""
    numbered = (
        "1. Introduction\nFraming prose that runs for a sentence or two so the "
        "section is not empty.\n\n"
        "2. Materials and Methods\nA description of the assays and the cell "
        "lines used throughout the study.\n\n"
        "3. Results\nThe measured outcome, reported with the relevant numbers "
        "and their confidence intervals.\n\n"
        "4. Discussion\nInterpretation, limitations, and comparison with the "
        "previously published literature.\n"
    )
    a = assess_content(numbered, file_format="pdf", page_count=6)
    assert a.signals["imrad_count"] >= 3
    assert a.quality == ContentQuality.FULL_TEXT


@pytest.mark.parametrize("sample,expected", [
    (FULL_TEXT, ContentQuality.FULL_TEXT),
    (NATURE_LANDING_PAGE, ContentQuality.ABSTRACT_ONLY),
    (SPRINGER_PAYWALL, ContentQuality.PAYWALL_INTERSTITIAL),
    (ABSTRACT_PDF, ContentQuality.ABSTRACT_ONLY),
    (ERROR_PAGE, ContentQuality.REJECTED),
])
def test_no_sample_is_misclassified_upward(sample, expected):
    """The unsafe direction, pinned: nothing that is not full text may be
    classified as full text."""
    quality = assess_content(sample).quality
    assert quality == expected
    if expected != ContentQuality.FULL_TEXT:
        assert quality != ContentQuality.FULL_TEXT
