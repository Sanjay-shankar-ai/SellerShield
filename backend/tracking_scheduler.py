import asyncio
import datetime
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from .database import SessionLocal
from .models import Order, TrackingEvent, Setting, Conversation, Message, User
from .audit_log import log_audit_event
from .policy_engine import get_setting_value

# Stage transition definitions: (current_stage, next_stage, default_seconds, event_title, location, description)
STAGE_TRANSITIONS = [
    (
        "PLACED",
        "PACKED",
        1800,  # 30 mins
        "Order Packed & Sealed",
        "Central Fulfillment Hub, Whitefield",
        "Items verified, barcoded, and sealed with tamper-proof security tape."
    ),
    (
        "PACKED",
        "SHIPPED",
        10800,  # 3 hours
        "Dispatched on Linehaul Transit",
        "Bengaluru South Distribution Hub",
        "Package dispatched via Delhivery Express Air Cargo linehaul route."
    ),
    (
        "SHIPPED",
        "OUT_FOR_DELIVERY",
        86400,  # 24 hours
        "Out for Doorstep Delivery",
        "Local Delivery Hub, Sector 4",
        "Courier executive Ramesh (+91 98451 22100) is out for doorstep delivery."
    ),
    (
        "OUT_FOR_DELIVERY",
        "DELIVERED",
        21600,  # 6 hours
        "Delivered Successfully",
        "Customer Doorstep Address",
        "Delivered to recipient. 7-day return and doorstep size swap window is now active!"
    )
]

def get_scheduler_multiplier(db: Session) -> float:
    """Read demo speed multiplier from settings. Default 120.0 for smooth demo flow."""
    s = db.query(Setting).filter(Setting.key == "scheduler_demo_multiplier").first()
    if s:
        try:
            return float(s.value)
        except Exception:
            pass
    # If tracking_advance_interval_sec is configured small, compute effective multiplier
    inv = db.query(Setting).filter(Setting.key == "tracking_advance_interval_sec").first()
    if inv:
        try:
            sec = float(inv.value)
            if sec > 0:
                return max(1.0, 1800.0 / sec)  # Scales 30 mins to configured seconds
        except Exception:
            pass
    return 1.0  # Default to 1.0 (real-time/slow pace, not rapid auto-rush)

def post_proactive_chat_message(
    db: Session,
    customer_id: str,
    text: str,
    order_id: str,
    action_tag: str
):
    """Post an automatic proactive notification into the customer's ongoing chat thread."""
    conv = db.query(Conversation).filter(
        Conversation.customer_id == customer_id
    ).order_by(Conversation.updated_at.desc()).first()

    if not conv:
        conv = Conversation(customer_id=customer_id, options_offered="[]", declined_options="[]")
        db.add(conv)
        db.commit()
        db.refresh(conv)

    msg = Message(
        conversation_id=conv.id,
        sender="agent",
        text=text,
        tool_calls=f'[{{"tool": "{action_tag}", "status": "POSTED"}}]'
    )
    db.add(msg)
    conv.updated_at = datetime.datetime.utcnow()
    db.commit()

async def tracking_scheduler_loop():
    """
    Background worker advancing active orders strictly according to stage duration,
    posting proactive delay and early-delivery notifications.
    """
    while True:
        db: Session = SessionLocal()
        try:
            now = datetime.datetime.utcnow()
            multiplier = get_scheduler_multiplier(db)
            auto_advance_str = get_setting_value(db, "auto_advance_tracking", "false")
            auto_advance_enabled = str(auto_advance_str).strip().lower() == "true"

            # 1. Fetch active orders that are in transit pipeline
            active_orders = db.query(Order).filter(
                Order.status.in_(["PLACED", "PACKED", "SHIPPED", "OUT_FOR_DELIVERY"])
            ).all()

            for order in active_orders:
                # Initialize stage_entered_at if missing
                if not order.stage_entered_at:
                    order.stage_entered_at = order.created_at or now

                # Initialize expected_delivery_at if missing
                if not order.expected_delivery_at:
                    order.expected_delivery_at = (order.created_at or now) + datetime.timedelta(days=2)

                # Check for Proactive Delay Notification
                if (
                    now > order.expected_delivery_at
                    and order.status != "DELIVERED"
                    and not order.delay_notified
                ):
                    first_name = order.customer_name.split()[0]
                    new_eta = (now + datetime.timedelta(hours=18)).strftime("%b %d by %I:%M %p")
                    delay_msg = (
                        f"Hey {first_name}, a quick heads-up regarding order {order.order_number}: "
                        f"our linehaul courier experienced a slight weather delay on the highway. "
                        f"Your new estimated delivery is {new_eta}. We are tracking it closely for you!"
                    )
                    order.delay_notified = True
                    order.expected_delivery_at = now + datetime.timedelta(hours=18)
                    db.commit()

                    post_proactive_chat_message(
                        db=db,
                        customer_id=order.customer_id,
                        text=delay_msg,
                        order_id=order.id,
                        action_tag="proactive_delay_alert"
                    )

                    log_audit_event(
                        db=db,
                        actor="SYSTEM_SCHEDULER",
                        tool="tracking_scheduler.delay_alert",
                        input_payload={"order_number": order.order_number, "status": order.status},
                        output_payload={"new_eta": new_eta},
                        verdict="AUTO_APPROVE",
                        customer_id=order.customer_id,
                        order_id=order.id
                    )

                # If auto-advancement is disabled, admin has manual shipment authority
                if not auto_advance_enabled:
                    continue

                # Find current stage rule
                current_rule = next((r for r in STAGE_TRANSITIONS if r[0] == order.status), None)
                if not current_rule:
                    continue

                _, next_stage, default_secs, title, location, desc = current_rule
                required_secs = default_secs / max(1.0, multiplier)
                time_in_stage = (now - order.stage_entered_at).total_seconds()

                # Advance stage only when required minimum duration has elapsed
                if time_in_stage >= required_secs:
                    # Check for Early Delivery Notification
                    if (
                        next_stage in ("OUT_FOR_DELIVERY", "DELIVERED")
                        and order.expected_delivery_at
                        and now < (order.expected_delivery_at - datetime.timedelta(hours=6))
                        and not order.early_notified
                    ):
                        first_name = order.customer_name.split()[0]
                        early_msg = (
                            f"Great news, {first_name}! 🚀 Order {order.order_number} is moving faster "
                            f"than expected and is currently {next_stage.replace('_', ' ').lower()} ahead of schedule!"
                        )
                        order.early_notified = True
                        post_proactive_chat_message(
                            db=db,
                            customer_id=order.customer_id,
                            text=early_msg,
                            order_id=order.id,
                            action_tag="proactive_early_alert"
                        )
                        log_audit_event(
                            db=db,
                            actor="SYSTEM_SCHEDULER",
                            tool="tracking_scheduler.early_alert",
                            input_payload={"order_number": order.order_number, "status": next_stage},
                            output_payload={"early": True},
                            verdict="AUTO_APPROVE",
                            customer_id=order.customer_id,
                            order_id=order.id
                        )

                    # Strictly advance order stage
                    order.status = next_stage
                    order.stage_entered_at = now
                    if next_stage == "DELIVERED":
                        order.delivered_at = now

                    # Append immutable tracking event
                    event = TrackingEvent(
                        order_id=order.id,
                        status=next_stage,
                        title=title,
                        location=location,
                        description=desc,
                        created_at=now
                    )
                    db.add(event)
                    db.commit()

                    log_audit_event(
                        db=db,
                        actor="SYSTEM_SCHEDULER",
                        tool="tracking_scheduler.advance_stage",
                        input_payload={"order_number": order.order_number, "from": current_rule[0]},
                        output_payload={"to": next_stage, "location": location},
                        verdict="AUTO_APPROVE",
                        customer_id=order.customer_id,
                        order_id=order.id
                    )

        except Exception as e:
            print(f"[TrackingScheduler Error]: {e}")
        finally:
            db.close()

        # Tick interval: check every 5 seconds
        await asyncio.sleep(5)
