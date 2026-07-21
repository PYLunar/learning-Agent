"""
API tests for request validation and normalization.
"""

from fastapi.testclient import TestClient

from app import main


class DummyWorkflow:
    async def run(self, user_input: dict) -> dict:
        return {
            "status": "completed",
            "destination": user_input["destination"],
            "days": user_input["days"],
            "budget": user_input["budget"],
            "final_plan": f"# {user_input['destination']} {user_input['days']}天旅行计划",
            "final_plan_structured": {"overview": user_input},
            "logs": [],
            "errors": [],
        }


def test_plan_rejects_unsupported_destination():
    main._workflow = DummyWorkflow()
    client = TestClient(main.app)

    response = client.post(
        "/plan",
        json={
            "destination": "Tokyo",
            "days": 3,
            "budget": 5000,
            "origin": "北京",
            "preferences": ["food"],
        },
    )

    assert response.status_code == 400
    assert "目前仅支持国内城市旅行规划" in response.json()["detail"]


def test_plan_rejects_return_date_before_departure():
    main._workflow = DummyWorkflow()
    client = TestClient(main.app)

    response = client.post(
        "/plan",
        json={
            "destination": "成都",
            "budget": 5000,
            "origin": "北京",
            "travel_dates": {"departure": "2026-08-05", "return": "2026-08-01"},
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "返回日期不能早于出发日期"


def test_plan_calculates_days_from_dates():
    main._workflow = DummyWorkflow()
    client = TestClient(main.app)

    response = client.post(
        "/plan",
        json={
            "destination": "成都",
            "budget": 5000,
            "origin": "北京",
            "travel_dates": {"departure": "2026-08-01", "return": "2026-08-04"},
            "preferences": ["food", "culture"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["days"] == 4
    assert body["structured_data"]["overview"]["days"] == 4
