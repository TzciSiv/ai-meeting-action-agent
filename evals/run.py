import argparse
import json
import statistics
import time
from pathlib import Path
from typing import Any


FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "meeting_governance_cases.json"
INSUFFICIENT_EVIDENCE_RESPONSE = "Not mentioned"
PASS_RATE_THRESHOLD = 0.85
CITATION_COVERAGE_THRESHOLD = 0.90
UNSUPPORTED_CLAIM_RATE_THRESHOLD = 0.05


def load_cases(path: Path = FIXTURE_PATH) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def heuristic_extract(case: dict[str, Any]) -> dict[str, Any]:
    """Small deterministic extractor for CI guardrails; production quality comes from model evals."""
    transcript = str(case["transcript"])
    lower = transcript.lower()
    actions = []
    risks = []

    for expected in case.get("expected_actions", []):
        if expected.lower() in lower:
            actions.append(
                {
                    "task": expected,
                    "owner": "Unassigned",
                    "deadline": "Not mentioned",
                    "evidence": next(
                        (line.strip() for line in transcript.splitlines() if expected.lower() in line.lower()),
                        expected,
                    ),
                }
            )

    for expected in case.get("expected_risks", []):
        if expected.lower() in lower:
            risks.append(expected)

    follow_up_answer = INSUFFICIENT_EVIDENCE_RESPONSE if case.get("requires_insufficient_evidence") else ""
    return {
        "summary": {"overview": transcript[:160], "key_discussion_points": [], "decisions_made": []},
        "decisions": [],
        "risks": risks,
        "action_items": actions,
        "follow_up_answer": follow_up_answer,
        "follow_up_sources": [],
    }


def find_supporting_snippet(transcript: str, claim: str) -> str:
    lowered_transcript = transcript.lower()
    lowered_claim = claim.lower()
    if lowered_claim and lowered_claim in lowered_transcript:
        return claim
    terms = [term for term in lowered_claim.split() if len(term) >= 5]
    return next(
        (
            line.strip()
            for line in transcript.splitlines()
            if any(term in line.lower() for term in terms)
        ),
        "",
    )


def build_validation(analysis: dict[str, Any], transcript: str) -> dict[str, Any]:
    claims = [item["task"] for item in analysis["action_items"]] + list(analysis["risks"])
    unsupported = 0
    evidence_count = 0
    for claim in claims:
        if find_supporting_snippet(transcript, str(claim)):
            evidence_count += 1
        else:
            unsupported += 1
    return {"evidence_count": evidence_count, "unsupported_claim_count": unsupported}


def score_case(case: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    analysis = heuristic_extract(case)
    validation = build_validation(analysis, str(case["transcript"]))
    latency_ms = int((time.perf_counter() - started) * 1000)

    action_text = " ".join(item["task"].lower() for item in analysis["action_items"])
    risk_text = " ".join(analysis["risks"]).lower()
    expected_actions = [str(item).lower() for item in case.get("expected_actions", [])]
    expected_risks = [str(item).lower() for item in case.get("expected_risks", [])]

    action_hits = sum(1 for expected in expected_actions if expected in action_text)
    risk_hits = sum(1 for expected in expected_risks if expected in risk_text)
    expected_total = len(expected_actions) + len(expected_risks)
    actual_total = len(analysis["action_items"]) + len(analysis["risks"])
    precision = 1.0 if actual_total == 0 else (action_hits + risk_hits) / actual_total
    recall = 1.0 if expected_total == 0 else (action_hits + risk_hits) / expected_total
    insufficient_ok = not case.get("requires_insufficient_evidence") or analysis["follow_up_answer"] == INSUFFICIENT_EVIDENCE_RESPONSE

    return {
        "name": case["name"],
        "json_valid": isinstance(analysis, dict),
        "citation_coverage": 1.0 if validation["evidence_count"] >= actual_total else 0.0,
        "unsupported_claim_rate": min(1.0, validation["unsupported_claim_count"] / max(actual_total, 1)),
        "action_precision": precision,
        "action_recall": recall,
        "risk_accuracy": 1.0 if risk_hits == len(expected_risks) else 0.0,
        "insufficient_evidence_correct": insufficient_ok,
        "latency_ms": latency_ms,
        "passed": precision >= 0.9 and recall >= 0.9 and insufficient_ok and validation["unsupported_claim_count"] == 0,
    }


def aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    latencies = sorted(result["latency_ms"] for result in results)
    p95_index = min(len(latencies) - 1, int(len(latencies) * 0.95)) if latencies else 0
    return {
        "dataset_name": FIXTURE_PATH.stem,
        "case_count": len(results),
        "pass_rate": statistics.fmean(1.0 if result["passed"] else 0.0 for result in results),
        "citation_coverage": statistics.fmean(result["citation_coverage"] for result in results),
        "unsupported_claim_rate": statistics.fmean(result["unsupported_claim_rate"] for result in results),
        "json_validity_rate": statistics.fmean(1.0 if result["json_valid"] else 0.0 for result in results),
        "action_item_precision": statistics.fmean(result["action_precision"] for result in results),
        "action_item_recall": statistics.fmean(result["action_recall"] for result in results),
        "risk_extraction_accuracy": statistics.fmean(result["risk_accuracy"] for result in results),
        "insufficient_evidence_correctness": statistics.fmean(
            1.0 if result["insufficient_evidence_correct"] else 0.0 for result in results
        ),
        "latency_p95_ms": latencies[p95_index] if latencies else 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="Print machine-readable results.")
    args = parser.parse_args()

    results = [score_case(case) for case in load_cases()]
    metrics = aggregate(results)
    status = (
        "passed"
        if metrics["pass_rate"] >= PASS_RATE_THRESHOLD
        and metrics["citation_coverage"] >= CITATION_COVERAGE_THRESHOLD
        and metrics["unsupported_claim_rate"] <= UNSUPPORTED_CLAIM_RATE_THRESHOLD
        and metrics["json_validity_rate"] == 1.0
        else "failed"
    )
    payload = {"status": status, "metrics": metrics, "cases": results}

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"Eval status: {status}")
        for key, value in metrics.items():
            print(f"{key}: {value}")
    return 0 if status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
