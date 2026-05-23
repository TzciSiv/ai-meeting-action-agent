import { useEffect, useState } from "react";
import type { FollowUpSource } from "../types";

interface Props {
  question: string;
  answer: string;
  sources?: FollowUpSource[];
}

export default function FollowUpAnswer({ question, answer, sources = [] }: Props) {
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const answerIsNotMentioned = answer.trim().replace(/\.$/, "").toLowerCase() === "not mentioned";
  const visibleSources = answerIsNotMentioned ? [] : sources;
  const sourceSignature = visibleSources.map((source) => `${source.rank}:${source.chunk_index}:${source.score}`).join("|");

  useEffect(() => {
    setSourcesOpen(false);
  }, [question, answer, sourceSignature]);

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
      {visibleSources.length > 0 && (
        <div className={`source-list ${sourcesOpen ? "open" : ""}`}>
          <button
            className="source-toggle"
            type="button"
            aria-expanded={sourcesOpen}
            onClick={() => setSourcesOpen((open) => !open)}
          >
            <span>Retrieved evidence</span>
            <small>{visibleSources.length} chunks</small>
          </button>
          {sourcesOpen && (
            <div className="source-cards">
              {visibleSources.map((source) => (
                <article className="source-card" key={`${source.chunk_index}-${source.rank}`}>
                  <div>
                    <span>#{source.rank}</span>
                    <strong>Chunk {source.chunk_index + 1}</strong>
                  </div>
                  <p>{source.content}</p>
                  <small>Score {source.score.toFixed(3)}</small>
                </article>
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
