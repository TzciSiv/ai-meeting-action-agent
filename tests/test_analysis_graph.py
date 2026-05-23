import unittest
from types import SimpleNamespace

import backend.analysis_graph as graph_module
from backend.analysis_graph import (
    ActionItemOutput,
    FollowUpAnswerOutput,
    MeetingInsightsOutput,
    SummaryOutput,
    answer_follow_up_node,
    extract_insights_node,
    normalize_action_items,
    normalize_summary_output,
    retrieve_sources_node,
    split_transcript_node,
    store_chunks_node,
    summarize_node,
)


class FakeSplitter:
    def split_text(self, text: str) -> list[str]:
        return [text[:1200], text[1000:]] if len(text) > 1200 else [text]


class FakeVectorStore:
    def __init__(self) -> None:
        self.added_documents = []
        self.added_ids = []
        self.last_query = ""
        self.last_filter = {}

    def add_documents(self, documents, ids):
        self.added_documents = documents
        self.added_ids = ids

    def similarity_search_with_relevance_scores(self, query: str, k: int, filter: dict):
        self.last_query = query
        self.last_filter = filter
        document = SimpleNamespace(
            page_content="James: I will finalize the Android crash fix by Tuesday.",
            metadata={"meeting_id": 42, "user_id": 7, "chunk_index": 3},
        )
        return [(document, 0.91)]


class AnalysisGraphTests(unittest.TestCase):
    def setUp(self):
        self.original_invoke_structured_model = graph_module.invoke_structured_model
        self.original_build_text_splitter = graph_module.build_text_splitter
        self.original_build_vector_store = graph_module.build_vector_store
        self.original_make_document = graph_module.make_document

    def tearDown(self):
        graph_module.invoke_structured_model = self.original_invoke_structured_model
        graph_module.build_text_splitter = self.original_build_text_splitter
        graph_module.build_vector_store = self.original_build_vector_store
        graph_module.make_document = self.original_make_document

    def test_normalizes_summary_output(self):
        summary = normalize_summary_output(
            SummaryOutput(
                overview="Demo planning meeting.",
                key_discussion_points=["Stability"],
                decisions_made=["Ship the demo Friday"],
            )
        )

        self.assertEqual(summary["overview"], "Demo planning meeting.")
        self.assertEqual(summary["key_discussion_points"], ["Stability"])
        self.assertEqual(summary["decisions_made"], ["Ship the demo Friday"])

    def test_normalizes_action_items(self):
        actions = normalize_action_items(
            [
                ActionItemOutput(
                    task="Finalize the Android crash fix",
                    owner="James",
                    deadline="Tuesday",
                    evidence="James: I will finalize the Android crash fix by Tuesday.",
                ),
                {"task": "None", "owner": "Maya"},
            ]
        )

        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["owner"], "James")

    def test_summary_node_uses_structured_model(self):
        def fake_invoke(schema, messages, temperature=None):
            self.assertIs(schema, SummaryOutput)
            self.assertIn("Do not invent decisions", messages[-1][1])
            return SummaryOutput(
                overview="Test summary.",
                key_discussion_points=["Discussion captured"],
                decisions_made=["Approved demo plan"],
            )

        graph_module.invoke_structured_model = fake_invoke

        result = summarize_node({"cleaned_transcript": "Sarah: We approved the demo plan."})

        self.assertEqual(result["summary"]["overview"], "Test summary.")
        self.assertEqual(result["decisions"], ["Approved demo plan"])
        self.assertIn("## Overview", result["summary_markdown"])

    def test_extract_insights_node_returns_actions_and_risks(self):
        def fake_invoke(schema, messages, temperature=None):
            self.assertIs(schema, MeetingInsightsOutput)
            return MeetingInsightsOutput(
                action_items=[
                    ActionItemOutput(
                        task="Finalize the Android crash fix",
                        owner="James",
                        deadline="Tuesday",
                        evidence="James will finalize the Android crash fix by Tuesday.",
                    )
                ],
                risks=["Customer support reported hallucination issues."],
            )

        graph_module.invoke_structured_model = fake_invoke

        result = extract_insights_node({"cleaned_transcript": "James will finalize the Android crash fix by Tuesday."})

        self.assertEqual(result["action_items"][0]["task"], "Finalize the Android crash fix")
        self.assertEqual(result["risks"], ["Customer support reported hallucination issues."])

    def test_split_and_store_chunks_use_langchain_shapes(self):
        fake_store = FakeVectorStore()
        graph_module.build_text_splitter = lambda: FakeSplitter()
        graph_module.build_vector_store = lambda: fake_store
        graph_module.make_document = lambda page_content, metadata: SimpleNamespace(
            page_content=page_content,
            metadata=metadata,
        )

        split_state = split_transcript_node({"cleaned_transcript": ("A" * 1200) + ("B" * 300)})
        store_state = store_chunks_node(
            {
                "chunks": split_state["chunks"],
                "meeting_id": 42,
                "user_id": 7,
            }
        )

        self.assertEqual(len(split_state["chunks"]), 2)
        self.assertEqual(fake_store.added_documents[0].metadata["meeting_id"], 42)
        self.assertEqual(fake_store.added_documents[0].metadata["user_id"], 7)
        self.assertEqual(store_state["stored_chunk_ids"][0], "meeting:42:user:7:chunk:0")

    def test_retrieve_sources_uses_metadata_filter(self):
        fake_store = FakeVectorStore()
        graph_module.build_vector_store = lambda: fake_store

        result = retrieve_sources_node(
            {
                "meeting_id": 42,
                "user_id": 7,
                "follow_up_question": "Who owns the Android fix?",
            }
        )

        self.assertEqual(fake_store.last_query, "Who owns the Android fix?")
        self.assertEqual(fake_store.last_filter, {"meeting_id": 42, "user_id": 7})
        self.assertEqual(result["follow_up_sources"][0]["chunk_index"], 3)
        self.assertEqual(result["follow_up_sources"][0]["score"], 0.91)

    def test_no_follow_up_skips_retrieval_and_answer(self):
        graph_module.build_vector_store = lambda: self.fail("Vector store should not be called without a question.")

        self.assertEqual(retrieve_sources_node({"meeting_id": 42, "follow_up_question": ""}), {"follow_up_sources": []})
        self.assertEqual(answer_follow_up_node({"follow_up_question": ""}), {"follow_up_answer": ""})

    def test_no_sources_answer_is_not_mentioned(self):
        result = answer_follow_up_node({"follow_up_question": "What was the budget?", "follow_up_sources": []})

        self.assertEqual(result["follow_up_answer"], "Not mentioned")
        self.assertEqual(result["follow_up_sources"], [])

    def test_not_mentioned_answer_clears_retrieved_sources(self):
        graph_module.invoke_structured_model = lambda *args, **kwargs: FollowUpAnswerOutput(answer="Not mentioned")

        result = answer_follow_up_node(
            {
                "follow_up_question": "When was the meeting?",
                "follow_up_sources": [{"rank": 1, "chunk_index": 0, "content": "No meeting date here."}],
            }
        )

        self.assertEqual(result["follow_up_answer"], "Not mentioned")
        self.assertEqual(result["follow_up_sources"], [])


if __name__ == "__main__":
    unittest.main()
