"""Zero/few-shot ticket classification via Gemini on Vertex AI.

Gated behind USE_LLM_CLASSIFIER (default False) so nobody who clones this
repo triggers Vertex AI spend by accident — instantiating GeminiClassifier
without that flag set raises immediately, before any network call.

Auth: Application Default Credentials only (`gcloud auth application-default
login`). No API key, no service-account JSON file — never hardcode or
commit credentials for this.

The taxonomy is embedded directly in the prompt (category_id, name,
description, example_phrases) so, like EmbeddingCentroid, this classifier
can recognise a brand-new category the moment it's added to
taxonomy.yaml — no retraining, no fine-tuning.
"""
from __future__ import annotations

import json
import os
import time

from taxonomy import Taxonomy

# Free-trial Vertex AI projects carry a low per-minute quota for generative
# model requests -- a sequential loop with no delay hits 429
# RESOURCE_EXHAUSTED quickly. This pacing + retry policy was tuned against
# that quota empirically (a fixed delay alone still hit occasional 429s;
# adding backoff-and-retry on top made every request eventually succeed).
REQUEST_DELAY_SECONDS = 2.0
MAX_RETRIES = 6
RETRY_BASE_DELAY_SECONDS = 5.0

# gemini-2.0-flash-001 isn't served on the `global` Vertex AI endpoint for
# this project (404 NOT_FOUND) -- confirmed via client.models.list();
# gemini-2.5-flash is available there and current as of this writing.
GEMINI_MODEL = "gemini-2.5-flash"
VERTEX_LOCATION = "global"


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _build_taxonomy_prompt(taxonomy: Taxonomy) -> str:
    lines = ["You are classifying a customer support ticket for NovaCart, an e-commerce marketplace.",
             "Choose the single best-matching category from this list:\n"]
    for cat in taxonomy.active():
        examples = "; ".join(cat.example_phrases) if cat.example_phrases else ""
        lines.append(f"- {cat.category_id} ({cat.name}): {cat.description} Examples: {examples}")
    lines.append(
        "\nRespond with a single JSON object with exactly these keys: "
        '"category_id" (one of the ids above, exactly as written), '
        '"confidence" (a number from 0 to 1), '
        '"reasoning" (one short sentence explaining the choice).'
    )
    return "\n".join(lines)


class GeminiClassifier:
    """Shares the classifiers.py fit/predict shape where it makes sense, so
    it can drop into the same evaluation harness used for the other three
    approaches — but `fit` is a no-op: there's no training step, only a
    prompt built from the taxonomy."""

    name = "Gemini Flash (Vertex AI, zero-shot)"

    def __init__(self, taxonomy: Taxonomy, project: str | None = None, location: str = VERTEX_LOCATION):
        if not _truthy(os.environ.get("USE_LLM_CLASSIFIER")):
            raise RuntimeError(
                "GeminiClassifier is gated behind USE_LLM_CLASSIFIER=true. "
                "Set that env var explicitly before instantiating this class — "
                "it calls the Vertex AI API and incurs real cost."
            )

        from google import genai
        from google.genai import types

        project = project or os.environ.get("GCP_PROJECT_ID")
        if not project:
            raise RuntimeError("GCP_PROJECT_ID must be set (env var or passed explicitly).")

        self.taxonomy = taxonomy
        self.system_prompt = _build_taxonomy_prompt(taxonomy)
        self.valid_ids = set(taxonomy.active_ids())
        self._types = types
        self.client = genai.Client(vertexai=True, project=project, location=location)

    def fit(self, texts: list[str], labels: list[str]) -> "GeminiClassifier":
        # No training: the taxonomy prompt already carries everything the
        # model needs, including any category added after this object was
        # constructed (call add_category, not fit, to pick up a new one).
        return self

    def add_category(self, category) -> None:
        """Rebuild the taxonomy prompt to include a newly added category —
        no retraining, matches EmbeddingCentroid's zero-retrain story."""
        self.taxonomy.categories.append(category)
        self.valid_ids.add(category.category_id)
        self.system_prompt = _build_taxonomy_prompt(self.taxonomy)

    def _classify_one(self, text: str) -> dict:
        from google.genai import errors

        for attempt in range(MAX_RETRIES):
            try:
                response = self.client.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=[self.system_prompt, f"\nTicket:\n{text}"],
                    config=self._types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.0,
                        # Simple structured-output classification, not a task
                        # that benefits from extended reasoning -- disabling
                        # thinking tokens cuts cost substantially (confirmed:
                        # a trivial call dropped from 35 total tokens to 6
                        # with this set) without changing the output.
                        thinking_config=self._types.ThinkingConfig(thinking_budget=0),
                    ),
                )
                break
            except errors.ClientError as e:
                if e.code == 429 and attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_BASE_DELAY_SECONDS * (2**attempt))
                    continue
                raise

        result = json.loads(response.text)
        if result.get("category_id") not in self.valid_ids:
            result["category_id"] = "GEN-OTHER"
            result["reasoning"] = (result.get("reasoning") or "") + " [invalid category_id, fell back to GEN-OTHER]"
        return result

    def predict(self, texts: list[str]) -> list[str]:
        return [d["category_id"] for d in self.predict_detailed(texts)]

    def predict_detailed(self, texts: list[str]) -> list[dict]:
        """Returns the full {category_id, confidence, reasoning} per ticket
        — used by the evaluation notebook and the Cloud Run handler, which
        both want more than just the winning category."""
        results = []
        for i, t in enumerate(texts):
            if i > 0:
                time.sleep(REQUEST_DELAY_SECONDS)
            results.append(self._classify_one(t))
        return results

    def supports_new_category(self) -> bool:
        return True
