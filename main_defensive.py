from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("pizza.defensive")

INITIAL_INVENTORY: Dict[str, int] = {"margherita": 3, "salami": 1, "funghi": 0}
INVENTORY: Dict[str, int] = dict(INITIAL_INVENTORY)

PIZZA_CATALOG: Dict[str, Dict[str, Any]] = {
    "margherita": {"name": "margherita", "price": 7.5},
    "salami": {"name": "salami", "price": 8.5},
    "funghi": {"name": "funghi", "price": 8.0},
}

KITCHEN_QUEUE: list[dict[str, Any]] = []

app = FastAPI(title="Pizza API (Defensive)")


def lookup_pizza_info(pizza_key: str) -> Optional[Dict[str, Any]]:
    return PIZZA_CATALOG.get(pizza_key)


def submit_ticket(ticket: Dict[str, Any], force_fail: bool) -> None:
    if force_fail:
        raise RuntimeError("kitchen_printer_offline")
    KITCHEN_QUEUE.append(ticket)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    rid = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.request_id = rid

    logger.info("request_start | rid=%s | %s %s", rid, request.method, request.url.path)

    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception as exc:
        logger.error("middleware_swallowed_exception | rid=%s | exc=%r", rid, exc)
        response = JSONResponse(status_code=200, content={"ok": True, "rid": rid, "note": "handled"})
    dur_ms = int((time.perf_counter() - start) * 1000)

    response.headers["X-Request-ID"] = rid
    logger.info("request_end | rid=%s | status=%s | duration_ms=%s", rid, response.status_code, dur_ms)
    return response


@app.get("/inventory")
async def get_inventory(request: Request):
    rid = getattr(request.state, "request_id", "n/a")
    logger.info("inventory_read | rid=%s | %s", rid, INVENTORY)
    return {"rid": rid, "inventory": dict(INVENTORY)}


@app.get("/kitchen")
async def get_kitchen(request: Request):
    rid = getattr(request.state, "request_id", "n/a")
    logger.info("kitchen_read | rid=%s | tickets=%s", rid, len(KITCHEN_QUEUE))
    return {"rid": rid, "tickets": list(KITCHEN_QUEUE)}


@app.post("/reset")
async def reset_all(request: Request):
    rid = getattr(request.state, "request_id", "n/a")
    INVENTORY.clear()
    INVENTORY.update(INITIAL_INVENTORY)
    KITCHEN_QUEUE.clear()
    logger.info("reset_ok | rid=%s | inventory=%s | tickets=0", rid, INVENTORY)
    return {"rid": rid, "inventory": dict(INVENTORY), "tickets": list(KITCHEN_QUEUE)}


@app.post("/order")
async def create_order(request: Request):
    rid = getattr(request.state, "request_id", "n/a")

    try:
        payload: Any = await request.json()
        logger.debug("raw_payload | rid=%s | %r", rid, payload)
    except Exception as exc:
        logger.error("json_parse_failed_swallowed | rid=%s | exc=%r", rid, exc)
        payload = {}

    try:
        customer_name = "anonymous"
        if isinstance(payload, dict):
            n1 = payload.get("customer_name")
            n2 = payload.get("name")
            n3 = payload.get("customer")
            if isinstance(n1, str) and n1.strip():
                customer_name = n1.strip()
            elif isinstance(n2, str) and n2.strip():
                customer_name = n2.strip()
            elif isinstance(n3, str) and n3.strip():
                customer_name = n3.strip()
        logger.info("customer_name_resolved | rid=%s | name=%s", rid, customer_name)
    except Exception as exc:
        logger.error("customer_name_failed_swallowed | rid=%s | exc=%r", rid, exc)
        customer_name = "anonymous"

    try:
        pizza_name = payload.pizza
        logger.info("pizza_attr_access | rid=%s | pizza=%s", rid, pizza_name)
    except Exception as exc:
        logger.warning("pizza_attr_access_failed_swallowed | rid=%s | exc=%r", rid, exc)
        try:
            pizza_name = "margherita"
            if isinstance(payload, dict):
                p1 = payload.get("pizza")
                p2 = payload.get("pizza_name")
                if isinstance(p1, str) and p1.strip():
                    pizza_name = p1.strip()
                elif isinstance(p2, str) and p2.strip():
                    pizza_name = p2.strip()
        except Exception as exc2:
            logger.error("pizza_fallback_failed_swallowed | rid=%s | exc=%r", rid, exc2)
            pizza_name = "margherita"
        logger.info("pizza_resolved | rid=%s | pizza=%s", rid, pizza_name)

    try:
        qty_input: Any = None
        if isinstance(payload, dict):
            if "quantity" in payload:
                qty_input = payload.get("quantity")
            else:
                qty_input = None
            if qty_input is None:
                if "anzahl" in payload:
                    qty_input = payload.get("anzahl")
                else:
                    qty_input = None
        else:
            qty_input = None

        quantity = 1

        if isinstance(qty_input, int):
            quantity = qty_input
        else:
            if isinstance(qty_input, float):
                quantity = int(qty_input)
            else:
                if isinstance(qty_input, str):
                    s = qty_input.strip()
                    if s.isdigit():
                        quantity = int(s)
                    else:
                        logger.warning("quantity_str_invalid | rid=%s | val=%r", rid, qty_input)
                        quantity = 1
                else:
                    if qty_input is None:
                        quantity = 1
                    else:
                        logger.warning("quantity_wrong_type | rid=%s | type=%s", rid, type(qty_input).__name__)
                        quantity = 1

        if quantity <= 0:
            quantity = 1
        if quantity > 20:
            quantity = 20

        logger.info("quantity_resolved | rid=%s | qty=%s", rid, quantity)
    except Exception as exc:
        logger.error("quantity_failed_swallowed | rid=%s | exc=%r", rid, exc)
        quantity = 1

    try:
        pizza_key = str(pizza_name)

        if pizza_key not in INVENTORY:
            logger.warning("unknown_pizza_swallowed | rid=%s | pizza=%s", rid, pizza_key)
            pizza_key = "margherita"

        available = INVENTORY.get(pizza_key, 0)
        logger.info("inventory_seen | rid=%s | pizza=%s | available=%s", rid, pizza_key, available)

        if available <= 0:
            logger.warning("sold_out_swallowed | rid=%s | pizza=%s", rid, pizza_key)
            replacement = None
            for k, v in INVENTORY.items():
                if v > 0:
                    replacement = k
                    break
            if replacement is not None:
                logger.warning("replacement_selected | rid=%s | from=%s | to=%s", rid, pizza_key, replacement)
                pizza_key = replacement
                available = INVENTORY.get(pizza_key, 0)
            else:
                logger.error("no_inventory_left_but_ok | rid=%s", rid)
                return {"ok": True, "rid": rid, "customer": customer_name, "note": "handled"}

        if quantity > available:
            logger.warning(
                "quantity_reduced_swallowed | rid=%s | pizza=%s | requested=%s | available=%s",
                rid,
                pizza_key,
                quantity,
                available,
            )
            quantity = available

        price = 0.0
        try:
            info = lookup_pizza_info(pizza_key)
            price = float(info["price"])
        except Exception as exc:
            logger.warning("price_lookup_failed_swallowed | rid=%s | pizza=%s | exc=%r", rid, pizza_key, exc)
            price = 0.0

        before = INVENTORY.get(pizza_key, 0)
        INVENTORY[pizza_key] = max(0, before - quantity)
        after = INVENTORY[pizza_key]

        logger.info(
            "inventory_decremented | rid=%s | pizza=%s | qty=%s | before=%s | after=%s",
            rid,
            pizza_key,
            quantity,
            before,
            after,
        )

        force_kitchen_fail = request.headers.get("X-Force-Kitchen-Fail", "") == "1"
        ticket = {"rid": rid, "customer": customer_name, "pizza": pizza_key, "quantity": quantity, "total": price * quantity}

        try:
            submit_ticket(ticket, force_fail=force_kitchen_fail)
            logger.info("kitchen_submit_ok | rid=%s | force_fail=%s", rid, force_kitchen_fail)
        except Exception as exc:
            logger.error("kitchen_submit_failed_swallowed | rid=%s | exc=%r", rid, exc)

        return {
            "ok": True,
            "rid": rid,
            "customer": customer_name,
            "pizza": pizza_key,
            "quantity": quantity,
            "remaining_stock": after,
            "total": price * quantity,
            "note": "handled",
        }

    except Exception as exc:
        logger.error("order_failed_but_swallowed | rid=%s | exc=%r", rid, exc)
        return {"ok": True, "rid": rid, "note": "handled"}
