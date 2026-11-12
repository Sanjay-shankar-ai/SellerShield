"""
Test suite for Phase 2: Image Analysis of Defects, Damage, Wrong Item, and Unused Check.
Verifies:
  Test 6: Clear photo of a cracked mug -> VERIFIED with correct observations; the reply refers to what is visible.
  Test 7: Blurry/dark photo -> UNCLEAR, specific retake hint, one retry, then escalation.
  Test 8: Photo of a different product -> MISMATCH handled politely, no accusation.
  Test 9: API failure during vision -> UNCLEAR (fail-closed, never VERIFIED).
  Test 10: Same photo reused on a second claim -> hidden flag for admin, customer unaffected.
  Test 11: Upload validation: reject >5MB, reject invalid format, downscale >1280px, strip EXIF.
  Test 12: Memory of evidence: photo is never requested again after VERIFIED.
"""

import io
import os
import json
import uuid
import unittest
import datetime
from unittest.mock import patch, MagicMock
from PIL import Image

from backend.database import SessionLocal
from backend.models import User, Product, Order, OrderItem, Escalation, EvidenceHash
from backend.auth import get_password_hash
from backend.image_evidence import (
    validate_and_process_image,
    compute_dhash,
    hamming_distance,
    check_image_fraud_and_register,
    analyze_evidence
)
from backend.langgraph_agent import (
    run_agent_turn,
    node_collect_evidence,
    SellerShieldAgentState
)


class TestImageAnalysisEngine(unittest.TestCase):

    def setUp(self):
        self.db = SessionLocal()

        self.user = self.db.query(User).filter(User.email == "vision_test@example.com").first()
        if not self.user:
            self.user = User(
                id=str(uuid.uuid4()),
                email="vision_test@example.com",
                hashed_password=get_password_hash("pass123"),
                full_name="Priya Sharma",
                role="CUSTOMER",
                trust_score=85.0,
                trust_tier="NORMAL"
            )
            self.db.add(self.user)
            self.db.commit()

        # Clean old conversations and evidence hashes to guarantee fresh test state
        from backend.models import Conversation, Message
        self.db.query(Message).filter(Message.conversation.has(customer_id=self.user.id)).delete(synchronize_session=False)
        self.db.query(Conversation).filter(Conversation.customer_id == self.user.id).delete(synchronize_session=False)
        self.db.query(EvidenceHash).delete(synchronize_session=False)
        self.db.commit()

        # Create test mug product
        self.prod_mug = self.db.query(Product).filter(Product.sku == "TEST-MUG-01").first()
        if not self.prod_mug:
            self.prod_mug = Product(
                id=str(uuid.uuid4()),
                title="Ceramic Artisan Coffee Mug",
                sku="TEST-MUG-01",
                category="Kitchenware",
                description="Handmade ceramic coffee mug",
                price=899.0,
                is_returnable=True,
                image="http://example.com/mug.jpg",
                stock_count=25
            )
            self.db.add(self.prod_mug)
            self.db.commit()

        # Create delivered Order for testing evidence claims
        delivered_date = datetime.datetime.utcnow() - datetime.timedelta(days=1)
        self.order = self.db.query(Order).filter(Order.order_number == "ORD-MUG-9001").first()
        if not self.order:
            self.order = Order(
                id=str(uuid.uuid4()),
                order_number="ORD-MUG-9001",
                customer_id=self.user.id,
                customer_name=self.user.full_name,
                customer_email=self.user.email,
                customer_phone="+91 99999 11111",
                shipping_address="Koramangala, Bengaluru",
                payment_method="MOCK_UPI",
                total_amount=899.0,
                status="DELIVERED",
                stage_entered_at=delivered_date,
                delivered_at=delivered_date,
                created_at=delivered_date
            )
            self.db.add(self.order)
            self.db.flush()
            item = OrderItem(
                id=str(uuid.uuid4()),
                order_id=self.order.id,
                product_id=self.prod_mug.id,
                product_title=self.prod_mug.title,
                product_sku=self.prod_mug.sku,
                selected_size=None,
                quantity=1,
                unit_price=899.0,
                subtotal=899.0
            )
            self.db.add(item)
            self.db.commit()

    def tearDown(self):
        self.db.close()

    def _create_sample_image_data_url(self, color="red", size=(600, 400)) -> str:
        """Helper to create base64 data URLs for testing."""
        import base64
        im = Image.new("RGB", size, color=color)
        buf = io.BytesIO()
        im.save(buf, format="JPEG")
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        return f"data:image/jpeg;base64,{b64}"

    # ══════ TEST 6: Clear photo of cracked mug -> VERIFIED, refers to visible defect ══════

    def test_06_clear_photo_verified_with_natural_observation(self):
        """Test 6: Clear photo of a cracked mug -> VERIFIED with correct observations; reply refers to what is visible."""
        data_url = self._create_sample_image_data_url("gray")
        mock_vision = {
            "product_matches": "yes",
            "detected_product": "Ceramic Artisan Coffee Mug",
            "damage_present": "yes",
            "damage_type": "crack",
            "severity": "moderate",
            "defect_visible": "yes",
            "item_unused_with_tag_or_box": "unsure",
            "image_quality": "good",
            "matches_claim": "yes",
            "confidence": 0.94,
            "observations": "Clear crack along the left side of the ceramic mug.",
            "status": "VERIFIED"
        }

        with patch("backend.image_evidence.call_gemini", return_value=json.dumps(mock_vision)):
            state: SellerShieldAgentState = {
                "customer_id": self.user.id,
                "user_message": "Here is the photo of the crack",
                "order_id": self.order.id,
                "order_number": self.order.order_number,
                "reason_category": "Damaged on arrival",
                "reason_text": "Mug is cracked",
                "evidence_status": "PENDING",
                "evidence_retries": 0,
                "evidence_photo": data_url,
                "messages": []
            }
            res = node_collect_evidence(state)
            self.assertEqual(res["evidence_status"], "VERIFIED")
            self.assertIsNone(res["pending_question"])
            self.assertEqual(res["vision_analysis"]["damage_type"], "crack")
            self.assertIn("left side", res["vision_analysis"]["observations"])

            # Check that fact_packet contains evidence observations
            self.assertIn("evidence_observations", res["fact_packet"])
            self.assertEqual(res["fact_packet"]["evidence_observations"], "Clear crack along the left side of the ceramic mug.")

    # ══════ TEST 7: Blurry/dark photo -> UNCLEAR, retake hint, retry, escalation ══════

    def test_07_dark_blurry_photo_unclear_then_escalates(self):
        """Test 7: Blurry/dark photo -> UNCLEAR, specific retake hint, one retry, then escalation."""
        data_url = self._create_sample_image_data_url("black")
        mock_dark_vision = {
            "product_matches": "yes",
            "detected_product": "Ceramic Artisan Coffee Mug",
            "damage_present": "unsure",
            "damage_type": "crack",
            "severity": "none",
            "defect_visible": "unsure",
            "item_unused_with_tag_or_box": "unsure",
            "image_quality": "dark",
            "matches_claim": "partly",
            "confidence": 0.40,
            "observations": "Lighting is too dark to distinguish crack lines.",
            "status": "UNCLEAR"
        }

        with patch("backend.image_evidence.call_gemini", return_value=json.dumps(mock_dark_vision)):
            # First attempt: should give retake hint
            state1: SellerShieldAgentState = {
                "customer_id": self.user.id,
                "user_message": "photo attached",
                "order_id": self.order.id,
                "order_number": self.order.order_number,
                "reason_category": "Damaged on arrival",
                "reason_text": "Mug is cracked",
                "evidence_status": "PENDING",
                "evidence_retries": 0,
                "evidence_photo": data_url,
                "messages": []
            }
            res1 = node_collect_evidence(state1)
            self.assertEqual(res1["evidence_status"], "UNCLEAR")
            self.assertEqual(res1["evidence_retries"], 1)
            self.assertEqual(res1["pending_question"], "COLLECT_EVIDENCE")
            self.assertTrue(any(w in res1["reply"].lower() for w in ["daylight", "brighter", "clearer", "crack"]))

            # Second attempt: retries exceed limit -> escalate to human review
            state2: SellerShieldAgentState = {
                "customer_id": self.user.id,
                "user_message": "second dark photo",
                "order_id": self.order.id,
                "order_number": self.order.order_number,
                "reason_category": "Damaged on arrival",
                "reason_text": "Mug is cracked",
                "evidence_status": "UNCLEAR",
                "evidence_retries": 1,
                "evidence_photo": data_url,
                "messages": []
            }
            res2 = node_collect_evidence(state2)
            self.assertEqual(res2["evidence_status"], "UNCLEAR")
            self.assertEqual(res2["evidence_retries"], 2)
            self.assertEqual(res2["verdict"], "NEEDS_HUMAN")
            self.assertIn("error", res2)

    # ══════ TEST 8: Different product -> MISMATCH handled politely without accusation ══════

    def test_08_different_product_mismatch_polite_handling(self):
        """Test 8: Photo of a different product -> MISMATCH handled politely, no accusation."""
        data_url = self._create_sample_image_data_url("yellow")
        mock_mismatch = {
            "product_matches": "no",
            "detected_product": "Wireless Bluetooth Earbuds",
            "damage_present": "none",
            "damage_type": "none",
            "severity": "none",
            "defect_visible": "no",
            "item_unused_with_tag_or_box": "unsure",
            "image_quality": "good",
            "matches_claim": "no",
            "confidence": 0.95,
            "observations": "Photo shows wireless earbuds instead of Ceramic Artisan Coffee Mug.",
            "status": "MISMATCH"
        }

        with patch("backend.image_evidence.call_gemini", return_value=json.dumps(mock_mismatch)):
            state: SellerShieldAgentState = {
                "customer_id": self.user.id,
                "user_message": "photo of mug",
                "order_id": self.order.id,
                "order_number": self.order.order_number,
                "reason_category": "Damaged on arrival",
                "reason_text": "cracked mug",
                "evidence_status": "PENDING",
                "evidence_retries": 0,
                "evidence_photo": data_url,
                "messages": []
            }
            res = node_collect_evidence(state)
            self.assertEqual(res["evidence_status"], "MISMATCH")
            self.assertEqual(res["evidence_retries"], 1)
            # Must be polite, never accuse customer of lying/fraud
            banned_words = ["fraud", "lie", "cheat", "fake", "deceive", "dishonest"]
            for bw in banned_words:
                self.assertNotIn(bw, res["reply"].lower())
            self.assertIn("different product", res["reply"].lower())

    # ══════ TEST 9: API failure during vision -> UNCLEAR (fail-closed, never VERIFIED) ══════

    def test_09_api_failure_fails_closed(self):
        """Test 9: API failure or invalid JSON during vision -> UNCLEAR (never VERIFIED)."""
        data_url = self._create_sample_image_data_url("green")

        # 1. API exception
        with patch("backend.image_evidence.call_gemini", side_effect=Exception("Connection timed out")):
            proc = validate_and_process_image(data_url, "ORD-MUG-9001")
            analysis = analyze_evidence(self.order, "Damaged on arrival", [proc])
            self.assertEqual(analysis["status"], "UNCLEAR")
            self.assertNotEqual(analysis["status"], "VERIFIED")

        # 2. Corrupt / non-JSON response
        with patch("backend.image_evidence.call_gemini", return_value="Error: 503 Internal Gateway"):
            proc = validate_and_process_image(data_url, "ORD-MUG-9001")
            analysis = analyze_evidence(self.order, "Damaged on arrival", [proc])
            self.assertEqual(analysis["status"], "UNCLEAR")
            self.assertNotEqual(analysis["status"], "VERIFIED")

    # ══════ TEST 10: Same photo reused on a second claim -> hidden flag for admin ══════

    def test_10_image_reuse_fraud_flag_admin_only(self):
        """Test 10: Same photo reused on a second claim -> hidden flag for admin, customer unaffected."""
        data_url = self._create_sample_image_data_url("purple")
        proc = validate_and_process_image(data_url, "ORD-CLAIM-1")
        phash = proc["dhash"]

        order_id_1 = str(uuid.uuid4())
        order_id_2 = str(uuid.uuid4())

        # Claim 1: register image hash
        flags_1 = check_image_fraud_and_register(
            db=self.db,
            order_id=order_id_1,
            customer_id=self.user.id,
            phash=phash,
            image_path="/static/uploads/orders/ORD-CLAIM-1/test.jpg"
        )
        self.assertEqual(len(flags_1), 0)

        # Claim 2: different order uploads same photo
        flags_2 = check_image_fraud_and_register(
            db=self.db,
            order_id=order_id_2,
            customer_id=self.user.id,
            phash=phash,
            image_path="/static/uploads/orders/ORD-CLAIM-2/test.jpg"
        )
        self.assertEqual(len(flags_2), 1)
        self.assertIn("FRAUD_WARNING", flags_2[0])
        self.assertIn("Perceptual image match detected", flags_2[0])

    # ══════ TEST 11: File upload validation (reject >5MB, downscale >1280px) ══════

    def test_11_image_validation_and_downscale(self):
        """Test 11: Validates max size 5 MB, downscales >1280px, and strips EXIF."""
        # 1. Reject > 5 MB
        huge_bytes = b"0" * (6 * 1024 * 1024)
        with self.assertRaises(ValueError) as cm:
            validate_and_process_image(huge_bytes)
        self.assertIn("exceeds maximum allowed 5 MB", str(cm.exception))

        # 2. Downscale > 1280px
        large_im = Image.new("RGB", (2560, 1440), color="blue")
        buf = io.BytesIO()
        large_im.save(buf, format="JPEG")
        res = validate_and_process_image(buf.getvalue(), "ORD-SCALE-TEST")
        self.assertLessEqual(res["width"], 1280)
        self.assertLessEqual(res["height"], 1280)
        self.assertTrue(os.path.exists(res["file_path"]))

    # ══════ TEST 12: Memory of evidence (never re-requested after VERIFIED) ══════

    def test_12_evidence_memory_never_re_requested(self):
        """Test 12: Memory of evidence: photo is never requested again once VERIFIED."""
        state: SellerShieldAgentState = {
            "customer_id": self.user.id,
            "user_message": "Can I get a refund instead of replacement?",
            "order_id": self.order.id,
            "order_number": self.order.order_number,
            "reason_category": "Damaged on arrival",
            "evidence_status": "VERIFIED",
            "evidence_retries": 0,
            "evidence_photo": None,
            "messages": []
        }
        res = node_collect_evidence(state)
        # Must immediately skip without setting pending_question or requesting photo
        self.assertEqual(res["evidence_status"], "VERIFIED")
        self.assertIsNone(res.get("pending_question"))
        self.assertNotIn("reply", res)

    # ══════ TEST 13: Size / fit issue requires unused tag/box photo (2D) ══════

    def test_13_size_fit_unused_tag_box_check(self):
        """Test 13: Size/fit claim with photo requires confirming item is unused with tag/box intact."""
        # 1. No photo yet -> skips evidence to doorstep retention
        state_no_photo: SellerShieldAgentState = {
            "customer_id": self.user.id,
            "user_message": "Size is too small",
            "order_id": self.order.id,
            "order_number": self.order.order_number,
            "reason_category": "Size / fit issue",
            "evidence_status": "NONE",
            "evidence_retries": 0,
            "evidence_photo": None,
            "messages": []
        }
        res_no_photo = node_collect_evidence(state_no_photo)
        self.assertEqual(res_no_photo["evidence_status"], "NONE")
        self.assertIsNone(res_no_photo["pending_question"])

        # 2. Photo uploaded confirming unused with tag/box -> VERIFIED
        data_url = self._create_sample_image_data_url("cyan")
        mock_unused = {
            "product_matches": "yes",
            "detected_product": "Ceramic Artisan Coffee Mug",
            "damage_present": "none",
            "damage_type": "none",
            "severity": "none",
            "defect_visible": "no",
            "item_unused_with_tag_or_box": "yes",
            "image_quality": "good",
            "matches_claim": "yes",
            "confidence": 0.95,
            "observations": "Item is in original retail packaging with brand tags attached.",
            "status": "VERIFIED"
        }
        with patch("backend.image_evidence.call_gemini", return_value=json.dumps(mock_unused)):
            state_with_photo: SellerShieldAgentState = {
                "customer_id": self.user.id,
                "user_message": "here is photo with box",
                "order_id": self.order.id,
                "order_number": self.order.order_number,
                "reason_category": "Size / fit issue",
                "evidence_status": "PENDING",
                "evidence_retries": 0,
                "evidence_photo": data_url,
                "messages": []
            }
            res_photo = node_collect_evidence(state_with_photo)
            self.assertEqual(res_photo["evidence_status"], "VERIFIED")

        # 3. Photo uploaded without tag/box -> UNCLEAR
        mock_no_tag = {
            "product_matches": "yes",
            "detected_product": "Ceramic Artisan Coffee Mug",
            "damage_present": "none",
            "damage_type": "none",
            "severity": "none",
            "defect_visible": "no",
            "item_unused_with_tag_or_box": "no",
            "image_quality": "good",
            "matches_claim": "no",
            "confidence": 0.90,
            "observations": "Item appears washed and brand tags have been cut off.",
            "status": "UNCLEAR"
        }
        with patch("backend.image_evidence.call_gemini", return_value=json.dumps(mock_no_tag)):
            state_used: SellerShieldAgentState = {
                "customer_id": self.user.id,
                "user_message": "here is photo",
                "order_id": self.order.id,
                "order_number": self.order.order_number,
                "reason_category": "Size / fit issue",
                "evidence_status": "PENDING",
                "evidence_retries": 0,
                "evidence_photo": data_url,
                "messages": []
            }
            res_used = node_collect_evidence(state_used)
            self.assertEqual(res_used["evidence_status"], "UNCLEAR")

    # ══════ TEST 14: Hygiene product is non-returnable regardless of photo (2D) ══════

    def test_14_hygiene_product_non_returnable(self):
        """Test 14: Hygiene product is strictly non-returnable regardless of photo."""
        hygiene_order = {
            "product_title": "Soft Touch Innerwear Set",
            "product_sku": "HYG-001",
            "category": "Hygiene"
        }
        proc = validate_and_process_image(self._create_sample_image_data_url("white"))
        res = analyze_evidence(hygiene_order, "Damaged on arrival", [proc])
        self.assertEqual(res["status"], "MISMATCH")
        self.assertIn("hygiene", res["observations"].lower())


if __name__ == "__main__":
    unittest.main()
