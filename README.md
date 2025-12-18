# Defensive Programming

Two FastAPI apps that model the same pizza ordering workflow with opposite philosophies:
- `main_offensive.py` is strict: validated inputs, explicit error responses, and consistent state changes.
- `main_defensive.py` is lenient: swallows errors, tries to autocorrect payloads, and prefers returning 200 responses.

The repository exists to demonstrate how different error-handling strategies affect reliability, observability, and client experience.

## Quickstart
Prerequisites: Python 3.11+ and [uv](https://docs.astral.sh/uv/getting-started/installation/) installed.

```bash
uv venv
uv sync
```

Start both APIs in separate terminals:
- Offensive API: `uv run uvicorn main_offensive:app --port 8000`
- Defensive API: `uv run uvicorn main_defensive:app --port 8001`

Optional comparison run:
```bash
uv run python client.py
```

## Endpoints
Both services expose the same basic endpoints:
- `POST /order` creates an order.
- `GET /inventory` shows current stock.
- `GET /kitchen` shows queued tickets.
- `POST /reset` resets inventory and clears the kitchen queue.

Behavior diverges under invalid input or failures:
- Offensive API rejects malformed payloads (422), sold-out items (409), and kitchen outages (503) while keeping state consistent.
- Defensive API tries to make the request succeed anyway: it guesses field names, caps quantities, swaps in available pizzas, and may ignore backend errors.

To simulate a kitchen outage, add the header `X-Force-Kitchen-Fail: 1` to the `/order` request.

## Using the comparison client
`client.py` runs a handful of scenarios against both services, resets state between cases, and prints side-by-side results. It is a quick way to see how the two philosophies behave with:
- Valid payloads.
- Typos in field names.
- Unsupported pizzas.
- Quantity type mismatches.
- Forced downstream failures.

Run it with `uv run python client.py` after both servers are up.

## Observing the difference
- The offensive app uses Pydantic validation, typed domain models, and explicit exception handlers, so failures are loud and traceable.
- The defensive app logs a lot but returns 200 OK in many error cases, making client-facing behavior look successful even when the system state is questionable.

Use the request IDs in the responses (or the `X-Request-ID` header you pass in) to correlate logs across calls. A few minutes of experimenting with `curl` or the provided client will show how defensive programming can hide problems while offensive programming surfaces them early.
