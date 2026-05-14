const GENERIC_EVIDENCE = "structured action item returned by the summary model.";

export function getReadableEvidence(evidence: string): string {
  return evidence.trim().toLowerCase() === GENERIC_EVIDENCE ? "" : evidence.trim();
}
