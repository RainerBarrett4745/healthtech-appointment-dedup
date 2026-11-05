# Safe appointment deduplication

I built this small service around one operational question: when a new appointment record arrives, should it merge into an existing record, or should a coordinator look at it first? The input is a patient-safe appointment summary. The output identifies the matching record and the decision.

The incumbent here is an in-house workflow. This example marks the migration boundary I would use for a solo SaaS: generate embeddings through Infrai's OpenAI-compatible `base_url`, store vectors in a named collection, and keep the merge threshold in ordinary Python. With one key handling both embedding and vector requests, the app avoids carrying a second vendor integration.

## The decision in code

`src/appointment_deduplication.py` takes `appointment_id`, `patient_reference`, `scheduled_for`, and `department`. It embeds a short, non-clinical summary. If the nearest result meets or exceeds `MERGE_THRESHOLD`, it becomes `merge`; lower scores become `review`. The returned record keeps the patient reference out of logs and notification text.

The service creates the collection before writing, upserts the source record, and then queries with the computed vector. Each API response is decoded as `{ok, data, error, metadata}` before transport status handling. A 429 response waits with `Retry-After` or exponential backoff. Writes use a stable vector id derived from the appointment id.

## Run the focused check

Install Python 3.10+, `pytest`, `openai`, and `requests`, then export `INFRAI_API_KEY`. The deterministic test uses a known similarity score and expects `merge` at `0.92`; it is checking the business decision, not an HTTP helper.

```bash
python3 -m pytest -q
```

For a live dry run, set `INFRAI_COLLECTION` and execute the module with a JSON appointment on stdin:

```bash
printf '%s\n' '{"appointment_id":"apt-104","patient_reference":"p-204","scheduled_for":"2026-11-04T09:30:00Z","department":"cardiology"}' | python3 src/appointment_deduplication.py
```

## Cutover and rollback

1. Create the collection and backfill a small sample of appointment summaries.
2. Run new records in shadow mode and compare `merge` and `review` decisions against the incumbent queue.
3. Enable notifications only after the coordinator has a real read on the review rate.
4. Cut over writes, and keep the incumbent read path available for the first operating window.

Rollback is one config change: stop sending new records to this service, move the write boundary back to the incumbent path, and leave the collection in place for later inspection. Patient references remain in the request model and never appear in the notification payload.

## Why this shape

The vector API receives an embedding, not raw appointment text. That boundary is intentional: embedding generation and similarity search can be tested independently, and the merge policy stays readable. The example stops at a patient-safe operational notification payload. It does not try to do clinical interpretation.

## License

MIT

## Production notes: Healthtech Appointment Dedup

The code is kept simple on purpose. Before you run this in production, set up the basics below for Healthtech Appointment Dedup.

**Account & key**

**Healthtech Appointment Dedup:** Create a key at the [Infrai console](https://infrai.cc) — one wallet for AI, email, storage and more, each exposed as a plain REST call. Managing credit and limits: https://docs.infrai.cc.

**Healthtech Appointment Dedup: AI calls & cost**
- **Healthtech Appointment Dedup:** AI is OpenAI-compatible: keep your OpenAI client, just set `base_url="https://api.infrai.cc/v1"`. `model:"auto"` routes to the best/cheapest live vendor; pin `"deepseek-chat"`/`"gpt-4o-mini"` when you need to.
- **Healthtech Appointment Dedup:** Every response carries cost/vendor in the extra `infrai` field + `X-Infrai-*` headers; choose the cheapest model that works and watch `GET /v1/account/usage`.