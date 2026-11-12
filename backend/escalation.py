import datetime
import json
import uuid
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from .models import Escalation, Order, User, Message, Conversation
from .audit_log import log_audit_event

def escalate_to_human(
    db: Session,
    customer: User,
    order: Order,
    product_title: str,
    amount: float,
    reason: str,
    urgency: str,
    evidence_photo: Optional[str],
    chat_summary: str,
    checks_done: List[Dict[str, Any]],
    escalation_reason: str,
    agent_recommendation: str,
    evidence_photos: Optional[List[str]] = None,
    vision_analysis: Optional[Dict[str, Any]] = None,
    fraud_flags: Optional[List[str]] = None
) -> Escalation:
    case_num = f"ESC-{uuid.uuid4().hex[:6].upper()}"

    esc = Escalation(
        case_number=case_num,
        customer_id=customer.id,
        customer_name=customer.full_name,
        order_id=order.id,
        order_number=order.order_number,
        product_title=product_title,
        amount=amount,
        reason=reason,
        urgency=urgency,
        evidence_photo=evidence_photo,
        evidence_photos=json.dumps(evidence_photos) if evidence_photos else (json.dumps([evidence_photo]) if evidence_photo else None),
        vision_analysis=json.dumps(vision_analysis) if vision_analysis else None,
        fraud_flags=json.dumps(fraud_flags) if fraud_flags else "[]",
        chat_summary=chat_summary,
        checks_done=json.dumps(checks_done),
        escalation_reason=escalation_reason,
        agent_recommendation=agent_recommendation,
        status="PENDING"
    )
    db.add(esc)
    db.commit()
    db.refresh(esc)

    # Log to audit trail
    log_audit_event(
        db=db,
        actor="AI_AGENT",
        tool="escalation.create_case",
        input_payload={"order_number": order.order_number, "reason": reason, "amount": amount},
        output_payload={"case_number": case_num, "status": "PENDING"},
        verdict="NEEDS_HUMAN",
        customer_id=customer.id,
        order_id=order.id,
        idempotency_key=f"esc-{esc.id}"
    )

    return esc

def resolve_escalation(
    db: Session,
    escalation_id: str,
    decision: str,  # 'APPROVED' or 'REJECTED'
    admin_notes: str,
    admin_user: User
) -> Escalation:
    esc = db.query(Escalation).filter(Escalation.id == escalation_id).first()
    if not esc:
        raise ValueError("Escalation case not found")

    esc.status = decision
    esc.admin_notes = admin_notes
    esc.resolved_at = datetime.datetime.utcnow()

    # Update associated order if approved
    order = db.query(Order).filter(Order.id == esc.order_id).first()
    if order:
        if decision == "APPROVED":
            order.status = "REFUNDED"
            order.return_reason = f"Approved by admin: {admin_notes}"
        elif decision == "REJECTED":
            order.status = "DELIVERED"
            order.return_reason = f"Claim rejected by admin: {admin_notes}"

    # Append resolution message into customer's chat conversation
    conv = db.query(Conversation).filter(Conversation.customer_id == esc.customer_id).order_by(Conversation.updated_at.desc()).first()
    if conv:
        msg_text = (
            f"Update on your case {esc.case_number}: Our senior seller team has reviewed your request and {decision.lower()} it. "
            f"Notes: {admin_notes}"
        )
        msg = Message(
            conversation_id=conv.id,
            sender="agent",
            text=msg_text
        )
        db.add(msg)

    db.commit()
    db.refresh(esc)

    log_audit_event(
        db=db,
        actor=f"ADMIN:{admin_user.full_name}",
        tool="escalation.resolve",
        input_payload={"escalation_id": escalation_id, "decision": decision, "notes": admin_notes},
        output_payload={"status": esc.status},
        verdict=decision,
        customer_id=esc.customer_id,
        order_id=esc.order_id,
        idempotency_key=f"resolve-{esc.id}"
    )

    return esc
