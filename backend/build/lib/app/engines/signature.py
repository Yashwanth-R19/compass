import hashlib


def finding_signature(category: str, key: str) -> str:
    """Stable identity for a finding ACROSS runs.

    `key` is a category-specific, order-normalised string identifying the
    thing the finding is about -- NOT its title or detail text, which embed
    numbers that change between runs and would make every finding look new.
    Returns the first 32 chars of a sha256 hex digest.

    Key convention, by category (session 01, CLAUDE.md):

        hidden_dependency          the two paths, sorted, joined with "|"
        architecture (cycle)       the cycle's member paths, sorted, joined with "|"
        architecture (layering)    f"{from_path}->{to_path}"
        risk                       the file path

    Sorting the members of an unordered set (a coupling pair, a cycle) is
    what makes the signature order-independent: a cycle detected as
    a->b->c in one run and b->c->a in the next is the same cycle -- the
    graph didn't change, only which node nx.simple_cycles happened to start
    walking from -- and must produce the same signature, or session 13's
    run-to-run diff would report it as both "resolved" and "newly
    appeared" instead of "persisted".
    """
    digest = hashlib.sha256(f"{category}:{key}".encode()).hexdigest()
    return digest[:32]
