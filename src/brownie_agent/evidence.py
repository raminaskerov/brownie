"""Local exact-passage candidates from one source page without another model call."""

import re

MAX_PASSAGES = 5
STOP_WORDS = {
    "about", "after", "also", "and", "are", "for", "find", "from", "has", "have", "into",
    "documentation", "official", "page", "that", "the", "their", "this", "was", "what", "when", "where", "which",
    "with", "your",
}


def _terms(text: str) -> set[str]:
    return {
        token.casefold()
        for token in re.findall(r"[^\W_]+", text, flags=re.UNICODE)
        if len(token) >= 3 and token.casefold() not in STOP_WORDS
    }


def evidence_candidates(goal: str, material: str, *, limit: int = MAX_PASSAGES) -> dict:
    """Rank exact source lines by goal-term overlap; make no sufficiency claim."""
    if type(limit) is not int or not 1 <= limit <= MAX_PASSAGES:
        raise ValueError(f"limit must be an integer from 1 to {MAX_PASSAGES}")
    goal_terms = _terms(goal)
    ranked = []
    seen = set()
    lines = material.splitlines()
    for size in range(1, 4):
        for offset in range(len(lines) - size + 1):
            passage = "\n".join(line.strip() for line in lines[offset : offset + size]).strip()
            if len(passage) < 20 or len(passage) > 500 or passage in seen or passage not in material:
                continue
            seen.add(passage)
            overlap = goal_terms & _terms(passage)
            if overlap:
                ranked.append((-len(overlap), len(passage), offset, offset + size, passage, sorted(overlap)))
    ranked.sort()
    selected = []
    occupied = []
    for candidate in ranked:
        start, end = candidate[2], candidate[3]
        if any(start < used_end and used_start < end for used_start, used_end in occupied):
            continue
        selected.append(candidate)
        occupied.append((start, end))
        if len(selected) >= limit:
            break
    return {
        "method": "local_goal_term_overlap",
        "passages": [passage for _score, _length, _start, _end, passage, _overlap in selected],
        "matched_terms": sorted({
            term for _score, _length, _start, _end, _passage, overlap in selected for term in overlap
        }),
        "relevance": None,
        "sufficient": None,
    }
