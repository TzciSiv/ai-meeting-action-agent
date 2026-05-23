import type { Meeting } from "../types";

interface Props {
  meeting: Meeting;
}

function splitLead(text: string) {
  const match = text.match(/^([^:]{3,74}):\s+(.+)$/);
  if (!match) {
    return { lead: "", body: text };
  }

  return { lead: match[1], body: match[2] };
}

function InsightText({ text }: { text: string }) {
  const { lead, body } = splitLead(text);

  return (
    <p>
      {lead && <strong>{lead}</strong>}
      {lead && <span aria-hidden="true">: </span>}
      <span>{body}</span>
    </p>
  );
}

function lineToElement(line: string, index: number) {
  if (line.startsWith("## ")) {
    return <h3 key={index}>{line.replace(/^##\s*/, "")}</h3>;
  }
  if (line.startsWith("- ")) {
    const text = line.replace(/^-\s*/, "");
    return (
      <div className="summary-insight" key={index}>
        <span className="summary-marker" aria-hidden="true" />
        <InsightText text={text} />
      </div>
    );
  }
  return (
    <p className="summary-overview-copy" key={index}>
      {line}
    </p>
  );
}

function summaryLinesWithoutStructuredSections(markdown: string) {
  const structuredHeadings = new Set(["decisions", "decisions made", "risks", "risks detected"]);
  let skippingStructuredSection = false;

  return markdown
    .split("\n")
    .filter((line) => {
      const trimmedLine = line.trim();
      const heading = trimmedLine.match(/^##\s+(.+)$/);

      if (heading) {
        skippingStructuredSection = structuredHeadings.has(heading[1].trim().toLowerCase());
        return !skippingStructuredSection;
      }

      return Boolean(trimmedLine) && !skippingStructuredSection;
    });
}

export default function MeetingSummary({ meeting }: Props) {
  const lines = summaryLinesWithoutStructuredSections(meeting.summary_markdown);
  const elements = lines.map(lineToElement);

  return (
    <section className="panel summary-panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Readable recap</p>
          <h2>Meeting Summary</h2>
        </div>
      </div>
      <div className="summary-body">{elements}</div>
      {(meeting.decisions.length > 0 || meeting.risks.length > 0) && (
        <div className="decision-risk-grid">
          <div>
            <h3>Decisions</h3>
            {meeting.decisions.length === 0 ? (
              <p className="muted">None captured.</p>
            ) : (
              <ul className="structured-insight-list">
                {meeting.decisions.map((decision, index) => (
                  <li key={`${decision}-${index}`}>
                    <span>{index + 1}</span>
                    <InsightText text={decision} />
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div>
            <h3>Risks</h3>
            {meeting.risks.length === 0 ? (
              <p className="muted">None detected.</p>
            ) : (
              <ul className="structured-insight-list risk">
                {meeting.risks.map((risk, index) => (
                  <li key={`${risk}-${index}`}>
                    <span>{index + 1}</span>
                    <InsightText text={risk} />
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
