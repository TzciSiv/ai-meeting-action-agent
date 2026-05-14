import unittest

import backend.action_agent as action_agent_module
from backend.action_agent import extract_risks, run_action_agent


SAMPLE_TRANSCRIPT = """
Sarah: We need the demo to be stable before Friday.
James: I will finalize the Android crash fix by Tuesday.
Ravi: I will investigate model latency before the investor demo.
Maya: This one I couldn't pick, and I'll tell you why.
Emily: Customer support reported hallucination issues in summaries.
"""


def sample_gpt_action_items(transcript: str) -> list[dict[str, str]]:
    return [
        {
            "task": "Finalize the Android crash fix",
            "owner": "James",
            "deadline": "Tuesday",
            "evidence": "James: I will finalize the Android crash fix by Tuesday.",
        }
    ]


class ActionAgentTests(unittest.TestCase):
    def setUp(self):
        self.original_extract_action_items = action_agent_module.extract_action_items
        action_agent_module.extract_action_items = sample_gpt_action_items

    def tearDown(self):
        action_agent_module.extract_action_items = self.original_extract_action_items

    def test_agent_uses_gpt_action_items_only(self):
        result = run_action_agent(SAMPLE_TRANSCRIPT, {"overview": "Demo planning meeting."})

        self.assertEqual(len(result["action_items"]), 1)
        self.assertEqual(result["action_items"][0]["task"], "Finalize the Android crash fix")

    def test_agent_still_returns_risks(self):
        result = run_action_agent(SAMPLE_TRANSCRIPT, {"overview": "Demo planning meeting."})

        self.assertTrue(result["risks"])

    def test_risks_strip_speaker_labels(self):
        risks = extract_risks("**Speaker 1:** We need to have a security one in there.")

        self.assertEqual(risks, ["We need to have a security one in there."])


if __name__ == "__main__":
    unittest.main()
