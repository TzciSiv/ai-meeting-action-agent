import type { Meeting } from "../types";

interface Props {
  meeting: Meeting;
}

function lineToElement(line: string, index: number) {
  if (line.startsWith("## ")) {
    return <h3 key={index}>{line.replace(/^##\s*/, "")}</h3>;
  }
  if (line.startsWith("- ")) {
    return (
      <p className="summary-bullet" key={index}>
        {line.replace(/^-\s*/, "")}
      </p>
    );
  }
  return <p key={index}>{line}</p>;
}

export default function MeetingSummary({ meeting }: Props) {
  const lines = meeting.summary_markdown.split("\n").filter((line) => line.trim());
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
              <ul>
                {meeting.decisions.map((decision, index) => (
                  <li key={`${decision}-${index}`}>{decision}</li>
                ))}
              </ul>
            )}
          </div>
          <div>
            <h3>Risks</h3>
            {meeting.risks.length === 0 ? (
              <p className="muted">None detected.</p>
            ) : (
              <ul>
                {meeting.risks.map((risk, index) => (
                  <li key={`${risk}-${index}`}>{risk}</li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
