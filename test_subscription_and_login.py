"""
Automated Test Suite for SellerShield Subscription Plans & Admin Auth:
1. GET /api/plans returns 3 plans with monthly/yearly pricing (yearly = monthly * 10).
2. Login validation: wrong password raises 401; right password returns token and user role.
3. Choosing a plan when logged out -> signup -> mock checkout -> plan active with invoice.
4. Trial countdown: 14-day trial; after expiry + 3-day grace period, auto-downgrades to Starter.
5. Feature gating: Starter admin calling gated feature (e.g. csv_export, escalation_queue) raises 403; Pro admin succeeds.
6. Chat turn counting: counts 1 turn per turn, warns at 80%, and hands over to human at 100%.
"""

import os
import unittest
import uuid
import datetime
from fastapi import HTTPException

from backend.database import SessionLocal
from backend.models import User, Plan, Subscription, Invoice, AuditLog
from backend.subscription import (
    has_feature,
    check_and_expire_subscription,
    record_chat_turn,
    get_or_create_admin_subscription,
    format_subscription_response
)
from backend.main import (
    get_plans,
    login_for_access_token,
    signup_admin,
    checkout_subscription,
    get_subscription,
    change_subscription,
    cancel_subscription,
    export_audit_logs_csv,
    get_escalations,
    LoginRequest,
    SignupRequest,
    SubscriptionCheckoutRequest,
    PlanChangeRequest
)

class TestSubscriptionAndLogin(unittest.TestCase):
    def setUp(self):
        self.db = SessionLocal()

    def tearDown(self):
        self.db.close()

    def test_1_plans_pricing_and_features(self):
        """Test 1: Plans endpoint returns Starter (0), Growth (999/9990), Pro (2999/29990)."""
        plans = get_plans(self.db)
        self.assertEqual(len(plans), 3)
        plan_dict = {p["id"]: p for p in plans}

        # Starter
        self.assertEqual(plan_dict["starter"]["price_monthly"], 0.0)
        self.assertEqual(plan_dict["starter"]["price_yearly"], 0.0)
        self.assertEqual(plan_dict["starter"]["chat_limit"], 50)
        self.assertIn("50 AI chats a month", plan_dict["starter"]["features"])

        # Growth
        self.assertEqual(plan_dict["growth"]["price_monthly"], 999.0)
        self.assertEqual(plan_dict["growth"]["price_yearly"], 9990.0)
        self.assertEqual(plan_dict["growth"]["chat_limit"], 1000)
        self.assertIn("Escalation queue", plan_dict["growth"]["features"])

        # Pro
        self.assertEqual(plan_dict["pro"]["price_monthly"], 2999.0)
        self.assertEqual(plan_dict["pro"]["price_yearly"], 29990.0)
        self.assertEqual(plan_dict["pro"]["chat_limit"], -1)
        self.assertIn("Image defect analysis", plan_dict["pro"]["features"])
        print("[PASS] Test 1: GET /api/plans pricing & features verified.")

    def test_2_login_validation_and_roles(self):
        """Test 2: Wrong password raises 401; correct password returns token with role."""
        # Wrong password
        with self.assertRaises(HTTPException) as ctx:
            login_for_access_token(LoginRequest(email="admin@sellershield.com", password="wrongpassword"), self.db)
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertIn("Incorrect email or password", ctx.exception.detail)

        # Admin login
        admin_res = login_for_access_token(LoginRequest(email="admin@sellershield.com", password="admin123"), self.db)
        self.assertEqual(admin_res.user.role, "ADMIN")
        self.assertTrue(len(admin_res.access_token) > 20)

        # Customer login
        cust_res = login_for_access_token(LoginRequest(email="rahul@gmail.com", password="rahul123"), self.db)
        self.assertEqual(cust_res.user.role, "CUSTOMER")
        print("[PASS] Test 2: Login validation & role routing verified.")

    def test_3_signup_and_mock_checkout(self):
        """Test 3: Choosing a plan when logged out -> signup -> mock checkout with test card -> plan active."""
        email = f"boutique_{uuid.uuid4().hex[:6]}@store.com"
        # Signup
        signup_res = signup_admin(SignupRequest(
            store_name="Silk & Velvet",
            email=email,
            password="storepassword123"
        ), self.db)
        self.assertEqual(signup_res.user.role, "ADMIN")
        self.assertEqual(signup_res.user.store_name, "Silk & Velvet")

        new_admin = self.db.query(User).filter(User.id == signup_res.user.id).first()

        # Checkout Growth Yearly with valid mock test card
        chk_res = checkout_subscription(SubscriptionCheckoutRequest(
            plan_id="growth",
            billing_cycle="yearly",
            test_card={
                "number": "4242 4242 4242 4242",
                "exp": "12/28",
                "cvc": "123",
                "name": "Silk & Velvet"
            }
        ), new_admin, self.db)

        self.assertTrue(chk_res["success"])
        self.assertTrue(chk_res["payment_id"].startswith("mock_pay_"))
        self.assertEqual(chk_res["subscription"]["plan_id"], "growth")
        self.assertEqual(chk_res["subscription"]["billing_cycle"], "yearly")
        self.assertEqual(chk_res["subscription"]["status"], "active")

        # Verify mock invoice created
        inv = self.db.query(Invoice).filter(Invoice.subscription_id == chk_res["subscription"]["id"]).first()
        self.assertIsNotNone(inv)
        self.assertEqual(inv.amount, 9990.0)
        self.assertEqual(inv.payment_method, "TEST_CARD")

        # Test card number must NEVER be stored
        raw_db_values = [str(col) for col in inv.__dict__.values()]
        self.assertFalse(any("4242 4242" in val for val in raw_db_values))

        # Test Pro 14-day trial checkout
        trial_email = f"trial_{uuid.uuid4().hex[:6]}@store.com"
        trial_user_res = signup_admin(SignupRequest(
            store_name="Trial Co",
            email=trial_email,
            password="trialpassword123"
        ), self.db)
        trial_admin = self.db.query(User).filter(User.id == trial_user_res.user.id).first()

        trial_chk = checkout_subscription(SubscriptionCheckoutRequest(
            plan_id="pro",
            is_trial=True
        ), trial_admin, self.db)
        self.assertEqual(trial_chk["subscription"]["plan_id"], "pro")
        self.assertEqual(trial_chk["subscription"]["status"], "trial")
        self.assertGreaterEqual(trial_chk["subscription"]["trial_days_left"], 13)
        print("[PASS] Test 3: Signup, mock checkout, and trial initiation verified.")

    def test_4_trial_countdown_and_grace_period(self):
        """Test 4: Trial counts down; after expiry + 3-day grace period, auto-downgrades to Starter."""
        test_user = User(
            email=f"trial_expire_{uuid.uuid4().hex[:6]}@test.com",
            hashed_password="hash",
            full_name="Trial Expire",
            role="ADMIN"
        )
        self.db.add(test_user)
        self.db.commit()
        self.db.refresh(test_user)

        now = datetime.datetime.utcnow()
        # Active trial (expires in 10 days)
        sub = Subscription(
            admin_id=test_user.id,
            plan_id="pro",
            status="trial",
            started_at=now - datetime.timedelta(days=4),
            trial_ends_at=now + datetime.timedelta(days=10)
        )
        self.db.add(sub)
        self.db.commit()

        sub_active = check_and_expire_subscription(sub, self.db)
        self.assertEqual(sub_active.status, "trial")
        self.assertEqual(sub_active.plan_id, "pro")

        # In 3-day grace period (trial ended 1 day ago)
        sub.trial_ends_at = now - datetime.timedelta(days=1)
        self.db.commit()
        sub_grace = check_and_expire_subscription(sub, self.db)
        self.assertEqual(sub_grace.status, "past_due")
        self.assertEqual(sub_grace.plan_id, "pro")

        # Beyond 3-day grace period (trial ended 4 days ago) -> downgrades to Starter
        sub.trial_ends_at = now - datetime.timedelta(days=4)
        self.db.commit()
        sub_expired = check_and_expire_subscription(sub, self.db)
        self.assertEqual(sub_expired.status, "active")
        self.assertEqual(sub_expired.plan_id, "starter")
        print("[PASS] Test 4: Trial countdown and 3-day grace period auto-downgrade verified.")

    def test_5_feature_gating_and_403(self):
        """Test 5: Starter admin calling gated endpoints (CSV export, Escalations) gets 403; Pro admin gets 200."""
        starter_admin = User(
            email=f"starter_admin_{uuid.uuid4().hex[:6]}@store.com",
            hashed_password="hash",
            full_name="Starter User",
            role="ADMIN"
        )
        self.db.add(starter_admin)
        self.db.commit()
        self.db.refresh(starter_admin)

        sub_starter = Subscription(
            admin_id=starter_admin.id,
            plan_id="starter",
            status="active"
        )
        self.db.add(sub_starter)
        self.db.commit()

        # Feature checks
        self.assertTrue(has_feature(starter_admin, "order_tracking", self.db))
        self.assertTrue(has_feature(starter_admin, "basic_audit", self.db))
        self.assertFalse(has_feature(starter_admin, "csv_export", self.db))
        self.assertFalse(has_feature(starter_admin, "escalation_queue", self.db))

        # Direct call to export_audit_logs_csv with Starter admin -> 403
        with self.assertRaises(HTTPException) as ctx_csv:
            export_audit_logs_csv(self.db, starter_admin)
        self.assertEqual(ctx_csv.exception.status_code, 403)
        self.assertIn("requires a Growth or Pro plan", ctx_csv.exception.detail)

        # Direct call to get_escalations with Starter admin -> 403
        with self.assertRaises(HTTPException) as ctx_esc:
            get_escalations(None, self.db, starter_admin)
        self.assertEqual(ctx_esc.exception.status_code, 403)
        self.assertIn("requires a Growth or Pro plan", ctx_esc.exception.detail)

        # Pro admin -> succeeds
        pro_admin = self.db.query(User).filter(User.email == "admin@sellershield.com").first()
        esc_res = get_escalations(None, self.db, pro_admin)
        self.assertIsInstance(esc_res, list)

        # Verify gate denial was written to audit log
        gate_audit = self.db.query(AuditLog).filter(
            AuditLog.tool == "subscription.gate_denied"
        ).order_by(AuditLog.timestamp.desc()).first()
        self.assertIsNotNone(gate_audit)
        self.assertEqual(gate_audit.verdict, "REJECT")
        print("[PASS] Test 5: Feature gating, 403 exceptions, and audit logging verified.")

    def test_6_chat_turn_counting_and_handover(self):
        """Test 6: Count 1 chat per turn, warn at 80%, hand over to human politely at 100%."""
        test_admin = User(
            email=f"turn_test_{uuid.uuid4().hex[:6]}@store.com",
            hashed_password="hash",
            full_name="Turn Test",
            role="ADMIN"
        )
        self.db.add(test_admin)
        self.db.commit()
        self.db.refresh(test_admin)

        sub = Subscription(
            admin_id=test_admin.id,
            plan_id="starter",
            status="active",
            chats_used=0
        )
        self.db.add(sub)
        self.db.commit()

        # Turn 1
        ok, msg = record_chat_turn(test_admin, self.db)
        self.assertTrue(ok)
        self.assertEqual(msg, "ok")
        self.assertEqual(sub.chats_used, 1)

        # At 80% (40/50 for Starter)
        sub.chats_used = 40
        self.db.commit()
        ok_80, msg_80 = record_chat_turn(test_admin, self.db)
        self.assertTrue(ok_80)
        self.assertIn("80%+", msg_80)

        # At 100% (50/50 for Starter)
        sub.chats_used = 50
        self.db.commit()
        ok_100, msg_100 = record_chat_turn(test_admin, self.db)
        self.assertFalse(ok_100)
        self.assertIn("monthly AI chat limit", msg_100)
        print("[PASS] Test 6: Chat turn counting, 80% warning, and 100% polite handover verified.")

if __name__ == "__main__":
    unittest.main()
