"""
Integration tests for the Case Timeline router.

The timeline uses in-memory storage (_timelines dict) so no database
mocking is required. conftest.py clears the dict between tests automatically.
"""

import io
import pytest


# ─── Manual event management ──────────────────────────────────────────────────

class TestManualEvents:

    BASE_EVENT = {
        "client_name": "jane_doe",
        "event_type": "filing",
        "date": "2024-03-15",
        "description": "Filed I-485 Adjustment of Status application.",
        "receipt_number": None,
        "form_type": "I-485",
    }

    def test_add_event_returns_200(self, client):
        resp = client.post("/api/timeline/events/add", json=self.BASE_EVENT)
        assert resp.status_code == 200

    def test_add_event_response_contains_events_list(self, client):
        data = client.post("/api/timeline/events/add", json=self.BASE_EVENT).json()
        assert "events" in data
        assert isinstance(data["events"], list)
        assert len(data["events"]) == 1

    def test_add_event_description_preserved(self, client):
        data = client.post("/api/timeline/events/add", json=self.BASE_EVENT).json()
        assert data["events"][0]["description"] == self.BASE_EVENT["description"]

    def test_add_event_form_type_preserved(self, client):
        data = client.post("/api/timeline/events/add", json=self.BASE_EVENT).json()
        assert data["events"][0]["form_type"] == "I-485"

    def test_add_event_date_preserved(self, client):
        data = client.post("/api/timeline/events/add", json=self.BASE_EVENT).json()
        assert data["events"][0]["date"] == "2024-03-15"

    def test_add_rfe_event(self, client):
        rfe_event = {
            "client_name": "jane_doe",
            "event_type": "rfe_issued",
            "date": "2024-06-10",
            "description": "USCIS issued Request for Evidence for additional documents.",
            "receipt_number": "EAC2390012345",
            "form_type": "I-485",
        }
        data = client.post("/api/timeline/events/add", json=rfe_event).json()
        assert data["events"][0]["event_type"] == "rfe_issued"
        assert data["events"][0]["receipt_number"] == "EAC2390012345"

    def test_add_multiple_events_sorted_by_date(self, client):
        """Events added out of order should be returned sorted by date."""
        events = [
            {**self.BASE_EVENT, "date": "2024-09-01",
             "description": "Biometrics appointment attended.", "event_type": "biometrics"},
            {**self.BASE_EVENT, "date": "2024-03-15",
             "description": "I-485 filed.", "event_type": "filing"},
            {**self.BASE_EVENT, "date": "2024-05-20",
             "description": "Receipt notice received.", "event_type": "receipt"},
        ]
        for evt in events:
            client.post("/api/timeline/events/add", json=evt)

        data = client.get(f"/api/timeline/events/{self.BASE_EVENT['client_name']}").json()
        dates = [e["date"] for e in data["events"]]
        assert dates == sorted(dates)

    def test_get_empty_timeline(self, client):
        resp = client.get("/api/timeline/events/nonexistent_client")
        assert resp.status_code == 200
        data = resp.json()
        assert data["events"] == []

    def test_get_timeline_for_client(self, client):
        client.post("/api/timeline/events/add", json=self.BASE_EVENT)
        data = client.get(f"/api/timeline/events/{self.BASE_EVENT['client_name']}").json()
        assert len(data["events"]) == 1

    def test_client_isolation(self, client):
        """Events from different clients should not bleed into each other."""
        client.post("/api/timeline/events/add", json={**self.BASE_EVENT, "client_name": "alice"})
        client.post("/api/timeline/events/add", json={**self.BASE_EVENT, "client_name": "bob"})

        alice_data = client.get("/api/timeline/events/alice").json()
        bob_data = client.get("/api/timeline/events/bob").json()

        assert len(alice_data["events"]) == 1
        assert len(bob_data["events"]) == 1

    def test_event_without_date_is_valid(self, client):
        event = {**self.BASE_EVENT, "date": None}
        resp = client.post("/api/timeline/events/add", json=event)
        assert resp.status_code == 200


# ─── Timeline extraction from documents ──────────────────────────────────────

class TestTimelineExtraction:

    RECEIPT_NOTICE_TEXT = (
        "U.S. Citizenship and Immigration Services\n"
        "Receipt Notice\n"
        "Receipt Number: EAC2390012345\n"
        "Notice Date: March 15, 2024\n\n"
        "We have received your Form I-485 Adjustment of Status application."
    )

    def test_extract_from_txt_returns_200(self, client):
        resp = client.post(
            "/api/timeline/extract",
            files={"file": ("notice.txt", io.BytesIO(self.RECEIPT_NOTICE_TEXT.encode()), "text/plain")},
        )
        assert resp.status_code == 200

    def test_extract_detects_receipt_event(self, client):
        data = client.post(
            "/api/timeline/extract",
            files={"file": ("notice.txt", io.BytesIO(self.RECEIPT_NOTICE_TEXT.encode()), "text/plain")},
        ).json()
        event_types = [e["event_type"] for e in data["events"]]
        assert "receipt" in event_types

    def test_extract_captures_receipt_number(self, client):
        data = client.post(
            "/api/timeline/extract",
            files={"file": ("notice.txt", io.BytesIO(self.RECEIPT_NOTICE_TEXT.encode()), "text/plain")},
        ).json()
        assert data["receipt_number"] == "EAC2390012345"

    def test_extract_approval_notice(self, client):
        approval_text = (
            "U.S. Citizenship and Immigration Services\n"
            "Approval Notice\n"
            "Receipt Number: WAC2100099999\n\n"
            "Your petition has been approved."
        )
        data = client.post(
            "/api/timeline/extract",
            files={"file": ("approval.txt", io.BytesIO(approval_text.encode()), "text/plain")},
        ).json()
        event_types = [e["event_type"] for e in data["events"]]
        assert "approval" in event_types

    def test_extract_rfe_notice(self, client):
        rfe_text = (
            "U.S. Citizenship and Immigration Services\n"
            "Request for Evidence\n\n"
            "We need additional evidence to process your case. "
            "Please submit the requested documentation within 87 days."
        )
        data = client.post(
            "/api/timeline/extract",
            files={"file": ("rfe.txt", io.BytesIO(rfe_text.encode()), "text/plain")},
        ).json()
        event_types = [e["event_type"] for e in data["events"]]
        assert "rfe_issued" in event_types

    def test_extract_unsupported_file_type_returns_400(self, client):
        resp = client.post(
            "/api/timeline/extract",
            files={"file": ("scan.jpg", io.BytesIO(b"fake"), "image/jpeg")},
        )
        assert resp.status_code == 400

    def test_extract_with_client_name(self, client):
        data = client.post(
            "/api/timeline/extract",
            files={"file": ("notice.txt", io.BytesIO(self.RECEIPT_NOTICE_TEXT.encode()), "text/plain")},
            data={"client_name": "john_smith"},
        ).json()
        assert data["client_name"] == "john_smith"
