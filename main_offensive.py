from __future__ import annotations

import logging
import threading
import time
import uuid
from enum import Enum
from typing import Dict, List

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("pizza.offensive")


class PizzaType(str, Enum):
    margherita = "margherita"
    salami = "salami"
    funghi = "funghi"


class DomainError(Exception):
    pass


class PizzaSoldOutError(DomainError):
    pass


class NotEnoughInventoryError(DomainError):
    pass


class KitchenDownError(DomainError):
    pass


class OrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    customer_name: StrictStr = Field(..., min_length=1, max_length=60)
    pizza: PizzaType
    quantity: StrictInt = Field(..., gt=0, le=20)


class OrderResponse(BaseModel):
    request_id: str
    accepted: bool
    customer_name: str
    pizza: PizzaType
    quantity: int
    remaining_stock: int


class Ticket(BaseModel):
    request_id: str
    customer_name: str
    pizza: PizzaType
    quantity: int


class InventoryDB:
    def __init__(self, initial: Dict[PizzaType, int]) -> None:
        self._lock = threading.Lock()
        self._initial: Dict[PizzaType, int] = dict(initial)
        self._stock: Dict[PizzaType, int] = dict(initial)

    def snapshot(self) -> Dict[PizzaType, int]:
        with self._lock:
            return dict(self._stock)

    def reset(self) -> Dict[PizzaType, int]:
        with self._lock:
            self._stock = dict(self._initial)
            return dict(self._stock)

    def reserve(self, pizza: PizzaType, quantity: int, request_id: str) -> int:
        with self._lock:
            available = self._stock.get(pizza, 0)
            logger.debug(
                "inventory_check | rid=%s | pizza=%s | available=%s | requested=%s",
                request_id,
                pizza.value,
                available,
                quantity,
            )

            if available <= 0:
                raise PizzaSoldOutError(f"pizza_sold_out: {pizza.value}")

            if quantity > available:
                raise NotEnoughInventoryError(
                    f"insufficient_inventory: pizza={pizza.value} requested={quantity} available={available}"
                )

            before = available
            self._stock[pizza] = available - quantity
            after = self._stock[pizza]

            logger.info(
                "inventory_reserved | rid=%s | pizza=%s | qty=%s | before=%s | after=%s",
                request_id,
                pizza.value,
                quantity,
                before,
                after,
            )
            return after

    def release(self, pizza: PizzaType, quantity: int, request_id: str) -> int:
        with self._lock:
            before = self._stock.get(pizza, 0)
            self._stock[pizza] = before + quantity
            after = self._stock[pizza]
            logger.warning(
                "inventory_rollback | rid=%s | pizza=%s | qty=%s | before=%s | after=%s",
                request_id,
                pizza.value,
                quantity,
                before,
                after,
            )
            return after


class KitchenQueue:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tickets: List[Ticket] = []

    def reset(self) -> None:
        with self._lock:
            self._tickets = []

    def snapshot(self) -> List[Ticket]:
        with self._lock:
            return list(self._tickets)

    def submit(self, ticket: Ticket, request_id: str, force_fail: bool) -> None:
        logger.debug("kitchen_submit_attempt | rid=%s | force_fail=%s", request_id, force_fail)
        if force_fail:
            raise KitchenDownError("kitchen_down")
        with self._lock:
            self._tickets.append(ticket)
        logger.info(
            "kitchen_submit_ok | rid=%s | customer=%s | pizza=%s | qty=%s",
            request_id,
            ticket.customer_name,
            ticket.pizza.value,
            ticket.quantity,
        )


class OrderService:
    def __init__(self, inventory: InventoryDB, kitchen: KitchenQueue) -> None:
        self._inventory = inventory
        self._kitchen = kitchen

    def place_order(self, order: OrderRequest, request_id: str, force_kitchen_fail: bool) -> OrderResponse:
        logger.info(
            "place_order_start | rid=%s | customer=%s | pizza=%s | qty=%s",
            request_id,
            order.customer_name,
            order.pizza.value,
            order.quantity,
        )

        remaining = self._inventory.reserve(order.pizza, int(order.quantity), request_id)

        ticket = Ticket(
            request_id=request_id,
            customer_name=str(order.customer_name),
            pizza=order.pizza,
            quantity=int(order.quantity),
        )

        try:
            self._kitchen.submit(ticket, request_id=request_id, force_fail=force_kitchen_fail)
        except KitchenDownError:
            self._inventory.release(order.pizza, int(order.quantity), request_id)
            raise

        time.sleep(0.02)

        logger.info(
            "place_order_ok | rid=%s | customer=%s | pizza=%s | qty=%s | remaining=%s",
            request_id,
            order.customer_name,
            order.pizza.value,
            order.quantity,
            remaining,
        )

        return OrderResponse(
            request_id=request_id,
            accepted=True,
            customer_name=str(order.customer_name),
            pizza=order.pizza,
            quantity=int(order.quantity),
            remaining_stock=remaining,
        )


app = FastAPI(title="Pizza API (Offensive)")

inventory = InventoryDB(
    {
        PizzaType.margherita: 3,
        PizzaType.salami: 1,
        PizzaType.funghi: 0,
    }
)
kitchen = KitchenQueue()
service = OrderService(inventory, kitchen)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    rid = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.request_id = rid

    logger.info("request_start | rid=%s | %s %s", rid, request.method, request.url.path)

    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception as exc:
        dur_ms = int((time.perf_counter() - start) * 1000)
        logger.exception("request_error | rid=%s | duration_ms=%s | exc=%r", rid, dur_ms, exc)
        raise

    dur_ms = int((time.perf_counter() - start) * 1000)
    response.headers["X-Request-ID"] = rid
    logger.info(
        "request_end | rid=%s | status=%s | duration_ms=%s",
        rid,
        getattr(response, "status_code", "n/a"),
        dur_ms,
    )
    return response


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    rid = getattr(request.state, "request_id", "n/a")
    logger.warning("validation_error | rid=%s | errors=%s", rid, exc.errors())
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"request_id": rid, "detail": exc.errors()},
    )


@app.exception_handler(PizzaSoldOutError)
async def sold_out_handler(request: Request, exc: PizzaSoldOutError):
    rid = getattr(request.state, "request_id", "n/a")
    logger.warning("domain_error | rid=%s | type=sold_out | msg=%s", rid, str(exc))
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"request_id": rid, "error": "sold_out", "message": str(exc)},
    )


@app.exception_handler(NotEnoughInventoryError)
async def not_enough_handler(request: Request, exc: NotEnoughInventoryError):
    rid = getattr(request.state, "request_id", "n/a")
    logger.warning("domain_error | rid=%s | type=insufficient_inventory | msg=%s", rid, str(exc))
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"request_id": rid, "error": "insufficient_inventory", "message": str(exc)},
    )


@app.exception_handler(KitchenDownError)
async def kitchen_down_handler(request: Request, exc: KitchenDownError):
    rid = getattr(request.state, "request_id", "n/a")
    logger.error("domain_error | rid=%s | type=kitchen_down | msg=%s", rid, str(exc))
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"request_id": rid, "error": "kitchen_down", "message": str(exc)},
    )


@app.post("/order", response_model=OrderResponse)
async def create_order(order: OrderRequest, request: Request):
    rid = getattr(request.state, "request_id", "n/a")
    force_kitchen_fail = request.headers.get("X-Force-Kitchen-Fail", "") == "1"
    logger.debug("order_received | rid=%s | payload=%s | force_kitchen_fail=%s", rid, order.model_dump(), force_kitchen_fail)
    return service.place_order(order, rid, force_kitchen_fail)


@app.get("/inventory")
async def get_inventory(request: Request):
    rid = getattr(request.state, "request_id", "n/a")
    snap = inventory.snapshot()
    logger.info("inventory_read | rid=%s | %s", rid, snap)
    return {"request_id": rid, "inventory": {k.value: v for k, v in snap.items()}}


@app.get("/kitchen")
async def get_kitchen(request: Request):
    rid = getattr(request.state, "request_id", "n/a")
    tickets = kitchen.snapshot()
    logger.info("kitchen_read | rid=%s | tickets=%s", rid, len(tickets))
    return {"request_id": rid, "tickets": [t.model_dump() for t in tickets]}


@app.post("/reset")
async def reset_all(request: Request):
    rid = getattr(request.state, "request_id", "n/a")
    snap = inventory.reset()
    kitchen.reset()
    logger.info("reset_ok | rid=%s | inventory=%s | tickets=0", rid, snap)
    return {"request_id": rid, "inventory": {k.value: v for k, v in snap.items()}, "tickets": []}
