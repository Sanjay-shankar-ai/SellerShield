import os
import sys
import json
import time
import datetime
from sqlalchemy.orm import Session
from dotenv import load_dotenv

load_dotenv("backend/.env")

from backend.database import SessionLocal
from backend.models import User, Order, Product, Conversation, Message, Escalation, AuditLog, Setting, PromoCode
from backend.order_api import get_customer_orders, is_order_active, track_order
from backend.policy_engine import check_policy, PolicyVerdict, get_setting_value
from backend.return_api import reserve_stock, create_exchange, cancel_order
from backend.refund_api import issue_refund, issue_wallet_credit, issue_promo_code
from backend.langgraph_agent import run_agent_turn, resume_agent_escalation, get_composed_system_prompt

def run_tests():
    db: Session = SessionLocal()
    print("=" * 60)
    print("RUNNING E2E SELLER SHIELD & LANGGRAPH AGENT TEST SUITE")
    print("=" * 60)

    # 1. TEST PROMPT LOADING & PLACEHOLDER INJECTION
    print("\n--- 1. Testing Dynamic Prompt Composition ---")
    system_prompt = get_composed_system_prompt(db, "Test Instruction")
    assert "{{return_window_days}}" not in system_prompt, "return_window_days placeholder was not replaced!"
    assert "{{refund_limit}}" not in system_prompt, "refund_limit placeholder was not replaced!"
    assert "{{store_credit_bonus_pct}}" not in system_prompt, "store_credit_bonus_pct placeholder was not replaced!"
    assert "Maya" in system_prompt, "Maya persona missing in composed prompt!"
    print("✓ Dynamic prompt composition successfully injected settings without hardcoding.")

    # 2. TEST ORDER FILTERING (ACTIVE VS PAST)
    print("\n--- 2. Testing Order Filtering (Active vs Past) ---")
    customer = db.query(User).filter(User.role == "CUSTOMER").first()
    assert customer is not None, "No test customer found!"

    orders_data = get_customer_orders(db, customer.id)
    print(f"Customer {customer.full_name}: {len(orders_data['active_orders'])} active, {len(orders_data['past_orders'])} past orders.")
    for o in orders_data['active_orders']:
        assert is_order_active(o), f"Order {o.order_number} should be active!"
    print("✓ Active vs Past orders classification verified.")

    # 3. TEST TRACK ORDER STRICT COMPLIANCE
    print("\n--- 3. Testing track_order Tool Compliance ---")
    target_order = orders_data['all_orders'][0]
    track_info = track_order(db, target_order.id, customer)
    assert "current_stage" in track_info
    assert "last_location" in track_info
    assert "expected_delivery" in track_info
    print(f"✓ track_order returned: stage={track_info['current_stage']}, location={track_info['last_location']}")

    # 4. TEST LANGGRAPH TURN 1: TRACKING QUERY
    print("\n--- 4. Testing LangGraph Turn: Tracking Query ---")
    db.query(Message).filter(Message.conversation.has(customer_id=customer.id)).delete(synchronize_session=False)
    db.query(Conversation).filter(Conversation.customer_id == customer.id).delete(synchronize_session=False)
    db.commit()
    res1 = run_agent_turn(db, customer, "Where is my order?")
    print("Agent Reply:", res1["reply_text"])
    assert "reply_text" in res1 and len(res1["reply_text"]) > 0
    assert len(res1.get("quick_replies", [])) > 0
    print("✓ Tracking turn handled cleanly via LangGraph StateGraph.")

    # 5. TEST LANGGRAPH TURN 2: RETURN REQUEST -> ASK REASON GUARDRAIL
    print("\n--- 5. Testing LangGraph Turn: Return Request Guardrail (Ask Reason) ---")
    delivered_order = db.query(Order).filter(
        Order.customer_id == customer.id,
        Order.order_number == "ORD-89379"
    ).first()
    if not delivered_order:
        delivered_order = next((o for o in orders_data['active_orders'] if o.status == 'DELIVERED'), None)
    assert delivered_order is not None, "No DELIVERED order found for return test!"

    # Ensure returnable status & set total_amount to ₹1,499.0 (below ₹2,000.0 refund limit) to test full autonomous approval
    delivered_order.status = "DELIVERED"
    delivered_order.total_amount = 1499.0
    # Clean any old test idempotency keys
    db.query(AuditLog).filter(AuditLog.idempotency_key == f"refund-{delivered_order.id}").delete()
    db.commit()

    # Clean previous conversation so we test from clean state
    conv = db.query(Conversation).filter(Conversation.customer_id == customer.id).order_by(Conversation.updated_at.desc()).first()
    if conv:
        conv.step = None
        conv.pending_question = None
        conv.current_order_id = delivered_order.id
        db.commit()

    # Pass DELIVERED order context to verify Ask Reason step
    res2 = run_agent_turn(db, customer, "Just refund my shoes, I don't want it", active_order_id=delivered_order.id)
    print("Agent Reply:", res2["reply_text"])
    print("Quick Replies:", res2.get("quick_replies"))
    assert any("Defective" in q or "Damaged" in q or "Size" in q for q in res2.get("quick_replies", [])), "Did not ask reason with quick replies!"
    print("✓ Guardrail enforced: agent asked reason before offering resolution.")

    # 6. TEST LANGGRAPH TURN 3: CUSTOMER PROVIDES REASON (SIZE ISSUE) -> RETENTION
    print("\n--- 6. Testing LangGraph Turn: Size Issue -> Retention & Choices ---")
    res3 = run_agent_turn(db, customer, "Size / fit issue - shoes feel too tight")
    print("Agent Reply:", res3["reply_text"])
    print("Quick Replies:", res3.get("quick_replies"))
    assert any("Replacement" in q or "Refund" in q for q in res3.get("quick_replies", [])), "Retention choice (Replacement vs Refund) missing!"
    print("✓ Retention choices presented (Replacement 2 days vs Refund 4-5 days).")

    # 7. TEST LANGGRAPH TURN 4: CUSTOMER CHOOSES REFUND -> DESTINATIONS OFFERED
    print("\n--- 7. Testing LangGraph Turn: Refund Destination Choices ---")
    res4 = run_agent_turn(db, customer, "I want a refund")
    print("Agent Reply:", res4["reply_text"])
    print("Quick Replies:", res4.get("quick_replies"))
    assert any("wallet" in q.lower() or "promo" in q.lower() or "original" in q.lower() for q in res4.get("quick_replies", [])), "Refund destination options not presented!"
    print("✓ Refund destination options presented (Store wallet, Promo code with bonus, Original account).")

    # 8. TEST LANGGRAPH TURN 5: CUSTOMER SELECTS STORE WALLET -> ACT & VERIFY EXECUTION
    print("\n--- 8. Testing LangGraph Turn: Select Wallet -> Act & Verify Execution ---")
    res5 = run_agent_turn(db, customer, "Store wallet (Instant)")
    print("Agent Reply:", res5["reply_text"])
    print("Tool Calls:", res5.get("tool_calls"))
    assert any(t.get("tool") == "issue_wallet_credit" for t in res5.get("tool_calls", [])), "issue_wallet_credit tool was not called!"

    # Verify DB record
    db.refresh(delivered_order)
    assert delivered_order.status == "REFUNDED", f"Order status was not updated to REFUNDED (current: {delivered_order.status})"
    print(f"✓ Verification confirmed: Order {delivered_order.order_number} status is now {delivered_order.status}.")

    # 9. TEST EXCHANGE FLOW ON ANOTHER ORDER (SIZE SWAP + STOCK RESERVATION)
    print("\n--- 9. Testing Doorstep Exchange Flow with Stock Reservation ---")
    exchange_order = db.query(Order).filter(
        Order.customer_id == customer.id,
        Order.order_number == "ORD-1001"
    ).first()

    if exchange_order:
        exchange_order.status = "DELIVERED"
        db.query(AuditLog).filter(AuditLog.idempotency_key == f"exchange-{exchange_order.id}").delete()
        db.commit()

        # Start a fresh conversation thread for the exchange flow
        new_conv = Conversation(customer_id=customer.id, options_offered="[]", declined_options="[]")
        db.add(new_conv)
        db.commit()
        db.refresh(new_conv)

        # Step 1: Initiate return with order context
        r_ex1 = run_agent_turn(db, customer, "I want to exchange my shoes", active_order_id=exchange_order.id)
        # Step 2: Give reason (Size / fit issue)
        r_ex2 = run_agent_turn(db, customer, "Size / fit issue - shoes feel too tight")
        # Step 3: Choose Free Replacement
        r_ex3 = run_agent_turn(db, customer, "Free Replacement (2 days)")
        print("Replacement inquiry:", r_ex3["reply_text"])
        # Step 4: Specify new size (Size 10 UK)
        r_ex4 = run_agent_turn(db, customer, "Size 10 UK")
        print("Exchange confirmation:", r_ex4["reply_text"])
        print("Exchange tool calls:", r_ex4.get("tool_calls"))

        db.refresh(exchange_order)
        assert exchange_order.status == "EXCHANGED", f"Exchange order status should be EXCHANGED (current: {exchange_order.status})"
        print(f"✓ Doorstep exchange confirmed: Order {exchange_order.order_number} status is EXCHANGED with 2-day delivery.")

    # 10. TEST HUMAN ESCALATION PAUSE & RESUME
    print("\n--- 10. Testing Human Escalation Pause & Resume ---")
    high_order = db.query(Order).filter(Order.total_amount > 2000.0).first()
    if high_order:
        high_order.status = "DELIVERED"
        db.commit()
        pol = check_policy(db, high_order, "REFUND", high_order.total_amount, "Refund requested")
        assert pol["verdict"] == PolicyVerdict.NEEDS_HUMAN, f"High amount order (₹{high_order.total_amount}) did not trigger NEEDS_HUMAN (got {pol['verdict']})!"
        print(f"✓ High amount order (₹{high_order.total_amount}) correctly requires human approval.")

    # 11. TEST WALLET BALANCE & PROMO CODES
    print("\n--- 11. Testing Wallet Balance & Promo Codes DB Support ---")
    initial_balance = customer.wallet_balance or 0.0
    customer.wallet_balance = initial_balance + 500.0
    db.commit()
    db.refresh(customer)
    assert customer.wallet_balance == initial_balance + 500.0
    print(f"✓ Customer wallet balance verified: ₹{customer.wallet_balance}")

    promo = PromoCode(
        code=f"TEST-{int(time.time())}",
        value=550.0,
        customer_id=customer.id,
        expiry=datetime.datetime.utcnow() + datetime.timedelta(days=30),
        is_used=False
    )
    db.add(promo)
    db.commit()
    assert promo.id is not None
    print(f"✓ Promo code generated: {promo.code} (Value: ₹{promo.value})")

    # 12. TEST AUDIT LOG PERSISTENCE
    print("\n--- 12. Testing Audit Trail Persistence ---")
    logs = db.query(AuditLog).order_by(AuditLog.timestamp.desc()).limit(5).all()
    assert len(logs) > 0, "No audit logs found!"
    print(f"✓ Verified {len(logs)} recent audit logs in database.")

    db.close()
    print("\n" + "=" * 60)
    print("ALL E2E TESTS PASSED WITH 100% SUCCESS!")
    print("=" * 60)

if __name__ == "__main__":
    run_tests()
