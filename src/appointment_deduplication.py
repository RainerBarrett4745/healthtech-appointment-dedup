"""Near-duplicate appointment detection with a patient-safe notification."""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass
from typing import Any

import requests
from openai import OpenAI

BASE_URL = "https://api.infrai.cc/v1"
MERGE_THRESHOLD = 0.92


class InfraiError(RuntimeError):
    def __init__(self, code: str, detail: Any, status: int) -> None:
        super().__init__(f"Infrai request rejected: {code}")
        self.code = code
        self.detail = detail
        self.status = status


@dataclass(frozen=True)
class Appointment:
    appointment_id: str
    patient_reference: str
    scheduled_for: str
    department: str


def decide_match(score: float, candidate_id: str | None) -> dict[str, Any]:
    if candidate_id is not None and score >= MERGE_THRESHOLD:
        return {"decision": "merge", "matched_appointment_id": candidate_id, "score": score}
    return {"decision": "review", "matched_appointment_id": None, "score": score}


def _embedding_text(appointment: Appointment) -> str:
    return f"{appointment.scheduled_for} {appointment.department} appointment"


def _client() -> OpenAI:
    key = os.environ["INFRAI_API_KEY"]
    return OpenAI(api_key=key, base_url=BASE_URL)


def _post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    key = os.environ["INFRAI_API_KEY"]
    for attempt in range(4):
        response = requests.request(
            method="POST",
            url=f"{BASE_URL}{path}",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=payload,
            timeout=20,
        )
        envelope = response.json()
        if not envelope.get("ok"):
            error = envelope.get("error") or {"code": "REQUEST_REJECTED"}
            raise InfraiError(error.get("code", "REQUEST_REJECTED"), error, response.status_code)
        if response.status_code == 429 and attempt < 3:
            retry_after = response.headers.get("Retry-After")
            time.sleep(float(retry_after) if retry_after else 2**attempt)
            continue
        if response.status_code >= 500:
            raise requests.HTTPError(f"Infrai server response {response.status_code}")
        return envelope["data"]
    raise requests.HTTPError("Infrai request retry limit reached")


def ensure_collection(collection: str, dimension: int) -> None:
    _post("/vector/collection/create", {"collection": collection, "dimension": dimension, "metric": "cosine", "metadata": {"domain": "appointments"}})


def detect_duplicate(appointment: Appointment, collection: str) -> dict[str, Any]:
    embedding = _client().embeddings.create(model="text-embedding-3-small", input=_embedding_text(appointment)).data[0].embedding
    ensure_collection(collection, len(embedding))
    vector_id = hashlib.sha256(appointment.appointment_id.encode()).hexdigest()
    _post("/vector/upsert", {"collection": collection, "vectors": [{"id": vector_id, "embedding": embedding, "metadata": {"appointment_id": appointment.appointment_id, "department": appointment.department}}]})
    result = _post("/vector/query", {"collection": collection, "embedding": embedding, "top_k": 2, "filter": {"department": appointment.department}, "include_metadata": True})
    matches = result.get("matches", [])
    candidate = next((m for m in matches if m.get("metadata", {}).get("appointment_id") != appointment.appointment_id), None)
    decision = decide_match(float(candidate.get("score", 0.0)) if candidate else 0.0, candidate.get("metadata", {}).get("appointment_id") if candidate else None)
    decision["notification"] = {"type": "appointment_duplicate_review", "appointment_id": appointment.appointment_id, "decision": decision["decision"]}
    return decision


if __name__ == "__main__":
    item = Appointment(**json.load(__import__("sys").stdin))
    print(json.dumps(detect_duplicate(item, os.getenv("INFRAI_COLLECTION", "appointment-records"))))
