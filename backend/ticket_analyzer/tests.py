from django.test import TestCase
from rest_framework.test import APIClient


class TicketAnalyzerApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_health(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_wrong_transfer_analysis_matches_transaction(self):
        payload = {
            "ticket_id": "TKT-001",
            "complaint": "I sent 5000 taka to a wrong number around 2pm today.",
            "language": "en",
            "channel": "in_app_chat",
            "user_type": "customer",
            "transaction_history": [
                {
                    "transaction_id": "TXN-9101",
                    "timestamp": "2026-04-14T14:08:22Z",
                    "type": "transfer",
                    "amount": 5000,
                    "counterparty": "+8801719876543",
                    "status": "completed",
                }
            ],
        }

        response = self.client.post("/analyze-ticket", payload, format="json")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["ticket_id"], "TKT-001")
        self.assertEqual(body["relevant_transaction_id"], "TXN-9101")
        self.assertEqual(body["evidence_verdict"], "consistent")
        self.assertEqual(body["case_type"], "wrong_transfer")
        self.assertEqual(body["department"], "dispute_resolution")
        self.assertTrue(body["human_review_required"])

    def test_payment_failed_completed_status_is_inconsistent(self):
        payload = {
            "ticket_id": "TKT-002",
            "complaint": "My payment of 1200 failed but money was deducted.",
            "transaction_history": [
                {
                    "transaction_id": "TXN-2200",
                    "timestamp": "2026-04-14T15:12:00Z",
                    "type": "payment",
                    "amount": 1200,
                    "counterparty": "MRC-99",
                    "status": "completed",
                }
            ],
        }

        response = self.client.post("/analyze-ticket", payload, format="json")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["evidence_verdict"], "inconsistent")
        self.assertEqual(body["department"], "payments_ops")
        self.assertTrue(body["human_review_required"])

    def test_phishing_reply_uses_safe_official_channel_language(self):
        payload = {
            "ticket_id": "TKT-003",
            "complaint": "Someone called asking for my OTP and password for campaign bonus.",
            "transaction_history": [],
        }

        response = self.client.post("/analyze-ticket", payload, format="json")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["case_type"], "phishing_or_social_engineering")
        self.assertEqual(body["department"], "fraud_risk")
        self.assertEqual(body["severity"], "critical")
        self.assertNotIn("OTP", body["customer_reply"])
        self.assertNotIn("password", body["customer_reply"].lower())

    def test_missing_and_empty_fields(self):
        missing = self.client.post("/analyze-ticket", {"complaint": "help"}, format="json")
        empty = self.client.post("/analyze-ticket", {"ticket_id": "TKT-004", "complaint": ""}, format="json")

        self.assertEqual(missing.status_code, 400)
        self.assertEqual(empty.status_code, 422)
