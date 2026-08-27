"""Shared evaluation helpers for comparing classifiers on the ticket dataset."""
from __future__ import annotations

import matplotlib.pyplot as plt
import pandas as pd
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score


def score(y_true: list[str], y_pred: list[str]) -> dict:
    return {
        "accuracy": accuracy_score(y_true, y_pred),
        "macro_f1": f1_score(y_true, y_pred, average="macro", zero_division=0),
    }


def results_table(results: dict[str, dict]) -> pd.DataFrame:
    """results: {model_name: {"accuracy": ..., "macro_f1": ...}}"""
    return pd.DataFrame(results).T.sort_values("macro_f1", ascending=False)


def plot_confusion_matrix(y_true: list[str], y_pred: list[str], labels: list[str], title: str, figsize=(11, 9)):
    cm = confusion_matrix(y_true, y_pred, labels=labels)
    fig, ax = plt.subplots(figsize=figsize)
    im = ax.imshow(cm, cmap="Blues")
    ax.set_xticks(range(len(labels)))
    ax.set_yticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=90, fontsize=7)
    ax.set_yticklabels(labels, fontsize=7)
    ax.set_xlabel("Predicted")
    ax.set_ylabel("True")
    ax.set_title(title)
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    fig.tight_layout()
    return fig, cm


def new_category_accuracy(df: pd.DataFrame, y_pred: list[str], category_id: str) -> dict:
    """Accuracy on the injected-category tickets only, and how many were
    predicted as *some* other, more established category (the typical
    failure mode for classifiers that must be retrained)."""
    mask = df["is_injected_new_category"].values
    preds = pd.Series(y_pred)[mask]
    correct = (preds == category_id).sum()
    total = mask.sum()
    return {
        "n_new_category_tickets": int(total),
        "correct": int(correct),
        "accuracy": (correct / total) if total else float("nan"),
        "predicted_as": preds.value_counts().to_dict(),
    }
