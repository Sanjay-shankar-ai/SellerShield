"""
Unit tests for Phase 1: Store Policy, Policy Engine (R1 through R10), and Dynamic Prompt Formatting.
"""

import os
import unittest
import uuid
import datetime
from sqlalchemy.orm import Session

from backend.database import SessionLocal
from backend.models import User, Product, Order, OrderItem, Setting, AuditLog
from backend.policy_engine import (
    check_policy,
    compute_trust,
    get_setting_value,
    PolicyVerdict,
    ACCEPTED_REASON_CATEGORIES
)
from backend.langgraph_agent import compose_system_prompt
from backend.auth import get_password_hash


class TestStorePolicyPhase1(unittest.TestCase):

    def setUp(self):
        self.db: Session = SessionLocal()

        # Create or fetch clean test users with distinct trust tiers
        self.high_user = self.db.query(User).filter(User.email == "policy_high@example.com").first()
        if not self.high_user:
            self.high_user = User(
                id=str(uuid.uuid4()),
                email="policy_high@example.com",
                hashed_password=get_password_hash("pass123"),
                full_name="High Trust User",
                role="CUSTOMER",
                trust_score=95.0,
                trust_tier="HIGH",
                latitude=12.9716,
                longitude=77.5946
            )
            self.db.add(self.high_user)

        self.normal_user = self.db.query(User).filter(User.email == "policy_normal@example.com").first()
        if not self.normal_user:
            self.normal_user = User(
                id=str(uuid.uuid4()),
                email="policy_normal@example.com",
                hashed_password=get_password_hash("pass123"),
                full_name="Normal Trust User",
                role="CUSTOMER",
                trust_score=65.0,
                trust_tier="NORMAL",
                latitude=12.9352,
                longitude=77.6245
            )
            self.db.add(self.normal_user)

        self.risky_user = self.db.query(User).filter(User.email == "policy_risky@example.com").first()
        if not self.risky_user:
            self.risky_user = User(
                id=str(uuid.uuid4()),
                email="policy_risky@example.com",
                hashed_password=get_password_hash("pass123"),
                full_name="Risky User",
                role="CUSTOMER",
                trust_score=20.0,
                trust_tier="RISKY",
                latitude=12.9141,
                longitude=77.6109
            )
            self.db.add(self.risky_user)

        # Create standard returnable product
        self.returnable_prod = self.db.query(Product).filter(Product.sku == "TEST-SHOE-01").first()
        if not self.returnable_prod:
            self.returnable_prod = Product(
                id=str(uuid.uuid4()),
                title="Pro Running Shoes",
                sku="TEST-SHOE-01",
                category="Footwear",
                description="Test running shoes",
                price=1500.0,
                is_returnable=True,
                image="http://example.com/shoe.jpg",
                stock_count=20
            )
            self.db.add(self.returnable_prod)

        # Create intimate hygiene non-returnable product
        self.hygiene_prod = self.db.query(Product).filter(Product.sku == "TEST-HYGIENE-01").first()
        if not self.hygiene_prod:
            self.hygiene_prod = Product(
                id=str(uuid.uuid4()),
                title="Organic Cotton Undergarments",
                sku="TEST-HYGIENE-01",
                category="Intimates",
                description="Intimate hygiene product",
                price=800.0,
                is_returnable=False,
                image="http://example.com/hygiene.jpg",
                stock_count=20
            )
            self.db.add(self.hygiene_prod)

        self.db.commit()

    def tearDown(self):
        self.db.close()

    def _create_test_order(self, customer, product, status="DELIVERED", delivered_days_ago=2, total_amount=1500.0, delivery_fee=0.0):
        delivered_at = datetime.datetime.utcnow() - datetime.timedelta(days=delivered_days_ago)
        order = Order(
            id=str(uuid.uuid4()),
            order_number=f"ORD-TEST-{uuid.uuid4().hex[:6].upper()}",
            customer_id=customer.id,
            customer_name=customer.full_name,
            customer_email=customer.email,
            customer_phone="+91 99999 88888",
            shipping_address="123 Test St, Bengaluru",
            payment_method="MOCK_UPI",
            total_amount=total_amount,
            delivery_fee=delivery_fee,
            status=status,
            stage_entered_at=delivered_at,
            delivered_at=delivered_at if status == "DELIVERED" else None,
            created_at=delivered_at
        )
        self.db.add(order)
        self.db.flush()

        item = OrderItem(
            id=str(uuid.uuid4()),
            order_id=order.id,
            product_id=product.id,
            product_title=product.title,
            product_sku=product.sku,
            selected_size="9 UK",
            quantity=1,
            unit_price=product.price,
            subtotal=product.price
        )
        self.db.add(item)
        self.db.commit()
        self.db.refresh(order)
        return order

    # ══════ RULE 1: ELIGIBILITY TESTS ══════

    def test_r1_delivered_check_fails_if_in_transit(self):
        """R1: Non-delivered orders cannot be returned or exchanged."""
        order = self._create_test_order(self.normal_user, self.returnable_prod, status="SHIPPED")
        res = check_policy(self.db, order, action="RETURN", amount=1500.0, reason="Too small", reason_category="SIZE_FIT")
        self.assertEqual(res["verdict"], PolicyVerdict.DENY)
        self.assertIn("delivered", res["reason"].lower())

    def test_r1_return_window_exceeded(self):
        """R1: Return window exceeds return_window_days (7 days) -> DENY."""
        order = self._create_test_order(self.normal_user, self.returnable_prod, status="DELIVERED", delivered_days_ago=10)
        res = check_policy(self.db, order, action="RETURN", amount=1500.0, reason="Defective", reason_category="DEFECTIVE")
        self.assertEqual(res["verdict"], PolicyVerdict.DENY)
        self.assertIn("return window", res["reason"].lower())

    def test_r1_hygiene_product_non_returnable(self):
        """R1: Product with is_returnable=False (hygiene) must be strictly DENIED."""
        order = self._create_test_order(self.normal_user, self.hygiene_prod, status="DELIVERED", delivered_days_ago=2, total_amount=800.0)
        res = check_policy(self.db, order, action="RETURN", amount=800.0, reason="Changed mind", reason_category="CHANGED_MIND")
        self.assertEqual(res["verdict"], PolicyVerdict.DENY)
        self.assertIn("hygiene", res["reason"].lower())

    # ══════ RULE 3 & RULE 2: MANDATORY REASON & ACCEPTED REASONS ══════

    def test_r3_mandatory_reason_missing(self):
        """R3: Reason is mandatory before any offer or action. Never default it silently."""
        order = self._create_test_order(self.normal_user, self.returnable_prod, status="DELIVERED", delivered_days_ago=2)
        res = check_policy(self.db, order, action="RETURN", amount=1500.0, reason=None, reason_category=None)
        self.assertEqual(res["verdict"], PolicyVerdict.DENY)
        self.assertIn("reason", res["reason"].lower())

    def test_r2_accepted_reasons(self):
        """R2: Valid accepted reasons recognized."""
        order = self._create_test_order(self.normal_user, self.returnable_prod, status="DELIVERED", delivered_days_ago=2)
        res = check_policy(self.db, order, action="RETURN", amount=1500.0, reason="Defective sole", reason_category="DEFECTIVE", evidence_status="VERIFIED")
        self.assertIn(res["verdict"], (PolicyVerdict.AUTO_APPROVE, PolicyVerdict.NEEDS_HUMAN))

    # ══════ RULE 4: EVIDENCE REQUIREMENTS ══════

    def test_r4_evidence_required_for_damage_and_size(self):
        """R4: Evidence must be VERIFIED before auto-approve for defect/damage and size/fit."""
        order = self._create_test_order(self.normal_user, self.returnable_prod, status="DELIVERED", delivered_days_ago=2)
        # Defect with unverified evidence -> NEEDS_HUMAN
        res_defect = check_policy(self.db, order, action="RETURN", amount=1500.0, reason="Damaged on arrival", reason_category="DAMAGED", evidence_status="NONE")
        self.assertEqual(res_defect["verdict"], PolicyVerdict.NEEDS_HUMAN)

        # Size fit with unverified evidence -> NEEDS_HUMAN
        res_size = check_policy(self.db, order, action="RETURN", amount=1500.0, reason="Size too small", reason_category="SIZE_FIT", evidence_status="NONE")
        self.assertEqual(res_size["verdict"], PolicyVerdict.NEEDS_HUMAN)

        # With VERIFIED evidence -> AUTO_APPROVE (amount ₹1500 <= ₹2000 normal limit)
        res_verified = check_policy(self.db, order, action="RETURN", amount=1500.0, reason="Size too small", reason_category="SIZE_FIT", evidence_status="VERIFIED")
        self.assertEqual(res_verified["verdict"], PolicyVerdict.AUTO_APPROVE)

    # ══════ RULE 5 & RULE 6: RESOLUTIONS & REFUND AMOUNTS ══════

    def test_r5_recommended_resolutions(self):
        """R5: Defect -> replacement first; size -> size swap first; changed mind -> store credit."""
        order = self._create_test_order(self.normal_user, self.returnable_prod, status="DELIVERED", delivered_days_ago=2)
        res_defect = check_policy(self.db, order, action="RETURN", amount=1500.0, reason="Defective", reason_category="DEFECTIVE", evidence_status="VERIFIED")
        self.assertEqual(res_defect["recommended_resolution"], "REPLACEMENT")

        res_size = check_policy(self.db, order, action="RETURN", amount=1500.0, reason="Tight fit", reason_category="SIZE_FIT", evidence_status="VERIFIED")
        self.assertEqual(res_size["recommended_resolution"], "SIZE_SWAP")

        res_mind = check_policy(self.db, order, action="RETURN", amount=1500.0, reason="Changed mind", reason_category="CHANGED_MIND", evidence_status="VERIFIED")
        self.assertEqual(res_mind["recommended_resolution"], "STORE_CREDIT")

    def test_r6_refund_amount_shipping_fee(self):
        """R6: Delivery fee refunded ONLY for seller fault (defective, damaged, wrong item)."""
        order = self._create_test_order(self.normal_user, self.returnable_prod, status="DELIVERED", delivered_days_ago=2, total_amount=1600.0, delivery_fee=100.0)
        # Seller fault (defective): refund includes delivery fee (₹1500 + ₹100 = ₹1600)
        res_seller = check_policy(self.db, order, action="REFUND", amount=None, reason="Defective sole", reason_category="DEFECTIVE", evidence_status="VERIFIED")
        self.assertEqual(res_seller["refund_amount"], 1600.0)

        # Customer fault (size/fit): refund excludes delivery fee (₹1500)
        res_cust = check_policy(self.db, order, action="REFUND", amount=None, reason="Size too large", reason_category="SIZE_FIT", evidence_status="VERIFIED")
        self.assertEqual(res_cust["refund_amount"], 1500.0)

    # ══════ RULE 7: TRUST-TIERED AUTO-APPROVE CEILING ══════

    def test_r7_trust_tiered_limits(self):
        """R7: HIGH tier up to ₹5000, NORMAL tier up to ₹2000, RISKY tier ₹0 (always NEEDS_HUMAN)."""
        # Order amount ₹3500
        order_high = self._create_test_order(self.high_user, self.returnable_prod, status="DELIVERED", delivered_days_ago=2, total_amount=3500.0)
        res_high = check_policy(self.db, order_high, action="REFUND", amount=3500.0, reason="Defective", reason_category="DEFECTIVE", evidence_status="VERIFIED")
        self.assertEqual(res_high["verdict"], PolicyVerdict.AUTO_APPROVE)

        order_normal = self._create_test_order(self.normal_user, self.returnable_prod, status="DELIVERED", delivered_days_ago=2, total_amount=3500.0)
        res_normal = check_policy(self.db, order_normal, action="REFUND", amount=3500.0, reason="Defective", reason_category="DEFECTIVE", evidence_status="VERIFIED")
        self.assertEqual(res_normal["verdict"], PolicyVerdict.NEEDS_HUMAN)

        order_risky = self._create_test_order(self.risky_user, self.returnable_prod, status="DELIVERED", delivered_days_ago=2, total_amount=500.0)
        res_risky = check_policy(self.db, order_risky, action="REFUND", amount=500.0, reason="Defective", reason_category="DEFECTIVE", evidence_status="VERIFIED")
        self.assertEqual(res_risky["verdict"], PolicyVerdict.NEEDS_HUMAN)

    # ══════ RULE 8: CANCELLATIONS ══════

    def test_r8_pre_dispatch_cancellation(self):
        """R8: Pre-dispatch cancel (PLACED, PACKED) -> instant cancel + full refund (AUTO_APPROVE)."""
        order = self._create_test_order(self.normal_user, self.returnable_prod, status="PLACED", total_amount=1500.0)
        res = check_policy(self.db, order, action="CANCEL", amount=1500.0, reason="Cancel my order")
        self.assertEqual(res["verdict"], PolicyVerdict.AUTO_APPROVE)
        self.assertTrue(res["auto_approve"])
        self.assertEqual(res["refund_amount"], 1500.0)

    def test_r8_post_dispatch_cancellation(self):
        """R8: Post-dispatch cancel (SHIPPED, OUT_FOR_DELIVERY) -> cannot cancel in transit (DENY)."""
        order = self._create_test_order(self.normal_user, self.returnable_prod, status="OUT_FOR_DELIVERY", total_amount=1500.0)
        res = check_policy(self.db, order, action="CANCEL", amount=1500.0, reason="Cancel my order")
        self.assertEqual(res["verdict"], PolicyVerdict.DENY)
        self.assertIn("transit", res["reason"].lower())

    # ══════ RULE 9: IDEMPOTENCY / DUPLICATE REQUEST ══════

    def test_r9_duplicate_request_denied(self):
        """R9: Duplicate request on order with REFUNDED or RETURN_REQUESTED -> DENY."""
        order = self._create_test_order(self.normal_user, self.returnable_prod, status="REFUNDED")
        res = check_policy(self.db, order, action="RETURN", amount=1500.0, reason="Defective", reason_category="DEFECTIVE")
        self.assertEqual(res["verdict"], PolicyVerdict.DENY)
        self.assertIn("already", res["reason"].lower())

    # ══════ RULE 10: AUDIT LOG CREATION ══════

    def test_r10_audit_log_created_on_check_policy(self):
        """R10: Every check_policy evaluation creates an AuditLog row."""
        order = self._create_test_order(self.normal_user, self.returnable_prod, status="DELIVERED", delivered_days_ago=2)
        initial_count = self.db.query(AuditLog).filter(AuditLog.order_id == order.id).count()

        check_policy(self.db, order, action="RETURN", amount=1500.0, reason="Defective", reason_category="DEFECTIVE", evidence_status="VERIFIED")

        new_count = self.db.query(AuditLog).filter(AuditLog.order_id == order.id).count()
        self.assertGreater(new_count, initial_count)
        latest_audit = self.db.query(AuditLog).filter(AuditLog.order_id == order.id).order_by(AuditLog.timestamp.desc()).first()
        self.assertEqual(latest_audit.tool, "policy_engine.check_policy")
        self.assertEqual(latest_audit.verdict, "AUTO_APPROVE")

    # ══════ PROMPT PLACEHOLDER TESTS ══════

    def test_prompt_placeholders_resolved_dynamically(self):
        """Prompts must fill placeholders from settings without raw unreplaced {{...}}."""
        system_prompt = compose_system_prompt(self.db, summary="Test summary", customer_memory={"usual_size": "9 UK"})
        self.assertNotIn("{{return_window_days}}", system_prompt)
        self.assertNotIn("{{trust_high_refund_limit}}", system_prompt)
        self.assertNotIn("{{refund_limit}}", system_prompt)
        self.assertIn("7 days", system_prompt)
        self.assertIn("5,000", system_prompt)


if __name__ == "__main__":
    unittest.main()
