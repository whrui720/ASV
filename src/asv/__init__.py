"""ASV — Automated Source Validation.

Top-level package. Subpackages:
- ``asv.core``          — shared data models, run-folder paths, LLM config, interaction seam
- ``asv.extraction``    — Stage 1: claim extraction (formerly ``hybrid_citation_scraper``)
- ``asv.sourcefinder``  — Stage 3 utilities: dataset/text source finding + downloading
- ``asv.validator``     — verification backends (truth table, LLM, script)
- ``asv.orchestrator``  — Stage 2: routes claims through the four processing groups
"""
