"""Three approaches to classifying a ticket's text into a taxonomy category.

1. TfidfBaseline          — TF-IDF + Logistic Regression, the usual sklearn stack.
2. EmbeddingCentroid      — sentence-transformer embeddings, no training: a
                             category's "vector" is the embedding of its
                             description + example phrases. Handles a brand
                             new category the moment it's added to the
                             taxonomy, with zero retraining.
3. EmbeddingClassifier    — Logistic Regression trained on top of the same
                             sentence-transformer embeddings.

All three share the same interface: `fit(texts, labels)` / `predict(texts)`,
so the evaluation notebook can loop over them uniformly. EmbeddingCentroid's
`fit` is a no-op over tickets — it only needs the taxonomy.
"""
from __future__ import annotations

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics.pairwise import cosine_similarity

from taxonomy import Taxonomy


class TfidfBaseline:
    """TF-IDF + Logistic Regression (or Random Forest)."""

    def __init__(self, model: str = "logreg"):
        self.vectorizer = TfidfVectorizer(max_features=20000, ngram_range=(1, 2), min_df=2)
        if model == "logreg":
            self.clf = LogisticRegression(max_iter=2000, class_weight="balanced")
        elif model == "random_forest":
            self.clf = RandomForestClassifier(n_estimators=300, class_weight="balanced", random_state=42)
        else:
            raise ValueError(f"unknown model: {model}")
        self.name = f"TF-IDF + {'Logistic Regression' if model == 'logreg' else 'Random Forest'}"

    def fit(self, texts: list[str], labels: list[str]) -> "TfidfBaseline":
        X = self.vectorizer.fit_transform(texts)
        self.clf.fit(X, labels)
        return self

    def predict(self, texts: list[str]) -> list[str]:
        X = self.vectorizer.transform(texts)
        return list(self.clf.predict(X))

    def supports_new_category(self) -> bool:
        return False


class EmbeddingEncoder:
    """Thin wrapper around a sentence-transformers model, shared by the two
    embedding-based approaches so the model is only loaded once."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(model_name)

    def encode(self, texts: list[str]) -> np.ndarray:
        return self.model.encode(list(texts), show_progress_bar=False, normalize_embeddings=True)


class EmbeddingCentroid:
    """Nearest-centroid classifier: a category's vector is the embedding of
    its description + example phrases, taken directly from the taxonomy.
    No ticket-level training at all — adding a category to taxonomy.yaml is
    enough for this classifier to start recognising it correctly."""

    name = "Embeddings + nearest centroid"

    def __init__(self, encoder: EmbeddingEncoder, taxonomy: Taxonomy):
        self.encoder = encoder
        self.taxonomy = taxonomy
        self._centroids: dict[str, np.ndarray] = {}
        self._build_centroids(taxonomy.active())

    def _build_centroids(self, categories) -> None:
        for cat in categories:
            text = cat.description + " " + " ".join(cat.example_phrases)
            vec = self.encoder.encode([text])[0]
            self._centroids[cat.category_id] = vec

    def add_category(self, category) -> None:
        """Register a brand-new category's centroid without touching the
        rest of the model — this is the whole point of this approach."""
        self._build_centroids([category])

    def fit(self, texts: list[str], labels: list[str]) -> "EmbeddingCentroid":
        # No training over tickets: centroids come from the taxonomy alone.
        return self

    def predict(self, texts: list[str]) -> list[str]:
        cat_ids = list(self._centroids.keys())
        centroid_matrix = np.stack([self._centroids[c] for c in cat_ids])
        embeddings = self.encoder.encode(texts)
        sims = cosine_similarity(embeddings, centroid_matrix)
        best = sims.argmax(axis=1)
        return [cat_ids[i] for i in best]

    def supports_new_category(self) -> bool:
        return True


class EmbeddingClassifier:
    """Logistic Regression trained on top of sentence-transformer embeddings."""

    name = "Embeddings + Logistic Regression"

    def __init__(self, encoder: EmbeddingEncoder):
        self.encoder = encoder
        self.clf = LogisticRegression(max_iter=2000, class_weight="balanced")

    def fit(self, texts: list[str], labels: list[str]) -> "EmbeddingClassifier":
        X = self.encoder.encode(texts)
        self.clf.fit(X, labels)
        return self

    def predict(self, texts: list[str]) -> list[str]:
        X = self.encoder.encode(texts)
        return list(self.clf.predict(X))

    def supports_new_category(self) -> bool:
        return False
