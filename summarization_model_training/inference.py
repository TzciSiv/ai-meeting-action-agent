import argparse
import json
from pathlib import Path

from backend.local_model import (
    DEFAULT_BASE_MODEL,
    DEFAULT_MODEL_DIR,
    summarize_file,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize a transcript with a trained local model.")
    parser.add_argument("--transcript", required=True)
    parser.add_argument("--model-dir", default=str(DEFAULT_MODEL_DIR))
    parser.add_argument("--base-model", default=DEFAULT_BASE_MODEL)
    parser.add_argument("--reference")
    parser.add_argument("--output", default="summary.json")
    args = parser.parse_args()

    result = summarize_file(args.transcript, args.model_dir, args.base_model, args.reference)
    Path(args.output).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(result["summary_markdown"])


if __name__ == "__main__":
    main()

