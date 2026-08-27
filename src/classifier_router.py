"""Hybrid router: trained-classifier accuracy on known categories, without
losing the nearest-centroid approach's zero-retrain coverage of brand-new
categories.

Routing is deterministic, not confidence-based. A trained classifier's
prediction is always an argmax over the categories it was trained on, so it
can *never* output a category it has never seen — even when that's the
right answer, it silently misfiles into whichever known category looks
closest (this is exactly what the new-category test in
02_classifier_comparison.ipynb showed). So the signal for "this ticket is
probably a new category" has to come from the centroid classifier, not from
low confidence on the trained model — there isn't a confidence signal to
read here.

    route(ticket):
        centroid_pred = centroid_classifier.predict(ticket)
        if centroid_pred not in trained_classifier.classes_:
            return centroid_pred            # trained model has never seen this category
        else:
            return trained_classifier.predict(ticket)   # known category, more accurate

Scheduled retraining — periodically "graduating" a centroid-only category
into the trained model once it has enough examples — is intentionally not
built here. It stays a documented TODO: the natural home for that job is
the weekly Cloud Scheduler run introduced in Phase 4.
"""
from __future__ import annotations


class HybridRouter:
    """Wraps a trained classifier (TF-IDF or embeddings + Logistic
    Regression) and an EmbeddingCentroid, routing each ticket to whichever
    one can actually answer correctly."""

    name = "Hybrid router (TF-IDF+LogReg / centroid)"

    def __init__(self, trained_classifier, centroid_classifier):
        self.trained_classifier = trained_classifier
        self.centroid_classifier = centroid_classifier

    @property
    def known_classes(self) -> set[str]:
        return set(self.trained_classifier.clf.classes_)

    def fit(self, texts: list[str], labels: list[str]) -> "HybridRouter":
        # Both sub-classifiers are expected to already be fit/built by the
        # caller (the centroid classifier in particular is built from the
        # taxonomy, not from tickets) — this is a no-op for interface
        # parity with the other classifiers.
        return self

    def predict(self, texts: list[str]) -> list[str]:
        known = self.known_classes
        centroid_preds = self.centroid_classifier.predict(texts)
        trained_preds = self.trained_classifier.predict(texts)
        return [
            centroid_pred if centroid_pred not in known else trained_pred
            for centroid_pred, trained_pred in zip(centroid_preds, trained_preds)
        ]

    def supports_new_category(self) -> bool:
        return True
