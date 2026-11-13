import datetime
import json
import uuid
from typing import Optional, Dict, Any, Tuple, List
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from .models import User, Plan, Subscription, Invoice, AuditLog
from .audit_log import log_audit_event

# In-memory sliding-window rate limiter for sensitive auth and payment endpoints
# Maps (key, action) -> list of timestamp floats
_RATE_LIMIT_STORE: Dict[str, List[float]] = {}

def check_rate_limit(key: str, action: str, max_requests: int = 10, window_seconds: int = 60):
    """
    In-memory rate limiter. Raises 429 if request count exceeds max_requests within window_seconds.
    """
    now = datetime.datetime.utcnow().timestamp()
    limit_key = f"{action}:{key}"
    timestamps = _RATE_LIMIT_STORE.get(limit_key, [])
    # Filter out timestamps older than window
    cutoff = now - window_seconds
    timestamps = [ts for ts in timestamps if ts > cutoff]
    if len(timestamps) >= max_requests:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many requests for {action}. Please try again in a few moments."
        )
    timestamps.append(now)
    _RATE_LIMIT_STORE[limit_key] = timestamps

def get_or_create_admin_subscription(admin: User, db: Session) -> Subscription:
    """
    Retrieves admin's active subscription, or creates default Starter / Trial if none exists.
    """
    sub = db.query(Subscription).filter(Subscription.admin_id == admin.id).first()
    if not sub:
        now = datetime.datetime.utcnow()
        sub = Subscription(
            admin_id=admin.id,
            plan_id="starter",
            status="active",
            billing_cycle="monthly",
            started_at=now,
            renew_at=now + datetime.timedelta(days=30),
            trial_ends_at=None,
            chats_used=0,
            cancel_at_period_end=False
        )
        db.add(sub)
        db.commit()
        db.refresh(sub)
    return sub

def check_and_expire_subscription(sub: Subscription, db: Session) -> Subscription:
    """
    Checks and expires trials/subscriptions with a 3-day grace period before downgrading to Starter.
    """
    now = datetime.datetime.utcnow()
    changed = False

    # 1. Trial Expiration
    if sub.status in ("trial", "past_due") and sub.trial_ends_at:
        if now > sub.trial_ends_at:
            grace_period_end = sub.trial_ends_at + datetime.timedelta(days=3)
            if now > grace_period_end:
                # Downgrade to Starter after 3-day grace period
                prev_plan = sub.plan_id
                sub.plan_id = "starter"
                sub.status = "active"
                sub.trial_ends_at = None
                sub.renew_at = None
                changed = True
                log_audit_event(
                    db=db,
                    actor=f"SYSTEM:trial_monitor",
                    tool="subscription.trial_expired_downgraded",
                    input_payload={"admin_id": sub.admin_id, "prev_plan": prev_plan},
                    output_payload={"status": "DOWNGRADED_TO_STARTER", "reason": "3_day_grace_period_ended"},
                    verdict="AUTO_APPROVE"
                )
            else:
                # In 3-day grace period
                if sub.status != "past_due":
                    sub.status = "past_due"
                    changed = True

    # 2. Active Subscription Expiration / Downgrade at period end
    elif sub.status in ("active", "past_due") and sub.renew_at:
        if now > sub.renew_at:
            if sub.cancel_at_period_end:
                # Scheduled downgrade or cancel
                new_plan = sub.downgrade_plan_id or "starter"
                sub.plan_id = new_plan
                sub.status = "active"
                sub.cancel_at_period_end = False
                sub.downgrade_plan_id = None
                sub.renew_at = now + datetime.timedelta(days=30)
                changed = True
                log_audit_event(
                    db=db,
                    actor="SYSTEM:subscription_lifecycle",
                    tool="subscription.period_end_downgrade",
                    input_payload={"admin_id": sub.admin_id, "downgraded_to": new_plan},
                    output_payload={"status": "APPLIED"},
                    verdict="AUTO_APPROVE"
                )
            else:
                grace_end = sub.renew_at + datetime.timedelta(days=3)
                if now > grace_end and sub.plan_id != "starter":
                    sub.plan_id = "starter"
                    sub.status = "active"
                    changed = True
                    log_audit_event(
                        db=db,
                        actor="SYSTEM:subscription_lifecycle",
                        tool="subscription.past_due_downgraded",
                        input_payload={"admin_id": sub.admin_id},
                        output_payload={"status": "DOWNGRADED_TO_STARTER"},
                        verdict="AUTO_APPROVE"
                    )

    if changed:
        db.commit()
        db.refresh(sub)
    return sub

def has_feature(admin: Optional[User], feature_name: str, db: Session) -> bool:
    """
    Single central feature gating helper used across agent, API endpoints, and dashboard.
    Returns True if feature is allowed, False otherwise.
    Logs gate denial to audit log if denied.
    """
    if not admin:
        return False

    sub = get_or_create_admin_subscription(admin, db)
    sub = check_and_expire_subscription(sub, db)

    plan = db.query(Plan).filter(Plan.id == sub.plan_id).first()
    if not plan:
        return False

    try:
        plan_features = json.loads(plan.features)
        feature_keys = plan_features.get("keys", [])
    except Exception:
        feature_keys = []

    allowed = (feature_name in feature_keys)
    if not allowed:
        # Write gate denial to audit log
        log_audit_event(
            db=db,
            actor=f"{admin.role}:{admin.email}",
            tool="subscription.gate_denied",
            input_payload={"feature": feature_name, "plan_id": plan.id, "sub_status": sub.status},
            output_payload={"allowed": False, "required_plan": "Growth/Pro"},
            verdict="REJECT",
            status="DENIED"
        )
    return allowed

def record_chat_turn(admin: Optional[User], db: Session) -> Tuple[bool, str]:
    """
    Counts one chat turn per AI interaction.
    Warns at 80% limit; hands over politely at 100%.
    Returns (can_continue: bool, status_message: str).
    """
    if not admin:
        return True, "ok"

    sub = get_or_create_admin_subscription(admin, db)
    sub = check_and_expire_subscription(sub, db)

    plan = db.query(Plan).filter(Plan.id == sub.plan_id).first()
    limit = plan.chat_limit if plan else 50

    if limit == -1:
        # Unlimited chats
        sub.chats_used += 1
        db.commit()
        return True, "ok"

    if sub.chats_used >= limit:
        # Handover to human at 100%
        return False, "Your store has reached its monthly AI chat limit. To ensure uninterrupted service, this conversation is being safely handed over to human support."

    sub.chats_used += 1
    db.commit()

    if sub.chats_used >= int(limit * 0.8):
        return True, f"Warning: Your store has utilized {sub.chats_used}/{limit} (80%+) of monthly AI chats."

    return True, "ok"

def format_subscription_response(sub: Subscription, db: Session) -> Dict[str, Any]:
    """
    Formats complete subscription details including trial days left, usage, features, and plan details.
    """
    sub = check_and_expire_subscription(sub, db)
    plan = db.query(Plan).filter(Plan.id == sub.plan_id).first()

    now = datetime.datetime.utcnow()
    trial_days_left = 0
    if sub.status == "trial" and sub.trial_ends_at:
        diff = (sub.trial_ends_at - now).total_seconds()
        trial_days_left = max(0, int(diff // 86400) + 1)

    plan_features_data = {}
    if plan and plan.features:
        try:
            plan_features_data = json.loads(plan.features)
        except Exception:
            plan_features_data = {"keys": [], "display": []}

    invoices = db.query(Invoice).filter(Invoice.subscription_id == sub.id).order_by(Invoice.issued_at.desc()).limit(10).all()

    return {
        "id": sub.id,
        "admin_id": sub.admin_id,
        "plan_id": sub.plan_id,
        "plan_name": plan.name if plan else "Starter",
        "status": sub.status,
        "billing_cycle": sub.billing_cycle,
        "price_monthly": plan.price_monthly if plan else 0.0,
        "price_yearly": plan.price_yearly if plan else 0.0,
        "chat_limit": plan.chat_limit if plan else 50,
        "chats_used": sub.chats_used,
        "started_at": sub.started_at.isoformat() if sub.started_at else None,
        "renew_at": sub.renew_at.isoformat() if sub.renew_at else None,
        "trial_ends_at": sub.trial_ends_at.isoformat() if sub.trial_ends_at else None,
        "trial_days_left": trial_days_left,
        "is_trial": (sub.status == "trial"),
        "cancel_at_period_end": sub.cancel_at_period_end,
        "downgrade_plan_id": sub.downgrade_plan_id,
        "features": plan_features_data.get("display", []),
        "feature_keys": plan_features_data.get("keys", []),
        "invoices_count": len(invoices)
    }
