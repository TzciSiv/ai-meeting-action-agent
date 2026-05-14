interface Props {
  question: string;
  answer: string;
}

export default function FollowUpAnswer({ question, answer }: Props) {
  if (!question && !answer) return null;

  return (
    <section className="panel answer-panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Asked during analysis</p>
          <h2>Follow-up Answer</h2>
        </div>
      </div>
      <div className="qa-card">
        {question && (
          <div className="question-line">
            <span>Question</span>
            <p>{question}</p>
          </div>
        )}
        {answer && (
          <div className="answer-line">
            <span>Answer</span>
            <strong>{answer}</strong>
          </div>
        )}
      </div>
    </section>
  );
}
