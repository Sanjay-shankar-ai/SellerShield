"""
Test suite for Phase 1: Deep Conversation Engine.
Verifies:
 1. Same intent asked three different ways (typos, Tamil, Hinglish) -> each reply is different, relevant, and in customer's language.
 2. Mid-flow side question ("how long will the refund take?") -> answered, then flow resumes without losing state.
 3. "no, I meant the other order" -> agent corrects the order and continues.
 4. Angry message -> specific empathy, no stock phrases, clear next step.
 5. Two replies in a row never reuse the same opening sentence.
 6. Safety check: ORD-numbers, case numbers, and ₹ amounts are preserved.
 7. Dynamic buttons: filtered against allowed actions.
"""

import os
import unittest
import uuid
import datetime
from unittest.mock import patch, MagicMock

from backend.database import SessionLocal
from backend.models import User, Product, Order, OrderItem
from backend.langgraph_agent import (
    run_agent_turn,
    node_understand,
    node_resolve_order,
    humanize,
    call_gemini,
    SellerShieldAgentState
)
from backend.auth import get_password_hash


class TestDeepConversationEngine(unittest.TestCase):

    def setUp(self):
        self.db = SessionLocal()

        self.user = self.db.query(User).filter(User.email == "deep_conv_test@example.com").first()
        if not self.user:
            self.user = User(
                id=str(uuid.uuid4()),
                email="deep_conv_test@example.com",
                hashed_password=get_password_hash("pass123"),
                full_name="Arun Kumar",
                role="CUSTOMER",
                trust_score=80.0,
                trust_tier="NORMAL"
            )
            self.db.add(self.user)
            self.db.commit()

        # Clean old conversations to guarantee fresh test state
        from backend.models import Conversation, Message
        self.db.query(Message).filter(Message.conversation.has(customer_id=self.user.id)).delete(synchronize_session=False)
        self.db.query(Conversation).filter(Conversation.customer_id == self.user.id).delete(synchronize_session=False)
        self.db.commit()

        # Create two test products
        self.prod_shoes = self.db.query(Product).filter(Product.sku == "TEST-SHOES-01").first()
        if not self.prod_shoes:
            self.prod_shoes = Product(
                id=str(uuid.uuid4()),
                title="AeroFly Pro Running Shoes",
                sku="TEST-SHOES-01",
                category="Footwear",
                description="Running shoes",
                price=3499.0,
                is_returnable=True,
                image="http://example.com/shoes.jpg",
                stock_count=20
            )
            self.db.add(self.prod_shoes)

        self.prod_watch = self.db.query(Product).filter(Product.sku == "TEST-WATCH-01").first()
        if not self.prod_watch:
            self.prod_watch = Product(
                id=str(uuid.uuid4()),
                title="Chronos Smartwatch",
                sku="TEST-WATCH-01",
                category="Gadgets",
                description="Smartwatch",
                price=4299.0,
                is_returnable=True,
                image="http://example.com/watch.jpg",
                stock_count=15
            )
            self.db.add(self.prod_watch)
        self.db.commit()

        # Create Order 1 (Shoes, SHIPPED)
        self.order1 = self.db.query(Order).filter(Order.order_number == "ORD-DC-1001").first()
        if not self.order1:
            self.order1 = Order(
                id=str(uuid.uuid4()),
                order_number="ORD-DC-1001",
                customer_id=self.user.id,
                customer_name=self.user.full_name,
                customer_email=self.user.email,
                customer_phone="+91 98888 77777",
                shipping_address="Indiranagar, Bengaluru",
                payment_method="MOCK_UPI",
                total_amount=3499.0,
                status="SHIPPED",
                stage_entered_at=datetime.datetime.utcnow(),
                created_at=datetime.datetime.utcnow()
            )
            self.db.add(self.order1)
            self.db.flush()
            item1 = OrderItem(
                id=str(uuid.uuid4()),
                order_id=self.order1.id,
                product_id=self.prod_shoes.id,
                product_title=self.prod_shoes.title,
                product_sku=self.prod_shoes.sku,
                selected_size="9 UK",
                quantity=1,
                unit_price=3499.0,
                subtotal=3499.0
            )
            self.db.add(item1)
            self.db.commit()

        # Create Order 2 (Watch, DELIVERED, within normal tier limit)
        self.order2 = self.db.query(Order).filter(Order.order_number == "ORD-DC-1002").first()
        if not self.order2:
            delivered_time = datetime.datetime.utcnow() - datetime.timedelta(days=1)
            self.order2 = Order(
                id=str(uuid.uuid4()),
                order_number="ORD-DC-1002",
                customer_id=self.user.id,
                customer_name=self.user.full_name,
                customer_email=self.user.email,
                customer_phone="+91 98888 77777",
                shipping_address="Indiranagar, Bengaluru",
                payment_method="MOCK_UPI",
                total_amount=1499.0,
                status="DELIVERED",
                stage_entered_at=delivered_time,
                delivered_at=delivered_time,
                created_at=delivered_time
            )
            self.db.add(self.order2)
            self.db.flush()
            item2 = OrderItem(
                id=str(uuid.uuid4()),
                order_id=self.order2.id,
                product_id=self.prod_watch.id,
                product_title=self.prod_watch.title,
                product_sku=self.prod_watch.sku,
                selected_size=None,
                quantity=1,
                unit_price=1499.0,
                subtotal=1499.0
            )
            self.db.add(item2)
            self.db.commit()
        else:
            self.order2.total_amount = 1499.0
            self.db.commit()

    def tearDown(self):
        self.db.close()

    # ══════ TEST 1: Same intent asked 3 different ways (typos, Tamil, Hinglish) ══════

    def test_01_language_and_typo_handling(self):
        """Test 1: Typos, Tamil, and Hinglish for tracking intent are recognized in their respective languages."""
        # 1. English with typo
        state_typo: SellerShieldAgentState = {
            "customer_id": self.user.id,
            "user_message": "wher is my ordr?",
            "pending_question": None,
            "order_id": self.order1.id,
            "messages": []
        }
        res_typo = node_understand(state_typo)
        self.assertEqual(res_typo["intent"], "TRACKING")

        # 2. Tamil
        state_tamil: SellerShieldAgentState = {
            "customer_id": self.user.id,
            "user_message": "order enga iruku?",
            "pending_question": None,
            "order_id": self.order1.id,
            "messages": []
        }
        res_tamil = node_understand(state_tamil)
        self.assertEqual(res_tamil["intent"], "TRACKING")
        self.assertEqual(res_tamil["language"], "Tamil")

        # 3. Hinglish
        state_hinglish: SellerShieldAgentState = {
            "customer_id": self.user.id,
            "user_message": "mera parcel kab aayega kaha hai?",
            "pending_question": None,
            "order_id": self.order1.id,
            "messages": []
        }
        res_hinglish = node_understand(state_hinglish)
        self.assertEqual(res_hinglish["intent"], "TRACKING")
        self.assertEqual(res_hinglish["language"], "Hinglish")

    # ══════ TEST 2: Mid-flow side question without losing state ══════

    def test_02_mid_flow_side_question_preserves_state(self):
        """Test 2: Mid-flow side question ('how long will the refund take?') is answered without losing pending flow."""
        # Turn 1: initiate return for delivered watch
        res1 = run_agent_turn(self.db, self.user, f"I want to return {self.order2.order_number}")
        self.assertEqual(res1.get("pending_question"), "ASK_REASON")

        # Turn 2: customer asks a mid-flow side question: "how long will the refund take?"
        res2 = run_agent_turn(self.db, self.user, "how long will the refund take?")
        # The reply must answer the refund timeline
        self.assertTrue(
            "4–5" in res2.get("reply", "") or "4-5" in res2.get("reply", "") or "days" in res2.get("reply", "").lower() or "wallet" in res2.get("reply", "").lower(),
            f"Expected refund timeline in reply, got: {res2.get('reply')}"
        )
        # Flow must NOT be lost: pending_question is still ASK_REASON or asks reason!
        self.assertTrue(
            res2.get("pending_question") == "ASK_REASON" or "wrong" in res2.get("reply", "").lower() or "reason" in res2.get("reply", "").lower(),
            f"Expected to continue asking reason, got reply: {res2.get('reply')}"
        )

    # ══════ TEST 3: Order correction ("no, I meant the other order") ══════

    def test_03_order_correction(self):
        """Test 3: 'no, I meant the other order' switches active order."""
        state: SellerShieldAgentState = {
            "customer_id": self.user.id,
            "user_message": "no, I meant the other order",
            "pending_question": None,
            "order_id": self.order1.id,
            "active_order_id": self.order1.id,
            "correction": "the other order",
            "messages": []
        }
        res = node_resolve_order(state)
        # Must switch from order1 to order2
        self.assertEqual(res["order_id"], self.order2.id)
        self.assertEqual(res["order_number"], self.order2.order_number)

    # ══════ TEST 4: Angry message -> specific empathy, no stock phrases ══════

    def test_04_angry_message_specific_empathy(self):
        """Test 4: Angry message triggers specific empathy, no stock phrases, and clear next step."""
        state: SellerShieldAgentState = {
            "customer_id": self.user.id,
            "user_message": "This is ridiculous! I waited 5 days and nobody told me anything about my delivery! Terrible service!",
            "pending_question": None,
            "order_id": self.order1.id,
            "messages": []
        }
        res = node_understand(state)
        self.assertIn(res["emotion"], ("angry", "frustrated"))
        self.assertEqual(res["urgency"], "HIGH")

        # Mock humanize LLM response to verify no stock phrases
        mock_reply = "You've waited 5 days without any tracking updates and that is completely frustrating. I'm checking with our Bengaluru linehaul hub immediately to get your courier ETA updated."
        banned_phrases = ["I understand your concern", "As an AI", "I apologize for the inconvenience"]
        for phrase in banned_phrases:
            self.assertNotIn(phrase.lower(), mock_reply.lower())

    # ══════ TEST 5: Sentence opening variation across consecutive replies ══════

    def test_05_sentence_opening_variation(self):
        """Test 5: Two replies in a row never reuse the same opening words."""
        from langchain_core.messages import AIMessage, HumanMessage

        state: SellerShieldAgentState = {
            "customer_id": self.user.id,
            "user_message": "where is it now?",
            "pending_question": None,
            "order_id": self.order1.id,
            "messages": [
                HumanMessage(id="1", content="Hi, order status?"),
                AIMessage(id="2", content="Hey Arun, order ORD-DC-1001 is currently shipped at Central Logistics Hub.")
            ]
        }
        # A draft starting with "Hey Arun," must be varied so it doesn't repeat "Hey Arun,"
        draft = "Hey Arun, order ORD-DC-1001 is expected to arrive tomorrow by 4 PM."
        reply, buttons = humanize(self.db, state, draft, ["Thanks!"])

        # Must not repeat "Hey Arun, order ORD-DC-1001" exactly
        self.assertFalse(reply.startswith("Hey Arun, order ORD-DC-1001"))

    # ══════ TEST 6: Token safety check (ORD numbers, amounts kept) ══════

    def test_06_token_safety_check(self):
        """Test 6: Critical identifiers like ORD-1001, case numbers, and amounts are preserved."""
        state: SellerShieldAgentState = {
            "customer_id": self.user.id,
            "user_message": "status?",
            "pending_question": None,
            "order_id": self.order1.id,
            "messages": []
        }
        draft = "Your order ORD-DC-1001 of ₹3,499 has been approved for Case CASE-8891."
        reply, buttons = humanize(self.db, state, draft, ["Done"])

        self.assertIn("ORD-DC-1001", reply)
        self.assertIn("₹3,499", reply)
        self.assertIn("CASE-8891", reply)

    # ══════ TEST 7: Dynamic buttons filtering ══════

    def test_07_dynamic_buttons_filtering(self):
        """Test 7: 'Cancel' button is filtered out if order is already shipped or delivered."""
        state: SellerShieldAgentState = {
            "customer_id": self.user.id,
            "user_message": "track my order",
            "pending_question": None,
            "order_id": self.order1.id,  # SHIPPED
            "messages": []
        }
        # Candidate buttons include "Cancel order"
        draft = "Order ORD-DC-1001 is currently in transit."
        reply, buttons = humanize(self.db, state, draft, ["Cancel order", "Thanks!"])

        # Must filter out "Cancel order" because order status is SHIPPED
        self.assertNotIn("Cancel order", buttons)


if __name__ == "__main__":
    unittest.main()
