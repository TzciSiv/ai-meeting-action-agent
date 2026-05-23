import unittest

from backend.observability import (
    increment_counter,
    metrics_snapshot,
    prometheus_metrics,
    record_latency,
    record_http_request,
    reset_metrics,
    sanitize_fields,
    timed_operation,
)


class ObservabilityTests(unittest.TestCase):
    def setUp(self):
        reset_metrics()

    def tearDown(self):
        reset_metrics()

    def test_records_counters_and_latency(self):
        increment_counter("api.requests")
        record_latency("analysis.graph.run", 2.5)
        record_latency("analysis.graph.run", 1.5)

        snapshot = metrics_snapshot()

        self.assertEqual(snapshot["counters"]["api.requests"], 1)
        self.assertEqual(snapshot["latencies"]["analysis.graph.run"]["count"], 2)
        self.assertEqual(snapshot["latencies"]["analysis.graph.run"]["average_seconds"], 2.0)
        self.assertEqual(snapshot["latencies"]["analysis.graph.run"]["max_seconds"], 2.5)
        self.assertEqual(snapshot["sla_targets"]["scope"], "production_style_objectives")
        self.assertIn("prometheus", snapshot["integrations"])
        self.assertIn("opentelemetry", snapshot["integrations"])
        self.assertIn("summary", snapshot["models"])

    def test_timed_operation_records_success_and_failure(self):
        with timed_operation("demo.success", success_counter="demo.success.count"):
            pass

        with self.assertRaises(ValueError):
            with timed_operation("demo.failure", failure_counter="demo.failure.count"):
                raise ValueError("bad input")

        snapshot = metrics_snapshot()

        self.assertEqual(snapshot["counters"]["demo.success.count"], 1)
        self.assertEqual(snapshot["counters"]["demo.failure.count"], 1)
        self.assertEqual(snapshot["latencies"]["demo.success"]["count"], 1)
        self.assertEqual(snapshot["latencies"]["demo.failure"]["count"], 1)

    def test_sanitizes_sensitive_log_fields(self):
        fields = sanitize_fields(
            {
                "user_id": 1,
                "transcript": "private meeting text",
                "api_key": "secret",
                "authorization": "Bearer token",
                "source_content": "retrieved quote",
            }
        )

        self.assertEqual(fields["user_id"], 1)
        self.assertEqual(fields["transcript"], "[redacted]")
        self.assertEqual(fields["api_key"], "[redacted]")
        self.assertEqual(fields["authorization"], "[redacted]")
        self.assertEqual(fields["source_content"], "[redacted]")

    def test_prometheus_metrics_expose_runtime_counters(self):
        increment_counter("api.requests")
        record_http_request("GET", "/api/health", 200, 0.05)

        payload, content_type = prometheus_metrics()
        text = payload.decode("utf-8")

        self.assertIn("text/plain", content_type)
        self.assertIn("meeting_agent", text)
        self.assertIn("api.requests", text)


if __name__ == "__main__":
    unittest.main()
