import datetime
from enum import Enum
from typing import Dict, Any, Optional, List
from sqlalchemy.orm import Session
from .models import Order, Product, Setting, User, AuditLog
from .audit_log import log_audit_event

class PolicyVerdict(str, Enum):
    AUTO_APPROVE = "AUTO_APPROVE"
    NEEDS_HUMAN = "NEEDS_HUMAN"
    DENY = "DENY"

# Normalized accepted reason categories (R2)
ACCEPTED_REASON_CATEGORIES = {
    "DEFECTIVE": "Defective or not working",
    "DAMAGED": "Damaged on arrival",
    "WRONG_ITEM": "Wrong item received",
    "SIZE_FIT": "Size or fit issue",
    "NOT_AS_DESCRIBED": "Item not as described",
    "CHANGED_MIND": "Changed mind"
}

SELLER_FAULT_CATEGORIES = {"DEFECTIVE", "DAMAGED", "WRONG_ITEM", "NOT_AS_DESCRIBED"}

def get_setting_value(db: Session, key: str, default: Any) -> Any:
    s = db.query(Setting).filter(Setting.key == key).first()
    if s:
        try:
            if isinstance(default, int):
                return int(s.value)
            if isinstance(default, float):
                return float(s.value)
            if isinstance(default, bool):
                return s.value.lower() in ("true", "1")
            return s.value
        except Exception:
            return default
    return default

def compute_trust(customer: Optional[User], db: Optional[Session] = None) -> Dict[str, Any]:
    """
    Computes customer trust score (0-100) and tier (HIGH, NORMAL, RISKY).
    Factors: account age, completed orders, lifetime value (LTV), claim history/return rate, velocity.
    """
    if not customer:
        return {"score": 50.0, "tier": "NORMAL", "factors": {}}

    # If customer has explicit tier and score set on the model
    explicit_tier = getattr(customer, "trust_tier", None)
    explicit_score = getattr(customer, "trust_score", None)

    # Compute factors if DB session available
    score = 25.0  # Base score
    factors: Dict[str, Any] = {}

    # 1. Account age
    account_created = getattr(customer, "created_at", None) or datetime.datetime.utcnow()
    age_days = (datetime.datetime.utcnow() - account_created).days
    if age_days >= 180:
        age_pts = 20.0
    elif age_days >= 30:
        age_pts = 15.0
    elif age_days >= 7:
        age_pts = 10.0
    else:
        age_pts = 5.0
    score += age_pts
    factors["account_age_days"] = age_days
    factors["age_points"] = age_pts

    if db:
        orders = db.query(Order).filter(Order.customer_id == customer.id).all()
        total_orders = len(orders)
        completed_orders = [o for o in orders if o.status == "DELIVERED"]
        claims = [o for o in orders if o.status in ("RETURN_REQUESTED", "EXCHANGED", "REFUNDED")]

        # 2. Completed orders
        completed_count = len(completed_orders)
        if completed_count >= 5:
            orders_pts = 25.0
        elif completed_count >= 2:
            orders_pts = 15.0
        elif completed_count == 1:
            orders_pts = 10.0
        else:
            orders_pts = 0.0
        score += orders_pts
        factors["completed_orders"] = completed_count
        factors["completed_points"] = orders_pts

        # 3. LTV
        ltv = sum(o.total_amount for o in completed_orders)
        if ltv >= 10000:
            ltv_pts = 20.0
        elif ltv >= 5000:
            ltv_pts = 15.0
        elif ltv >= 2000:
            ltv_pts = 10.0
        elif ltv > 0:
            ltv_pts = 5.0
        else:
            ltv_pts = 0.0
        score += ltv_pts
        factors["ltv"] = ltv
        factors["ltv_points"] = ltv_pts

        # 4. Return rate / claim history
        if total_orders > 0:
            return_rate = len(claims) / total_orders
            if return_rate > 0.75 and total_orders >= 2:
                claim_pts = -30.0
            elif return_rate > 0.5 and total_orders >= 2:
                claim_pts = -20.0
            elif return_rate > 0.25:
                claim_pts = -10.0
            else:
                claim_pts = 5.0
        else:
            return_rate = 0.0
            claim_pts = 0.0
        score += claim_pts
        factors["return_rate"] = return_rate
        factors["claim_points"] = claim_pts

        # 5. Velocity: claims in last 7 days
        seven_days_ago = datetime.datetime.utcnow() - datetime.timedelta(days=7)
        recent_claims = [o for o in claims if (o.updated_at or o.created_at) >= seven_days_ago]
        if len(recent_claims) >= 2:
            velocity_pts = -25.0
        elif len(recent_claims) == 1:
            velocity_pts = -10.0
        else:
            velocity_pts = 5.0
        score += velocity_pts
        factors["recent_claims_7d"] = len(recent_claims)
        factors["velocity_points"] = velocity_pts

    # Clamp score
    final_score = max(0.0, min(100.0, score if explicit_score is None else explicit_score))

    if explicit_tier and explicit_tier.upper() in ("HIGH", "NORMAL", "RISKY"):
        tier = explicit_tier.upper()
    else:
        if final_score >= 75.0:
            tier = "HIGH"
        elif final_score >= 40.0:
            tier = "NORMAL"
        else:
            tier = "RISKY"

    return {
        "score": final_score,
        "tier": tier,
        "factors": factors
    }

def normalize_reason_category(reason: Optional[str], reason_category: Optional[str]) -> Optional[str]:
    """Helper to map free-text reasons or raw codes to normalized reason categories."""
    raw = f"{reason_category or ''} {reason or ''}".lower().strip()
    if not raw:
        return None

    if any(k in raw for k in ("defect", "not work", "malfunction", "broken", "stop working")):
        return "DEFECTIVE"
    if any(k in raw for k in ("damage", "crack", "torn", "tear", "crushed", "scratched")):
        return "DAMAGED"
    if any(k in raw for k in ("wrong item", "wrong product", "different item", "wrong colour", "wrong color")):
        return "WRONG_ITEM"
    if any(k in raw for k in ("size", "fit", "tight", "loose", "too small", "too big", "too large")):
        return "SIZE_FIT"
    if any(k in raw for k in ("not as described", "different from picture", "misleading", "fake")):
        return "NOT_AS_DESCRIBED"
    if any(k in raw for k in ("changed mind", "don't want", "dont want", "no longer needed", "unwanted", "mind")):
        return "CHANGED_MIND"

    # Direct uppercase key check
    if reason_category:
        cat_key = reason_category.upper().replace(" ", "_").replace("/", "_")
        if cat_key in ACCEPTED_REASON_CATEGORIES:
            return cat_key

    return None

def check_policy(
    db: Session,
    order: Order,
    action: str,  # 'REFUND', 'EXCHANGE', 'STORE_CREDIT', 'CANCEL', 'RETURN', 'ELIGIBILITY_CHECK'
    amount: Optional[float] = None,
    reason: Optional[str] = None,
    evidence_photo: Optional[str] = None,
    customer: Optional[User] = None,
    reason_category: Optional[str] = None,
    evidence_status: Optional[str] = None
) -> Dict[str, Any]:
    """
    Pure Python deterministic policy engine (R1 through R10).
    The LLM proposes, the Python policy engine decides.
    Returns: verdict (AUTO_APPROVE | NEEDS_HUMAN | DENY), list of reasons, checks list, refund_amount.
    Logs every policy evaluation to audit_logs (R10).
    """
    checks: List[Dict[str, Any]] = []
    reasons: List[str] = []
    action_upper = (action or "RETURN").upper()

    # Determine customer and trust tier (R7, F2)
    cust = customer or order.customer or db.query(User).filter(User.id == order.customer_id).first()
    trust_data = compute_trust(cust, db)
    trust_tier = trust_data["tier"]
    trust_score = trust_data["score"]

    # Limits from settings table (Never hardcoded)
    trust_high_limit = float(get_setting_value(db, "trust_high_refund_limit", 5000.0))
    trust_normal_limit = float(get_setting_value(db, "trust_normal_refund_limit", 2000.0))
    trust_risky_limit = float(get_setting_value(db, "trust_risky_refund_limit", 0.0))
    return_window_days = int(get_setting_value(db, "return_window_days", 7))

    tier_limit = trust_normal_limit
    if trust_tier == "HIGH":
        tier_limit = trust_high_limit
    elif trust_tier == "RISKY":
        tier_limit = trust_risky_limit

    # ══════ RULE 8: CANCELLATIONS ══════
    if action_upper == "CANCEL":
        if order.status in ("PLACED", "PACKED"):
            checks.append({"rule": "R8_cancellation", "passed": True, "detail": f"Pre-dispatch cancellation allowed in stage {order.status}."})
            reasons.append("Pre-dispatch order cancellation eligible for instant 100% full refund.")
            result = {
                "verdict": PolicyVerdict.AUTO_APPROVE,
                "reasons": reasons,
                "reason": "Your order has not been dispatched yet and can be cancelled immediately with a full refund.",
                "checks": checks,
                "auto_approve": True,
                "refund_amount": order.total_amount,
                "recommended_resolution": "REFUND",
                "customer_tier": trust_tier,
                "tier_limit": tier_limit
            }
            log_policy_audit(db, order, action_upper, result, checks)
            return result
        elif order.status in ("SHIPPED", "OUT_FOR_DELIVERY"):
            checks.append({"rule": "R8_cancellation", "passed": False, "detail": f"Order already dispatched ({order.status}); cannot cancel in transit."})
            reasons.append(f"Order is in transit ({order.status}) and cannot be cancelled directly. Please refuse delivery at doorstep or return after delivery.")
            result = {
                "verdict": PolicyVerdict.DENY,
                "reasons": reasons,
                "reason": f"Your order has already shipped and is currently {order.status.lower().replace('_', ' ')}. We cannot cancel orders in transit. You can refuse delivery when the courier arrives or initiate a return once delivered.",
                "checks": checks,
                "auto_approve": False,
                "refund_amount": 0.0,
                "recommended_resolution": "REFUSE_DELIVERY",
                "customer_tier": trust_tier,
                "tier_limit": tier_limit
            }
            log_policy_audit(db, order, action_upper, result, checks)
            return result
        elif order.status == "DELIVERED":
            checks.append({"rule": "R8_cancellation", "passed": False, "detail": "Order already delivered; cancellation invalid."})
            reasons.append("Order is already delivered. Cancellations are not valid for delivered orders; please request a return or exchange.")
            result = {
                "verdict": PolicyVerdict.DENY,
                "reasons": reasons,
                "reason": "This order has already been delivered. Delivered orders cannot be cancelled, but you can request a return or exchange within our return window.",
                "checks": checks,
                "auto_approve": False,
                "refund_amount": 0.0,
                "recommended_resolution": "RETURN",
                "customer_tier": trust_tier,
                "tier_limit": tier_limit
            }
            log_policy_audit(db, order, action_upper, result, checks)
            return result

    # ══════ RULE 9: IDEMPOTENCY / DUPLICATE REQUESTS ══════
    if order.status in ("RETURN_REQUESTED", "EXCHANGED", "REFUNDED", "CANCELLED"):
        existing_log = db.query(AuditLog).filter(
            AuditLog.order_id == order.id,
            AuditLog.status == "SUCCESS",
            (AuditLog.tool.like("%refund%") | AuditLog.tool.like("%return%") | AuditLog.tool.like("%exchange%") | AuditLog.tool.like("%cancel%"))
        ).order_by(AuditLog.timestamp.desc()).first()
        ref_text = f" (Ref: {existing_log.id})" if existing_log else ""
        checks.append({"rule": "R9_idempotency", "passed": False, "detail": f"Existing status is {order.status}{ref_text}."})
        reasons.append(f"Duplicate request: Order {order.order_number} already has active or completed status '{order.status}'{ref_text}.")
        result = {
            "verdict": PolicyVerdict.DENY,
            "reasons": reasons,
            "reason": f"A resolution has already been processed for order {order.order_number} (Status: {order.status.replace('_', ' ')}). Please refer to your existing resolution record.",
            "checks": checks,
            "auto_approve": False,
            "refund_amount": 0.0,
            "customer_tier": trust_tier,
            "tier_limit": tier_limit
        }
        log_policy_audit(db, order, action_upper, result, checks)
        return result
    checks.append({"rule": "R9_idempotency", "passed": True, "detail": "No duplicate active resolution."})

    # ══════ RULE 1: ELIGIBILITY ══════
    # 1.1 Status must be DELIVERED
    if order.status != "DELIVERED":
        checks.append({"rule": "R1_delivered", "passed": False, "detail": f"Order status is {order.status}."})
        reasons.append(f"Only delivered orders are eligible for return or exchange. Your order is currently {order.status}.")
        result = {
            "verdict": PolicyVerdict.DENY,
            "reasons": reasons,
            "reason": f"Only delivered orders are eligible for return or exchange. Your order is currently {order.status.lower().replace('_', ' ')}.",
            "checks": checks,
            "auto_approve": False,
            "refund_amount": 0.0,
            "customer_tier": trust_tier,
            "tier_limit": tier_limit
        }
        log_policy_audit(db, order, action_upper, result, checks)
        return result
    checks.append({"rule": "R1_delivered", "passed": True, "detail": "Order is DELIVERED."})

    # 1.2 Return Window
    delivered_time = order.delivered_at or order.stage_entered_at or order.created_at
    days_since_delivery = (datetime.datetime.utcnow() - delivered_time).days
    if days_since_delivery > return_window_days:
        checks.append({
            "rule": "R1_return_window",
            "passed": False,
            "detail": f"{days_since_delivery} days elapsed > {return_window_days} days limit."
        })
        reasons.append(f"Order delivered {days_since_delivery} days ago, exceeding the {return_window_days}-day return window.")
        result = {
            "verdict": PolicyVerdict.DENY,
            "reasons": reasons,
            "reason": f"This order was delivered {days_since_delivery} days ago, which exceeds our {return_window_days}-day return window.",
            "checks": checks,
            "auto_approve": False,
            "refund_amount": 0.0,
            "customer_tier": trust_tier,
            "tier_limit": tier_limit
        }
        log_policy_audit(db, order, action_upper, result, checks)
        return result
    checks.append({
        "rule": "R1_return_window",
        "passed": True,
        "detail": f"{days_since_delivery} days elapsed <= {return_window_days} days limit."
    })

    # 1.3 Product Returnability (Hygiene items strictly non-returnable)
    for item in order.items:
        prod = item.product or db.query(Product).filter(Product.id == item.product_id).first()
        if prod and not prod.is_returnable:
            checks.append({
                "rule": "R1_product_returnable",
                "passed": False,
                "detail": f"'{prod.title}' is a non-returnable intimate hygiene product."
            })
            reasons.append(f"Product '{prod.title}' is an intimate hygiene item and is strictly non-returnable for sanitation reasons.")
            result = {
                "verdict": PolicyVerdict.DENY,
                "reasons": reasons,
                "reason": f"\"{prod.title}\" is an intimate hygiene/personal care product and is strictly non-returnable for health and sanitation reasons.",
                "checks": checks,
                "auto_approve": False,
                "refund_amount": 0.0,
                "customer_tier": trust_tier,
                "tier_limit": tier_limit
            }
            log_policy_audit(db, order, action_upper, result, checks)
            return result
    checks.append({"rule": "R1_product_returnable", "passed": True, "detail": "All items returnable."})

    # ══════ RULE 3: REASON IS MANDATORY ══════
    norm_category = normalize_reason_category(reason, reason_category)
    if not reason and not reason_category and not norm_category and not order.reason_category:
        checks.append({"rule": "R3_mandatory_reason", "passed": False, "detail": "Missing mandatory return reason."})
        reasons.append("Return/exchange reason is mandatory before any resolution or offer can be made.")
        result = {
            "verdict": PolicyVerdict.DENY,
            "reasons": reasons,
            "reason": "Please provide the specific reason for your return or exchange so we can evaluate your request.",
            "checks": checks,
            "auto_approve": False,
            "refund_amount": 0.0,
            "customer_tier": trust_tier,
            "tier_limit": tier_limit
        }
        log_policy_audit(db, order, action_upper, result, checks)
        return result
    checks.append({"rule": "R3_mandatory_reason", "passed": True, "detail": "Reason provided."})

    # ══════ RULE 2: ACCEPTED REASONS ══════
    if not norm_category:
        checks.append({"rule": "R2_accepted_reason", "passed": False, "detail": f"Unrecognized reason category: {reason or reason_category}."})
        reasons.append(f"Reason '{reason or reason_category}' requires manual evaluation by our support team.")
        result = {
            "verdict": PolicyVerdict.NEEDS_HUMAN,
            "reasons": reasons,
            "reason": "Your reason requires a quick check by our support team. Escalating for priority review.",
            "checks": checks,
            "auto_approve": False,
            "refund_amount": 0.0,
            "customer_tier": trust_tier,
            "tier_limit": tier_limit
        }
        log_policy_audit(db, order, action_upper, result, checks)
        return result
    checks.append({"rule": "R2_accepted_reason", "passed": True, "detail": f"Accepted reason: {ACCEPTED_REASON_CATEGORIES.get(norm_category, norm_category)}."})

    # ══════ RULE 5: PREFERRED RESOLUTIONS ══════
    if norm_category in ("DEFECTIVE", "DAMAGED", "WRONG_ITEM", "NOT_AS_DESCRIBED"):
        recommended_resolution = "REPLACEMENT"
    elif norm_category == "SIZE_FIT":
        recommended_resolution = "SIZE_SWAP"
    else:  # CHANGED_MIND
        recommended_resolution = "STORE_CREDIT"

    # ══════ RULE 6: REFUND AMOUNT CALCULATION ══════
    item_total = sum(item.subtotal for item in order.items) if order.items else order.total_amount
    delivery_fee = getattr(order, "delivery_fee", 0.0) or 0.0
    if delivery_fee == 0.0 and order.total_amount > item_total:
        delivery_fee = max(0.0, order.total_amount - item_total)

    is_seller_fault = norm_category in SELLER_FAULT_CATEGORIES
    if is_seller_fault:
        calc_refund = item_total + delivery_fee
        fee_note = f"Full refund including delivery fee ₹{delivery_fee:.0f} (seller fault: {norm_category})."
    else:
        calc_refund = item_total
        fee_note = "Item price refund. Delivery fee is non-refundable for customer preference return."

    final_refund_amount = amount if amount is not None else calc_refund
    checks.append({"rule": "R6_refund_amount", "passed": True, "detail": f"Amount calculated: ₹{final_refund_amount:.2f}. {fee_note}"})

    # ══════ RULE 4: EVIDENCE REQUIREMENTS ══════
    ev_status = (evidence_status or getattr(order, "evidence_status", None) or "NONE").upper()
    if evidence_photo and ev_status == "NONE":
        ev_status = "PENDING"

    # If this is the initial eligibility check in the graph (chat -> policy engine -> evidence):
    # Order is eligible to proceed to evidence collection if all preceding eligibility checks passed.
    if action_upper == "ELIGIBILITY_CHECK":
        checks.append({
            "rule": "R4_evidence",
            "passed": True,
            "detail": f"Eligibility confirmed. Current evidence status: '{ev_status}'. Proceeding to evidence collection and retention."
        })
    else:
        # For execution actions (REFUND, EXCHANGE, STORE_CREDIT, RETURN): evidence MUST be VERIFIED
        evidence_passed = (ev_status == "VERIFIED")
        if is_seller_fault:
            if not evidence_passed:
                checks.append({
                    "rule": "R4_evidence",
                    "passed": False,
                    "detail": f"Evidence status is '{ev_status}'. Photo/video verification required for {norm_category} before auto-approval."
                })
                reasons.append(f"Evidence status is '{ev_status}'. Verified photo/video proof required before auto-approval.")
                result = {
                    "verdict": PolicyVerdict.NEEDS_HUMAN,
                    "reasons": reasons,
                    "reason": "Please provide a clear photo or video showing the issue so our system can verify it, or our support team will inspect the case.",
                    "checks": checks,
                    "auto_approve": False,
                    "refund_amount": final_refund_amount,
                    "recommended_resolution": recommended_resolution,
                    "customer_tier": trust_tier,
                    "tier_limit": tier_limit
                }
                log_policy_audit(db, order, action_upper, result, checks)
                return result
        else:
            # Size/fit or changed mind: unused with tag/box photo
            if not evidence_passed:
                checks.append({
                    "rule": "R4_evidence",
                    "passed": False,
                    "detail": f"Evidence status is '{ev_status}'. Photo of unused item with tag/box intact required before auto-approval."
                })
                reasons.append(f"Evidence status is '{ev_status}'. Photo of unused product with tag/box is required before auto-approval.")
                result = {
                    "verdict": PolicyVerdict.NEEDS_HUMAN,
                    "reasons": reasons,
                    "reason": "For size/preference returns, please share a quick photo showing the unused item with its original packaging and tags attached.",
                    "checks": checks,
                    "auto_approve": False,
                    "refund_amount": final_refund_amount,
                    "recommended_resolution": recommended_resolution,
                    "customer_tier": trust_tier,
                    "tier_limit": tier_limit
                }
                log_policy_audit(db, order, action_upper, result, checks)
                return result
        checks.append({"rule": "R4_evidence", "passed": True, "detail": "Evidence is VERIFIED."})

    # ══════ RULE 7: TRUST-TIERED AUTO-APPROVE CEILING ══════
    if trust_tier == "RISKY":
        checks.append({
            "rule": "R7_trust_ceiling",
            "passed": False,
            "detail": "Customer account is classified as RISKY (limit ₹0). Always requires human escalation."
        })
        reasons.append("Account security check: RISKY customer tier requires supervisor approval.")
        result = {
            "verdict": PolicyVerdict.NEEDS_HUMAN,
            "reasons": reasons,
            "reason": "For your security, this request has been forwarded to a customer service supervisor for priority review.",
            "checks": checks,
            "auto_approve": False,
            "refund_amount": final_refund_amount,
            "recommended_resolution": recommended_resolution,
            "customer_tier": trust_tier,
            "tier_limit": tier_limit
        }
        log_policy_audit(db, order, action_upper, result, checks)
        return result

    if action_upper in ("REFUND", "RETURN") and final_refund_amount > tier_limit:
        checks.append({
            "rule": "R7_trust_ceiling",
            "passed": False,
            "detail": f"Amount ₹{final_refund_amount:,.2f} exceeds {trust_tier} tier ceiling of ₹{tier_limit:,.2f}."
        })
        reasons.append(f"Refund amount ₹{final_refund_amount:,.2f} exceeds {trust_tier} trust tier limit of ₹{tier_limit:,.2f}.")
        result = {
            "verdict": PolicyVerdict.NEEDS_HUMAN,
            "reasons": reasons,
            "reason": f"Claim amount of ₹{final_refund_amount:,.2f} exceeds our instant automated limit of ₹{tier_limit:,.2f} for your tier. Escalating to our manager for priority review.",
            "checks": checks,
            "auto_approve": False,
            "refund_amount": final_refund_amount,
            "recommended_resolution": recommended_resolution,
            "customer_tier": trust_tier,
            "tier_limit": tier_limit
        }
        log_policy_audit(db, order, action_upper, result, checks)
        return result
    checks.append({
        "rule": "R7_trust_ceiling",
        "passed": True,
        "detail": f"Amount ₹{final_refund_amount:,.2f} is within {trust_tier} tier limit of ₹{tier_limit:,.2f}."
    })

    # ══════ ALL POLICY CHECKS PASSED: AUTO_APPROVE ══════
    reasons.append("Order meets all return criteria. Instant auto-approval granted.")
    result = {
        "verdict": PolicyVerdict.AUTO_APPROVE,
        "reasons": reasons,
        "reason": "Order meets all return criteria. Instant auto-approval granted.",
        "checks": checks,
        "auto_approve": True,
        "refund_amount": final_refund_amount,
        "recommended_resolution": recommended_resolution,
        "customer_tier": trust_tier,
        "tier_limit": tier_limit
    }
    log_policy_audit(db, order, action_upper, result, checks)
    return result

def log_policy_audit(
    db: Session,
    order: Order,
    action: str,
    result: Dict[str, Any],
    checks: List[Dict[str, Any]]
) -> None:
    """R10 Audit: log every policy check to audit_logs."""
    try:
        evaluated_rules = [c.get("rule") for c in checks]
        verdict_str = result["verdict"].value if hasattr(result["verdict"], "value") else str(result["verdict"])
        log_audit_event(
            db=db,
            actor="POLICY_ENGINE",
            tool="policy_engine.check_policy",
            customer_id=order.customer_id,
            order_id=order.id,
            verdict=verdict_str,
            input_payload={
                "action": action,
                "order_number": order.order_number,
                "total_amount": order.total_amount,
                "status": order.status,
                "customer_tier": result.get("customer_tier")
            },
            output_payload={
                "verdict": verdict_str,
                "reasons": result.get("reasons"),
                "evaluated_rules": evaluated_rules,
                "refund_amount": result.get("refund_amount"),
                "auto_approve": result.get("auto_approve")
            },
            status="SUCCESS"
        )
    except Exception as e:
        print(f"[PolicyEngine] Failed to write audit log: {e}")
