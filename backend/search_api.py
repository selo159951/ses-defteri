"""Bridge methods for search by meaning. `Api` (bridge.py) inherits from SearchApi."""
from __future__ import annotations

from . import semantic


class SearchApi:
    def semantic_search(self, q: str, limit: int = 30) -> dict:
        """Passages that match the meaning of q (plus exact keyword hits first) across all recordings."""
        return semantic.search(q or "", limit=max(1, min(int(limit or 30), 100)))

    def get_search_info(self) -> dict:
        """Search model state (downloaded?, download progress) and how many recordings are indexed."""
        return semantic.status()

    def download_search_model(self) -> dict:
        return semantic.start_download()
