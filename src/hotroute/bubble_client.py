import json

import requests

from .config import Config


class BubbleClient:
    def __init__(self, config: Config):
        if not config.bubble_app_url or not config.bubble_api_token:
            raise RuntimeError(
                "BUBBLE_APP_URL and BUBBLE_API_TOKEN must be set in .env to use BubbleClient"
            )
        self._base_url = config.bubble_app_url
        self._session = requests.Session()
        self._session.headers["Authorization"] = f"Bearer {config.bubble_api_token}"

    def list(self, obj_type: str, constraints: list | None = None, cursor: int = 0, limit: int = 100) -> dict:
        """GET /api/1.1/obj/{type} — paginated search."""
        params = {"cursor": cursor, "limit": limit}
        if constraints:
            params["constraints"] = json.dumps(constraints)
        response = self._session.get(f"{self._base_url}/api/1.1/obj/{obj_type}", params=params, timeout=30)
        response.raise_for_status()
        return response.json()["response"]

    def find_one(self, obj_type: str, constraints: list) -> dict | None:
        results = self.list(obj_type, constraints=constraints, limit=1)
        matches = results["results"]
        return matches[0] if matches else None

    def list_all(self, obj_type: str, constraints: list | None = None) -> list[dict]:
        """Page through GET /api/1.1/obj/{type} until exhausted."""
        results = []
        cursor = 0
        while True:
            page = self.list(obj_type, constraints=constraints, cursor=cursor, limit=100)
            results.extend(page["results"])
            if page.get("remaining", 0) <= 0:
                break
            cursor += len(page["results"])
        return results

    def patch(self, obj_type: str, obj_id: str, data: dict) -> None:
        """PATCH /api/1.1/obj/{type}/{id} — partial update."""
        response = self._session.patch(f"{self._base_url}/api/1.1/obj/{obj_type}/{obj_id}", json=data, timeout=30)
        response.raise_for_status()

    def trigger_workflow(self, workflow_name: str, params: dict | None = None) -> dict:
        """POST /api/1.1/wf/{workflow_name} — run an API Workflow."""
        response = self._session.post(f"{self._base_url}/api/1.1/wf/{workflow_name}", json=params or {}, timeout=60)
        response.raise_for_status()
        return response.json()
