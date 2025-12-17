import asyncio
import json
import uuid

import httpx

OFFENSIVE_BASE = "http://127.0.0.1:8000"
DEFENSIVE_BASE = "http://127.0.0.1:8001"


def pretty(x: object) -> str:
    return json.dumps(x, indent=2, ensure_ascii=False)


async def reset(client: httpx.AsyncClient, base: str) -> None:
    rid = str(uuid.uuid4())
    await client.post(f"{base}/reset", headers={"X-Request-ID": rid})


async def get_inventory(client: httpx.AsyncClient, base: str) -> dict:
    rid = str(uuid.uuid4())
    r = await client.get(f"{base}/inventory", headers={"X-Request-ID": rid})
    try:
        return r.json()
    except Exception:
        return {"status_code": r.status_code, "text": r.text}


async def get_kitchen(client: httpx.AsyncClient, base: str) -> dict:
    rid = str(uuid.uuid4())
    r = await client.get(f"{base}/kitchen", headers={"X-Request-ID": rid})
    try:
        return r.json()
    except Exception:
        return {"status_code": r.status_code, "text": r.text}


async def post_order(client: httpx.AsyncClient, base: str, payload: dict, extra_headers: dict | None) -> tuple[int, dict]:
    rid = str(uuid.uuid4())
    headers = {"X-Request-ID": rid}
    if extra_headers:
        headers.update(extra_headers)
    r = await client.post(f"{base}/order", json=payload, headers=headers)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"text": r.text}


async def run_case(client: httpx.AsyncClient, title: str, payload: dict, extra_headers: dict | None = None) -> None:
    await reset(client, OFFENSIVE_BASE)
    await reset(client, DEFENSIVE_BASE)

    o_inv_before = await get_inventory(client, OFFENSIVE_BASE)
    d_inv_before = await get_inventory(client, DEFENSIVE_BASE)

    o_k_before = await get_kitchen(client, OFFENSIVE_BASE)
    d_k_before = await get_kitchen(client, DEFENSIVE_BASE)

    o_status, o_body = await post_order(client, OFFENSIVE_BASE, payload, extra_headers)
    d_status, d_body = await post_order(client, DEFENSIVE_BASE, payload, extra_headers)

    o_inv_after = await get_inventory(client, OFFENSIVE_BASE)
    d_inv_after = await get_inventory(client, DEFENSIVE_BASE)

    o_k_after = await get_kitchen(client, OFFENSIVE_BASE)
    d_k_after = await get_kitchen(client, DEFENSIVE_BASE)

    print("\n" + "=" * 90)
    print(title)
    print("- payload")
    print(pretty(payload))
    print("- headers")
    print(pretty(extra_headers or {}))

    print("\n- offensive")
    print(f"status={o_status}")
    print(pretty(o_body))
    print("inventory_before=" + pretty(o_inv_before))
    print("inventory_after =" + pretty(o_inv_after))
    print("kitchen_before  =" + pretty(o_k_before))
    print("kitchen_after   =" + pretty(o_k_after))

    print("\n- defensive")
    print(f"status={d_status}")
    print(pretty(d_body))
    print("inventory_before=" + pretty(d_inv_before))
    print("inventory_after =" + pretty(d_inv_after))
    print("kitchen_before  =" + pretty(d_k_before))
    print("kitchen_after   =" + pretty(d_k_after))


async def main() -> None:
    cases: list[tuple[str, dict, dict | None]] = [
        ("CASE 1: valid contract payload", {"customer_name": "Markus", "pizza": "margherita", "quantity": 1}, None),
        ("CASE 2: quantity wrong type (string)", {"customer_name": "Markus", "pizza": "margherita", "quantity": "10"}, None),
        ("CASE 3: unknown pizza", {"customer_name": "Markus", "pizza": "salmai", "quantity": 1}, None),
        ("CASE 4: sold out pizza", {"customer_name": "Markus", "pizza": "funghi", "quantity": 1}, None),
        ("CASE 5: typo field names + too large", {"name": "Markus", "pizaa": "salami", "anzahl": "99"}, None),
        ("CASE 6: extra field", {"customer_name": "Markus", "pizza": "margherita", "quantity": 1, "coupon": "FREE"}, None),
        (
            "CASE 7: forced kitchen fail (state consistency test)",
            {"customer_name": "Markus", "pizza": "margherita", "quantity": 1},
            {"X-Force-Kitchen-Fail": "1"},
        ),
    ]

    async with httpx.AsyncClient(timeout=5.0) as client:
        for title, payload, headers in cases:
            await run_case(client, title, payload, headers)


if __name__ == "__main__":
    asyncio.run(main())
