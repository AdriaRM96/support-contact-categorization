"""Single-ticket classification service, built once and reused across
requests — the shape the Cloud Run handlers and simulate_tickets.py's local
dry-run mode both need, as opposed to classification_pipeline.py's
batch-oriented `build_classified_export`.

There's no persisted model artifact anywhere in this project (see
classifier_router.py) — the router is cheap enough to retrain from a
bundled training CSV at process start, and EmbeddingCentroid only needs
taxonomy.yaml. In a container, that means the training CSV and the
sentence-transformer weights need to be baked into the image (see
infra/ Dockerfiles) so cold start doesn't depend on external state.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from classifier_router import HybridRouter
from classifiers import EmbeddingCentroid, EmbeddingEncoder, TfidfBaseline
from taxonomy import Taxonomy, load_taxonomy
from text_features import final_text

DEFAULT_TRAINING_DATA_PATH = Path(__file__).parent.parent / "outputs" / "tickets.csv"


class TicketClassifierService:
    """Builds the hybrid router once and exposes simple text-in,
    category-id-out methods for both pipeline stages."""

    def __init__(
        self,
        taxonomy: Taxonomy | None = None,
        training_data_path: Path | str = DEFAULT_TRAINING_DATA_PATH,
    ):
        self.taxonomy = taxonomy or load_taxonomy()
        self.encoder = EmbeddingEncoder()
        self.centroid = EmbeddingCentroid(self.encoder, self.taxonomy)

        training_df = pd.read_csv(training_data_path)
        # tickets.csv already has a `description` (first message) column;
        # for training the router we want the same final-stage signal used
        # in Phase 2 (subject + full-ish text), so fall back to description
        # when no conversation thread is available at training time.
        if "true_category_id_final" not in training_df.columns:
            raise ValueError(f"{training_data_path} is missing true_category_id_final")
        train_text = (training_df["subject"].fillna("") + ". " + training_df["description"].fillna("")).str.strip()
        self.trained = TfidfBaseline("logreg").fit(list(train_text), list(training_df["true_category_id_final"]))
        self.router = HybridRouter(self.trained, self.centroid)

    def classify_triage(self, subject: str, first_message: str) -> str:
        """Runs at ticket creation: first message only."""
        text = f"{subject}. {first_message}".strip()
        return self.router.predict([text])[0]

    def classify_final(self, subject: str, conversation_messages: list[str]) -> str:
        """Runs at ticket close: full conversation thread."""
        text = (subject + ". " + " ".join(conversation_messages)).strip()
        return self.router.predict([text])[0]

    def add_category(self, category) -> None:
        """Register a new taxonomy category without rebuilding the service —
        the centroid path picks it up immediately, the trained path won't
        until its next retrain (see classifier_router.py's routing rule)."""
        self.centroid.add_category(category)
