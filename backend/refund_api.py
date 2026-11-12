import datetime
import uuid
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from .models import Order, TrackingEvent, AuditLog, User, PromoCode, Setting, WalletTransaction
from .audit_log import log_audit_event
from .policy_engine import PolicyVerdict

def get_store_credit_bonus_pct(db: Session) -> float:
    s = db.query(Setting).filter(Setting.key == "store_credit_bonus_pct").first()
    return float(s.value) if s else 10.0

def validate_tool_preconditions(
    order: Order,
    reason_category: Optional[str],
    evidence_status: Optional[str],
    actor: str
):
    """Enforce strict guardrails: reject call if required fields are missing."""
    if not reason_category:
        raise ValueError("Missing required field: reason_category must be established before issuing resolution.")

    # Damage, defect, and wrong item claims strictly require photo verification
    damage_defect_categories = ("Damaged on arrival", "Defective or not working", "Wrong item", "Not as described")
    if reason_category in damage_defect_categories:
        if actor != "ADMIN" and evidence_status != "VERIFIED":
            raise ValueError(f"Evidence status must be VERIFIED (current: {evidence_status}) for {reason_category} before issuing refund or credit.")
    else:
        # Size/fit or changed mind: no photo required (evidence_status = NONE or VERIFIED)
        if actor != "ADMIN" and evidence_status not in ("NONE", "VERIFIED", None):
            raise ValueError(f"Invalid evidence status for {reason_category}: {evidence_status}")

def issue_refund(
    db: Session,
    order: Order,
    amount: float,
    reason: str,
    reason_category: str,
    evidence_status: str,
    refund_destination: str = "ORIGINAL",
    policy_verdict: Optional[str] = None,
    actor: str = "AI_AGENT"
) -> Dict[str, Any]:
    """Refund to original payment method (Bank / UPI). Takes 4-5 working days."""
    idempotency_key = f"refund-{order.id}"

    # Guardrails validation
    validate_tool_preconditions(order, reason_category, evidence_status, actor)

    # Check idempotency
    existing_log = db.query(AuditLog).filter(
        AuditLog.idempotency_key == idempotency_key,
        AuditLog.status == "SUCCESS"
    ).first()
    if existing_log:
        return {
            "success": True,
            "idempotent": True,
            "action": "REFUND_ALREADY_ISSUED",
            "message": f"Refund of ₹{amount:,.0f} has already been processed for order {order.order_number}."
        }

    if policy_verdict != PolicyVerdict.AUTO_APPROVE and not actor.startswith("ADMIN"):
        raise PermissionError("Refund requires verified policy approval or admin sign-off.")

    order.status = "REFUNDED"
    order.return_reason = reason
    order.reason_category = reason_category
    order.evidence_status = evidence_status
    order.refund_destination = "ORIGINAL"

    txn_id = f"TXN-REF-{uuid.uuid4().hex[:8].upper()}"
    ev = TrackingEvent(
        order_id=order.id,
        status="REFUNDED",
        title="Refund Disbursed",
        location="Bank / Payment Gateway",
        description=f"Refund of ₹{amount:,.0f} disbursed to original payment method (Ref: {txn_id}). Expected in 4–5 working days."
    )
    db.add(ev)
    db.commit()

    log_audit_event(
        db=db,
        actor=actor,
        tool="refund_api.issue_refund",
        input_payload={"order_number": order.order_number, "amount": amount, "destination": "ORIGINAL", "reason_category": reason_category},
        output_payload={"status": "REFUNDED", "txn_id": txn_id, "amount": amount},
        verdict="AUTO_APPROVE" if policy_verdict == PolicyVerdict.AUTO_APPROVE else "APPROVED",
        customer_id=order.customer_id,
        order_id=order.id,
        idempotency_key=idempotency_key
    )

    return {
        "success": True,
        "action": "REFUND_PROCESSED",
        "destination": "ORIGINAL",
        "txn_id": txn_id,
        "amount": amount,
        "message": f"Your refund of ₹{amount:,.0f} has been processed back to your original payment method. It will reach your account within 4–5 working days."
    }

def issue_wallet_credit(
    db: Session,
    order: Order,
    amount: float,
    reason: str,
    reason_category: str,
    evidence_status: str,
    policy_verdict: Optional[str] = None,
    actor: str = "AI_AGENT"
) -> Dict[str, Any]:
    """Instant credit deposited into customer's store wallet balance."""
    idempotency_key = f"refund-{order.id}"

    validate_tool_preconditions(order, reason_category, evidence_status, actor)

    existing_log = db.query(AuditLog).filter(
        AuditLog.idempotency_key == idempotency_key,
        AuditLog.status == "SUCCESS"
    ).first()
    if existing_log:
        return {
            "success": True,
            "idempotent": True,
            "action": "WALLET_CREDIT_ALREADY_ISSUED",
            "message": f"Store wallet credit has already been issued for order {order.order_number}."
        }

    # Credit user wallet
    user = db.query(User).filter(User.id == order.customer_id).first()
    if user:
        user.wallet_balance = (user.wallet_balance or 0.0) + amount
        # Record positive credit transaction
        tx = WalletTransaction(
            customer_id=user.id,
            order_id=order.id,
            order_number=order.order_number,
            amount=amount,
            transaction_type="CREDIT",
            description=f"Refund credit for {order.order_number} ({reason_category or 'Store Credit'})",
            balance_after=user.wallet_balance
        )
        db.add(tx)

    order.status = "REFUNDED"
    order.return_reason = reason
    order.reason_category = reason_category
    order.evidence_status = evidence_status
    order.refund_destination = "WALLET"

    ev = TrackingEvent(
        order_id=order.id,
        status="REFUNDED",
        title="Store Wallet Credited",
        location="Customer Wallet",
        description=f"₹{amount:,.0f} credited to your store wallet. Usable immediately on any order."
    )
    db.add(ev)
    db.commit()

    log_audit_event(
        db=db,
        actor=actor,
        tool="refund_api.issue_wallet_credit",
        input_payload={"order_number": order.order_number, "amount": amount, "destination": "WALLET", "reason_category": reason_category},
        output_payload={"new_wallet_balance": user.wallet_balance if user else amount},
        verdict="AUTO_APPROVE",
        customer_id=order.customer_id,
        order_id=order.id,
        idempotency_key=idempotency_key
    )

    return {
        "success": True,
        "action": "WALLET_CREDITED",
        "destination": "WALLET",
        "amount": amount,
        "new_wallet_balance": user.wallet_balance if user else amount,
        "message": f"Done! ₹{amount:,.0f} has been credited to your SellerShield wallet instantly. You can use it on any product right away."
    }

def issue_promo_code(
    db: Session,
    order: Order,
    amount: float,
    reason: str,
    reason_category: str,
    evidence_status: str,
    policy_verdict: Optional[str] = None,
    actor: str = "AI_AGENT"
) -> Dict[str, Any]:
    """Single-use promo code with store-credit bonus percentage applied."""
    idempotency_key = f"refund-{order.id}"

    validate_tool_preconditions(order, reason_category, evidence_status, actor)

    existing_log = db.query(AuditLog).filter(
        AuditLog.idempotency_key == idempotency_key,
        AuditLog.status == "SUCCESS"
    ).first()
    if existing_log:
        return {
            "success": True,
            "idempotent": True,
            "action": "PROMO_CODE_ALREADY_ISSUED",
            "message": f"Promo code refund already generated for order {order.order_number}."
        }

    bonus_pct = get_store_credit_bonus_pct(db)
    bonus_amount = round(amount * (bonus_pct / 100.0), 2)
    total_val = amount + bonus_amount

    code = f"SHIELD-{uuid.uuid4().hex[:6].upper()}"
    expiry_date = datetime.datetime.utcnow() + datetime.timedelta(days=90)

    promo = PromoCode(
        code=code,
        value=total_val,
        customer_id=order.customer_id,
        expiry=expiry_date,
        is_used=False
    )
    db.add(promo)

    order.status = "REFUNDED"
    order.return_reason = reason
    order.reason_category = reason_category
    order.evidence_status = evidence_status
    order.refund_destination = "PROMO"

    ev = TrackingEvent(
        order_id=order.id,
        status="REFUNDED",
        title="Bonus Promo Code Issued",
        location="Discount Voucher Registry",
        description=f"Generated coupon {code} for ₹{total_val:,.0f} (includes ₹{bonus_amount:,.0f} bonus). Valid for 90 days."
    )
    db.add(ev)
    db.commit()

    log_audit_event(
        db=db,
        actor=actor,
        tool="refund_api.issue_promo_code",
        input_payload={"order_number": order.order_number, "base_amount": amount, "bonus_pct": bonus_pct, "code": code},
        output_payload={"code": code, "total_value": total_val},
        verdict="AUTO_APPROVE",
        customer_id=order.customer_id,
        order_id=order.id,
        idempotency_key=idempotency_key
    )

    return {
        "success": True,
        "action": "PROMO_CODE_ISSUED",
        "destination": "PROMO",
        "code": code,
        "value": total_val,
        "bonus_amount": bonus_amount,
        "message": f"Here is your exclusive promo code: {code} worth ₹{total_val:,.0f} (includes an extra ₹{bonus_amount:,.0f} bonus!). Apply it at checkout on any order."
    }
