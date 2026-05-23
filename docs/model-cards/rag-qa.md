# RAG Q&A Prompt Card

## Purpose

Answer a user follow-up question using only retrieved transcript chunks.

## Inputs

- follow-up question
- retrieved transcript chunks filtered by meeting and user metadata
- current `grounded_follow_up` prompt version

## Outputs

- grounded answer
- retrieved source chunks
- traceable AI run

## Controls

- object-level retrieval filter
- insufficient-evidence response when sources are missing
- no outside knowledge
- retrieved chunk ids recorded in `ai_runs`

## Limitations

Retrieval quality affects answer quality. Weak retrieval returns `Not mentioned` instead of guessing.
