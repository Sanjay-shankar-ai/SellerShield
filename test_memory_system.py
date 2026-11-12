"""
Unit tests for SellerShield Conversation Summary & Customer Memory System.

Tests cover:
1. Messages > 12 triggers summarization; last 6 messages preserved; older removed via RemoveMessage.
2. Tool results override stale memory in prompt composition and policy engine execution.
3. Customer A's memory is never leaked to Customer B (strict customer_id isolation).
4. Sensitive data (cards, OTPs, passwords, phones, addresses) is redacted before memory save.
"""

import os
import json
import uuid
import unittest
from datetime import datetime

from langchain_core.messages import HumanMessage, AIMessage, RemoveMessage

from backend.database import SessionLocal, Base, engine
from backend.models import User, Product, Order, OrderItem, CustomerMemory, Setting, AuditLog
from backend.langgraph_agent import (
    sanitize_memory_text,
    get_composed_system_prompt,
    node_load_memory,
    node_summarize_memory,
    node_save_memory,
    node_policy_check,
    node_understand,
    SUMMARIZE_THRESHOLD,
    MESSAGES_TO_KEEP,
    SellerShieldAgentState
)
from backend.auth import get_password_hash


class TestMemorySystem(unittest.TestCase):

    def setUp(self):
        self.db = SessionLocal()
        # Seed test customers
        self.customer_a = self.db.query(User).filter(User.email == "test_customer_a@example.com").first()
        if not self.customer_a:
            self.customer_a = User(
                id=str(uuid.uuid4()),
                email="test_customer_a@example.com",
                hashed_password=get_password_hash("password123"),
                full_name="Priya Sharma",
                role="CUSTOMER"
            )
            self.db.add(self.customer_a)

        self.customer_b = self.db.query(User).filter(User.email == "test_customer_b@example.com").first()
        if not self.customer_b:
            self.customer_b = User(
                id=str(uuid.uuid4()),
                email="test_customer_b@example.com",
                hashed_password=get_password_hash("password123"),
                full_name="Rahul Verma",
                role="CUSTOMER"
            )
            self.db.add(self.customer_b)

        self.db.commit()

        # Clean any prior memory
        self.db.query(CustomerMemory).filter(
            CustomerMemory.customer_id.in_([self.customer_a.id, self.customer_b.id])
        ).delete(synchronize_session=False)
        self.db.commit()

    def tearDown(self):
        try:
            self.db.rollback()
            self.db.query(CustomerMemory).filter(
                CustomerMemory.customer_id.in_([self.customer_a.id, self.customer_b.id])
            ).delete(synchronize_session=False)
            self.db.commit()
        except Exception:
            self.db.rollback()
        finally:
            self.db.close()

    # =========================================================================
    # Test 1: Messages > 12 triggers summarization; last 6 preserved; older removed
    # =========================================================================
    def test_summarization_threshold_and_pruning(self):
        # Case A: 10 messages (<= SUMMARIZE_THRESHOLD = 12) -> should NOT trigger summarization
        msgs_under = [
            HumanMessage(content=f"Customer message {i}", id=f"m-{i}")
            for i in range(10)
        ]
        state_under: SellerShieldAgentState = {
            "customer_id": self.customer_a.id,
            "conv_id": "test-conv-1",
            "user_message": "Hello",
            "evidence_photo": None,
            "active_order_id": None,
            "messages": msgs_under,
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
            "step": "respond",
            "pending_question": None,
            "reply": "Hi!",
            "quick_replies": [],
            "tool_calls": [],
            "error": None,
            "start_time": 0.0
        }
        res_under = node_summarize_memory(state_under)
        self.assertNotIn("messages", res_under, "Under threshold should not prune messages")
        self.assertNotIn("summary", res_under, "Under threshold should not update summary")

        # Case B: 14 messages (> SUMMARIZE_THRESHOLD = 12) -> triggers summarization
        msgs_over = [
            HumanMessage(content=f"Message turn {i}", id=f"msg-id-{i}")
            for i in range(14)
        ]
        state_over = dict(state_under)
        state_over["messages"] = msgs_over
        state_over["summary"] = "Existing previous summary."

        res_over = node_summarize_memory(state_over)
        self.assertIn("summary", res_over, "Summarization should produce an updated summary")
        self.assertTrue(len(res_over["summary"]) > 0, "Summary should not be empty")

        # Verify pruning with RemoveMessage
        self.assertIn("messages", res_over, "Summarization must return pruned messages list")
        pruned_msgs = res_over["messages"]

        # Exactly 14 - 6 = 8 messages should be removed
        expected_remove_count = 14 - MESSAGES_TO_KEEP
        self.assertEqual(len(pruned_msgs), expected_remove_count, f"Should remove {expected_remove_count} older messages")

        # Verify each item is a RemoveMessage with correct id matching the first 8 messages
        for idx, rm in enumerate(pruned_msgs):
            self.assertIsInstance(rm, RemoveMessage)
            self.assertEqual(rm.id, f"msg-id-{idx}")

    # =========================================================================
    # Test 2: Tool results override stale memory in prompts and policy checks
    # =========================================================================
    def test_tool_results_override_stale_memory(self):
        stale_memory = {
            "preferred_language": "English",
            "usual_size": "8 UK",
            "tone_preference": "polite",
            "past_issues": ["Refund requested for order ORD-999"]
        }
        stale_summary = "Customer claims their shoes arrived damaged and wants a replacement size 8 UK."

        prompt = get_composed_system_prompt(
            db=self.db,
            node_instruction="Verify policy rules and return tools.",
            summary=stale_summary,
            customer_memory=stale_memory
        )

        # 1. Prompt must include grounding directive
        self.assertIn("CONVERSATION SO FAR: " + stale_summary, prompt)
        self.assertIn("Memory is background only", prompt)
        self.assertIn("If memory and a tool disagree, trust the tool.", prompt)

        # 2. Policy engine test: Even if stale summary claims "delivered and wants replacement",
        # a LIVE order with status 'PLACED' is not delivered, so policy check must reject return!
        test_product = self.db.query(Product).first()
        placed_order = Order(
            id=str(uuid.uuid4()),
            order_number=f"TEST-ORD-{int(datetime.utcnow().timestamp())}",
            customer_id=self.customer_a.id,
            customer_name=self.customer_a.full_name,
            customer_email=self.customer_a.email,
            customer_phone="9876543210",
            shipping_address="123 Test St",
            payment_method="COD",
            total_amount=1500.0,
            status="PLACED",  # Not delivered!
            stage_entered_at=datetime.utcnow(),
            created_at=datetime.utcnow()
        )
        self.db.add(placed_order)
        self.db.commit()

        state: SellerShieldAgentState = {
            "customer_id": self.customer_a.id,
            "conv_id": "test-conv-stale",
            "user_message": "I want a refund now",
            "evidence_photo": None,
            "active_order_id": placed_order.id,
            "messages": [],
            "summary": stale_summary,
            "customer_memory": stale_memory,
            "case_closed": False,
            "language": "en",
            "sentiment": "CALM",
            "urgency": "LOW",
            "intent": "RETURN_REFUND_EXCHANGE",
            "order_id": placed_order.id,
            "order_number": placed_order.order_number,
            "reason_category": "Defective or not working",
            "reason_text": "Item defective",
            "evidence_status": "NONE",
            "evidence_retries": 0,
            "resolution_type": "REFUND",
            "replacement_choice": None,
            "refund_destination": "ORIGINAL",
            "offered": [],
            "declined": [],
            "verdict": None,
            "step": "policy_check",
            "pending_question": None,
            "reply": "",
            "quick_replies": [],
            "tool_calls": [],
            "error": None,
            "start_time": 0.0
        }

        # Live policy check must DENY because order is PLACED, not DELIVERED
        # (ignoring any stale memory saying "replacement approved")
        policy_res = node_policy_check(state)
        self.assertEqual(policy_res.get("verdict"), "DENY", "Live order status PLACED must deny return despite stale memory")

        # Clean up test order
        self.db.delete(placed_order)
        self.db.commit()

    # =========================================================================
    # Test 3: Customer A's memory is never leaked to Customer B (Isolation)
    # =========================================================================
    def test_customer_isolation(self):
        # Create memory for Customer A
        mem_a = CustomerMemory(
            id=str(uuid.uuid4()),
            customer_id=self.customer_a.id,
            preferred_language="Tamil",
            usual_size="9 UK",
            tone_preference="direct",
            past_issues=json.dumps(["Damaged shoes replaced"])
        )
        self.db.add(mem_a)
        self.db.commit()

        # Load memory for Customer B
        state_b: SellerShieldAgentState = {
            "customer_id": self.customer_b.id,
            "conv_id": "test-b-conv",
            "user_message": "Hello",
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
            "step": "load_memory",
            "pending_question": None,
            "reply": "",
            "quick_replies": [],
            "tool_calls": [],
            "error": None,
            "start_time": 0.0
        }

        loaded_b = node_load_memory(state_b)
        mem_b_dict = loaded_b.get("customer_memory", {})

        # Customer B must NOT have Customer A's data
        self.assertEqual(mem_b_dict, {}, "Customer B must have empty memory, not Customer A's")
        self.assertNotEqual(mem_b_dict.get("preferred_language"), "Tamil")
        self.assertNotEqual(mem_b_dict.get("usual_size"), "9 UK")

        # Load memory for Customer A
        state_a = dict(state_b)
        state_a["customer_id"] = self.customer_a.id
        loaded_a = node_load_memory(state_a)
        mem_a_dict = loaded_a.get("customer_memory", {})

        # Customer A must see their own data
        self.assertEqual(mem_a_dict.get("preferred_language"), "Tamil")
        self.assertEqual(mem_a_dict.get("usual_size"), "9 UK")
        self.assertEqual(mem_a_dict.get("tone_preference"), "direct")

    # =========================================================================
    # Test 4: Sensitive data (cards, OTPs, passwords, phones, addresses) redacted
    # =========================================================================
    def test_sensitive_data_redaction(self):
        # 1. Card number redaction
        text_card = "Please refund to my card 4532-1488-1294-8492 right away."
        clean_card = sanitize_memory_text(text_card)
        self.assertNotIn("4532-1488-1294-8492", clean_card)
        self.assertIn("[REDACTED_CARD]", clean_card)

        # 2. OTP redaction
        text_otp1 = "My OTP is 482910 for payment authorization."
        clean_otp1 = sanitize_memory_text(text_otp1)
        self.assertNotIn("482910", clean_otp1)
        self.assertIn("[REDACTED_OTP]", clean_otp1)

        text_otp2 = "pin: 8392"
        clean_otp2 = sanitize_memory_text(text_otp2)
        self.assertNotIn("8392", clean_otp2)
        self.assertIn("[REDACTED_OTP]", clean_otp2)

        # 3. Password redaction
        text_pwd = "My account password is SecretPassword123! please fix it."
        clean_pwd = sanitize_memory_text(text_pwd)
        self.assertNotIn("SecretPassword123!", clean_pwd)
        self.assertIn("[REDACTED_PASSWORD]", clean_pwd)

        # 4. Phone number redaction
        text_phone = "Contact me at +91 9876543210 for doorstep pickup."
        clean_phone = sanitize_memory_text(text_phone)
        self.assertNotIn("9876543210", clean_phone)
        self.assertIn("[REDACTED_PHONE]", clean_phone)

        # 5. Full address & Pincode redaction
        text_addr = "Shipping address: Flat 402, Green Valley Apartments, MG Road, Pincode 560001"
        clean_addr = sanitize_memory_text(text_addr)
        self.assertNotIn("Flat 402", clean_addr)
        self.assertNotIn("MG Road", clean_addr)
        self.assertIn("[REDACTED_ADDRESS]", clean_addr)

    # =========================================================================
    # Test 5: save_memory runs on case_closed, merges facts, skips if nothing new
    # =========================================================================
    def test_save_memory_node(self):
        state_closed: SellerShieldAgentState = {
            "customer_id": self.customer_a.id,
            "conv_id": "test-conv-closed",
            "user_message": "Thank you for the refund to my wallet!",
            "evidence_photo": None,
            "active_order_id": None,
            "messages": [
                HumanMessage(content="Need refund for defective shoes", id="m1"),
                AIMessage(content="I have processed a full refund of 1,500 to your wallet", id="m2")
            ],
            "summary": "Customer requested refund for defective shoes. Full wallet refund issued.",
            "customer_memory": {},
            "case_closed": True,  # Case closed!
            "language": "en",
            "sentiment": "HAPPY",
            "urgency": "LOW",
            "intent": "RETURN_REFUND_EXCHANGE",
            "order_id": "ord-123",
            "order_number": "ORD-123",
            "reason_category": "Defective or not working",
            "reason_text": "Sole cracked",
            "evidence_status": "VERIFIED",
            "evidence_retries": 1,
            "resolution_type": "REFUND",
            "replacement_choice": {"size": "9 UK"},
            "refund_destination": "WALLET",
            "offered": ["REPLACEMENT", "REFUND"],
            "declined": ["REPLACEMENT"],
            "verdict": "AUTO_APPROVE",
            "step": "act",
            "pending_question": None,
            "reply": "Refund done!",
            "quick_replies": [],
            "tool_calls": [],
            "error": None,
            "start_time": 0.0
        }

        # 1. First save: writes new memory row
        res_save = node_save_memory(state_closed)
        self.assertIn("customer_memory", res_save)
        mem_saved = res_save["customer_memory"]
        self.assertEqual(mem_saved.get("usual_size"), "9 UK")
        self.assertTrue(len(mem_saved.get("past_issues", [])) > 0)

        # Check DB row
        db_mem = self.db.query(CustomerMemory).filter(CustomerMemory.customer_id == self.customer_a.id).first()
        self.assertIsNotNone(db_mem)
        self.assertEqual(db_mem.usual_size, "9 UK")

        # 2. Second save with identical state: skips DB write ("Skip the write if nothing new")
        updated_at_before = db_mem.updated_at
        state_closed["customer_memory"] = mem_saved
        res_save_again = node_save_memory(state_closed)
        self.assertEqual(res_save_again["customer_memory"], mem_saved)

        # DB row was not unnecessarily updated
        self.db.refresh(db_mem)
        self.assertEqual(db_mem.updated_at, updated_at_before)

    # =========================================================================
    # Test 6: API endpoints for customer memory retrieval, clear, and admin view
    # =========================================================================
    def test_api_memory_endpoints(self):
        from backend.main import get_my_customer_memory, clear_customer_memory, get_admin_customer_memory

        # Create memory record for Customer A
        mem_a = CustomerMemory(
            id=str(uuid.uuid4()),
            customer_id=self.customer_a.id,
            preferred_language="en",
            usual_size="9 UK",
            tone_preference="polite",
            past_issues=json.dumps(["Initial shoe return processed"])
        )
        self.db.add(mem_a)
        self.db.commit()

        # 1. GET /api/customer/memory (customer retrieves own memory)
        resp_get = get_my_customer_memory(db=self.db, current_user=self.customer_a)
        self.assertIn("customer_memory", resp_get)
        self.assertEqual(resp_get["customer_memory"]["usual_size"], "9 UK")
        self.assertEqual(resp_get["customer_memory"]["preferred_language"], "en")

        # 2. GET /api/admin/customer-memory (admin lists all memories)
        admin_user = self.db.query(User).filter(User.role == "ADMIN").first()
        if not admin_user:
            admin_user = User(
                id=str(uuid.uuid4()),
                email="admin_test@sellershield.com",
                hashed_password=get_password_hash("admin123"),
                full_name="Admin Maya",
                role="ADMIN"
            )
            self.db.add(admin_user)
            self.db.commit()

        admin_data = get_admin_customer_memory(db=self.db, admin=admin_user)
        self.assertIn("memories", admin_data)
        matching = [m for m in admin_data["memories"] if m["customer_id"] == self.customer_a.id]
        self.assertTrue(len(matching) > 0)
        self.assertEqual(matching[0]["usual_size"], "9 UK")

        # 3. POST /api/customer/memory/clear (wipe own memory under privacy)
        resp_clear = clear_customer_memory(db=self.db, current_user=self.customer_a)
        self.assertTrue(resp_clear["success"])

        # Verify memory is wiped in DB
        db_mem_after = self.db.query(CustomerMemory).filter(CustomerMemory.customer_id == self.customer_a.id).first()
        self.assertIsNone(db_mem_after, "Customer memory should be completely wiped after clear")

        # Verify GET returns empty memory after clear
        resp_get_after = get_my_customer_memory(db=self.db, current_user=self.customer_a)
        self.assertEqual(resp_get_after["customer_memory"], {})


if __name__ == "__main__":
    unittest.main()
