"""Confirms the 'deterministic given the same seed' claim already made in
the wiki: regenerating the dataset with the same seed produces the same
row count and the same set of category ids present."""
from data_generation import generate_dataset
from taxonomy import load_taxonomy

N_TICKETS = 100  # small on purpose -- this test only needs to check determinism, not realism


def test_same_seed_produces_same_row_count_and_categories():
    taxonomy = load_taxonomy()

    tickets_a, conversations_a = generate_dataset(n_tickets=N_TICKETS, taxonomy=taxonomy, seed=7)
    tickets_b, conversations_b = generate_dataset(n_tickets=N_TICKETS, taxonomy=taxonomy, seed=7)

    assert len(tickets_a) == len(tickets_b) == N_TICKETS
    assert len(conversations_a) == len(conversations_b)

    categories_a = set(tickets_a["true_category_id_final"])
    categories_b = set(tickets_b["true_category_id_final"])
    assert categories_a == categories_b

    # Same seed should reproduce the same ticket contents, not just the same shape.
    assert tickets_a["subject"].tolist() == tickets_b["subject"].tolist()
    assert tickets_a["true_category_id_final"].tolist() == tickets_b["true_category_id_final"].tolist()


def test_different_seed_can_produce_different_content():
    taxonomy = load_taxonomy()

    tickets_a, _ = generate_dataset(n_tickets=N_TICKETS, taxonomy=taxonomy, seed=1)
    tickets_b, _ = generate_dataset(n_tickets=N_TICKETS, taxonomy=taxonomy, seed=2)

    assert tickets_a["true_category_id_final"].tolist() != tickets_b["true_category_id_final"].tolist()
