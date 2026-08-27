"""The regression test that matters most in this repo.

Reconstructs the hybrid router exactly as notebooks/02_classifier_comparison.ipynb
does: trains TfidfBaseline on the 900 tickets NOT in the committed held-out
set, builds EmbeddingCentroid from the current taxonomy, and confirms:

  (a) the router reproduces TF-IDF+LogisticRegression's predictions EXACTLY
      on the held-out set (element-for-element, not just a matching
      aggregate score) -- known categories should never silently degrade.
  (b) the router still scores 100% on the new-category set, once the
      centroid has been told about the new category the same way Gemini's
      evaluation needed to be (a mistake made and fixed earlier in this
      project -- forgetting this call silently produces 0%, not an error).

Needs network access on first run only, to download the all-MiniLM-L6-v2
sentence-transformers model (~90MB) used by EmbeddingCentroid.
"""
from pathlib import Path

import pandas as pd
import pytest

from classifier_router import HybridRouter
from classifiers import EmbeddingCentroid, EmbeddingEncoder, TfidfBaseline
from evaluation import new_category_accuracy, score
from taxonomy import Category, load_taxonomy
from text_features import final_text

REPO_ROOT = Path(__file__).parent.parent
OUTPUTS = REPO_ROOT / "outputs"

# Pinned to the real numbers this test produced when it was written --
# reconstructed from outputs/tickets.csv + outputs/eval_holdout_set.csv.
# If these regress, something in TfidfBaseline, EmbeddingCentroid, or
# HybridRouter's routing rule has changed behaviour.
EXPECTED_FINAL_ACCURACY = 0.9266666666666666
EXPECTED_FINAL_MACRO_F1 = 0.9185209440015691
EXPECTED_TRIAGE_ACCURACY = 0.9866666666666667
EXPECTED_TRIAGE_MACRO_F1 = 0.9896853312016278

NEW_CATEGORY = Category(
    category_id="SHIP-EXP", name="Express shipping request", group="Order & shipping",
    description="Customer asks to upgrade their order to express/expedited shipping.",
    example_phrases=["can I get this shipped faster?", "is express shipping available for my order?"],
    status="active", created_at="2025-07-01", deprecated_at=None, replaced_by=None, taxonomy_version=2,
)


@pytest.fixture(scope="module")
def fitted_router():
    tickets = pd.read_csv(OUTPUTS / "tickets.csv")
    conversations = pd.read_csv(OUTPUTS / "conversations.csv")
    holdout = pd.read_csv(OUTPUTS / "eval_holdout_set.csv")

    train = tickets[~tickets["id"].isin(holdout["id"])]
    train_text = final_text(train, conversations)

    taxonomy = load_taxonomy()
    tfidf = TfidfBaseline("logreg").fit(list(train_text), list(train["true_category_id_final"]))
    encoder = EmbeddingEncoder()
    centroid = EmbeddingCentroid(encoder, taxonomy)
    router = HybridRouter(tfidf, centroid)

    return {"tfidf": tfidf, "encoder": encoder, "taxonomy": taxonomy, "router": router, "holdout": holdout}


def test_router_matches_tfidf_exactly_on_final_stage(fitted_router):
    holdout = fitted_router["holdout"]
    tfidf_preds = fitted_router["tfidf"].predict(list(holdout["final_text"]))
    router_preds = fitted_router["router"].predict(list(holdout["final_text"]))

    assert router_preds == tfidf_preds, "router's final-stage predictions diverged from TF-IDF on a known category"

    result = score(list(holdout["true_category_id_final"]), router_preds)
    assert result["accuracy"] == pytest.approx(EXPECTED_FINAL_ACCURACY)
    assert result["macro_f1"] == pytest.approx(EXPECTED_FINAL_MACRO_F1)


def test_router_matches_tfidf_exactly_on_triage_stage(fitted_router):
    holdout = fitted_router["holdout"]
    tfidf_preds = fitted_router["tfidf"].predict(list(holdout["triage_text"]))
    router_preds = fitted_router["router"].predict(list(holdout["triage_text"]))

    assert router_preds == tfidf_preds, "router's triage-stage predictions diverged from TF-IDF on a known category"

    result = score(list(holdout["true_category_id_triage"]), router_preds)
    assert result["accuracy"] == pytest.approx(EXPECTED_TRIAGE_ACCURACY)
    assert result["macro_f1"] == pytest.approx(EXPECTED_TRIAGE_MACRO_F1)


def test_router_scores_100_percent_on_new_category(fitted_router):
    nc_df = pd.read_csv(OUTPUTS / "eval_new_category_set.csv")

    # A fresh centroid, not the shared fixture's: add_category mutates
    # state, and this test shouldn't leak that into the other tests
    # regardless of execution order.
    nc_centroid = EmbeddingCentroid(fitted_router["encoder"], fitted_router["taxonomy"])
    # This call is the point of the test: without it, the centroid (and
    # therefore the router) has no way to know the new category exists,
    # and silently scores 0% instead of raising -- exactly the bug this
    # project's own Gemini evaluation hit before being caught and fixed.
    nc_centroid.add_category(NEW_CATEGORY)
    nc_router = HybridRouter(fitted_router["tfidf"], nc_centroid)

    preds = nc_router.predict(list(nc_df["final_text"]))
    result = new_category_accuracy(nc_df, preds, "SHIP-EXP")

    assert result["n_new_category_tickets"] == 52
    assert result["accuracy"] == pytest.approx(1.0)
