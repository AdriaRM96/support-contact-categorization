"""Build the text inputs each pipeline stage classifies on.

Triage runs on ticket creation with only the first message; final
classification runs at ticket close with the full conversation thread.
"""
from __future__ import annotations

import pandas as pd


def triage_text(tickets_df: pd.DataFrame) -> pd.Series:
    return (tickets_df["subject"].fillna("") + ". " + tickets_df["description"].fillna("")).str.strip()


def final_text(tickets_df: pd.DataFrame, conversations_df: pd.DataFrame) -> pd.Series:
    thread = (
        conversations_df.sort_values(["ticket_id", "created_at"])
        .groupby("ticket_id")["body"]
        .apply(lambda msgs: " ".join(msgs))
    )
    return (tickets_df["subject"].fillna("") + ". " + tickets_df["id"].map(thread).fillna("")).str.strip()
