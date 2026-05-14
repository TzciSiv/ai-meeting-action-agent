import re

from .llm import extract_action_items


RISK_TERMS = (
    "bug",
    "blocker",
    "crash",
    "deadline",
    "drain",
    "error",
    "fail",
    "hallucination",
    "issue",
    "latency",
    "memory",
    "privacy",
    "problem",
    "risk",
    "security",
    "sensitive",
    "slow",
)


def clean_sentence_for_output(sentence: str) -> str:
    sentence = sentence.strip()
    sentence = re.sub(
        r"^\s*\*{0,2}\s*(?:speaker\s*\d+|participant\s*\d+|[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,2})\s*:\s*\*{0,2}\s*",
        "",
        sentence,
        flags=re.IGNORECASE,
    )
    return sentence.strip()


def normalize_summary_dict(summary: dict | str | None) -> dict:
    if not isinstance(summary, dict):
        return {
            "overview": str(summary or "").strip(),
            "key_discussion_points": [],
            "decisions_made": [],
        }

    return {
        "overview": summary.get("overview", "No overview returned."),
        "key_discussion_points": summary.get("key_discussion_points", []) or [],
        "decisions_made": summary.get("decisions_made", []) or [],
    }


def extract_risks(transcript: str, limit: int = 6) -> list[str]:
    sentences = [sentence.strip() for sentence in re.findall(r"[^.!?\n]+[.!?]?", transcript) if sentence.strip()]
    risks = []
    seen = set()

    for sentence in sentences:
        lowered = sentence.lower()
        if any(term in lowered for term in RISK_TERMS):
            cleaned_sentence = clean_sentence_for_output(sentence)
            key = cleaned_sentence.lower()[:90]
            if key not in seen:
                seen.add(key)
                risks.append(cleaned_sentence)
        if len(risks) >= limit:
            break

    return risks


def extract_decisions(summary: dict, transcript: str) -> list[str]:
    normalized = normalize_summary_dict(summary)
    decisions = [decision for decision in normalized.get("decisions_made", []) if str(decision).strip()]
    if decisions:
        return decisions

    sentences = [sentence.strip() for sentence in re.findall(r"[^.!?\n]+[.!?]?", transcript) if sentence.strip()]
    decision_terms = ("decided", "agreed", "approved", "finalized", "let's avoid", "we should focus")
    return [sentence for sentence in sentences if any(term in sentence.lower() for term in decision_terms)][:5]


def run_action_agent(transcript: str, summary: dict) -> dict:
    return {
        "action_items": extract_action_items(transcript),
        "decisions": extract_decisions(summary, transcript),
        "risks": extract_risks(transcript),
    }
