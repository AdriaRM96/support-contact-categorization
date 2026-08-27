"""Synthetic NovaCart support-ticket dataset generator.

Plain Python + Faker, no LLM calls. Produces Ticket + Conversation records
that mirror the shape of the Zendesk Tickets API, with realistic messiness:
variable message length, occasional typos, conversations that drift to a
different underlying issue than the subject line suggests, and some
genuinely ambiguous contacts between two categories.
"""
from __future__ import annotations

import random
import string
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from faker import Faker

from taxonomy import Category, Taxonomy, load_taxonomy

# ---------------------------------------------------------------------------
# Category -> message templates
# ---------------------------------------------------------------------------
# Each entry gives a few subject-line templates and a few "opening message"
# templates (the first customer message, used by the triage stage) plus a
# couple of customer follow-up lines used to build out the conversation.
# Placeholders are filled with Faker-generated values per ticket.

CATEGORY_TEMPLATES: dict[str, dict[str, list[str]]] = {
    "ORD-001": {
        "subjects": ["Where is my order?", "Tracking question", "Order #{order_id} status"],
        "openers": [
            "Hi, I placed order #{order_id} on {order_date} and I can't find any tracking info. Can you tell me where it is?",
            "Hello, just checking on the status of order #{order_id}, it's been a few days and I haven't heard anything.",
        ],
        "followups": ["Any update on this? It's been a while.", "Still no movement on the tracking page, is that normal?"],
    },
    "ORD-002": {
        "subjects": ["My order is late", "Delivery delay on #{order_id}", "Package hasn't arrived yet"],
        "openers": [
            "Order #{order_id} was supposed to arrive on {order_date} and it's still not here. What's going on?",
            "Hi, my delivery is running late, I ordered the {product} over a week ago.",
        ],
        "followups": ["It's been {days} extra days now, this is getting frustrating.", "Do you have an updated delivery estimate?"],
    },
    "ORD-003": {
        "subjects": ["My order never arrived", "Package marked delivered but I got nothing", "Lost order #{order_id}"],
        "openers": [
            "Order #{order_id} shows as delivered but I never received anything. I've checked with neighbours and the building office.",
            "Hi, the courier says my package for order #{order_id} was delivered but it's nowhere to be found.",
        ],
        "followups": ["I've looked everywhere, it's genuinely not here.", "Can you open an investigation with the carrier?"],
    },
    "ORD-004": {
        "subjects": ["Item missing from my order", "Incomplete package", "Order #{order_id} missing an item"],
        "openers": [
            "I just opened my package for order #{order_id} and the {product} is missing, only the rest of the items were inside.",
            "Hi, my order arrived but it's short one item, the box wasn't damaged so I'm not sure what happened.",
        ],
        "followups": ["I checked the box twice, it's definitely not there.", "Can you send the missing item or refund it?"],
    },
    "ORD-005": {
        "subjects": ["Need to change shipping address", "Wrong address on order", "Address correction for #{order_id}"],
        "openers": [
            "Hi, I think I entered the wrong address for order #{order_id}, could you update it before it ships?",
            "I moved recently and my order #{order_id} is still set to go to my old address, can this be fixed?",
        ],
        "followups": ["Has the address been updated yet?", "I'm worried it will ship before this gets fixed."],
    },
    "RET-001": {
        "subjects": ["How do I return this?", "Return process question", "Need a return label"],
        "openers": [
            "Hi, I'd like to return the {product} from order #{order_id}, can you send me a return label?",
            "What's the process to send back an item I ordered? It doesn't fit.",
        ],
        "followups": ["Do I need to print anything or can I drop it off?", "Where do I send the package back to?"],
    },
    "RET-002": {
        "subjects": ["Refund status", "Where is my refund?", "Still waiting on refund for #{order_id}"],
        "openers": [
            "I returned my order #{order_id} {days} days ago and haven't seen a refund yet, can you check?",
            "Hi, when will I get my money back for the item I sent back?",
        ],
        "followups": ["It's been longer than the timeline you gave me.", "My bank still shows no refund received."],
    },
    "RET-003": {
        "subjects": ["Wrong refund amount", "Partial refund issue", "Refund doesn't match order #{order_id}"],
        "openers": [
            "I got refunded for order #{order_id} but the amount is way less than what I paid.",
            "Hi, I was only refunded part of my order, can you check what happened?",
        ],
        "followups": ["I paid {amount} and only got a fraction of that back.", "Can someone look into the difference?"],
    },
    "RET-004": {
        "subjects": ["Return policy question", "How long do I have to return an item?", "Return eligibility"],
        "openers": [
            "Hi, quick question about your returns policy, can I return an item I already opened?",
            "How many days do I have to return something after delivery?",
        ],
        "followups": ["Does that apply to sale items too?", "Is there a restocking fee?"],
    },
    "PRD-001": {
        "subjects": ["Product arrived defective", "Item stopped working", "Defective {product}"],
        "openers": [
            "The {product} I ordered stopped working after {days} days of normal use.",
            "Hi, my order arrived and the {product} is broken, it won't turn on at all.",
        ],
        "followups": ["I've tried everything, it's definitely faulty.", "Can I get a replacement or refund?"],
    },
    "PRD-002": {
        "subjects": ["Wrong item received", "This isn't what I ordered", "Received wrong product"],
        "openers": [
            "I ordered the {product} but received a completely different item.",
            "Hi, the color/size I received doesn't match order #{order_id} at all.",
        ],
        "followups": ["I still want the item I originally ordered.", "Should I send this one back first?"],
    },
    "PRD-003": {
        "subjects": ["Question before buying", "Does this come in other sizes?", "Product question about {product}"],
        "openers": [
            "Hi, before I order the {product}, does it come in a larger size?",
            "Quick question, is the {product} compatible with older devices?",
        ],
        "followups": ["Also, what material is it made from?", "Do you have a size guide I can check?"],
    },
    "PRD-004": {
        "subjects": ["When will this be back in stock?", "Stock availability question", "Out of stock item"],
        "openers": [
            "Hi, the {product} shows as out of stock, do you know when it'll be available again?",
            "Is there any way to get notified when the {product} is restocked?",
        ],
        "followups": ["I really want this before {order_date}, is that realistic?", "Can I reserve one in advance?"],
    },
    "PRD-005": {
        "subjects": ["Quality doesn't match description", "Not as pictured", "Disappointed with quality"],
        "openers": [
            "The {product} I received feels much cheaper than it looked in the photos.",
            "Hi, the quality of this item really doesn't match the product description on the site.",
        ],
        "followups": ["It just doesn't feel like a {amount} item.", "Is this normal for this product line?"],
    },
    "PAY-001": {
        "subjects": ["Payment declined", "Can't complete checkout", "Card not working at checkout"],
        "openers": [
            "My card keeps getting declined when I try to check out, even though there are funds available.",
            "Hi, I'm getting a payment error and can't finish my order.",
        ],
        "followups": ["I've tried two different cards now.", "Is there an issue on your end with payments?"],
    },
    "PAY-002": {
        "subjects": ["Charged twice", "Duplicate charge on my card", "Incorrect charge amount"],
        "openers": [
            "I was charged twice for order #{order_id}, can you refund the duplicate?",
            "Hi, the amount charged to my card doesn't match my order total, can you check?",
        ],
        "followups": ["I have both charges on my statement, want me to send a screenshot?", "This needs to be corrected soon."],
    },
    "PAY-003": {
        "subjects": ["Need an invoice", "Invoice request for #{order_id}", "Receipt for accounting"],
        "openers": [
            "Hi, could you send me an invoice for order #{order_id}? I need it for accounting.",
            "Where can I download a receipt for my recent purchase?",
        ],
        "followups": ["Can it include the VAT breakdown?", "I need this fairly soon for my records."],
    },
    "PAY-004": {
        "subjects": ["Discount code not working", "Coupon issue at checkout", "Didn't get my discount"],
        "openers": [
            "I used the code {coupon_code} but it didn't apply any discount at checkout.",
            "Hi, I was supposed to get a discount but my order #{order_id} was charged full price.",
        ],
        "followups": ["The code was definitely still valid.", "Can you apply it retroactively or refund the difference?"],
    },
    "ACC-001": {
        "subjects": ["Can't log in", "Locked out of my account", "Password reset not working"],
        "openers": [
            "Hi, I can't log into my account, it keeps saying my password is wrong even after resetting it.",
            "The password reset link you sent isn't working, can you help me get back in?",
        ],
        "followups": ["I've tried clearing my cache and cookies too.", "Is there another way to verify my identity?"],
    },
    "ACC-002": {
        "subjects": ["Update my account details", "Change email on file", "Need to update my address"],
        "openers": [
            "Hi, I need to update the email address on my account.",
            "Can you help me change the phone number linked to my account?",
        ],
        "followups": ["I want to make sure I still get order notifications after the change.", "Is this something I can do myself in settings?"],
    },
    "ACC-003": {
        "subjects": ["Delete my account", "GDPR data request", "Please erase my data"],
        "openers": [
            "Hi, I'd like to delete my account and all data you hold on me, please confirm once done.",
            "This is a formal request for a copy of all personal data you have on file for me.",
        ],
        "followups": ["How long will this take to process?", "Can you confirm in writing once it's complete?"],
    },
    "LOY-001": {
        "subjects": ["Loyalty points question", "Membership benefits", "Missing points from order"],
        "openers": [
            "Hi, I didn't get loyalty points for my last order #{order_id}, can you check why?",
            "What benefits come with the premium membership tier?",
        ],
        "followups": ["I usually get points within a day or two.", "Do points expire after a certain time?"],
    },
    "GEN-001": {
        "subjects": ["Not happy with my experience", "Complaint about recent order", "Frustrated customer"],
        "openers": [
            "I want to file a complaint, my overall experience with this order has been really disappointing.",
            "Hi, I've had several issues with my last few orders and I'm not happy with the service.",
        ],
        "followups": ["This isn't the first time either.", "I'd like to know how this will be addressed."],
    },
    "GEN-002": {
        "subjects": ["A suggestion for you", "Feedback about the website", "Feature request"],
        "openers": [
            "Just some feedback, it would be great if the website had a size comparison tool.",
            "Have you considered adding more filters to the search page? Would make browsing easier.",
        ],
        "followups": ["Just a thought, not urgent at all.", "Would love to see that in a future update."],
    },
    "GEN-003": {
        "subjects": ["Thank you!", "Great service", "Just wanted to say thanks"],
        "openers": [
            "Just wanted to say thank you, my order arrived early and in perfect condition.",
            "Hi, your support team helped me out so quickly yesterday, really appreciated it.",
        ],
        "followups": ["Wanted this on record, you don't get enough good feedback.", "Keep up the great work!"],
    },
    "GEN-OTHER": {
        "subjects": ["Quick question", "Not sure who to ask", "Random query"],
        "openers": [
            "Hi, I have a question but I'm not totally sure it's the right team to ask.",
            "This might not be the right place but I wasn't sure where else to send this.",
        ],
        "followups": ["Let me know if I should contact someone else instead.", "Sorry if this isn't the right department."],
    },
}

AGENT_REPLIES = [
    "Thanks for reaching out, let me look into this for you.",
    "I'm sorry for the trouble, checking your account now.",
    "Thanks for the details, give me a moment to check on this.",
    "I understand the frustration, let's get this sorted out.",
]

AGENT_RESOLUTIONS = [
    "I've resolved this on our end, please let us know if you need anything else.",
    "This has been taken care of, apologies again for the inconvenience.",
    "All set on our side now, thanks for your patience.",
    "Thanks for confirming, I've closed this out on our end.",
]

CUSTOMER_CLOSING = [
    "Thanks for the help!",
    "Great, appreciate the quick resolution.",
    "Perfect, thank you.",
    "OK thank you, that answers my question.",
]

PRODUCTS = [
    "wireless headphones", "running shoes", "denim jacket", "smartwatch", "backpack",
    "bluetooth speaker", "winter coat", "laptop sleeve", "sunglasses", "phone case",
    "yoga mat", "desk lamp", "sneakers", "leather wallet", "graphic t-shirt",
]

TYPOS = {
    "the": "teh", "and": "adn", "you": "yuo", "received": "recieved",
    "delivery": "delivry", "package": "pacakge", "still": "stil",
}

# Category pairs that are genuinely easy to confuse — used for ambiguous cases.
CONFUSABLE_PAIRS = [
    ("RET-002", "PAY-002"),   # refund status vs duplicate charge
    ("ORD-003", "RET-002"),   # lost order vs refund status
    ("PRD-001", "PRD-002"),   # defective vs wrong item
    ("ORD-002", "ORD-003"),   # delayed vs lost
    ("RET-003", "PAY-002"),   # partial refund vs incorrect charge
    ("PRD-005", "PRD-001"),   # quality mismatch vs defective
    ("RET-001", "RET-004"),   # how to return vs policy question
]


@dataclass
class GeneratedTicket:
    ticket: dict
    conversation: list[dict]


def _maybe_typo(text: str, rng: random.Random, p: float = 0.08) -> str:
    words = text.split(" ")
    out = []
    for w in words:
        bare = w.strip(string.punctuation).lower()
        if bare in TYPOS and rng.random() < p:
            replaced = TYPOS[bare]
            out.append(w.replace(bare, replaced) if bare in w.lower() else w)
        else:
            out.append(w)
    return " ".join(out)


def _fill(template: str, ctx: dict) -> str:
    return template.format(**ctx)


def _pick_category(taxonomy: Taxonomy, rng: random.Random, weights: dict[str, float] | None) -> Category:
    active = taxonomy.active()
    if weights:
        pool = [weights.get(c.category_id, 1.0) for c in active]
        return rng.choices(active, weights=pool, k=1)[0]
    return rng.choice(active)


def _default_weights(taxonomy: Taxonomy) -> dict[str, float]:
    """Imbalanced-by-design category distribution: a handful of categories
    dominate contact volume, most are moderate, a few are rare — mirrors a
    real support queue."""
    high = {"ORD-001", "ORD-002", "RET-002", "PRD-001"}
    low = {"ACC-003", "GEN-003", "LOY-001", "GEN-002"}
    weights = {}
    for c in taxonomy.active():
        if c.category_id in high:
            weights[c.category_id] = 6.0
        elif c.category_id in low:
            weights[c.category_id] = 0.5
        else:
            weights[c.category_id] = 1.5
    return weights


def generate_dataset(
    n_tickets: int = 1200,
    taxonomy: Taxonomy | None = None,
    seed: int = 42,
    drift_rate: float = 0.12,
    ambiguous_rate: float = 0.08,
    new_category_injection: dict | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Generate synthetic NovaCart tickets + conversations.

    new_category_injection: optional dict with keys:
        - category: Category to introduce partway through (must not be
          in `taxonomy`'s normal weighted pool, e.g. a taxonomy v2 addition)
        - start_index: ticket index (0-based) from which the category
          starts appearing, with zero examples before that point.
        - rate: fraction of tickets from start_index onward that use the
          new category.
    Used by Phase 2 to test how each classifier handles a brand-new
    category from its very first occurrence.
    """
    taxonomy = taxonomy or load_taxonomy()
    rng = random.Random(seed)
    fake = Faker()
    Faker.seed(seed)

    weights = _default_weights(taxonomy)

    tickets_rows = []
    conversations_rows = []

    base_time = datetime(2025, 6, 1)

    for i in range(n_tickets):
        ticket_id = 10000 + i
        requester_id = 50000 + rng.randint(0, n_tickets * 3)
        assignee_id = 900 + rng.randint(0, 25)
        group_id = 1 if rng.random() < 0.7 else 2

        created_at = base_time + timedelta(
            minutes=rng.randint(0, 60 * 24 * 90), seconds=rng.randint(0, 59)
        )

        # --- pick true category, honoring new-category injection ---
        injected = False
        if (
            new_category_injection is not None
            and i >= new_category_injection["start_index"]
            and rng.random() < new_category_injection.get("rate", 0.05)
        ):
            true_category = new_category_injection["category"]
            injected = True
        else:
            true_category = _pick_category(taxonomy, rng, weights)

        ctx = {
            "order_id": rng.randint(100000, 999999),
            "order_date": (created_at - timedelta(days=rng.randint(1, 20))).strftime("%b %d"),
            "product": rng.choice(PRODUCTS),
            "days": rng.randint(2, 15),
            "amount": f"${rng.randint(15, 250)}",
            "coupon_code": rng.choice(["SAVE10", "WELCOME15", "SUMMER20", "NOVA5"]),
        }

        tmpl = CATEGORY_TEMPLATES.get(true_category.category_id)
        if tmpl is None:
            # New injected category with no template yet: build a generic
            # opener from its description/example phrases so the pipeline
            # doesn't require hand-authored templates for it.
            subject = f"Question about: {true_category.name}"
            opener = rng.choice(true_category.example_phrases) if true_category.example_phrases else true_category.description
            followups = ["Any update on this?", "Just following up on my message."]
        else:
            subject = _fill(rng.choice(tmpl["subjects"]), ctx)
            opener = _fill(rng.choice(tmpl["openers"]), ctx)
            followups = [_fill(f, ctx) for f in tmpl["followups"]]

        opener = _maybe_typo(opener, rng)

        # --- ambiguous case: blend phrasing from a confusable pair ---
        is_ambiguous = False
        ambiguous_with = None
        if not injected and rng.random() < ambiguous_rate:
            pair = next((p for p in CONFUSABLE_PAIRS if true_category.category_id in p), None)
            if pair:
                other_id = pair[0] if pair[1] == true_category.category_id else pair[1]
                other_tmpl = CATEGORY_TEMPLATES.get(other_id)
                if other_tmpl:
                    is_ambiguous = True
                    ambiguous_with = other_id
                    opener = opener + " " + _fill(rng.choice(other_tmpl["openers"]), ctx)

        # --- drift: conversation reveals a different real issue than the subject ---
        is_drift = False
        drift_category = None
        if not injected and not is_ambiguous and rng.random() < drift_rate:
            candidates = [c for c in taxonomy.active() if c.category_id != true_category.category_id]
            drift_target = rng.choice(candidates)
            if drift_target.category_id in CATEGORY_TEMPLATES:
                is_drift = True
                drift_category = drift_target.category_id

        # --- conversation thread ---
        conv = []
        turn_time = created_at
        author_customer = requester_id
        author_agent = assignee_id

        conv.append({
            "id": f"{ticket_id}-1", "ticket_id": ticket_id, "author_id": author_customer,
            "body": opener, "public": True, "created_at": turn_time.isoformat(),
        })
        turn_time += timedelta(minutes=rng.randint(5, 240))

        conv.append({
            "id": f"{ticket_id}-2", "ticket_id": ticket_id, "author_id": author_agent,
            "body": rng.choice(AGENT_REPLIES), "public": True, "created_at": turn_time.isoformat(),
        })
        turn_time += timedelta(minutes=rng.randint(10, 300))

        # follow-up: either same-topic followup, or the drifted topic
        if is_drift:
            drift_tmpl = CATEGORY_TEMPLATES[drift_category]
            followup_body = _fill(rng.choice(drift_tmpl["openers"]), ctx)
            followup_body = "Actually, sorry, let me explain the real issue. " + followup_body
        else:
            followup_body = rng.choice(followups)
        followup_body = _maybe_typo(followup_body, rng)

        conv.append({
            "id": f"{ticket_id}-3", "ticket_id": ticket_id, "author_id": author_customer,
            "body": followup_body, "public": True, "created_at": turn_time.isoformat(),
        })
        turn_time += timedelta(minutes=rng.randint(10, 300))

        n_extra_turns = rng.choices([0, 1, 2], weights=[0.5, 0.35, 0.15])[0]
        for k in range(n_extra_turns):
            conv.append({
                "id": f"{ticket_id}-{4 + 2 * k}", "ticket_id": ticket_id, "author_id": author_agent,
                "body": rng.choice(AGENT_REPLIES), "public": True, "created_at": turn_time.isoformat(),
            })
            turn_time += timedelta(minutes=rng.randint(10, 200))
            conv.append({
                "id": f"{ticket_id}-{5 + 2 * k}", "ticket_id": ticket_id, "author_id": author_customer,
                "body": rng.choice(["OK, still waiting to hear back.", "Any news?", "Following up on this."]),
                "public": True, "created_at": turn_time.isoformat(),
            })
            turn_time += timedelta(minutes=rng.randint(10, 200))

        status = rng.choices(["solved", "closed", "pending", "open"], weights=[0.55, 0.25, 0.12, 0.08])[0]
        if status in ("solved", "closed"):
            conv.append({
                "id": f"{ticket_id}-{len(conv)+1}", "ticket_id": ticket_id, "author_id": author_agent,
                "body": rng.choice(AGENT_RESOLUTIONS), "public": True, "created_at": turn_time.isoformat(),
            })
            turn_time += timedelta(minutes=rng.randint(5, 120))
            conv.append({
                "id": f"{ticket_id}-{len(conv)+1}", "ticket_id": ticket_id, "author_id": author_customer,
                "body": rng.choice(CUSTOMER_CLOSING), "public": True, "created_at": turn_time.isoformat(),
            })

        updated_at = turn_time

        # Final ground-truth category: if drifted, the *true* underlying
        # issue (used for final classification) is the drift category, not
        # the original subject-implied one; triage (first message only)
        # will naturally see the original category's language.
        final_true_category = drift_category if is_drift else true_category.category_id
        triage_true_category = true_category.category_id  # what the opener alone implies

        tickets_rows.append({
            "id": ticket_id,
            "subject": subject,
            "description": opener,
            "status": status,
            "priority": rng.choices(["low", "normal", "high", "urgent"], weights=[0.3, 0.5, 0.15, 0.05])[0],
            "type": rng.choice(["question", "incident", "problem", "task"]),
            "via_channel": rng.choices(["web_widget", "email"], weights=[0.65, 0.35])[0],
            "tags": ",".join(rng.sample(["ecommerce", "priority", "vip", "mobile_app", "web"], k=rng.randint(0, 2))),
            "requester_id": requester_id,
            "assignee_id": assignee_id,
            "group_id": group_id,
            "created_at": created_at.isoformat(),
            "updated_at": updated_at.isoformat(),
            # ground truth / eval columns (would be custom_fields in real Zendesk)
            "true_category_id_triage": triage_true_category,
            "true_category_id_final": final_true_category,
            "taxonomy_version": taxonomy.taxonomy_version if not injected else new_category_injection["category"].taxonomy_version,
            "is_drift_case": is_drift,
            "is_ambiguous_case": is_ambiguous,
            "ambiguous_with_category_id": ambiguous_with,
            "is_injected_new_category": injected,
        })
        conversations_rows.extend(conv)

    tickets_df = pd.DataFrame(tickets_rows)
    conversations_df = pd.DataFrame(conversations_rows)
    return tickets_df, conversations_df


def save_dataset(tickets_df: pd.DataFrame, conversations_df: pd.DataFrame, out_dir: Path | str = "outputs") -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tickets_df.to_csv(out_dir / "tickets.csv", index=False)
    conversations_df.to_csv(out_dir / "conversations.csv", index=False)


if __name__ == "__main__":
    tickets_df, conversations_df = generate_dataset()
    save_dataset(tickets_df, conversations_df)
    print(f"Generated {len(tickets_df)} tickets, {len(conversations_df)} conversation messages")
    print(tickets_df["true_category_id_final"].value_counts())
