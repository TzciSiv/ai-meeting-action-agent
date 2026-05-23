import type { ActionItem } from "../types";

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
          {actions.map((action, index) => (
            <article className="action-card" key={action.id}>
              <div className="action-index">{index + 1}</div>
              <div>
                <h3>{action.task}</h3>
                <p>
                  Owner: {action.owner} | Deadline: {action.deadline}
                </p>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
