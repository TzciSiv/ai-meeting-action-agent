import type { ActionItem } from "../types";
import { getReadableEvidence } from "../actionEvidence";

interface Props {
  actions: ActionItem[];
}

export default function ActionBoard({ actions }: Props) {
  return (
    <section className="panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Agent output</p>
          <h2>Action Board</h2>
        </div>
        <span>{actions.length} items</span>
      </div>
      {actions.length === 0 ? (
        <p className="muted">No action items yet.</p>
      ) : (
        <div className="action-grid">
          {actions.map((action, index) => {
            const readableEvidence = getReadableEvidence(action.evidence);

            return (
              <article className="action-card" key={action.id}>
                <div className="action-index">{index + 1}</div>
                <div>
                  <h3>{action.task}</h3>
                  <p>
                    Owner: {action.owner} | Deadline: {action.deadline}
                  </p>
                  <span className={`status ${action.status.toLowerCase().replace(" ", "-")}`}>{action.status}</span>
                  {readableEvidence && <blockquote>{readableEvidence}</blockquote>}
                </div>
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}
