import datetime
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from .models import Order, TrackingEvent, User, Product, Setting

def get_return_window_days(db: Session) -> int:
    s = db.query(Setting).filter(Setting.key == "return_window_days").first()
    return int(s.value) if s else 7

def is_order_active(order: Order, return_window_days: int = 7) -> bool:
    """
    Active orders include:
    - In-transit orders: PLACED, PACKED, SHIPPED, OUT_FOR_DELIVERY
    - Recently delivered orders within return window (default 7 days)
    - Active exchange / return requested
    """
    if order.status in ("PLACED", "PACKED", "SHIPPED", "OUT_FOR_DELIVERY", "RETURN_REQUESTED", "EXCHANGED"):
        return True
    if order.status == "DELIVERED":
        delivered_date = order.delivered_at or order.created_at
        days_elapsed = (datetime.datetime.utcnow() - delivered_date).days
        return days_elapsed <= return_window_days
    return False

def get_customer_orders(
    db: Session,
    customer_id: str,
    include_past: bool = True
) -> Dict[str, Any]:
    """Return orders sorted by created_at descending, grouped into active and past."""
    orders = db.query(Order).filter(
        Order.customer_id == customer_id
    ).order_by(Order.created_at.desc()).all()

    return_window = get_return_window_days(db)
    active_list = []
    past_list = []

    for o in orders:
        if is_order_active(o, return_window):
            active_list.append(o)
        else:
            past_list.append(o)

    return {
        "active_orders": active_list,
        "past_orders": past_list,
        "all_orders": orders
    }

def get_order_by_id(db: Session, order_id: str, current_user: User) -> Order:
    order = db.query(Order).filter(
        (Order.id == order_id) | (Order.order_number == order_id)
    ).first()
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

    if current_user.role != "ADMIN" and order.customer_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access this order."
        )
    return order

def track_order(db: Session, order_id: str, current_user: User) -> Dict[str, Any]:
    order = get_order_by_id(db, order_id, current_user)
    events = db.query(TrackingEvent).filter(
        TrackingEvent.order_id == order.id
    ).order_by(TrackingEvent.created_at.asc()).all()

    latest_event = events[-1] if events else None
    expected_delivery_str = (
        order.expected_delivery_at.strftime("%b %d, %Y by %I:%M %p")
        if order.expected_delivery_at else "Within 2-3 business days"
    )

    return {
        "order_number": order.order_number,
        "current_stage": order.status,
        "status": order.status,
        "customer_name": order.customer_name,
        "order": {
            "id": order.id,
            "order_number": order.order_number,
            "status": order.status,
            "customer_name": order.customer_name,
            "total_amount": order.total_amount
        },
        "item_title": order.items[0].product_title if order.items else "Item",
        "total_amount": order.total_amount,
        "last_location": latest_event.location if latest_event else "Fulfillment Center",
        "last_update_time": latest_event.created_at.strftime("%b %d, %I:%M %p") if latest_event else "Just now",
        "expected_delivery": expected_delivery_str,
        "delivered_at": order.delivered_at.isoformat() if order.delivered_at else None,
        "created_at": order.created_at.isoformat(),
        "events": [
            {
                "id": ev.id,
                "status": ev.status,
                "title": ev.title,
                "location": ev.location,
                "description": ev.description,
                "timestamp": ev.created_at.strftime("%b %d, %I:%M %p")
            }
            for ev in events
        ]
    }
