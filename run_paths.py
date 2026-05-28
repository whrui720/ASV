"""RunPaths — per-PDF run folder management for ASV.

Every artifact produced during a PDF validation run lives under a single
timestamped folder at ``runs/{pdf_stem}__{YYYYMMDD_HHMMSS}/``. Components that
write to disk accept a ``RunPaths`` instance and use its named attributes to
locate their working subdirectory.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Union

RUNS_ROOT_DIR = "./runs"


@dataclass(frozen=True)
class RunPaths:
    """Container of every subdirectory used by one PDF processing run."""

    root: Path
    pdf_stem: str
    timestamp: str
    citations: Path
    sourcefinder: Path
    generated_scripts: Path
    datasets: Path
    text_sources: Path
    validation_results: Path
    final_output: Path
    logs: Path

    @classmethod
    def for_pdf(
        cls,
        pdf_path: Union[str, Path],
        runs_root: Optional[Union[str, Path]] = None,
    ) -> "RunPaths":
        """Create and materialize a fresh run folder for ``pdf_path``."""
        pdf_stem = Path(pdf_path).stem
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        runs_root_path = Path(runs_root) if runs_root is not None else Path(RUNS_ROOT_DIR)
        root = runs_root_path / f"{pdf_stem}__{timestamp}"
        instance = cls._build(root, pdf_stem, timestamp)
        instance._ensure()
        return instance

    @classmethod
    def from_existing(cls, run_dir: Union[str, Path]) -> "RunPaths":
        """Reattach to an already-created run folder by parsing its name."""
        root = Path(run_dir)
        if "__" not in root.name:
            raise ValueError(
                f"Run directory name '{root.name}' does not match expected "
                "'{pdf_stem}__{YYYYMMDD_HHMMSS}' format"
            )
        pdf_stem, timestamp = root.name.split("__", 1)
        instance = cls._build(root, pdf_stem, timestamp)
        instance._ensure()
        return instance

    @classmethod
    def _build(cls, root: Path, pdf_stem: str, timestamp: str) -> "RunPaths":
        return cls(
            root=root,
            pdf_stem=pdf_stem,
            timestamp=timestamp,
            citations=root / "citations",
            sourcefinder=root / "sourcefinder",
            generated_scripts=root / "generated_scripts",
            datasets=root / "datasets",
            text_sources=root / "text_sources",
            validation_results=root / "validation_results",
            final_output=root / "final_output",
            logs=root / "logs",
        )

    def _ensure(self) -> None:
        for p in (
            self.root,
            self.citations,
            self.sourcefinder,
            self.generated_scripts,
            self.datasets,
            self.text_sources,
            self.validation_results,
            self.final_output,
            self.logs,
        ):
            p.mkdir(parents=True, exist_ok=True)

    def claims_json(self) -> Path:
        return self.citations / f"{self.pdf_stem}_claims.json"

    def found_datasets_json(self) -> Path:
        return self.sourcefinder / "found_datasets.json"

    def found_text_sources_json(self) -> Path:
        return self.sourcefinder / "found_text_sources.json"

    def run_summary_json(self) -> Path:
        return self.final_output / "run_summary.json"

    def orchestration_log(self) -> Path:
        return self.logs / "orchestration.log"
