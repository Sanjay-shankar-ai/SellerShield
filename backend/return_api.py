import datetime
import json
import uuid
from typing import Dict, Any, List
from sqlalchemy.orm import Session
from .models import Order, Product, TrackingEvent, User
from .audit_log import log_audit_event

def list_alternatives(db: Session, product_id: str, target_size: str = None) -> List[Dict[str, Any]]:
    prod = db.query(Product).filter(Product.id == product_id).first()
    if not prod:
        return []

    results = []
    # If product has sizes
    if prod.sizes:
        try:
            available_sizes = json.loads(prod.sizes)
            for s in available_sizes:
                if prod.stock_count > 0:
                    results.append({
                        "product_id": prod.id,
                        "title": prod.title,
                        "size": s,
                        "price": prod.price,
                        "in_stock": True,
                        "stock_count": prod.stock_count
                    })
        except Exception:
            pass

    # Other in-stock products in same category
    similars = db.query(Product).filter(
        Product.category == prod.category,
        Product.id != prod.id,
        Product.stock_count > 0
    ).limit(2).all()

    for sim in similars:
        results.append({
            "product_id": sim.id,
            "title": sim.title,
            "size": "Standard",
            "price": sim.price,
            "in_stock": True,
            "stock_count": sim.stock_count
        })

    return results

def reserve_stock(
    db: Session,
    product_id: str,
    size: str = None,
    quantity: int = 1
) -> bool:
    """Check availability and reserve product inventory for exchange/order."""
    prod = db.query(Product).filter(Product.id == product_id).first()
    if not prod:
        return False
    if prod.stock_count < quantity:
        return False
    prod.stock_count -= quantity
    db.commit()
    return True

def create_exchange(
    db: Session,
    order: Order,
    new_size: str = None,
    reason: str = "Doorstep size exchange",
    reason_category: str = "Size / fit issue",
    evidence_status: str = "NONE",
    replacement_product_id: str = None,
    actor: str = "AI_AGENT"
) -> Dict[str, Any]:
    """Execute doorstep exchange: reserves stock and books delivery in 2 days."""
    if not reason_category:
        raise ValueError("Missing required field: reason_category must be provided.")

    if reason_category in ("Damaged on arrival", "Defective or not working", "Wrong item"):
        if evidence_status != "VERIFIED" and actor != "ADMIN":
            raise ValueError(f"Evidence must be VERIFIED for damage/defect exchange (current: {evidence_status})")

    # Reserve inventory for the exchange item
    target_prod_id = replacement_product_id
    if not target_prod_id and order.items:
        target_prod_id = order.items[0].product_id

    if target_prod_id:
        reserved = reserve_stock(db, target_prod_id, new_size, 1)
        if not reserved:
            raise ValueError("Requested exchange item or size is out of stock.")

    order.status = "EXCHANGED"
    order.return_reason = f"Exchanged: {reason}. Size: {new_size or 'Standard'}"
    order.reason_category = reason_category
    order.evidence_status = evidence_status

    # Add doorstep exchange tracking event (2 days delivery)
    awb = f"AWB-EXCH-{uuid.uuid4().hex[:6].upper()}"
    ev = TrackingEvent(
        order_id=order.id,
        status="EXCHANGED",
        title="Doorstep Exchange Scheduled",
        location="Fulfillment Logistics Hub",
        description=f"Exchange booked (AWB: {awb}). Doorstep delivery in 2 days. The courier will deliver your replacement and collect the current item together."
    )
    db.add(ev)
    db.commit()

    log_audit_event(
        db=db,
        actor=actor,
        tool="return_api.create_exchange",
        input_payload={
            "order_number": order.order_number,
            "new_size": new_size,
            "reason": reason,
            "reason_category": reason_category,
            "replacement_product_id": target_prod_id
        },
        output_payload={"status": "EXCHANGED", "awb": awb, "delivery_eta": "2 days"},
        verdict="AUTO_APPROVE",
        customer_id=order.customer_id,
        order_id=order.id,
        idempotency_key=f"exchange-{order.id}"
    )

    return {
        "success": True,
        "action": "EXCHANGE_CONFIRMED",
        "new_size": new_size,
        "awb": awb,
        "delivery_eta_days": 2,
        "message": f"All set! Your doorstep exchange has been booked (AWB: {awb}). Delivery will arrive within 2 days. Our courier will hand over the replacement and collect the current item simultaneously."
    }

def create_return(
    db: Session,
    order: Order,
    reason: str,
    actor: str = "AI_AGENT"
) -> Dict[str, Any]:
    order.status = "RETURN_REQUESTED"
    order.return_reason = reason

    awb = f"AWB-RET-{uuid.uuid4().hex[:6].upper()}"
    ev = TrackingEvent(
        order_id=order.id,
        status="RETURN_REQUESTED",
        title="Return Pickup Booked",
        location="Doorstep Address",
        description=f"Reverse pickup booked under tracking {awb}. Please keep the item in original condition with tags intact."
    )
    db.add(ev)
    db.commit()

    log_audit_event(
        db=db,
        actor=actor,
        tool="return_api.create_return",
        input_payload={"order_number": order.order_number, "reason": reason},
        output_payload={"status": "RETURN_REQUESTED", "awb": awb},
        verdict="AUTO_APPROVE",
        customer_id=order.customer_id,
        order_id=order.id,
        idempotency_key=f"return-{order.id}"
    )

    return {
        "success": True,
        "action": "RETURN_BOOKED",
        "awb": awb,
        "message": f"Return pickup scheduled for tomorrow under tracking {awb}."
    }


def cancel_order(
    db: Session,
    order: Order,
    reason: str = "Customer requested cancellation",
    actor: str = "AI_AGENT"
) -> Dict[str, Any]:
    """Cancel an order if it hasn't shipped yet, restoring product stock."""
    if order.status in ("CANCELLED", "REFUNDED"):
        return {
            "success": False,
            "action": "ALREADY_CANCELLED",
            "message": f"Order {order.order_number} is already {order.status.lower()}."
        }

    if order.status in ("SHIPPED", "OUT_FOR_DELIVERY"):
        return {
            "success": False,
            "action": "IN_TRANSIT",
            "message": f"Order {order.order_number} has already shipped ({order.status.replace('_', ' ').lower()}) and is with the courier. Please decline the parcel at delivery and your refund will process automatically once it heads back."
        }

    if order.status == "DELIVERED":
        return {
            "success": False,
            "action": "ALREADY_DELIVERED",
            "message": f"Order {order.order_number} was already delivered, so we'll process a return rather than a cancellation."
        }

    # PLACED or PACKED -> cancel cleanly and restore stock
    order.status = "CANCELLED"
    order.return_reason = reason

    for item in order.items:
        prod = db.query(Product).filter(Product.id == item.product_id).first()
        if prod:
            prod.stock_count += item.quantity

    ev = TrackingEvent(
        order_id=order.id,
        status="CANCELLED",
        title="Order Cancelled",
        location="Fulfillment Center",
        description=f"Order cancelled before dispatch. Reason: {reason}. {'Refund initiated to original UPI.' if order.payment_method == 'MOCK_UPI' else 'COD order cancelled with no charge.'}"
    )
    db.add(ev)
    db.commit()

    log_audit_event(
        db=db,
        actor=actor,
        tool="return_api.cancel_order",
        input_payload={"order_number": order.order_number, "reason": reason},
        output_payload={"status": "CANCELLED"},
        verdict="AUTO_APPROVE",
        customer_id=order.customer_id,
        order_id=order.id,
        idempotency_key=f"cancel-{order.id}"
    )

    return {
        "success": True,
        "action": "CANCELLED",
        "message": f"Done! Order {order.order_number} has been cancelled before dispatch. {'Your UPI refund of ₹' + str(int(order.total_amount)) + ' has been initiated.' if order.payment_method == 'MOCK_UPI' else 'Since it was Cash on Delivery, nothing was charged.'}"
    }
