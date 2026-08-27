"""Data-integrity checks on the taxonomy — cheap, deterministic, no network."""
from taxonomy import Category, Taxonomy, load_taxonomy

EXPECTED_CATEGORY_COUNT = 26


def test_active_returns_only_active_status():
    taxonomy = load_taxonomy()
    assert len(taxonomy.active()) > 0
    assert all(c.status == "active" for c in taxonomy.active())


def test_active_excludes_deprecated():
    # Constructed fixture, not the real taxonomy.yaml: as of this writing every
    # seed category is active, so this invariant needs a synthetic deprecated
    # entry to actually exercise the filter rather than trivially passing on
    # an empty deprecated set.
    categories = [
        Category(
            category_id="ORD-999", name="Old category", group="Order & shipping",
            description="d", example_phrases=[], status="deprecated",
            created_at="2025-01-01", deprecated_at="2025-06-01",
            replaced_by="ORD-001", taxonomy_version=1,
        ),
        Category(
            category_id="ORD-001", name="Order status / tracking", group="Order & shipping",
            description="d", example_phrases=[], status="active",
            created_at="2025-01-01", deprecated_at=None, replaced_by=None, taxonomy_version=1,
        ),
    ]
    taxonomy = Taxonomy(taxonomy_version=1, categories=categories)
    active_ids = [c.category_id for c in taxonomy.active()]
    assert "ORD-999" not in active_ids
    assert "ORD-001" in active_ids


def test_ids_has_no_duplicates_and_expected_count():
    taxonomy = load_taxonomy()
    ids = taxonomy.ids()
    assert len(ids) == EXPECTED_CATEGORY_COUNT
    assert len(ids) == len(set(ids)), "duplicate category_id found in taxonomy.yaml"


def test_deprecated_categories_replaced_by_a_real_active_category():
    """Guards against a dangling replaced_by reference. Currently a no-op
    against the real taxonomy.yaml (no category has been deprecated yet) —
    this becomes a real check the moment one is. See
    test_active_excludes_deprecated above for a fixture that exercises this
    invariant directly against a constructed case."""
    taxonomy = load_taxonomy()
    active_ids = set(taxonomy.active_ids())
    deprecated = [c for c in taxonomy.categories if c.status == "deprecated"]
    for cat in deprecated:
        assert cat.replaced_by is not None, f"{cat.category_id} is deprecated but has no replaced_by"
        assert cat.replaced_by in active_ids, (
            f"{cat.category_id}.replaced_by={cat.replaced_by!r} does not point to a currently-active category"
        )
