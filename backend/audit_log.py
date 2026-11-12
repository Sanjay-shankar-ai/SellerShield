import json
from datetime import datetime
from typing import Any, Optional
from sqlalchemy.orm import Session
from .models import AuditLog

def log_audit_event(
    db: Session,
    actor: str,
    tool: str,
    input_payload: Any = None,
    output_payload: Any = None,
    verdict: Optional[str] = None,
    status: str = "SUCCESS",
    error: Optional[str] = None,
    customer_id: Optional[str] = None,
    order_id: Optional[str] = None,
    idempotency_key: Optional[str] = None
) -> AuditLog:
    """
    Records an immutable audit event for every API action, policy verdict, and escalation.
    """
    def serialize(obj):
        if obj is None:
            return None
        if isinstance(obj, str):
            return obj
        try:
            return json.dumps(obj)
        except Exception:
            return str(obj)

    entry = AuditLog(
        timestamp=datetime.utcnow(),
        actor=actor,
        customer_id=customer_id,
        order_id=order_id,
        tool=tool,
        input_payload=serialize(input_payload),
        output_payload=serialize(output_payload),
        verdict=verdict,
        status=status,
        error=error,
        idempotency_key=idempotency_key
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry
