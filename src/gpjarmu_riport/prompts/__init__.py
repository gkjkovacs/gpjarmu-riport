"""Prompt files (Markdown) loaded at runtime."""
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent

RELEVANCE_CLASSIFIER_SYSTEM = (PROMPTS_DIR / "relevance-classifier.system.md").read_text(encoding="utf-8")
REPORT_WRITER_SYSTEM = (PROMPTS_DIR / "report-writer.system.md").read_text(encoding="utf-8")
TOPIC_TAXONOMY = (PROMPTS_DIR / "topic-taxonomy.md").read_text(encoding="utf-8")

__all__ = [
    "RELEVANCE_CLASSIFIER_SYSTEM",
    "REPORT_WRITER_SYSTEM",
    "TOPIC_TAXONOMY",
    "PROMPTS_DIR",
]
