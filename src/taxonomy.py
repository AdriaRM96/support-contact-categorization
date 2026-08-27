"""Load and query the support-contact category taxonomy.

The taxonomy is kept as data (YAML), not code, so categories can be added
or deprecated without touching classification logic.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

TAXONOMY_PATH = Path(__file__).parent / "taxonomy.yaml"


@dataclass(frozen=True)
class Category:
    category_id: str
    name: str
    group: str
    description: str
    example_phrases: list[str]
    status: str
    created_at: str
    deprecated_at: str | None
    replaced_by: str | None
    taxonomy_version: int


class Taxonomy:
    """Wraps the loaded taxonomy version and its categories."""

    def __init__(self, taxonomy_version: int, categories: list[Category]):
        self.taxonomy_version = taxonomy_version
        self.categories = categories
        self._by_id = {c.category_id: c for c in categories}

    def get(self, category_id: str) -> Category:
        return self._by_id[category_id]

    def active(self) -> list[Category]:
        return [c for c in self.categories if c.status == "active"]

    def ids(self) -> list[str]:
        return [c.category_id for c in self.categories]

    def active_ids(self) -> list[str]:
        return [c.category_id for c in self.active()]


def load_taxonomy(path: Path | str = TAXONOMY_PATH) -> Taxonomy:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    categories = [Category(**entry) for entry in raw["categories"]]
    return Taxonomy(taxonomy_version=raw["taxonomy_version"], categories=categories)


if __name__ == "__main__":
    tax = load_taxonomy()
    print(f"Loaded taxonomy v{tax.taxonomy_version} with {len(tax.categories)} categories")
    for group in sorted({c.group for c in tax.categories}):
        ids = [c.category_id for c in tax.categories if c.group == group]
        print(f"  {group}: {len(ids)} categories -> {ids}")
