"""Builds the classified ticket export the dashboard reads.

Runs the recommended HybridRouter (TF-IDF+LogReg for known categories,
embedding-centroid fallback for anything it's never seen) across the whole
ticket set, producing a triage-time prediction for every ticket and a
final-time prediction for tickets that have actually closed — mirroring how
the two-stage pipeline runs in production.

This is a demo export, not a held-out evaluation: the router here is
trained on the full labeled dataset (there's no other source of ground
truth in this simulation). The accuracy numbers in
notebooks/02_classifier_comparison.ipynb, computed on a held-out split,
remain the authoritative metrics.
"""
from __future__ import annotations

import pandas as pd

from classifier_router import HybridRouter
from classifiers import EmbeddingCentroid, EmbeddingEncoder, TfidfBaseline
from taxonomy import Taxonomy
from text_features import final_text, triage_text

CLOSED_STATUSES = {"solved", "closed"}


def build_classified_export(
    tickets_df: pd.DataFrame,
    conversations_df: pd.DataFrame,
    taxonomy: Taxonomy,
    encoder: EmbeddingEncoder | None = None,
) -> pd.DataFrame:
    encoder = encoder or EmbeddingEncoder()

    X_triage = triage_text(tickets_df)
    X_final = final_text(tickets_df, conversations_df)
    y_final = tickets_df["true_category_id_final"]

    trained = TfidfBaseline("logreg").fit(list(X_final), list(y_final))
    centroid = EmbeddingCentroid(encoder, taxonomy)
    router = HybridRouter(trained, centroid)

    predicted_triage = router.predict(list(X_triage))

    is_closed = tickets_df["status"].isin(CLOSED_STATUSES)
    predicted_final = pd.Series([None] * len(tickets_df), index=tickets_df.index, dtype=object)
    if is_closed.any():
        predicted_final.loc[is_closed] = router.predict(list(X_final[is_closed]))

    group_by_id = {c.category_id: c.group for c in taxonomy.categories}

    out = tickets_df[
        ["id", "subject", "status", "priority", "type", "via_channel", "group_id", "created_at", "updated_at"]
    ].copy()
    out["predicted_category_triage"] = predicted_triage
    out["predicted_category_final"] = predicted_final.values
    out["predicted_group_triage"] = out["predicted_category_triage"].map(group_by_id)
    out["predicted_group_final"] = out["predicted_category_final"].map(group_by_id)
    out["category_disagreement"] = (
        out["predicted_category_final"].notna()
        & (out["predicted_category_triage"] != out["predicted_category_final"])
    )
    out["taxonomy_version"] = taxonomy.taxonomy_version

    return out


if __name__ == "__main__":
    from data_generation import generate_dataset
    from taxonomy import load_taxonomy

    tax = load_taxonomy()
    tickets_df, conversations_df = generate_dataset(taxonomy=tax)
    classified = build_classified_export(tickets_df, conversations_df, tax)
    classified.to_csv("../outputs/tickets_classified.csv", index=False)
    closed = classified[classified["predicted_category_final"].notna()]
    print(f"Wrote {len(classified)} classified tickets")
    print(f"Disagreement rate (closed tickets, n={len(closed)}): {closed['category_disagreement'].mean():.1%}")
