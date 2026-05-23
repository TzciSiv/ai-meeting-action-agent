# Summary Prompt Card

## Purpose

Create a concise, structured recap of a meeting transcript.

## Inputs

- authenticated user context
- meeting id
- cleaned transcript
- current `meeting_summary` prompt version

## Outputs

- overview
- key discussion points
- decisions made
- AI run trace metadata

## Controls

- prompt registry synchronization
- output hash in `ai_runs`
- token, latency, and model metadata

## Limitations

Summaries may compress nuance. Review the transcript before using a summary as a decision record.
