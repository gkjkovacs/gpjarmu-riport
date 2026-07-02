"""
Céges Gépjármű Magyar Közlöny Havi Riport.

A LangGraph pipeline that scrapes Magyar Közlöny issues, semantically classifies
paragraphs for relevance to corporate vehicle regulation, deduplicates against
a persistent state DB, and emits a single .txt report per run.
"""

__version__ = "0.1.0"
__all__ = ["__version__"]
