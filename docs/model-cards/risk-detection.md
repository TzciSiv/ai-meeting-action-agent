# Risk Detection Prompt Card

## Purpose

Identify risks, blockers, concerns, security issues, privacy issues, and reliability problems raised in a meeting.

## Inputs

- cleaned transcript
- current `meeting_insights` prompt version

## Outputs

- risk list
- AI run trace metadata

## Controls

- no outside knowledge
- eval fixtures include conflicting, sensitive, and prompt-injection transcripts

## Limitations

Risk extraction depends on evidence present in the transcript. Silent or implied risks should be handled by a reviewer.
