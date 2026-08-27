"""Plays the role of the Zendesk webhook this project doesn't have.

Replays outputs/tickets.csv against the deployed Cloud Run endpoints: a
triage call when a ticket is "created", a final call when it's "solved" —
with a small delay between tickets so a screen recording of this running
looks like a believable live ticket stream, not a batch dump.

Two modes:
  --dry-run          classify locally via src/predict_service.py (router
                      only, no network calls, no cost) — use this to sanity
                      check the script before pointing it at real endpoints.
  --triage-url / --final-url
                      the deployed Cloud Run service URLs (from
                      `terraform output` after infra/deploy.sh has run).
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def load_tickets(conversations_path: Path, tickets_path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    tickets_df = pd.read_csv(tickets_path)
    conversations_df = pd.read_csv(conversations_path)
    return tickets_df, conversations_df


def first_message(conversations_df: pd.DataFrame, ticket_id: int) -> str:
    thread = conversations_df[conversations_df["ticket_id"] == ticket_id].sort_values("created_at")
    return thread.iloc[0]["body"] if len(thread) else ""


def all_messages(conversations_df: pd.DataFrame, ticket_id: int) -> list[str]:
    thread = conversations_df[conversations_df["ticket_id"] == ticket_id].sort_values("created_at")
    return list(thread["body"])


def run_dry(tickets_df: pd.DataFrame, conversations_df: pd.DataFrame, delay: float, limit: int | None) -> None:
    from predict_service import TicketClassifierService

    service = TicketClassifierService()
    rows = tickets_df.head(limit) if limit else tickets_df

    for _, ticket in rows.iterrows():
        msg = first_message(conversations_df, ticket["id"])
        triage_category = service.classify_triage(ticket["subject"], msg)
        print(f"[triage]  ticket {ticket['id']} -> {triage_category}")

        if ticket["status"] in ("solved", "closed"):
            messages = all_messages(conversations_df, ticket["id"])
            final_category = service.classify_final(ticket["subject"], messages)
            print(f"[final]   ticket {ticket['id']} -> {final_category}")

        time.sleep(delay)


def run_live(
    tickets_df: pd.DataFrame,
    conversations_df: pd.DataFrame,
    triage_url: str,
    final_url: str,
    delay: float,
    limit: int | None,
    start_id: int | None = None,
) -> None:
    rows = tickets_df.head(limit) if limit else tickets_df
    if start_id is not None:
        rows = rows[rows["id"] >= start_id]

    n_failed = 0
    for _, ticket in rows.iterrows():
        try:
            msg = first_message(conversations_df, ticket["id"])
            resp = requests.post(
                f"{triage_url}/classify",
                json={"ticket_id": int(ticket["id"]), "subject": ticket["subject"], "first_message": msg},
                timeout=180,  # /classify calls Gemini synchronously (incl. its own backoff retries) + possible cold start
            )
            resp.raise_for_status()
            row = resp.json()
            gemini_note = f", gemini -> {row['gemini_category']}" if row.get("gemini_category") else ""
            print(f"[triage]  ticket {ticket['id']} -> {row['router_category']}{gemini_note}")

            if ticket["status"] in ("solved", "closed"):
                messages = all_messages(conversations_df, ticket["id"])
                resp = requests.post(
                    f"{final_url}/classify",
                    json={"ticket_id": int(ticket["id"]), "subject": ticket["subject"], "messages": messages},
                    timeout=180,
                )
                resp.raise_for_status()
                row = resp.json()
                gemini_note = f", gemini -> {row['gemini_category']}" if row.get("gemini_category") else ""
                print(f"[final]   ticket {ticket['id']} -> {row['router_category']}{gemini_note}")
        except requests.exceptions.RequestException as e:
            # A single ticket failing (transient rate limit, cold start, etc.)
            # shouldn't kill a run that's most of the way through a batch --
            # log it and keep going. Re-run with --start-id to pick up any
            # gaps afterward if needed.
            n_failed += 1
            print(f"[ERROR]   ticket {ticket['id']} failed: {e}")

        time.sleep(delay)

    if n_failed:
        print(f"\n{n_failed} ticket(s) failed during this run -- check the log above and consider a follow-up pass.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="classify locally, no network calls, no cost")
    parser.add_argument("--triage-url", help="deployed triage-classifier Cloud Run URL")
    parser.add_argument("--final-url", help="deployed final-classifier Cloud Run URL")
    parser.add_argument("--delay", type=float, default=1.5, help="seconds between tickets (default 1.5)")
    parser.add_argument("--limit", type=int, default=None, help="only replay the first N tickets")
    parser.add_argument("--start-id", type=int, default=None, help="skip tickets before this id (for resuming a partial run)")
    parser.add_argument(
        "--tickets", type=Path, default=Path(__file__).parent.parent / "outputs" / "tickets.csv"
    )
    parser.add_argument(
        "--conversations", type=Path, default=Path(__file__).parent.parent / "outputs" / "conversations.csv"
    )
    args = parser.parse_args()

    tickets_df, conversations_df = load_tickets(args.conversations, args.tickets)

    if args.dry_run:
        run_dry(tickets_df, conversations_df, args.delay, args.limit)
        return

    if not (args.triage_url and args.final_url):
        parser.error("--triage-url and --final-url are required unless --dry-run is set")

    run_live(tickets_df, conversations_df, args.triage_url, args.final_url, args.delay, args.limit, args.start_id)


if __name__ == "__main__":
    main()
