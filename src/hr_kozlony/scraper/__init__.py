"""Scraper package — Magyar Közlöny issue discovery + content extraction."""
from .magyarkozlony import Bekezdes, IssueMeta, MagyarKozlonyClient, content_hash

__all__ = ["MagyarKozlonyClient", "IssueMeta", "Bekezdes", "content_hash"]
