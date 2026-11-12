"""
SellerShield AI - Image Evidence & Forensic Vision Inspection Engine (Phase 2)
Provides:
  - 2A: Upload handling (JPEG/PNG/WebP, <=5MB, downscale <=1280px, EXIF location stripping, base64 inlineData)
  - 2B: analyze_evidence() calling Gemini Vision with strict JSON schema (temperature 0)
  - 2C: Deterministic decision rules (VERIFIED, UNCLEAR, MISMATCH, fail-closed)
  - 2D: Claim-specific checks (damage/defect, wrong item, size/fit unused with tag/box)
  - 2E: Perceptual hash (dHash) fraud awareness (reuse detection, repeated low-quality flags)
  - 2F: Memory of evidence persistence and natural LLM observations
"""

import io
import os
import re
import json
import uuid
import base64
import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Union, Tuple
from PIL import Image, ImageOps
from sqlalchemy.orm import Session

from .models import Order, Escalation, EvidenceHash, User
def call_gemini(*args, **kwargs):
    """Module-level wrapper around langgraph_agent.call_gemini to avoid circular imports."""
    from .langgraph_agent import call_gemini as _cg
    return _cg(*args, **kwargs)

# Upload storage directory
import tempfile
if os.environ.get("VERCEL"):
    UPLOAD_DIR = Path(tempfile.gettempdir()) / "static" / "uploads" / "orders"
else:
    UPLOAD_DIR = Path(__file__).resolve().parent.parent / "static" / "uploads" / "orders"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Strict Gemini Vision Schema (2B)
EVIDENCE_VISION_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "product_matches": {"type": "STRING", "enum": ["yes", "no", "unsure"]},
        "detected_product": {"type": "STRING"},
        "damage_present": {"type": "STRING", "enum": ["yes", "no", "unsure"]},
        "damage_type": {
            "type": "STRING",
            "enum": [
                "crack", "dent", "tear", "stain", "broken_part",
                "scratch", "water_damage", "missing_part",
                "packaging_only", "none"
            ]
        },
        "severity": {"type": "STRING", "enum": ["none", "minor", "moderate", "severe"]},
        "defect_visible": {"type": "STRING", "enum": ["yes", "no", "unsure"]},
        "item_unused_with_tag_or_box": {"type": "STRING", "enum": ["yes", "no", "unsure"]},
        "image_quality": {"type": "STRING", "enum": ["good", "blurry", "dark", "too_far", "cropped"]},
        "matches_claim": {"type": "STRING", "enum": ["yes", "no", "partly"]},
        "confidence": {"type": "NUMBER"},
        "observations": {"type": "STRING"},
        "status": {"type": "STRING", "enum": ["VERIFIED", "UNCLEAR", "MISMATCH"]}
    },
    "required": [
        "product_matches", "detected_product", "damage_present", "damage_type",
        "severity", "defect_visible", "item_unused_with_tag_or_box", "image_quality",
        "matches_claim", "confidence", "observations", "status"
    ]
}


# ============================================================================
# 1. PERCEPTUAL HASHING & FRAUD AWARENESS (2E)
# ============================================================================

def compute_dhash(image: Image.Image, hash_size: int = 8) -> str:
    """
    Computes a 64-bit difference hash (dHash) for an image.
    Resizes to (hash_size + 1, hash_size), converts to grayscale, and compares adjacent pixels.
    """
    # Resize and convert to grayscale
    img = image.convert("L").resize((hash_size + 1, hash_size), Image.Resampling.LANCZOS)
    
    # Compare adjacent pixels row by row
    diff = []
    # getpixel avoids deprecated getdata()
    for row in range(hash_size):
        for col in range(hash_size):
            pixel_left = img.getpixel((col, row))
            pixel_right = img.getpixel((col + 1, row))
            diff.append(pixel_left > pixel_right)

    # Convert binary list to hex string
    decimal_val = 0
    hex_chars = []
    for idx, val in enumerate(diff):
        if val:
            decimal_val += 2 ** (idx % 8)
        if (idx % 8) == 7:
            hex_chars.append(hex(decimal_val)[2:].rjust(2, "0"))
            decimal_val = 0
    return "".join(hex_chars)


def hamming_distance(h1: str, h2: str) -> int:
    """Computes Hamming distance between two hex hash strings."""
    try:
        val1 = int(h1, 16)
        val2 = int(h2, 16)
        return bin(val1 ^ val2).count("1")
    except Exception:
        return 64


def check_image_fraud_and_register(
    db: Session,
    order_id: Optional[str],
    customer_id: Optional[str],
    phash: str,
    image_path: str,
    quality: str = "good",
    status: str = "VERIFIED"
) -> List[str]:
    """
    Checks if this perceptual hash matches an image from a different claim/order (2E).
    Flags very low-quality repeated submissions. Adds to trust factors for admin.
    Never mentioned to customer.
    """
    fraud_flags: List[str] = []

    # 1. Check for reuse of the same photo on another claim/order
    existing_hashes = db.query(EvidenceHash).all()
    for eh in existing_hashes:
        if eh.order_id and order_id and eh.order_id != order_id:
            dist = hamming_distance(phash, eh.phash)
            if dist <= 6:  # Strong perceptual match (<= 6 bits difference out of 64)
                matched_ord = db.query(Order).filter(Order.id == eh.order_id).first()
                ord_num = matched_ord.order_number if matched_ord else eh.order_id
                fraud_flags.append(
                    f"FRAUD_WARNING: Perceptual image match detected with Order #{ord_num} (dHash distance: {dist}/64)."
                )
                break

    # 2. Check for repeated low-quality photos from same customer
    if quality in ("blurry", "dark", "too_far", "cropped") and customer_id:
        low_q_count = db.query(EvidenceHash).filter(
            EvidenceHash.customer_id == customer_id,
            EvidenceHash.quality.in_(["blurry", "dark", "too_far", "cropped"])
        ).count()
        if low_q_count >= 2:
            fraud_flags.append(
                f"FRAUD_WARNING: Customer has submitted {low_q_count + 1} low-quality / unclear evidence photos across claims."
            )

    # 3. Store new record in database
    new_record = EvidenceHash(
        id=str(uuid.uuid4()),
        order_id=order_id,
        customer_id=customer_id,
        image_path=image_path,
        phash=phash,
        quality=quality,
        status=status,
        created_at=datetime.datetime.utcnow()
    )
    db.add(new_record)
    db.commit()

    return fraud_flags


# ============================================================================
# 2. IMAGE PREPROCESSING & UPLOAD VALIDATION (2A)
# ============================================================================

def validate_and_process_image(
    image_input: Union[str, bytes],
    order_number: Optional[str] = None
) -> Dict[str, Any]:
    """
    Accepts JPEG/PNG/WebP up to 5 MB.
    Validates size and type, strips EXIF location/metadata, downscales to max 1280 px,
    stores under per-order folder, and produces base64 inlineData.
    """
    MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB
    MAX_DIMENSION = 1280

    raw_bytes: bytes = b""
    detected_mime = "image/jpeg"

    if isinstance(image_input, bytes):
        raw_bytes = image_input
    elif isinstance(image_input, str):
        if image_input.startswith("data:image/"):
            # Base64 data URL
            header, b64_str = image_input.split(";base64,")
            detected_mime = header.split("data:")[1].lower()
            raw_bytes = base64.b64decode(b64_str)
        elif image_input.startswith("/static/uploads/") or Path(image_input).exists():
            # Local file path
            file_path = Path(image_input)
            if not file_path.exists():
                file_path = Path(__file__).resolve().parent.parent / image_input.lstrip("/\\")
            if file_path.exists():
                raw_bytes = file_path.read_bytes()
            else:
                raise ValueError(f"Image file not found: {image_input}")
        else:
            # Plain base64 string
            try:
                raw_bytes = base64.b64decode(image_input)
            except Exception:
                raise ValueError("Invalid image input: expected base64 or file path.")

    # Size check
    if len(raw_bytes) > MAX_FILE_SIZE:
        raise ValueError(f"Image file size ({len(raw_bytes) / (1024*1024):.1f} MB) exceeds maximum allowed 5 MB limit.")

    # Open with PIL & validate format
    try:
        pil_img = Image.open(io.BytesIO(raw_bytes))
    except Exception as e:
        raise ValueError(f"Invalid or corrupted image file: {e}")

    fmt = (pil_img.format or "").upper()
    if fmt not in ("JPEG", "JPG", "PNG", "WEBP"):
        raise ValueError(f"Unsupported image format '{fmt}'. Please upload JPEG, PNG, or WebP.")

    # Correct orientation from EXIF before stripping metadata
    pil_img = ImageOps.exif_transpose(pil_img)

    # Convert RGBA/P/palette to RGB for consistent JPEG storage & clean metadata stripping
    if pil_img.mode in ("RGBA", "LA", "P"):
        rgb_img = Image.new("RGB", pil_img.size, (255, 255, 255))
        if pil_img.mode == "RGBA":
            rgb_img.paste(pil_img, mask=pil_img.split()[3])
        else:
            rgb_img.paste(pil_img.convert("RGB"))
        pil_img = rgb_img
    elif pil_img.mode != "RGB":
        pil_img = pil_img.convert("RGB")

    orig_w, orig_h = pil_img.size

    # Downscale if > 1280 px while preserving aspect ratio
    if orig_w > MAX_DIMENSION or orig_h > MAX_DIMENSION:
        pil_img.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.Resampling.LANCZOS)

    new_w, new_h = pil_img.size

    # Compute perceptual hash (dHash)
    phash = compute_dhash(pil_img)

    # Save to disk under per-order folder without EXIF metadata (clean strip)
    folder_name = re.sub(r'[^A-Za-z0-9_-]', '_', order_number or "general")
    target_dir = UPLOAD_DIR / folder_name
    target_dir.mkdir(parents=True, exist_ok=True)

    file_id = f"img_{uuid.uuid4().hex[:8]}"
    out_filename = f"{file_id}.jpg"
    out_path = target_dir / out_filename

    # Save as clean stripped JPEG
    pil_img.save(str(out_path), format="JPEG", quality=88, optimize=True)

    # Re-encode to clean base64 for Gemini inlineData
    buffer = io.BytesIO()
    pil_img.save(buffer, format="JPEG", quality=88, optimize=True)
    clean_b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

    return {
        "file_url": f"/static/uploads/orders/{folder_name}/{out_filename}",
        "file_path": str(out_path),
        "mime_type": "image/jpeg",
        "inline_data": clean_b64,
        "dhash": phash,
        "width": new_w,
        "height": new_h
    }


# ============================================================================
# 3. EVIDENCE ANALYSIS FUNCTION (2B, 2C, 2D)
# ============================================================================

def analyze_evidence(
    order: Any,
    claim_type: str,
    images: List[Dict[str, Any]],
    claim_text: str = "",
    db: Optional[Session] = None
) -> Dict[str, Any]:
    """
    2B: Calls Gemini Vision with strict JSON schema (temperature 0).
    2C: Deterministic decision rules in Python.
    2D: Claim-specific checks (damage/defect, unused tag/box check, hygiene).
    Fails closed: Any API error or invalid JSON returns UNCLEAR, never VERIFIED.
    """
    prod_title = "Purchased Product"
    prod_sku = "N/A"
    prod_category = "General"

    if isinstance(order, dict):
        prod_title = order.get("product_title", prod_title)
        prod_sku = order.get("product_sku", prod_sku)
        prod_category = order.get("category", prod_category)
    elif hasattr(order, "items") and not callable(getattr(order, "items")) and order.items:
        first_item = order.items[0]
        prod_title = getattr(first_item, "product_title", prod_title)
        prod_sku = getattr(first_item, "product_sku", prod_sku)
        if hasattr(first_item, "product") and first_item.product:
            prod_category = getattr(first_item.product, "category", prod_category)

    # 2D: Check if hygiene product (non-returnable regardless of photo)
    if "hygiene" in prod_category.lower() or "undergarment" in prod_category.lower() or "cosmetic" in prod_category.lower():
        return {
            "product_matches": "yes",
            "detected_product": prod_title,
            "damage_present": "none",
            "damage_type": "none",
            "severity": "none",
            "defect_visible": "no",
            "item_unused_with_tag_or_box": "unsure",
            "image_quality": "good",
            "matches_claim": "no",
            "confidence": 1.0,
            "observations": f"Item belongs to hygiene/intimate category ({prod_category}) which is strictly non-returnable under store policy.",
            "status": "MISMATCH",
            "retake_hint": "Hygiene products are non-returnable under store health safety standards."
        }

    # Prepare prompt for Gemini Vision
    system_prompt = (
        "You are an objective, strict QA inspection vision model for an e-commerce platform.\n"
        f"TARGET PRODUCT TO INSPECT: '{prod_title}' (SKU: {prod_sku}, Category: {prod_category}).\n"
        f"CUSTOMER'S CLAIM: '{claim_type}'. Additional customer notes: '{claim_text or 'None'}'.\n\n"
        "INSPECTION GUIDELINES:\n"
        "1. Describe ONLY what is directly visible in the image. NEVER guess, assume, or hallucinate.\n"
        "2. If the product in the photo is clearly different from the target product, set product_matches='no'.\n"
        "3. Check for physical defects or damage (crack, dent, tear, stain, broken part, water damage). Describe visible damage precisely.\n"
        "4. If the customer claim is a size/fit issue or changed mind, verify if the item appears completely UNUSED with its brand tags or original box intact.\n"
        "5. Assess image quality strictly: if the photo is blurry, too dark, taken from too far away, or cropped so the defect cannot be confirmed, set image_quality accordingly.\n"
        "6. Do NOT accuse the customer of dishonesty. Provide concise, professional, plain-language observations."
    )

    parts: List[Dict[str, Any]] = [
        {"text": f"Inspect the evidence photo(s) for product '{prod_title}' regarding claim '{claim_type}'."}
    ]

    for img in images:
        if img.get("inline_data"):
            parts.append({
                "inlineData": {
                    "mimeType": img.get("mime_type", "image/jpeg"),
                    "data": img["inline_data"]
                }
            })

    # Call Gemini Vision (temperature 0.0)
    raw_response = None
    try:
        raw_response = call_gemini(
            system_prompt=system_prompt,
            contents=[{"role": "user", "parts": parts}],
            schema=EVIDENCE_VISION_SCHEMA,
            temperature=0.0,
            max_tokens=600
        )
    except Exception as e:
        print(f"[Vision Engine Exception]: {e}")

    # Fail closed on API error / empty response (2C, Test 9)
    if not raw_response:
        return {
            "product_matches": "unsure",
            "detected_product": "unknown",
            "damage_present": "unsure",
            "damage_type": "none",
            "severity": "none",
            "defect_visible": "unsure",
            "item_unused_with_tag_or_box": "unsure",
            "image_quality": "blurry",
            "matches_claim": "no",
            "confidence": 0.0,
            "observations": "Visual inspection could not be completed automatically due to an image processing service timeout.",
            "status": "UNCLEAR",
            "retake_hint": "could you please upload another photo taken in good daylight?"
        }

    # Parse JSON
    try:
        parsed = json.loads(raw_response)
    except Exception as e:
        print(f"[Vision Engine JSON Parse Error]: {e}")
        # Fail closed on invalid JSON (2C)
        return {
            "product_matches": "unsure",
            "detected_product": "unknown",
            "damage_present": "unsure",
            "damage_type": "none",
            "severity": "none",
            "defect_visible": "unsure",
            "item_unused_with_tag_or_box": "unsure",
            "image_quality": "blurry",
            "matches_claim": "no",
            "confidence": 0.0,
            "observations": "Visual analysis output could not be formatted properly.",
            "status": "UNCLEAR",
            "retake_hint": "could you please upload a clearer photo?"
        }

    # ========================================================================
    # DETERMINISTIC DECISION RULES IN PYTHON (2C, 2D)
    # ========================================================================
    product_matches = str(parsed.get("product_matches", "unsure")).lower()
    image_quality = str(parsed.get("image_quality", "blurry")).lower()
    confidence = float(parsed.get("confidence", 0.0))
    damage_present = str(parsed.get("damage_present", "unsure")).lower()
    defect_visible = str(parsed.get("defect_visible", "unsure")).lower()
    matches_claim = str(parsed.get("matches_claim", "no")).lower()
    item_unused = str(parsed.get("item_unused_with_tag_or_box", "unsure")).lower()
    damage_type = str(parsed.get("damage_type", "none")).lower()
    observations = parsed.get("observations") or "Inspection completed."

    # Generate specific retake hint based on vision feedback
    retake_hint = generate_retake_hint(image_quality, damage_type, prod_title)

    final_status = "UNCLEAR"

    # Rule 1: Product mismatch
    if product_matches == "no":
        final_status = "MISMATCH"
        retake_hint = f"This photo appears to show a different product than {prod_title}. Could you share a photo of your {prod_title}?"

    # Rule 2: Low quality photo (blurry, dark, too far, cropped) or low confidence -> UNCLEAR
    elif image_quality in ("blurry", "dark", "too_far", "cropped") or confidence < 0.7:
        final_status = "UNCLEAR"

    # Rule 3: Size / fit issue or Changed mind -> requires item unused with tag or box intact (2D)
    elif claim_type in ("Size / fit issue", "Changed my mind"):
        if item_unused == "yes" and confidence >= 0.7 and image_quality == "good":
            final_status = "VERIFIED"
        else:
            final_status = "UNCLEAR"
            retake_hint = "could you please upload a photo clearly showing the original tags and box intact to confirm it is unused?"

    # Rule 4: Defective / Damaged on arrival / Not as described
    elif claim_type in ("Damaged on arrival", "Defective or not working", "Wrong item", "Not as described"):
        condition_visible = (damage_present == "yes" or defect_visible == "yes" or matches_claim in ("yes", "partly"))
        if product_matches == "yes" and condition_visible and confidence >= 0.7 and image_quality == "good":
            final_status = "VERIFIED"
        elif damage_present == "no" and defect_visible == "no" and matches_claim == "no":
            final_status = "MISMATCH"
            retake_hint = f"I couldn't spot the damage in this photo. Could you share another angle showing where it is damaged?"
        else:
            final_status = "UNCLEAR"
    else:
        # Generic claim fallback
        if product_matches == "yes" and confidence >= 0.7 and image_quality == "good":
            final_status = "VERIFIED"
        else:
            final_status = "UNCLEAR"

    parsed["status"] = final_status
    parsed["retake_hint"] = retake_hint
    return parsed


def generate_retake_hint(image_quality: str, damage_type: str, prod_title: str) -> str:
    """Generates polite, specific retake guidance for UNCLEAR or MISMATCH photos (2C)."""
    if image_quality == "blurry":
        return "could you please take a steady, in-focus photo so we can verify the issue?"
    elif image_quality == "dark":
        damage_ref = damage_type if damage_type not in ("none", "other") else "defect"
        return f"could you take it in daylight or brighter lighting, closer to the {damage_ref}?"
    elif image_quality == "too_far":
        return "could you please take a close-up photo showing the defect clearly?"
    elif image_quality == "cropped":
        return "could you please capture the entire item in the photo frame?"
    return "could you take it in daylight, closer to the defect?"
