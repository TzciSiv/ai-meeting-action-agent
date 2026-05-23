# Report Generation Card

## Purpose

Export a meeting report from saved, reviewed meeting analysis.

## Inputs

- meeting summary
- action items
- decisions
- risks
- follow-up answer
- authenticated user authorization

## Outputs

- DOCX report export
- audit event for export

## Controls

- meeting ownership or explicit access required
- export event is audited
- audit metadata excludes raw transcript text
- transcript export requires raw transcript permission

## Limitations

The report generator uses stored analysis and does not independently revalidate transcript claims at export time.
