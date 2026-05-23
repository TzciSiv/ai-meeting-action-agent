# Action Extraction Prompt Card

## Purpose

Extract concrete post-meeting action items from a transcript.

## Inputs

- cleaned transcript
- current `meeting_insights` prompt version

## Outputs

- task
- owner
- deadline
- evidence quote

## Controls

- evidence required for generated action items
- action edits are audited

## Limitations

Ambiguous discussion topics are intentionally excluded unless a concrete task is stated.
