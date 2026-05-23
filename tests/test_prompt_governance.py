import unittest

import backend.analysis_graph as graph_module
from backend.analysis_graph import (
    ActionItemOutput,
    FollowUpAnswerOutput,
    MeetingInsightsOutput,
    SummaryOutput,
    answer_follow_up_node,
    extract_insights_node,
    summarize_node,
)
from backend.prompts import (
    build_follow_up_messages,
    build_insights_messages,
    build_summary_messages,
    get_prompt_specs,
    prompt_inventory,
)


class PromptGovernanceTests(unittest.TestCase):
    def setUp(self):
        self.original_invoke_structured_model = graph_module.invoke_structured_model
        self.original_build_summary_messages = graph_module.build_summary_messages

    def tearDown(self):
        graph_module.invoke_structured_model = self.original_invoke_structured_model
        graph_module.build_summary_messages = self.original_build_summary_messages

    def test_prompt_registry_has_versions_and_schemas(self):
        specs = get_prompt_specs()

        self.assertIn("meeting_summary", specs)
        self.assertIn("meeting_insights", specs)
        self.assertIn("grounded_follow_up", specs)
        self.assertTrue(all(spec.version for spec in specs.values()))
        self.assertEqual(specs["meeting_summary"].output_schema, "SummaryOutput")
        self.assertEqual(specs["meeting_insights"].output_schema, "MeetingInsightsOutput")
        self.assertEqual(specs["grounded_follow_up"].output_schema, "FollowUpAnswerOutput")

    def test_prompt_safety_rules_cover_no_invention_and_grounding(self):
        inventory_text = " ".join(
            " ".join(str(rule) for rule in item["safety_rules"])
            for item in prompt_inventory()
        ).lower()

        self.assertIn("do not invent", inventory_text)
        self.assertIn("evidence", inventory_text)
        self.assertIn("retrieved transcript sources", inventory_text)
        self.assertIn("not mentioned", inventory_text)

    def test_prompt_builders_include_runtime_context(self):
        summary_messages = build_summary_messages("James: We approved the launch.")
        insight_messages = build_insights_messages("Maya: We should think about pricing.")
        follow_up_messages = build_follow_up_messages("Who owns the fix?", "Source 1: James owns it.")

        self.assertIn("approved the launch", summary_messages[-1][1])
        self.assertIn("Do not invent", insight_messages[-1][1])
        self.assertIn("Who owns the fix?", follow_up_messages[-1][1])
        self.assertIn("Source 1", follow_up_messages[-1][1])

    def test_summary_node_uses_registered_prompt_builder(self):
        def fake_builder(cleaned_transcript: str):
            return [("system", "registered system"), ("human", f"registered human: {cleaned_transcript}")]

        def fake_invoke(schema, messages, temperature=None):
            self.assertIs(schema, SummaryOutput)
            self.assertEqual(messages[0], ("system", "registered system"))
            self.assertIn("registered human", messages[1][1])
            return SummaryOutput(overview="Governed.", key_discussion_points=[], decisions_made=[])

        graph_module.build_summary_messages = fake_builder
        graph_module.invoke_structured_model = fake_invoke

        result = summarize_node({"cleaned_transcript": "Demo transcript"})

        self.assertEqual(result["summary"]["overview"], "Governed.")


class HallucinationMitigationEvalTests(unittest.TestCase):
    def setUp(self):
        self.original_invoke_structured_model = graph_module.invoke_structured_model

    def tearDown(self):
        graph_module.invoke_structured_model = self.original_invoke_structured_model

    def test_normal_meeting_extracts_supported_action_and_risk(self):
        def fake_invoke(schema, messages, temperature=None):
            self.assertIs(schema, MeetingInsightsOutput)
            return MeetingInsightsOutput(
                action_items=[
                    ActionItemOutput(
                        task="Finalize the Android crash fix",
                        owner="James",
                        deadline="Tuesday",
                        evidence="James: I will finalize the Android crash fix by Tuesday.",
                    )
                ],
                risks=["Customer support reported hallucination issues."],
            )

        graph_module.invoke_structured_model = fake_invoke

        result = extract_insights_node(
            {
                "cleaned_transcript": (
                    "James: I will finalize the Android crash fix by Tuesday.\n"
                    "Emily: Customer support reported hallucination issues."
                )
            }
        )

        self.assertEqual(result["action_items"][0]["owner"], "James")
        self.assertIn("James:", result["action_items"][0]["evidence"])
        self.assertEqual(result["risks"], ["Customer support reported hallucination issues."])

    def test_vague_discussion_does_not_become_task(self):
        def fake_invoke(schema, messages, temperature=None):
            prompt = messages[-1][1]
            self.assertIn("Do not turn discussion topics into tasks", prompt)
            return MeetingInsightsOutput(action_items=[], risks=[])

        graph_module.invoke_structured_model = fake_invoke

        result = extract_insights_node({"cleaned_transcript": "Maya: We should think about pricing someday."})

        self.assertEqual(result["action_items"], [])
        self.assertEqual(result["risks"], [])

    def test_no_action_transcript_returns_empty_actions(self):
        graph_module.invoke_structured_model = lambda *args, **kwargs: MeetingInsightsOutput(action_items=[], risks=[])

        result = extract_insights_node({"cleaned_transcript": "Sarah: Thanks everyone, that was helpful."})

        self.assertEqual(result["action_items"], [])

    def test_unsupported_follow_up_returns_not_mentioned_without_sources(self):
        result = answer_follow_up_node({"follow_up_question": "What budget was approved?", "follow_up_sources": []})

        self.assertEqual(result["follow_up_answer"], "Not mentioned")

    def test_grounded_follow_up_uses_structured_answer(self):
        def fake_invoke(schema, messages, temperature=None):
            self.assertIs(schema, FollowUpAnswerOutput)
            self.assertIn("Source 1", messages[-1][1])
            return FollowUpAnswerOutput(answer="James")

        graph_module.invoke_structured_model = fake_invoke

        result = answer_follow_up_node(
            {
                "follow_up_question": "Who owns the Android crash fix?",
                "follow_up_sources": [
                    {"rank": 1, "content": "James: I will finalize the Android crash fix by Tuesday."}
                ],
            }
        )

        self.assertEqual(result["follow_up_answer"], "James")


if __name__ == "__main__":
    unittest.main()
