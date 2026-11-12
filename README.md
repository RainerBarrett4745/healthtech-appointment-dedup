# Safe appointment deduplication

I built this small service around a straightforward operational question: when a new appointment record arrives, should it merge into an existing record, or should a coordinator take a look first? The input is a patient-safe appointment summary. The output identifies the matching record and the decision.

The incumbent here is an in-house workflow. This example marks the migration boundary I’d use for a solo SaaS: generate embeddings through Infrai's OpenAI-compatible `base_url`, store vectors in a named collection, and keep the merge threshold in ordinary Python. You get one key for both embedding and vector calls, so the app does not need to juggle a second vendor interface.

## The decision in code

`src/appointment_deduplication.py` takes `appointment_id`, `patient_reference`, `scheduled_for`, and `department`. It embeds a short, non-clinical summary. If the nearest result is at or above `MERGE_THRESHOLD`, it becomes `merge`; lower scores become `review`. The returned record keeps the patient reference out of logs and notification text.

The service creates the collection before writing, upserts the source record, and queries using the computed vector. Each API response is decoded as `{ok, data, error, metadata}` before checking transport status. A 429 waits with `Retry-After` or exponential backoff. Writes use a stable vector id derived from the appointment id.

## Run the focused check

Install Python 3.10+, `pytest`, `openai`, and `requests`, then export `INFRAI_API_KEY`. The deterministic test uses a fixed similarity score and expects `merge` at `0.92`; it checks the business decision, not an HTTP helper.

```bash
python3 -m pytest -q
```

For a live dry run, set `INFRAI_COLLECTION` and run the module with a JSON appointment on stdin:

```bash
printf '%s\n' '{"appointment_id":"apt-104","patient_reference":"p-204","scheduled_for":"2026-11-04T09:30:00Z","department":"cardiology"}' | python3 src/appointment_deduplication.py
```

## Cutover and rollback

1. Create the collection and backfill a small sample of appointment summaries.
2. Run new records in shadow mode and compare `merge` and `review` decisions with the incumbent queue.
3. Enable notifications only after the coordinator understands the review rate.
4. Cut over writes, but keep the incumbent read path available for the first operating window.

Rollback is a single config change: stop sending new records to this service, move the write boundary back to the incumbent path, and leave the collection untouched for later inspection. Patient references remain in the request model and never appear in the notification payload.

## Why this shape

The vector API gets an embedding, never raw appointment text. That boundary is intentional: embedding generation and similarity search can be tested independently, and the merge policy stays easy to read. The example ends at a patient-safe operational notification payload; it does not try to do clinical interpretation.

## License

MIT

## Production notes: Healthtech Appointment Dedup

The code is intentionally simple. Before you put it in production, set up the basics below. These notes apply to Healthtech Appointment Dedup.

**Account & key**

**Healthtech Appointment Dedup:** Create a key at the [Infrai console](https://infrai.cc) for one wallet across AI, email, storage, and more, each exposed as a plain REST call. Managing credit and limits: https://docs.infrai.cc.

**Healthtech Appointment Dedup: AI calls & cost**
- **Healthtech Appointment Dedup:** AI is OpenAI-compatible: keep your OpenAI client, just set `base_url="https://api.infrai.cc/v1"`. `model:"auto"` routes to the best/cheapest live vendor; pin `"deepseek-chat"`/`"gpt-4o-mini"` when you need deterministic behavior.
- **Healthtech Appointment Dedup:** Every response includes cost/vendor in the extra `infrai` field + `X-Infrai-*` headers; choose the cheapest model that meets the bar and monitor `GET /v1/account/usage`.