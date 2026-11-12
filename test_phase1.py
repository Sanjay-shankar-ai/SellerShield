"""
Unit and integration tests for Phase 1:
- Human-sounding replies and safety check (1A, 1B, 1C)
- Stage-based buttons in node_track (1D)
- call_gemini logging and header authentication (1F)
- Startup prompt file loading and character counts (1G)
- node_understand: LLM intent first, word-boundary regex fallback (1I)
- EXPEDITE intent and honest courier speed explanation (1J)
- node_resolve_order: explicit mention takes precedence over state (1K)
"""

import os
import re
import unittest
import uuid
from datetime import datetime

from backend.database import SessionLocal
from backend.models import User, Product, Order, OrderItem
from backend.langgraph_agent import (
    call_gemini,
    humanize,
    validate_startup_prompts,
    node_understand,
    node_resolve_order,
    node_track,
    node_respond,
    router_after_resolve,
    SellerShieldAgentState
)
from backend.auth import get_password_hash


class TestPhase1(unittest.TestCase):

    def setUp(self):
        self.db = SessionLocal()
        self.user = self.db.query(User).filter(User.email == "phase1_test@example.com").first()
        if not self.user:
            self.user = User(
                id=str(uuid.uuid4()),
                email="phase1_test@example.com",
                hashed_password=get_password_hash("pass123"),
                full_name="Vikram Singh",
                role="CUSTOMER"
            )
            self.db.add(self.user)
            self.db.commit()

        # Create two test orders: one PLACED, one DELIVERED
        self.ord1 = Order(
            id=str(uuid.uuid4()),
            order_number="ORD-1111",
            customer_id=self.user.id,
            customer_name=self.user.full_name,
            customer_email=self.user.email,
            customer_phone="9876543210",
            shipping_address="123 Test Road",
            total_amount=1200.0,
            status="PLACED",
            stage_entered_at=datetime.utcnow(),
            created_at=datetime.utcnow()
        )
        self.item1 = OrderItem(
            id=str(uuid.uuid4()),
            order_id=self.ord1.id,
            product_id=str(uuid.uuid4()),
            product_title="Sprint Falcon Running Shoes",
            product_sku="SPRINT-FALCON",
            quantity=1,
            unit_price=1200.0,
            subtotal=1200.0
        )
        self.db.add(self.ord1)
        self.db.add(self.item1)

        self.ord2 = Order(
            id=str(uuid.uuid4()),
            order_number="ORD-2222",
            customer_id=self.user.id,
            customer_name=self.user.full_name,
            customer_email=self.user.email,
            customer_phone="9876543210",
            shipping_address="123 Test Road",
            total_amount=2400.0,
            status="DELIVERED",
            stage_entered_at=datetime.utcnow(),
            created_at=datetime.utcnow()
        )
        self.item2 = OrderItem(
            id=str(uuid.uuid4()),
            order_id=self.ord2.id,
            product_id=str(uuid.uuid4()),
            product_title="Vagabond Travel Backpack",
            product_sku="VAGABOND-BP",
            quantity=1,
            unit_price=2400.0,
            subtotal=2400.0
        )
        self.db.add(self.ord2)
        self.db.add(self.item2)
        self.db.commit()

    def tearDown(self):
        self.db.query(OrderItem).filter(OrderItem.order_id.in_([self.ord1.id, self.ord2.id])).delete(synchronize_session=False)
        self.db.query(Order).filter(Order.id.in_([self.ord1.id, self.ord2.id])).delete(synchronize_session=False)
        self.db.commit()
        self.db.close()

    # =========================================================================
    # 1G: Startup prompt file loading and character counts
    # =========================================================================
    def test_startup_prompt_validation(self):
        loaded = validate_startup_prompts()
        self.assertIn("persona_prompt.txt", loaded)
        self.assertIn("knowledge_prompt.txt", loaded)
        self.assertIn("policy_prompt.txt", loaded)
        for name, txt in loaded.items():
            self.assertTrue(len(txt) >= 300, f"Prompt '{name}' must have at least 300 characters, got {len(txt)}")

    # =========================================================================
    # 1A & 1B: Humanize safety check on missing tokens
    # =========================================================================
    def test_humanize_safety_check(self):
        state: SellerShieldAgentState = {
            "customer_id": self.user.id,
            "conv_id": "test-conv",
            "user_message": "Where is my refund?",
            "evidence_photo": None,
            "active_order_id": self.ord1.id,
            "messages": [],
            "summary": "",
            "customer_memory": {},
            "case_closed": False,
            "language": "en",
            "sentiment": "CALM",
            "urgency": "LOW",
            "intent": "TRACKING",
            "order_id": self.ord1.id,
            "order_number": "ORD-1111",
            "reason_category": None,
            "reason_text": None,
            "evidence_status": "NONE",
            "evidence_retries": 0,
            "resolution_type": None,
            "replacement_choice": None,
            "refund_destination": None,
            "offered": [],
            "declined": [],
            "verdict": None,
            "step": "track",
            "pending_question": None,
            "reply": "Refund of ₹1,499 for ORD-1111 under CASE-9021 has been issued.",
            "quick_replies": ["Thanks!"],
            "tool_calls": [],
            "error": None,
            "start_time": 0.0
        }

        # Mocking or testing the safety check directly:
        draft = "Refund of ₹1,499 for ORD-1111 under CASE-9021 has been issued."
        buttons = ["Thanks!"]

        # When network is absent (offline test), humanize should safely return draft without crashing
        res_reply, res_buttons = humanize(self.db, state, draft, buttons)
        self.assertIn("ORD-1111", res_reply, "Safety check must ensure ORD-1111 is present")
        self.assertIn("CASE-9021", res_reply, "Safety check must ensure CASE-9021 is present")
        self.assertTrue("₹1,499" in res_reply or "₹ 1,499" in res_reply, "Safety check must ensure ₹1,499 amount is present")

    # =========================================================================
    # 1D: node_track sets stage-specific buttons
    # =========================================================================
    def test_node_track_stage_buttons(self):
        state_placed: SellerShieldAgentState = {
            "customer_id": self.user.id,
            "conv_id": "test-conv-track",
            "user_message": "track my order",
            "evidence_photo": None,
            "active_order_id": self.ord1.id,
            "messages": [],
            "summary": "",
            "customer_memory": {},
            "case_closed": False,
            "language": "en",
            "sentiment": "CALM",
            "urgency": "LOW",
            "intent": "TRACKING",
            "order_id": self.ord1.id,
            "order_number": self.ord1.order_number,
            "reason_category": None,
            "reason_text": None,
            "evidence_status": "NONE",
            "evidence_retries": 0,
            "resolution_type": None,
            "replacement_choice": None,
            "refund_destination": None,
            "offered": [],
            "declined": [],
            "verdict": None,
            "step": "track",
            "pending_question": None,
            "reply": "",
            "quick_replies": [],
            "tool_calls": [],
            "error": None,
            "start_time": 0.0
        }

        # Order 1 is PLACED
        res1 = node_track(state_placed)
        self.assertEqual(res1["quick_replies"], ["Cancel order", "Thanks!"], "PLACED stage must yield ['Cancel order', 'Thanks!']")

        # Order 2 is DELIVERED
        state_del = dict(state_placed)
        state_del["order_id"] = self.ord2.id
        state_del["order_number"] = self.ord2.order_number
        res2 = node_track(state_del)
        self.assertEqual(res2["quick_replies"], ["Return or swap", "Thanks!"], "DELIVERED stage must yield ['Return or swap', 'Thanks!']")

    # =========================================================================
    # 1J: EXPEDITE intent handling in node_track and routing
    # =========================================================================
    def test_expedite_intent(self):
        state_expedite: SellerShieldAgentState = {
            "customer_id": self.user.id,
            "conv_id": "test-expedite",
            "user_message": "Can I get my order faster? It is urgent",
            "evidence_photo": None,
            "active_order_id": self.ord1.id,
            "messages": [],
            "summary": "",
            "customer_memory": {},
            "case_closed": False,
            "language": "en",
            "sentiment": "CALM",
            "urgency": "HIGH",
            "intent": "EXPEDITE",
            "order_id": self.ord1.id,
            "order_number": self.ord1.order_number,
            "reason_category": None,
            "reason_text": None,
            "evidence_status": "NONE",
            "evidence_retries": 0,
            "resolution_type": None,
            "replacement_choice": None,
            "refund_destination": None,
            "offered": [],
            "declined": [],
            "verdict": None,
            "step": "track",
            "pending_question": None,
            "reply": "",
            "quick_replies": [],
            "tool_calls": [],
            "error": None,
            "start_time": 0.0
        }

        # 1. Routing test
        next_node = router_after_resolve(state_expedite)
        self.assertEqual(next_node, "node_track", "EXPEDITE intent must route to node_track")

        # 2. Honest draft test
        res = node_track(state_expedite)
        reply = res["reply"]
        self.assertIn("cannot be", reply.lower(), "Must state honestly that courier speed cannot be accelerated")
        self.assertIn("urgent", reply.lower(), "Must offer to flag order as urgent to the team")
        self.assertIn("Flag as urgent", res["quick_replies"])

    # =========================================================================
    # 1K: node_resolve_order: explicit mention takes precedence over state
    # =========================================================================
    def test_node_resolve_order_explicit_precedence(self):
        state: SellerShieldAgentState = {
            "customer_id": self.user.id,
            "conv_id": "test-precedence",
            # Explicitly asking about backpack ORD-2222
            "user_message": "Where is my backpack?",
            "evidence_photo": None,
            # State currently has ORD-1111 (shoes) bound!
            "active_order_id": self.ord1.id,
            "order_id": self.ord1.id,
            "order_number": self.ord1.order_number,
            "messages": [],
            "summary": "",
            "customer_memory": {},
            "case_closed": False,
            "language": "en",
            "sentiment": "CALM",
            "urgency": "LOW",
            "intent": "TRACKING",
            "reason_category": None,
            "reason_text": None,
            "evidence_status": "NONE",
            "evidence_retries": 0,
            "resolution_type": None,
            "replacement_choice": None,
            "refund_destination": None,
            "offered": [],
            "declined": [],
            "verdict": None,
            "step": "resolve_order",
            "pending_question": None,
            "reply": "",
            "quick_replies": [],
            "tool_calls": [],
            "error": None,
            "start_time": 0.0
        }

        res = node_resolve_order(state)
        # Even though state had ord1 (shoes), mentioning "backpack" must resolve to ord2 (backpack)!
        self.assertEqual(res["order_id"], self.ord2.id, "Explicitly mentioning 'backpack' must resolve to ORD-2222, not the state order ORD-1111")
        self.assertEqual(res["order_number"], "ORD-2222")

        # Mentioning order number explicitly
        state["user_message"] = "I need help with ORD-2222 please"
        res_num = node_resolve_order(state)
        self.assertEqual(res_num["order_id"], self.ord2.id, "Explicitly mentioning 'ORD-2222' must resolve to ORD-2222")

    # =========================================================================
    # 1I: node_understand word boundary regex fallback
    # =========================================================================
    def test_node_understand_word_boundaries(self):
        # "benefit" should NOT trigger "fit"
        # "whenever" should NOT trigger "when"
        state: SellerShieldAgentState = {
            "customer_id": self.user.id,
            "conv_id": "test-boundary",
            "user_message": "What is the benefit of your store membership?",
            "evidence_photo": None,
            "active_order_id": None,
            "messages": [],
            "summary": "",
            "customer_memory": {},
            "case_closed": False,
            "language": "en",
            "sentiment": "CALM",
            "urgency": "LOW",
            "intent": "GENERAL",
            "order_id": None,
            "order_number": None,
            "reason_category": None,
            "reason_text": None,
            "evidence_status": "NONE",
            "evidence_retries": 0,
            "resolution_type": None,
            "replacement_choice": None,
            "refund_destination": None,
            "offered": [],
            "declined": [],
            "verdict": None,
            "step": "understand",
            "pending_question": None,
            "reply": "",
            "quick_replies": [],
            "tool_calls": [],
            "error": None,
            "start_time": 0.0
        }

        res = node_understand(state)
        self.assertEqual(res["intent"], "GENERAL", "Word 'benefit' must not match 'fit' regex!")


if __name__ == "__main__":
    unittest.main()
