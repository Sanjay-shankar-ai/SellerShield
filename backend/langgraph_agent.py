import os
import re
import json
import time
import datetime
import sqlite3
import uuid
from pathlib import Path
from typing import Annotated, TypedDict, Optional, List, Dict, Any, Union, Tuple
import httpx
from dotenv import load_dotenv
from pydantic import BaseModel, Field

env_path = Path(__file__).parent / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    load_dotenv()

from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.types import interrupt, Command
from langgraph.checkpoint.sqlite import SqliteSaver
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, RemoveMessage
from sqlalchemy.orm import Session

from .database import SessionLocal
from .models import User, Order, Product, Conversation, Message, TrackingEvent, Setting, Escalation, AuditLog, PromoCode, CustomerMemory, WalletTransaction, SupportCall
from .policy_engine import check_policy, PolicyVerdict, get_setting_value
from .order_api import track_order, get_customer_orders
from .return_api import create_exchange, create_return, list_alternatives, cancel_order, reserve_stock
from .refund_api import issue_refund, issue_wallet_credit, issue_promo_code
from .escalation import escalate_to_human
from .audit_log import log_audit_event
from .image_evidence import validate_and_process_image, analyze_evidence, check_image_fraud_and_register

# Configurable constants for memory summarization
SUMMARIZE_THRESHOLD = int(os.environ.get("SUMMARIZE_THRESHOLD", 12))
MESSAGES_TO_KEEP = int(os.environ.get("MESSAGES_TO_KEEP", 6))

# Persistent HTTP client for Gemini API calls
_http_client = httpx.Client(
    timeout=httpx.Timeout(12.0, connect=4.0),
    limits=httpx.Limits(max_keepalive_connections=10, max_connections=20)
)

# SQLite Checkpointer connection (thread-safe for SQLite)
CHECKPOINT_DB_PATH = str(Path(__file__).parent.parent / "sellershield_checkpoints.db")
_checkpoint_conn = sqlite3.connect(CHECKPOINT_DB_PATH, check_same_thread=False)
checkpointer = SqliteSaver(_checkpoint_conn)
checkpointer.setup()


# ============================================================================
# 0. SENSITIVE DATA FILTER & EXTRACTION SCHEMAS
# ============================================================================

def sanitize_memory_text(text: str) -> str:
    """
    Regex filter over summary and memory before saving to state or database.
    Redacts: credit/debit card numbers, OTPs/PINs, passwords, phone numbers, full addresses/pincodes.
    """
    if not text:
        return ""
    # Credit/debit card numbers (13-19 digits with optional hyphens/spaces)
    text = re.sub(r'\b(?:\d[ -]*?){13,19}\b', '[REDACTED_CARD]', text)
    # OTP / PIN / verification codes (4 to 8 digits)
    text = re.sub(r'(?i)\b(?:otp|pin|verification\s*code)\b[^\d]{0,10}(\d{4,8})\b', '[REDACTED_OTP]', text)
    text = re.sub(r'(?i)\b(\d{4,8})\s+(?:is my otp|is the otp|is my code)\b', '[REDACTED_OTP]', text)
    # Passwords
    text = re.sub(r'(?i)\b(?:password|pwd)(?:\s+(?:is|was))?[\s:=]+([^\s,;]+)', '[REDACTED_PASSWORD]', text)
    # Phone numbers (Indian and international formats)
    text = re.sub(r'(?:\+?91[\-\s]?)?[6-9]\d{9}\b', '[REDACTED_PHONE]', text)
    text = re.sub(r'\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b', '[REDACTED_PHONE]', text)
    # Full addresses / Pincodes
    text = re.sub(r'(?i)\b(?:address|shipping address)[\s:=]+([^\n\r]+)', '[REDACTED_ADDRESS]', text)
    text = re.sub(r'(?i)\b(?:pincode|pin code|zip code|postal code)[\s:=]*\d{5,6}\b', '[REDACTED_PINCODE]', text)
    return text


class CustomerMemoryExtract(BaseModel):
    preferred_language: Optional[str] = Field(None, description="Preferred language, e.g. English, Hinglish, Tamil")
    usual_size: Optional[str] = Field(None, description="Usual shoe or apparel size, e.g. 9 UK, XL")
    tone_preference: Optional[str] = Field(None, description="Tone preference, e.g. direct, polite, brief, detail-oriented")
    past_issue: Optional[str] = Field(None, description="A single one-line factual note of the issue and outcome if this case closed, e.g. 'Defective shoes: approved full refund to wallet'")


MEMORY_EXTRACT_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "preferred_language": {"type": "STRING", "nullable": True},
        "usual_size": {"type": "STRING", "nullable": True},
        "tone_preference": {"type": "STRING", "nullable": True},
        "past_issue": {"type": "STRING", "nullable": True}
    }
}


# ============================================================================
# 1. DYNAMIC PROMPT COMPOSER
# ============================================================================

def get_composed_system_prompt(
    db: Session,
    node_instruction: str = "",
    summary: Optional[str] = None,
    customer_memory: Optional[Dict[str, Any]] = None
) -> str:
    """
    Composes system prompt dynamically:
    system = persona_prompt + knowledge_prompt (with {{placeholders}} from settings) + policy_prompt + node_instruction +
             "CONVERSATION SO FAR: {summary or 'New conversation'}" +
             "KNOWN ABOUT THIS CUSTOMER: {customer_memory or 'Nothing yet'}" +
             "Memory is background only. For order status, delivery, eligibility, stock and amounts,
              always use live tool results. If memory and a tool disagree, trust the tool."
    Never hard-codes timelines, limits, or bonus % in prompt text.
    """
    prompts_dir = Path(__file__).parent / "prompts"
    persona_path = prompts_dir / "persona_prompt.txt"
    knowledge_path = prompts_dir / "knowledge_prompt.txt"
    policy_path = prompts_dir / "policy_prompt.txt"

    persona_text = persona_path.read_text(encoding="utf-8") if persona_path.exists() else "You are Maya, support executive."
    knowledge_text = knowledge_path.read_text(encoding="utf-8") if knowledge_path.exists() else "Store policies."
    policy_text = policy_path.read_text(encoding="utf-8") if policy_path.exists() else "Policy rules."

    # Dynamic settings from DB
    return_window_days = str(get_setting_value(db, "return_window_days", 7))
    replacement_delivery_days = str(get_setting_value(db, "replacement_delivery_days", 2))
    refund_processing_days = str(get_setting_value(db, "refund_processing_days", "4-5"))
    refund_limit = f"{float(get_setting_value(db, 'refund_limit', 2000.0)):,.0f}"
    store_credit_bonus_pct = str(int(float(get_setting_value(db, "store_credit_bonus_pct", 10.0))))
    trust_high_refund_limit = f"{float(get_setting_value(db, 'trust_high_refund_limit', 5000.0)):,.0f}"
    trust_normal_refund_limit = f"{float(get_setting_value(db, 'trust_normal_refund_limit', 2000.0)):,.0f}"
    trust_risky_refund_limit = f"{float(get_setting_value(db, 'trust_risky_refund_limit', 0.0)):,.0f}"
    p2p_radius_km = str(get_setting_value(db, "p2p_radius_km", 25))
    leakage_threshold = str(get_setting_value(db, "leakage_threshold", 5))
    leakage_window_hours = str(get_setting_value(db, "leakage_window_hours", 48))
    reservation_hours = str(get_setting_value(db, "reservation_hours", 48))

    def replace_placeholders(text: str) -> str:
        return text \
            .replace("{{return_window_days}}", return_window_days) \
            .replace("{{replacement_delivery_days}}", replacement_delivery_days) \
            .replace("{{refund_processing_days}}", refund_processing_days) \
            .replace("{{refund_limit}}", refund_limit) \
            .replace("{{store_credit_bonus_pct}}", store_credit_bonus_pct) \
            .replace("{{trust_high_refund_limit}}", trust_high_refund_limit) \
            .replace("{{trust_normal_refund_limit}}", trust_normal_refund_limit) \
            .replace("{{trust_risky_refund_limit}}", trust_risky_refund_limit) \
            .replace("{{p2p_radius_km}}", p2p_radius_km) \
            .replace("{{leakage_threshold}}", leakage_threshold) \
            .replace("{{leakage_window_hours}}", leakage_window_hours) \
            .replace("{{reservation_hours}}", reservation_hours)

    knowledge_filled = replace_placeholders(knowledge_text)
    policy_filled = replace_placeholders(policy_text)

    composed = f"{persona_text.strip()}\n\n{knowledge_filled.strip()}\n\n{policy_filled.strip()}"
    if node_instruction:
        composed += f"\n\n══ CURRENT NODE INSTRUCTION ══\n{node_instruction.strip()}"

    summary_val = summary.strip() if (summary and summary.strip()) else "New conversation"
    customer_mem_val = json.dumps(customer_memory, indent=2) if (customer_memory and any(customer_memory.values())) else "Nothing yet"

    composed += (
        f"\n\nCONVERSATION SO FAR: {summary_val}\n\n"
        f"KNOWN ABOUT THIS CUSTOMER: {customer_mem_val}\n\n"
        "Memory is background only. For order status, delivery, eligibility, stock and amounts, "
        "always use live tool results. If memory and a tool disagree, trust the tool."
    )
    return composed

compose_system_prompt = get_composed_system_prompt


# ============================================================================
# 2. LANGGRAPH STATE DEFINITION (TypedDict)
# ============================================================================

def safe_add_messages(left: Any, right: Any) -> List[Any]:
    """Safe wrapper over add_messages that gracefully coerces legacy dict messages with 'text' and 'model' keys into LangChain messages."""
    def fix_item(m: Any) -> Any:
        if isinstance(m, dict):
            m_copy = dict(m)
            if "text" in m_copy and "content" not in m_copy:
                m_copy["content"] = m_copy.pop("text")
            if m_copy.get("role") == "model":
                m_copy["role"] = "ai"
            return m_copy
        return m

    if isinstance(left, list):
        left = [fix_item(m) for m in left]
    if isinstance(right, list):
        right = [fix_item(m) for m in right]
    return add_messages(left, right)


PRODUCT_COLORS = {
    "Imperial Linen Slim-Fit Blazer": ["Midnight Navy", "Charcoal Grey", "Beige Sand", "Classic Black"],
    "AeroFly Pro Running Shoes": ["Crimson Red", "Obsidian Black", "Arctic White", "Volt Neon"],
    "SonicWave ANC Wireless Earbuds": ["Frost White", "Midnight Black", "Sage Green"],
    "Chronos X AMOLED Smartwatch": ["Space Titanium", "Stealth Black", "Rose Gold"],
    "TrailMaster Water-Repellent Backpack (30L)": ["Olive Drab", "Midnight Black", "Coyote Tan"],
    "Artisan Mechanical Keyboard (RGB)": ["Retro White", "Cyberpunk Purple", "Matte Black"],
    "Carbon Tactical EDC Box": ["Matte Black", "Desert Tan", "Tactical Grey"],
    "Pure Bamboo Fiber Underwear Pack (3-Pack)": ["Classic Black", "Navy Blue", "Heather Grey"],
    "Nordic Minimalist Ceramic Desk Lamp": ["Matte White", "Terracotta Clay", "Charcoal Black"],
    "ActiveFlex Compression Gym Leggings": ["Midnight Navy", "Carbon Black", "Plum Purple", "Sage Green"]
}

def get_product_colors(title: str) -> List[str]:
    title_lower = (title or "").lower()
    for prod_name, colors in PRODUCT_COLORS.items():
        if prod_name.lower() in title_lower or title_lower in prod_name.lower():
            return colors
    return ["Midnight Black", "Classic Navy", "Charcoal Grey", "Beige Sand"]


def is_electronic_gadget_product(title: str) -> bool:
    t = (title or "").lower()
    return any(k in t for k in (
        "smartwatch", "watch", "earbuds", "earbud", "headphones", "headphone",
        "keyboard", "audio", "gadget", "electronic", "wireless", "amoled", "anc", "rgb", "device"
    ))


def is_electronic_gadget_issue(text: str) -> bool:
    t = (text or "").lower()
    return any(k in t for k in (
        "screen", "display", "touch", "flicker", "flickering", "black screen", "blank screen",
        "battery", "drain", "draining", "charge", "charging", "not charging", "won't charge",
        "bluetooth", "pair", "pairing", "connect", "disconnect", "connectivity",
        "audio", "sound", "crackling", "distorted", "mic", "microphone", "speaker",
        "turn on", "turning on", "power on", "won't turn on", "not turning on", "dead",
        "not working", "defective", "malfunction", "hardware", "technical issue", "gadget issue",
        "electronic issue", "gadget problem", "device issue", "electronic gadget"
    ))


def get_order_refundable_amount(order: Optional[Order], db: Session) -> float:
    """
    Computes the full refundable order value.
    If the order was paid via wallet or promo, order.total_amount might be 0,
    so we check:
      1. Wallet debit transactions recorded for this order
      2. Items total value (sum of unit_price * quantity)
      3. Stored total_amount
    Returns the maximum valid amount so the customer is always refunded the full value.
    """
    if not order:
        return 1499.0

    # 1. Check wallet debit transaction for this order
    wallet_debit = db.query(WalletTransaction).filter(
        WalletTransaction.customer_id == order.customer_id,
        (WalletTransaction.order_id == order.id) | (WalletTransaction.order_number == order.order_number),
        WalletTransaction.transaction_type == "DEBIT"
    ).first()
    wallet_amount = float(wallet_debit.amount) if wallet_debit and wallet_debit.amount else 0.0

    # 2. Check items subtotal
    items_total = float(sum(it.subtotal for it in order.items)) if order.items else 0.0

    # 3. Calculate full refundable amount
    order_total = float(order.total_amount or 0.0)
    amt = max(order_total, wallet_amount, items_total)
    return round(amt, 2) if amt > 0 else 1499.0


class SellerShieldAgentState(TypedDict):
    # Core session & identity (customer_id strictly from session, never from chat text)
    customer_id: str
    conv_id: str
    user_message: str
    evidence_photo: Optional[str]
    active_order_id: Optional[str]
    messages: Annotated[List[Any], safe_add_messages]

    # Memory layers
    summary: str
    customer_memory: Dict[str, Any]
    case_closed: bool

    # NLU understanding (1B)
    language: str
    register: Optional[str]  # "formal" | "casual"
    sentiment: str
    emotion: Optional[str]  # "calm" | "confused" | "frustrated" | "angry" | "worried" | "happy"
    urgency: str
    intent: str  # "TRACKING" | "RETURN_REFUND_EXCHANGE" | "CANCEL" | "EXPEDITE" | "GENERAL"
    sub_intent: Optional[str]
    current_question: Optional[str]
    correction: Optional[str]
    offer_response: Optional[str]  # "ACCEPTED" | "DECLINED" | "NONE"
    needs_clarification: Optional[bool]
    clarification_question: Optional[str]
    fact_packet: Optional[Dict[str, Any]]
    voice_mode: Optional[bool]

    # Order tracking & resolution state
    order_id: Optional[str]
    order_number: Optional[str]
    reason_category: Optional[str]
    reason_text: Optional[str]
    evidence_status: str  # "NONE" | "PENDING" | "VERIFIED" | "UNCLEAR" | "MISMATCH"
    evidence_retries: int
    evidence_photos: Optional[List[str]]
    vision_analysis: Optional[Dict[str, Any]]
    fraud_flags: Optional[List[str]]
    resolution_type: Optional[str]  # "REPLACEMENT" | "REFUND"
    replacement_choice: Optional[Dict[str, Any]]
    refund_destination: Optional[str]  # "WALLET" | "PROMO" | "ORIGINAL"
    offered: List[str]
    declined: List[str]
    verdict: Optional[str]  # "AUTO_APPROVE" | "NEEDS_HUMAN" | "DENY"
    cancel_reason: Optional[str]  # Reason customer wants to cancel
    cancel_confirmed: Optional[bool]  # Customer insisted on cancelling after retention
    step: Optional[str]
    pending_question: Optional[str]

    # Outputs
    reply: str
    quick_replies: List[str]
    tool_calls: List[Dict[str, Any]]
    error: Optional[str]
    start_time: float


# Startup prompt file validation (1G)
def validate_startup_prompts() -> Dict[str, str]:
    """
    Validates and logs character counts for the three core prompt files at startup.
    Warns if a file is missing or under 300 characters.
    """
    prompts_dir = Path(__file__).parent / "prompts"
    prompt_files = {
        "persona_prompt.txt": prompts_dir / "persona_prompt.txt",
        "knowledge_prompt.txt": prompts_dir / "knowledge_prompt.txt",
        "policy_prompt.txt": prompts_dir / "policy_prompt.txt"
    }
    loaded = {}
    for filename, path in prompt_files.items():
        if not path.exists():
            print(f"[PROMPT WARNING] Prompt file '{filename}' is MISSING at {path}!")
            loaded[filename] = ""
        else:
            txt = path.read_text(encoding="utf-8")
            char_len = len(txt)
            if char_len < 300:
                print(f"[PROMPT WARNING] Prompt file '{filename}' has only {char_len} characters (under 300 characters)!")
            else:
                print(f"[PROMPT STARTUP] Loaded '{filename}' ({char_len} characters)")
            loaded[filename] = txt
    return loaded

_STARTUP_PROMPTS = validate_startup_prompts()


# ============================================================================
# 3. HELPER: CALL GEMINI API & HUMANIZE REWRITE
# ============================================================================

def call_gemini(
    system_prompt: str,
    contents: List[Dict[str, Any]],
    schema: Optional[Dict[str, Any]] = None,
    temperature: float = 0.2,
    max_tokens: int = 500
) -> Optional[str]:
    """
    Executes a Gemini generateContent request with header-based authentication.
    Logs every failure (HTTP status + first 300 chars of body), exceptions (with repr), and missing keys.
    """
    api_key = (os.environ.get("LLM_API_KEY") or os.environ.get("GEMINI_API_KEY") or "").strip()
    if not api_key:
        print("[Gemini Call Error]: Missing API key. Neither LLM_API_KEY nor GEMINI_API_KEY is configured in environment.")
        return None

    model = (os.environ.get("GEMINI_MODEL") or "gemini-2.5-flash").strip()
    preferred_models = [
        model,
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-1.5-flash",
        "gemini-1.5-flash-8b",
        "gemini-3-flash-preview"
    ]
    candidates_models = []
    seen = set()
    for m in preferred_models:
        if m and m not in seen:
            seen.add(m)
            candidates_models.append(m)

    payload: Dict[str, Any] = {
        "contents": contents,
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
            "thinkingConfig": {"thinkingBudget": 0}
        }
    }
    if schema:
        payload["generationConfig"]["responseMimeType"] = "application/json"
        payload["generationConfig"]["responseSchema"] = schema

    headers = {
        "x-goog-api-key": api_key,
        "Content-Type": "application/json"
    }

    for m in candidates_models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent"
        try:
            resp = _http_client.post(url, json=payload, headers=headers, timeout=6.0)
            if resp.status_code == 200:
                res_data = resp.json()
                return res_data["candidates"][0]["content"]["parts"][0]["text"]
            else:
                body_snippet = resp.text[:300] if resp.text else "(empty body)"
                print(f"[Gemini Failure on {m}]: HTTP {resp.status_code} - {body_snippet}")
        except Exception as e:
            print(f"[Gemini Exception on {m}]: {repr(e)}")
    return None


RESPOND_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "reply": {"type": "STRING"},
        "quick_replies": {
            "type": "ARRAY",
            "items": {"type": "STRING"}
        }
    },
    "required": ["reply"]
}

HUMANIZE_SCHEMA = RESPOND_SCHEMA


def humanize(
    db: Session,
    state: SellerShieldAgentState,
    draft: str,
    buttons: List[str]
) -> Tuple[str, List[str]]:
    """
    Phase 1 (Deep Conversation Engine - 1A, 1B, 1C, 1D, 1E, 1H):
    Generates human-like response from FACT PACKET, customer words, emotion, and context.
    - Temperature 0.7
    - Strict fact adherence: ORD numbers, case numbers, amounts, dates kept exact.
    - Token safety check: if critical token missing, regenerates once with temperature 0.7 before fallback.
    - Avoids repeating opening phrasing from recent agent messages.
    - Answers side questions in-flow, then gently returns to pending step.
    - Dynamically proposes and filters buttons against allowed actions.
    """
    if not draft or not draft.strip():
        return draft, buttons

    user = db.query(User).filter(User.id == state["customer_id"]).first()
    first_name = user.full_name.split()[0] if user else "there"

    # 1. Fact Packet
    fact_packet = dict(state.get("fact_packet") or {})
    if "draft" not in fact_packet:
        fact_packet["draft"] = draft
    if "order_number" not in fact_packet and state.get("order_number"):
        fact_packet["order_number"] = state.get("order_number")
    if "pending_question" not in fact_packet and state.get("pending_question"):
        fact_packet["pending_question"] = state.get("pending_question")

    # 2. Check for side questions
    side_q = state.get("current_question")
    user_msg_lower = state.get("user_message", "").lower()
    side_answer = None

    if any(k in user_msg_lower for k in ("how long", "when will", "kitna time", "time take", "processing time", "refund take")):
        side_answer = "Refunds to your original payment method take 4–5 working days after approval, while store wallet credit is instant with an extra 10% bonus for promo codes."
    elif any(k in user_msg_lower for k in ("replacement take", "when will replacement", "exchange time")):
        side_answer = "Doorstep replacements are delivered within 2 days with your size reserved."
    elif any(k in user_msg_lower for k in ("return window", "how many days to return")):
        side_answer = "Our return and exchange window is 7 days from the delivery date."
    elif any(k in user_msg_lower for k in ("can i cancel", "how to cancel")):
        side_answer = "Pre-dispatch orders can be cancelled immediately for a 100% full refund; orders in transit cannot be cancelled until delivered."

    if side_answer:
        fact_packet["side_question"] = side_q or state.get("user_message")
        fact_packet["side_question_answer"] = side_answer

    # 3. Gather recent agent openings to avoid repetition (1C)
    previous_openings = []
    for m in (state.get("messages") or []):
        role = getattr(m, "type", "") or (m.get("role") if isinstance(m, dict) else "")
        if role in ("ai", "model", "agent"):
            txt = getattr(m, "content", "") or (m.get("text") or m.get("content") or "")
            if txt:
                words = txt.strip().split()[:4]
                if words:
                    previous_openings.append(" ".join(words))

    # 4. Formulate Deep Conversation Instruction
    instruction = (
        f"You are Maya speaking to customer {user.full_name if user else 'Customer'} (first name: {first_name}).\n"
        f"Customer Emotion: {state.get('emotion') or state.get('sentiment', 'calm')}. Urgency: {state.get('urgency', 'medium')}.\n"
        f"Customer Language: {state.get('language', 'English')}. Register: {state.get('register', 'casual')}.\n"
        f"══ FACT PACKET (STRICT SOURCE OF TRUTH) ══\n{json.dumps(fact_packet, indent=2)}\n\n"
        f"══ CANDIDATE BUTTONS ══\n{json.dumps(buttons)}\n\n"
        f"PREVIOUS AGENT OPENINGS TO AVOID: {json.dumps(previous_openings[-2:] if previous_openings else [])}\n\n"
        "STRICT CONVERSATION RULES (1C, 1D, 1E, 1H):\n"
        "1. Respond directly to what the customer actually said first; then move the flow forward.\n"
        "2. Acknowledge emotion specifically (e.g. 'a chipped spout on a gift is so annoying' or 'I know you need these running shoes urgently'), "
        "NEVER using stock phrases like 'I understand your concern', 'As an AI', or 'I apologize for the inconvenience'.\n"
        "3. 1–3 short sentences only, one question at a time.\n"
        "4. Vary sentence openings: do NOT start your reply with the same opening words as previous agent replies.\n"
        "5. Match the customer's language and tone (English, Tamil, Hinglish, casual slang). Mixed language is welcome.\n"
        "6. If a side question is present in the fact packet, answer it concisely in 1 sentence, then gently return to the pending step.\n"
        "7. Never state a fact (status, amount, date, timeline, eligibility) not confirmed in the fact packet. Keep ORD-numbers, case numbers, and ₹ amounts EXACT.\n"
        "8. Don't re-offer what was declined; don't repeat what was just told.\n"
        "9. Persuasion is honest and gentle: solve the real problem once (swap, fix, credit), then respect choice. Never guilt or pressure.\n"
        "10. If evidence observations are present in the fact packet (e.g. 'crack along the left side'), refer naturally to what is visible to reassure the customer (e.g. 'I can see the crack along the left side. Let's get this resolved for you right away.').\n"
        "11. Propose 2-3 dynamic quick-reply buttons in quick_replies that fit this exact moment.\n"
        "Return JSON: {\"reply\": \"...\", \"quick_replies\": [\"...\", \"...\"]}"
    )

    system_prompt = get_composed_system_prompt(
        db=db,
        node_instruction=instruction,
        summary=state.get("summary"),
        customer_memory=state.get("customer_memory")
    )

    history_contents = []
    for m in (state.get("messages") or [])[-6:]:
        role = "user" if getattr(m, "type", "human") in ("human", "user") or (isinstance(m, dict) and m.get("role") in ("user", "human")) else "model"
        text = getattr(m, "content", "") if hasattr(m, "content") else (m.get("text") or m.get("content") or "")
        if text:
            history_contents.append({"role": role, "parts": [{"text": text}]})
    history_contents.append({"role": "user", "parts": [{"text": state.get("user_message", "")}]})

    res_text = call_gemini(
        system_prompt=system_prompt,
        contents=history_contents,
        schema=RESPOND_SCHEMA,
        temperature=0.7,
        max_tokens=500
    )

    candidate_reply = None
    candidate_buttons = buttons

    if res_text:
        try:
            parsed = json.loads(res_text)
            candidate_reply = (parsed.get("reply") or "").strip()
            candidate_buttons = parsed.get("quick_replies") or buttons
        except Exception as e:
            print(f"[Humanize JSON Parse Error]: {e}")

    # Fallback to draft if Gemini unavailable or returned empty
    if not candidate_reply:
        fallback_reply = draft
        if fact_packet.get("evidence_observations") and state.get("evidence_status") == "VERIFIED":
            obs_str = fact_packet['evidence_observations'].strip()
            if not any(k in fallback_reply.lower() for k in ("i can see", "visible", "crack", "damage", "noted")):
                fallback_reply = f"I can see the {obs_str.lower()}. {fallback_reply}"
        if side_answer and side_answer not in fallback_reply:
            fallback_reply = f"{side_answer} {fallback_reply}"

        # 1C Rule 3: Sentence opening variation check on fallback reply
        cand_words = fallback_reply.strip().split()
        if cand_words and previous_openings:
            last_opening = previous_openings[-1].lower()
            cand_opening = " ".join(cand_words[:3]).lower()
            if cand_opening.startswith(last_opening[:10]) or last_opening.startswith(cand_opening[:10]):
                if cand_words[0].lower() in ("hey", "hello", "hi") and len(cand_words) > 2:
                    fallback_reply = " ".join(cand_words[2:])
                    if fallback_reply:
                        fallback_reply = fallback_reply[0].upper() + fallback_reply[1:]

        # Filter buttons against allowed actions
        order_status = None
        if state.get("order_id"):
            ord_obj = db.query(Order).filter(Order.id == state.get("order_id")).first()
            if ord_obj:
                order_status = ord_obj.status

        filtered_buttons = []
        for b in buttons:
            b_lower = b.lower()
            if "cancel" in b_lower and order_status in ("SHIPPED", "OUT_FOR_DELIVERY", "DELIVERED", "REFUNDED", "EXCHANGED"):
                continue
            if "refund" in b_lower and order_status == "REFUNDED":
                continue
            filtered_buttons.append(b)

        return fallback_reply, filtered_buttons if filtered_buttons else buttons

    # 1C: Safety check - extract ORD-\d+, case numbers and ₹ amounts
    ord_matches = re.findall(r'\bORD-\d+\b', draft)
    case_matches = re.findall(r'\bCASE-[A-Za-z0-9-]+\b', draft)
    amount_matches = re.findall(r'₹\s*[\d,]+(?:\.\d+)?', draft)

    missing_tokens = []
    for tok in ord_matches + case_matches + amount_matches:
        tok_clean = tok.replace(" ", "")
        candidate_clean = candidate_reply.replace(" ", "")
        if tok not in candidate_reply and tok_clean not in candidate_clean:
            missing_tokens.append(tok)

    # If critical token missing, attempt regeneration ONCE with temperature 0.7
    if missing_tokens:
        print(f"[Humanize Safety Check]: token(s) {missing_tokens} missing. Attempting regeneration once...")
        regen_instruction = (
            instruction + "\n\n"
            f"IMPORTANT: You omitted the following required identifiers from your previous reply: {missing_tokens}. "
            f"You MUST include every one of them ({missing_tokens}) exactly as written!"
        )
        regen_system_prompt = get_composed_system_prompt(
            db=db,
            node_instruction=regen_instruction,
            summary=state.get("summary"),
            customer_memory=state.get("customer_memory")
        )
        res_regen = call_gemini(
            system_prompt=regen_system_prompt,
            contents=history_contents,
            schema=RESPOND_SCHEMA,
            temperature=0.7,
            max_tokens=500
        )
        if res_regen:
            try:
                parsed_regen = json.loads(res_regen)
                cand_regen = (parsed_regen.get("reply") or "").strip()
                if cand_regen and all(tok in cand_regen or tok.replace(" ", "") in cand_regen.replace(" ", "") for tok in missing_tokens):
                    candidate_reply = cand_regen
                    candidate_buttons = parsed_regen.get("quick_replies") or candidate_buttons
                    missing_tokens = []
            except Exception:
                pass

        if missing_tokens:
            print(f"[Humanize Fallback]: Discarding rewrite and using factual draft due to missing tokens: {missing_tokens}")
            fallback_reply = draft
            if side_answer and side_answer not in fallback_reply:
                fallback_reply = f"{side_answer} {fallback_reply}"
            return fallback_reply, buttons

    # 1D: Filter candidate buttons against allowed actions
    order_status = None
    if state.get("order_id"):
        ord_obj = db.query(Order).filter(Order.id == state.get("order_id")).first()
        if ord_obj:
            order_status = ord_obj.status

    filtered_buttons = []
    for b in candidate_buttons:
        b_lower = b.lower()
        if "cancel" in b_lower and order_status in ("SHIPPED", "OUT_FOR_DELIVERY", "DELIVERED", "REFUNDED", "EXCHANGED"):
            continue
        if "refund" in b_lower and order_status == "REFUNDED":
            continue
        filtered_buttons.append(b)

    if len(filtered_buttons) < 2 and buttons:
        for b in buttons:
            if b not in filtered_buttons:
                filtered_buttons.append(b)
                if len(filtered_buttons) >= 3:
                    break
    final_buttons = filtered_buttons[:3] if filtered_buttons else buttons

    # 1C Rule 3: Sentence opening variation check
    cand_words = candidate_reply.strip().split()
    if cand_words and previous_openings:
        last_opening = previous_openings[-1].lower()
        cand_opening = " ".join(cand_words[:3]).lower()
        if cand_opening.startswith(last_opening[:10]) or last_opening.startswith(cand_opening[:10]):
            if cand_words[0].lower() in ("hey", "hello", "hi") and len(cand_words) > 2:
                candidate_reply = " ".join(cand_words[2:])
                if candidate_reply:
                    candidate_reply = candidate_reply[0].upper() + candidate_reply[1:]

    return candidate_reply, final_buttons


# ============================================================================
# 4. GRAPH NODES (14 NODES)
# ============================================================================

UNDERSTAND_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "intent": {
            "type": "STRING",
            "enum": ["TRACKING", "RETURN_REFUND_EXCHANGE", "CANCEL", "EXPEDITE", "GENERAL"]
        },
        "sub_intent": {
            "type": "STRING",
            "enum": [
                "CHECK_STATUS", "ASK_TIMELINE", "ASK_REFUND_POLICY", "REQUEST_SWAP",
                "REQUEST_REFUND", "COMPLAIN", "CORRECTION", "GREETING",
                "SIDE_QUESTION", "CLARIFICATION", "OTHER"
            ]
        },
        "emotion": {
            "type": "STRING",
            "enum": ["calm", "confused", "frustrated", "angry", "worried", "happy"]
        },
        "sentiment": {
            "type": "STRING",
            "enum": ["CALM", "FRUSTRATED", "CONFUSED", "HAPPY"]
        },
        "urgency": {
            "type": "STRING",
            "enum": ["low", "medium", "high"]
        },
        "referenced_order": {"type": "STRING", "nullable": True},
        "reason_category": {
            "type": "STRING",
            "enum": [
                "Defective or not working",
                "Damaged on arrival",
                "Wrong item",
                "Size / fit issue",
                "Not as described",
                "Changed my mind",
                "Something else",
                "NONE"
            ]
        },
        "reason_text": {"type": "STRING", "nullable": True},
        "current_question": {"type": "STRING", "nullable": True},
        "correction": {"type": "STRING", "nullable": True},
        "offer_response": {
            "type": "STRING",
            "enum": ["ACCEPTED", "DECLINED", "NONE"]
        },
        "resolution_type": {
            "type": "STRING",
            "enum": ["REPLACEMENT", "REFUND", "NONE"]
        },
        "refund_destination": {
            "type": "STRING",
            "enum": ["WALLET", "PROMO", "ORIGINAL", "NONE"]
        },
        "new_size": {"type": "STRING", "nullable": True},
        "language": {"type": "STRING"},
        "register": {
            "type": "STRING",
            "enum": ["formal", "casual"]
        },
        "needs_clarification": {"type": "BOOLEAN"},
        "clarification_question": {"type": "STRING", "nullable": True}
    },
    "required": ["intent", "emotion", "urgency", "language", "needs_clarification"]
}


def node_understand(state: SellerShieldAgentState) -> Dict[str, Any]:
    """Node 1: LLM structured output. Understands typos, slang, sentiment, and resolves references."""
    db: Session = SessionLocal()
    try:
        user_msg = state.get("user_message", "")
        pending_q = state.get("pending_question")

        # Instruction for understanding
        instruction = (
            f"Analyze user input in the context of ongoing support.\n"
            f"Pending question: {pending_q or 'None'}\n"
            f"Active order ID in state: {state.get('order_id') or 'None'}\n"
            f"Customer language could be English, Hinglish, or Tamil. Extract intent, sentiment, urgency, "
            f"order reference (e.g. 'the shoes', 'it', 'ORD-1001'), reason category, requested resolution, or refund destination."
        )
        system_prompt = get_composed_system_prompt(
            db=db,
            node_instruction=instruction,
            summary=state.get("summary"),
            customer_memory=state.get("customer_memory")
        )

        history_contents = []
        for m in (state.get("messages") or [])[-6:]:
            role = "user" if getattr(m, "type", "human") in ("human", "user") or (isinstance(m, dict) and m.get("role") in ("user", "human")) else "model"
            text = getattr(m, "content", "") if hasattr(m, "content") else (m.get("text") or m.get("content") or "")
            if text:
                history_contents.append({"role": role, "parts": [{"text": text}]})
        history_contents.append({"role": "user", "parts": [{"text": user_msg}]})

        pred_text = call_gemini(
            system_prompt=system_prompt,
            contents=history_contents,
            schema=UNDERSTAND_SCHEMA,
            temperature=0.2,
            max_tokens=500
        )
        pred: Dict[str, Any] = {}
        if pred_text:
            try:
                pred = json.loads(pred_text)
            except Exception:
                pass

        # Resolve intent (1I & 1J: trust LLM intent first, word-boundary regexes for fallback)
        lower = user_msg.lower()
        raw_intent = (pred.get("intent") or "").upper()
        VALID_INTENTS = {"TRACKING", "RETURN_REFUND_EXCHANGE", "CANCEL", "EXPEDITE", "GENERAL"}

        is_refuse_delivery = any(k in lower for k in (
            "refuse delivery", "how do i refuse", "how to refuse", "decline delivery",
            "refuse parcel", "refuse or cancel delivery", "refuse package",
            "refuse the delivery", "refuse order", "cancel delivery"
        ))
        clean_thanks = lower.strip("!., ")
        is_thanks = any(t == clean_thanks or clean_thanks.startswith(t + " ") or clean_thanks.endswith(" " + t) for t in [
            "thanks", "thank you", "thx", "tq", "thank u", "many thanks", "thanks a lot",
            "thank you so much", "dhanyawad", "shukriya", "nandri"
        ])

        if pending_q == "ORDER_SELECTION":
            intent = state.get("intent") or "GENERAL"
        elif pending_q in ("ASK_REASON", "COLLECT_EVIDENCE", "RETENTION_CHOICE", "REPLACEMENT_DETAILS", "REFUND_DESTINATION"):
            intent = "RETURN_REFUND_EXCHANGE"
        elif pending_q in ("CANCEL_REASON", "CANCEL_CONFIRM", "EXPEDITE_CONFIRM", "CANCEL_REFUND_DEST"):
            intent = "CANCEL"
        elif is_refuse_delivery:
            intent = "GENERAL"
        elif is_thanks:
            intent = "GENERAL"
        elif raw_intent in VALID_INTENTS:
            intent = raw_intent
        else:
            # Fallback keyword rules using word-boundary regexes only (including common typos)
            if re.search(r'\b(?:return|refund|exchange|swap|replace|replacement|replacing|wapas|badal|money back|don\'?t want|size|fit|defective|damaged|broken)\b', lower):
                intent = "RETURN_REFUND_EXCHANGE"
            elif re.search(r'\b(?:expedite|faster|fast|urgent|hurry|speed up|jaldi|seekram)\b', lower):
                intent = "EXPEDITE"
            elif re.search(r'\b(?:where|wher|whr|track|trak|status|delivery|deliver|when|reach|kaha|enga|iruku|ordr)\b', lower):
                intent = "TRACKING"
            elif re.search(r'\b(?:cancel|cancelling|cancellation)\b', lower):
                intent = "CANCEL"
            else:
                # No keyword match and LLM failed — only keep previous intent if
                # we are in the middle of a multi-turn flow (pending_question set)
                if pending_q:
                    intent = state.get("intent") or "GENERAL"
                else:
                    intent = "GENERAL"

        # Emotion & sentiment
        raw_emotion = pred.get("emotion")
        if is_thanks:
            emotion = "happy"
        elif raw_emotion in ("calm", "confused", "frustrated", "angry", "worried", "happy"):
            emotion = raw_emotion
        else:
            if any(w in lower for w in ["angry", "ridiculous", "cheat", "scam", "furious", "worst", "terrible"]):
                emotion = "angry"
            elif any(w in lower for w in ["frustrated", "annoying", "upset"]):
                emotion = "frustrated"
            elif any(w in lower for w in ["worried", "urgent", "fast", "jaldi", "seekram"]):
                emotion = "worried"
            elif any(w in lower for w in ["what", "kya", "puriyala", "confused"]):
                emotion = "confused"
            elif any(w in lower for w in ["thanks", "thank you", "great", "happy"]):
                emotion = "happy"
            else:
                emotion = "calm"

        sentiment = emotion.upper() if emotion in ("calm", "frustrated", "confused", "happy") else ("FRUSTRATED" if emotion in ("angry", "worried") else "CALM")
        urgency = pred.get("urgency") or ("HIGH" if emotion in ("angry", "worried", "frustrated") or "urgent" in lower else "MEDIUM")

        # Language detection
        raw_lang = pred.get("language")
        if raw_lang:
            language = raw_lang
        else:
            if any(w in lower for w in ["enga", "iruku", "eppo", "seekram", "venum", "illai", "kedaikuma"]):
                language = "Tamil"
            elif any(w in lower for w in ["kaha", "kab", "jaldi", "wapas", "chahiye", "nahi", "mera", "hai", "batao"]):
                language = "Hinglish"
            else:
                language = "English"

        register = pred.get("register") or ("casual" if any(w in lower for w in ["hey", "hi", "bro", "wher", "ordr", "yaar"]) else "formal")

        # Side question & current question detection
        current_question = pred.get("current_question")
        if not current_question and any(w in lower for w in ["how long", "kitna time", "how much time", "when will", "can i cancel", "what is the return"]):
            current_question = user_msg

        # Correction detection
        correction = pred.get("correction")
        if not correction and any(w in lower for w in ["other order", "meant the other", "not order", "dusra order", "vera order"]):
            correction = user_msg

        # Offer response
        offer_resp = pred.get("offer_response")
        if not offer_resp or offer_resp == "NONE":
            if any(w in lower for w in ["yes", "swap", "replacement", "replace", "ok", "sure", "sari", "haan"]):
                offer_resp = "ACCEPTED"
            elif any(w in lower for w in ["no", "refund", "nahi", "vendam", "don't want"]):
                offer_resp = "DECLINED"
            else:
                offer_resp = "NONE"

        updates: Dict[str, Any] = {
            "intent": intent,
            "sub_intent": pred.get("sub_intent") or ("CHECK_STATUS" if intent == "TRACKING" else "OTHER"),
            "emotion": emotion,
            "sentiment": sentiment,
            "urgency": urgency,
            "language": language,
            "register": register,
            "current_question": current_question,
            "correction": correction,
            "referenced_order": pred.get("referenced_order"),
            "offer_response": offer_resp,
            "needs_clarification": pred.get("needs_clarification", False),
            "clarification_question": pred.get("clarification_question"),
            "step": "understand"
        }

        # Resolve reason category:
        # Strictly enforce Step 2: only set reason_category if responding to ASK_REASON or explicit selection
        rc = pred.get("reason_category")
        is_side_question = bool(
            current_question or
            pred.get("sub_intent") in ("SIDE_QUESTION", "ASK_TIMELINE", "ASK_POLICY") or
            any(q_word in lower for q_word in ["how long", "kitna time", "how much time", "when will", "can i cancel", "what is the return", "why do you need", "timeline", "how does", "what about", "is it possible"]) or
            ("?" in user_msg and not any(cat.lower() in lower for cat in ["defective", "damaged", "broken", "wrong item", "size", "fit", "not as described", "changed my mind"]))
        )

        if pending_q == "ASK_REASON":
            if rc and rc != "NONE":
                updates["reason_category"] = rc
                updates["reason_text"] = pred.get("reason_text") or user_msg
            elif not is_side_question:
                for cat in ["Defective or not working", "Damaged on arrival", "Wrong item", "Size / fit issue", "Not as described", "Changed my mind", "Something else"]:
                    if cat.lower() in lower or any(word in lower for word in cat.lower().split() if len(word) > 3):
                        updates["reason_category"] = cat
                        updates["reason_text"] = user_msg
                        break
                if not updates.get("reason_category"):
                    updates["reason_category"] = "Something else"
                    updates["reason_text"] = user_msg
            else:
                # Mid-flow side question asked: preserve pending_question, do NOT assume a reason yet
                updates["reason_category"] = None
                updates["reason_text"] = None
        elif any(cat.lower() in lower for cat in ["defective", "damaged", "broken", "wrong item", "size / fit", "not as described"]):
            # Explicit category mentioned in prompt
            for cat in ["Defective or not working", "Damaged on arrival", "Wrong item", "Size / fit issue", "Not as described", "Changed my mind", "Something else"]:
                if cat.lower() in lower:
                    updates["reason_category"] = cat
                    updates["reason_text"] = user_msg
                    break
        elif state.get("reason_category"):
            # Preserve existing reason category from previous turn in this conversation
            updates["reason_category"] = state.get("reason_category")
            updates["reason_text"] = state.get("reason_text")
        else:
            updates["reason_category"] = None
            updates["verdict"] = None

        # Resolve resolution choice
        res_type = pred.get("resolution_type")
        if any(w in lower for w in ["replace", "replacement", "replacing", "swap", "exchange"]):
            updates["resolution_type"] = "REPLACEMENT"
        elif any(w in lower for w in ["refund", "money back", "return for refund", "cash back"]):
            updates["resolution_type"] = "REFUND"
        elif pending_q == "RETENTION_CHOICE":
            if any(w in lower for w in ["refund", "money", "cash", "account", "wapas"]):
                updates["resolution_type"] = "REFUND"
            elif any(w in lower for w in ["replace", "swap", "exchange"]):
                updates["resolution_type"] = "REPLACEMENT"
        elif res_type and res_type != "NONE":
            updates["resolution_type"] = res_type
        elif state.get("resolution_type"):
            updates["resolution_type"] = state.get("resolution_type")

        # Resolve refund destination
        dest = pred.get("refund_destination")
        if pending_q == "REFUND_DESTINATION":
            if "wallet" in lower:
                updates["refund_destination"] = "WALLET"
            elif "promo" in lower or "code" in lower or "bonus" in lower or "voucher" in lower:
                updates["refund_destination"] = "PROMO"
            elif "original" in lower or "bank" in lower or "upi" in lower or "account" in lower:
                updates["refund_destination"] = "ORIGINAL"
        elif dest and dest != "NONE":
            updates["refund_destination"] = dest
        elif state.get("refund_destination"):
            updates["refund_destination"] = state.get("refund_destination")

        # Resolve replacement choice details
        if pred.get("new_size") or (pending_q == "REPLACEMENT_DETAILS"):
            size_val = pred.get("new_size")
            if not size_val:
                for sz in ["8", "8.5", "9", "9.5", "10", "10.5", "11", "S", "M", "L", "XL"]:
                    if sz.lower() in lower:
                        size_val = f"{sz} UK" if not sz.isalpha() else sz
                        break
            if size_val:
                updates["replacement_choice"] = {
                    "same_product": True,
                    "size": size_val,
                    "size_reason": user_msg
                }

        # Detect color change/swap intent
        is_color_change = any(w in lower for w in [
            "colour", "color", "different colour", "different color",
            "new colour", "new color", "another color", "another colour",
            "change colour", "change color", "swap colour", "swap color",
            "replace colour", "replace color", "plan to get for a new colour",
            "plan to get a new color", "plan to get for a new color",
            "plan to get a new colour"
        ])

        # Detect wallet query (only when not answering refund destination!)
        is_wallet_msg = pending_q not in ("CANCEL_REFUND_DEST", "ASK_DESTINATION") and any(k in lower for k in (
            "check my wallet", "check wallet", "my wallet", "wallet balance",
            "view wallet", "wallet money", "wallet credit", "wallet activity", "wallet history",
            "wallet transaction", "wallet transactions", "spend in wallet", "spent in wallet",
            "how much in my wallet", "what is my wallet balance", "check balance",
            "balance in my wallet", "balance in wallet"
        ))
        if is_wallet_msg:
            user = db.query(User).filter(User.id == state["customer_id"]).first()
            first_name = user.full_name.split()[0] if user else "there"
            balance = user.wallet_balance if user and user.wallet_balance else 0.0
            
            txs = db.query(WalletTransaction).filter(
                WalletTransaction.customer_id == state["customer_id"]
            ).order_by(WalletTransaction.created_at.desc()).limit(4).all()

            if txs:
                tx_lines = []
                for t in txs:
                    sign = "+" if t.transaction_type == "CREDIT" else "-"
                    tx_lines.append(f"• {sign} ₹{t.amount:,.0f} — {t.description}")
                hist_str = "\n\nRecent activity:\n" + "\n".join(tx_lines)
            else:
                hist_str = "\n\nYour store credit is ready to use on your next order at checkout."

            updates["reply"] = (
                f"Your current SellerShield Wallet balance is ₹{balance:,.0f}, {first_name}! 💳"
                f"{hist_str}\n\nYou can click your Wallet in the navbar anytime to open the full activity ledger."
            )
            updates["quick_replies"] = ["View wallet activity", "Browse store", "Check my orders", "Thanks!"]
            updates["intent"] = "GENERAL"
            updates["pending_question"] = None
            updates["step"] = "check_wallet"
            updates["case_closed"] = True

        # ====================================================================
        # GADGET CUSTOMER SERVICE & TECHNICAL CALLBACK FLOW
        # ====================================================================
        elif pending_q == "GADGET_CALL_OFFER":
            user = db.query(User).filter(User.id == state["customer_id"]).first()
            phone = user.phone if user and user.phone else "+91 98450 12891"
            order_id = state.get("order_id") or state.get("active_order_id")
            target_order = db.query(Order).filter(Order.id == order_id).first() if order_id else None
            if not target_order:
                all_cust_orders = db.query(Order).filter(Order.customer_id == state["customer_id"]).order_by(Order.created_at.desc()).all()
                for o in all_cust_orders:
                    if o.items and is_electronic_gadget_product(o.items[0].product_title):
                        target_order = o
                        break

            p_name = target_order.items[0].product_title if target_order and target_order.items else "Electronic Gadget"
            clean_p = p_name.split("(")[0].strip() if "(" in p_name else p_name

            wants_direct_call = any(w in lower for w in ["call 1800", "1800", "helpline", "i will call", "call them", "2"])
            wants_skip = any(w in lower for w in ["return/swap", "proceed", "no call", "skip", "just return", "just replace", "swap", "refund"])

            if wants_direct_call:
                updates["reply"] = (
                    f"Our customer service helpline 1800-419-7355 is available toll-free from 9:00 AM to 9:00 PM IST. "
                    f"Please keep your Order Number ({target_order.order_number if target_order else 'ORD-15530'}) ready when speaking to the specialist. "
                    f"Once your call is completed or if you'd like us to call you instead, simply let me know here!"
                )
                updates["quick_replies"] = ["Simulate Call Completed", "Simulate Call Declined", "Schedule a call instead"]
                updates["pending_question"] = "GADGET_CALL_STATUS"
                updates["step"] = "gadget_call_scheduled"
                updates["case_closed"] = False
            elif wants_skip:
                updates["reply"] = (
                    f"No problem! We can proceed directly with your {clean_p}. "
                    f"Would you like a replacement unit, refund to your SellerShield Wallet, or refund to your bank account?"
                )
                updates["quick_replies"] = ["Swap / Replacement", "Refund to Store Wallet", "Refund to Bank Account"]
                updates["pending_question"] = "GADGET_POST_CALL_RESOLUTION"
                updates["step"] = "gadget_post_call_resolution"
                updates["case_closed"] = False
            else:
                # Default: Schedule technical callback
                call = SupportCall(
                    customer_id=state["customer_id"],
                    order_id=target_order.id if target_order else None,
                    order_number=target_order.order_number if target_order else None,
                    product_title=clean_p,
                    customer_phone=phone,
                    status="SCHEDULED",
                    notes=f"Priority technical callback for {clean_p} hardware issue"
                )
                db.add(call)
                db.commit()

                updates["reply"] = (
                    f"I've scheduled a priority technical callback with our gadget customer service team to your registered phone number ({phone})! 📞\n\n"
                    f"A certified hardware specialist will call you shortly to assist with your {clean_p}. "
                    f"Once the call is finished, our system will automatically update to implement the next step (replacement or refund)."
                )
                updates["quick_replies"] = ["Simulate Call Completed", "Simulate Call Declined", "I called 1800-419-7355"]
                updates["pending_question"] = "GADGET_CALL_STATUS"
                updates["step"] = "gadget_call_scheduled"
                updates["case_closed"] = False

        elif pending_q == "GADGET_CALL_STATUS":
            user = db.query(User).filter(User.id == state["customer_id"]).first()
            phone = user.phone if user and user.phone else "+91 98450 12891"
            order_id = state.get("order_id") or state.get("active_order_id")
            target_order = db.query(Order).filter(Order.id == order_id).first() if order_id else None

            call = db.query(SupportCall).filter(
                SupportCall.customer_id == state["customer_id"]
            ).order_by(SupportCall.created_at.desc()).first()

            p_name = call.product_title if call and call.product_title else (target_order.items[0].product_title if target_order and target_order.items else "gadget")
            clean_p = p_name.split("(")[0].strip() if "(" in p_name else p_name

            is_declined = any(w in lower for w in [
                "declined", "didn't pick", "did not pick", "missed", "missed call",
                "simulate call declined", "no answer", "couldn't attend", "busy",
                "unable to attend", "not able to pick", "disconnect"
            ])
            is_completed = any(w in lower for w in [
                "completed", "call is done", "call done", "finished", "finished call",
                "spoke", "talked", "simulate call completed", "called 1800", "i called",
                "done", "finished talking", "attended", "call finished"
            ])

            if is_declined:
                if call:
                    call.status = "DECLINED"
                    db.commit()
                updates["reply"] = (
                    f"It looks like you didn't pick up the call from our customer service team. "
                    f"Can I arrange another call, or would you prefer to proceed directly with a replacement or refund for your {clean_p}?"
                )
                updates["quick_replies"] = [
                    "Arrange another call",
                    "Proceed to replacement",
                    "Refund to store wallet",
                    "Refund to bank account"
                ]
                updates["pending_question"] = "GADGET_DECLINED_FOLLOWUP"
                updates["step"] = "gadget_call_declined"
                updates["case_closed"] = False
            elif is_completed:
                if call:
                    call.status = "COMPLETED"
                    call.completed_at = datetime.datetime.utcnow()
                    db.commit()
                updates["reply"] = (
                    f"Technical verification completed with our customer service team! 🛠️\n\n"
                    f"Our specialist has verified the hardware issue with your {clean_p}. "
                    f"As verified by customer care, we can now implement the next step. Would you like a replacement, refund to your store wallet, or refund to your bank account?"
                )
                updates["quick_replies"] = [
                    "Swap / Replacement",
                    "Refund to Store Wallet",
                    "Refund to Bank Account"
                ]
                updates["pending_question"] = "GADGET_POST_CALL_RESOLUTION"
                updates["step"] = "gadget_call_completed"
                updates["case_closed"] = False
            else:
                updates["reply"] = (
                    f"Our technical specialist is dialing {phone} regarding your {clean_p}. "
                    f"Once your conversation is finished, please let me know whether the call was completed or missed so we can proceed with your resolution."
                )
                updates["quick_replies"] = ["Simulate Call Completed", "Simulate Call Declined", "I called 1800-419-7355"]
                updates["pending_question"] = "GADGET_CALL_STATUS"
                updates["step"] = "gadget_call_scheduled"
                updates["case_closed"] = False

        elif pending_q == "GADGET_DECLINED_FOLLOWUP":
            user = db.query(User).filter(User.id == state["customer_id"]).first()
            phone = user.phone if user and user.phone else "+91 98450 12891"
            order_id = state.get("order_id") or state.get("active_order_id")
            target_order = db.query(Order).filter(Order.id == order_id).first() if order_id else None
            call = db.query(SupportCall).filter(
                SupportCall.customer_id == state["customer_id"]
            ).order_by(SupportCall.created_at.desc()).first()

            p_name = call.product_title if call and call.product_title else (target_order.items[0].product_title if target_order and target_order.items else "gadget")
            clean_p = p_name.split("(")[0].strip() if "(" in p_name else p_name

            wants_rearrange = any(w in lower for w in [
                "arrange another call", "another call", "call again", "retry",
                "reschedule", "yes call", "re-arrange", "rearrange", "1"
            ])
            wants_replace = any(w in lower for w in ["replacement", "replace", "swap", "proceed to replacement"])
            wants_wallet = any(w in lower for w in ["wallet", "store wallet", "refund to store wallet"])
            wants_bank = any(w in lower for w in ["bank", "account", "bank account", "original", "upi"])

            if wants_rearrange:
                if call:
                    call.status = "SCHEDULED"
                    call.notes = "Re-arranged technical callback"
                    db.commit()
                updates["reply"] = (
                    f"I've re-arranged your priority technical callback with our customer service team to {phone}! 📞\n\n"
                    f"A specialist will dial you shortly. Please keep your phone reachable."
                )
                updates["quick_replies"] = ["Simulate Call Completed", "Simulate Call Declined", "I called 1800-419-7355"]
                updates["pending_question"] = "GADGET_CALL_STATUS"
                updates["step"] = "gadget_call_scheduled"
                updates["case_closed"] = False
            elif wants_replace:
                if target_order:
                    target_order.status = "EXCHANGED"
                    target_order.return_reason = "Customer Care Verified: Doorstep replacement"
                if call:
                    call.resolution_action = "REPLACEMENT"
                db.commit()
                updates["reply"] = (
                    f"Done! We have arranged an instant priority doorstep replacement for your {clean_p} (Order {target_order.order_number if target_order else ''})! 📦\n\n"
                    f"A brand-new, thoroughly tested unit will be delivered to your address within 2 business days. "
                    f"Our courier will deliver the replacement and collect the defective unit at the same time."
                )
                updates["quick_replies"] = ["Track replacement", "Browse store", "Thanks!"]
                updates["pending_question"] = None
                updates["step"] = "gadget_replacement_done"
                updates["case_closed"] = True
            elif wants_wallet:
                amt = get_order_refundable_amount(target_order, db)
                if user:
                    user.wallet_balance = (user.wallet_balance or 0.0) + amt
                tx = WalletTransaction(
                    customer_id=state["customer_id"],
                    order_id=target_order.id if target_order else None,
                    order_number=target_order.order_number if target_order else None,
                    amount=amt,
                    transaction_type="CREDIT",
                    description=f"Refund for {clean_p} (Customer Care Verified)",
                    balance_after=user.wallet_balance if user else amt
                )
                db.add(tx)
                if target_order:
                    target_order.status = "REFUNDED"
                    target_order.return_reason = "Customer Care Verified: Wallet refund"
                if call:
                    call.resolution_action = "REFUND_WALLET"
                db.commit()
                updates["reply"] = (
                    f"Done! A full refund of ₹{amt:,.0f} has been instantly credited to your SellerShield Wallet! 💳\n\n"
                    f"Your updated wallet balance is ₹{user.wallet_balance:,.0f}. "
                    f"You can use this store credit on any future purchase at checkout."
                )
                updates["quick_replies"] = ["Check my wallet", "Browse store", "Thanks!"]
                updates["pending_question"] = None
                updates["step"] = "gadget_wallet_refund_done"
                updates["case_closed"] = True
            elif wants_bank:
                amt = get_order_refundable_amount(target_order, db)
                if target_order:
                    target_order.status = "REFUNDED"
                    target_order.return_reason = "Customer Care Verified: Bank refund"
                if call:
                    call.resolution_action = "REFUND_ORIGINAL"
                db.commit()
                pay_m = target_order.payment_method if target_order and target_order.payment_method else "UPI / Bank Account"
                updates["reply"] = (
                    f"Done! A full refund of ₹{amt:,.0f} has been initiated back to your original payment account ({pay_m})! 🏦\n\n"
                    f"Refund Reference ID: ARN-883912. The funds will reflect in your bank account within 3–5 business days."
                )
                updates["quick_replies"] = ["Check my orders", "Browse store", "Thanks!"]
                updates["pending_question"] = None
                updates["step"] = "gadget_original_refund_done"
                updates["case_closed"] = True
            else:
                updates["reply"] = (
                    f"Would you like me to arrange another technical call to {phone}, or proceed directly with a replacement or refund for your {clean_p}?"
                )
                updates["quick_replies"] = [
                    "Arrange another call",
                    "Proceed to replacement",
                    "Refund to store wallet",
                    "Refund to bank account"
                ]
                updates["pending_question"] = "GADGET_DECLINED_FOLLOWUP"
                updates["step"] = "gadget_call_declined"
                updates["case_closed"] = False

        elif pending_q == "GADGET_POST_CALL_RESOLUTION":
            user = db.query(User).filter(User.id == state["customer_id"]).first()
            order_id = state.get("order_id") or state.get("active_order_id")
            target_order = db.query(Order).filter(Order.id == order_id).first() if order_id else None
            call = db.query(SupportCall).filter(
                SupportCall.customer_id == state["customer_id"]
            ).order_by(SupportCall.created_at.desc()).first()

            p_name = call.product_title if call and call.product_title else (target_order.items[0].product_title if target_order and target_order.items else "gadget")
            clean_p = p_name.split("(")[0].strip() if "(" in p_name else p_name
            amt = get_order_refundable_amount(target_order, db)

            wants_replace = any(w in lower for w in ["replacement", "replace", "swap", "exchange", "1"])
            wants_wallet = any(w in lower for w in ["wallet", "store wallet", "refund to store wallet", "2"])
            wants_bank = any(w in lower for w in ["bank", "account", "bank account", "original", "upi", "3"])

            if wants_replace:
                if target_order:
                    target_order.status = "EXCHANGED"
                    target_order.return_reason = "Customer Care Verified: Doorstep replacement"
                if call:
                    call.resolution_action = "REPLACEMENT"
                db.commit()
                updates["reply"] = (
                    f"Done! We have arranged an instant priority doorstep replacement for your {clean_p} (Order {target_order.order_number if target_order else ''})! 📦\n\n"
                    f"A brand-new, thoroughly tested unit will be delivered to your address within 2 business days. "
                    f"Our delivery partner will hand over the replacement and collect the defective unit at the same time."
                )
                updates["quick_replies"] = ["Track replacement", "Browse store", "Thanks!"]
                updates["pending_question"] = None
                updates["step"] = "gadget_replacement_done"
                updates["case_closed"] = True
            elif wants_wallet:
                if user:
                    user.wallet_balance = (user.wallet_balance or 0.0) + amt
                tx = WalletTransaction(
                    customer_id=state["customer_id"],
                    order_id=target_order.id if target_order else None,
                    order_number=target_order.order_number if target_order else None,
                    amount=amt,
                    transaction_type="CREDIT",
                    description=f"Refund for {clean_p} (Customer Care Verified)",
                    balance_after=user.wallet_balance if user else amt
                )
                db.add(tx)
                if target_order:
                    target_order.status = "REFUNDED"
                    target_order.return_reason = "Customer Care Verified: Wallet refund"
                if call:
                    call.resolution_action = "REFUND_WALLET"
                db.commit()
                updates["reply"] = (
                    f"Done! A full refund of ₹{amt:,.0f} has been instantly credited to your SellerShield Wallet! 💳\n\n"
                    f"Your updated wallet balance is ₹{user.wallet_balance:,.0f}. "
                    f"You can use this store credit on any future purchase at checkout, or view your ledger in the Wallet tab anytime."
                )
                updates["quick_replies"] = ["Check my wallet", "Browse store", "Thanks!"]
                updates["pending_question"] = None
                updates["step"] = "gadget_wallet_refund_done"
                updates["case_closed"] = True
            elif wants_bank:
                if target_order:
                    target_order.status = "REFUNDED"
                    target_order.return_reason = "Customer Care Verified: Bank refund"
                if call:
                    call.resolution_action = "REFUND_ORIGINAL"
                db.commit()
                pay_m = target_order.payment_method if target_order and target_order.payment_method else "UPI / Bank Account"
                updates["reply"] = (
                    f"Done! A full refund of ₹{amt:,.0f} has been initiated back to your original payment account ({pay_m})! 🏦\n\n"
                    f"Refund Reference ID: ARN-883912. The funds will reflect in your bank account within 3–5 business days."
                )
                updates["quick_replies"] = ["Check my orders", "Browse store", "Thanks!"]
                updates["pending_question"] = None
                updates["step"] = "gadget_original_refund_done"
                updates["case_closed"] = True
            else:
                updates["reply"] = (
                    f"How would you like to resolve your {clean_p}? We can arrange a brand-new replacement unit, a full refund to your SellerShield Wallet, or a refund to your bank account."
                )
                updates["quick_replies"] = [
                    "Swap / Replacement",
                    "Refund to Store Wallet",
                    "Refund to Bank Account"
                ]
                updates["pending_question"] = "GADGET_POST_CALL_RESOLUTION"
                updates["step"] = "gadget_post_call_resolution"
                updates["case_closed"] = False

        # Resolve cancellation retention flow
        elif pending_q == "CANCEL_REASON":
            if is_color_change:
                order_id = state.get("order_id") or state.get("active_order_id")
                target_order = db.query(Order).filter(Order.id == order_id).first() if order_id else None
                if not target_order:
                    target_order = db.query(Order).filter(
                        Order.customer_id == state["customer_id"],
                        Order.status.in_(["PLACED", "PACKED", "SHIPPED", "OUT_FOR_DELIVERY", "DELIVERED"])
                    ).order_by(Order.created_at.desc()).first()

                prod_title = target_order.items[0].product_title if target_order and target_order.items else "item"
                clean_title = prod_title.split("(")[0].strip() if "(" in prod_title else prod_title
                if clean_title.lower().startswith("your "):
                    clean_title = clean_title[5:].strip()
                if not clean_title:
                    clean_title = "item"
                colors = get_product_colors(clean_title)

                updates["reply"] = (
                    f"No problem at all! Instead of cancelling, I can easily swap or replace your {clean_title} "
                    f"for another colour we have in stock. Which colour would you like to choose?"
                )
                updates["quick_replies"] = [*colors, "Keep current color", "Cancel anyway"]
                updates["pending_question"] = "SWAP_COLOR_SELECTION"
                updates["step"] = "swap_color_offer"
                updates["cancel_reason"] = user_msg
                updates["case_closed"] = False
                if target_order:
                    updates["order_id"] = target_order.id
                    updates["order_number"] = target_order.order_number
            else:
                updates["cancel_reason"] = user_msg
                updates["intent"] = "CANCEL"
                updates["pending_question"] = None
        elif pending_q == "SWAP_COLOR_SELECTION":
            order_id = state.get("order_id") or state.get("active_order_id")
            target_order = db.query(Order).filter(Order.id == order_id).first() if order_id else None
            if not target_order:
                target_order = db.query(Order).filter(
                    Order.customer_id == state["customer_id"]
                ).order_by(Order.created_at.desc()).first()

            prod_title = target_order.items[0].product_title if target_order and target_order.items else "item"
            clean_title = prod_title.split("(")[0].strip() if "(" in prod_title else prod_title
            if clean_title.lower().startswith("your "):
                clean_title = clean_title[5:].strip()
            if not clean_title:
                clean_title = "item"
            colors = get_product_colors(clean_title)

            # Match color selected by user
            chosen_color = None
            for c in colors:
                if c.lower() in lower or any(w in lower for w in c.lower().split() if len(w) > 3):
                    chosen_color = c
                    break

            if chosen_color:
                if target_order:
                    target_order.return_reason = f"Color swapped to {chosen_color} by customer request"
                    if target_order.items:
                        target_order.items[0].product_title = f"{clean_title} ({chosen_color})"
                    db.commit()

                log_audit_event(
                    db=db,
                    actor="AI_AGENT",
                    tool="order.swap_color",
                    input_payload={"order_number": target_order.order_number if target_order else None, "new_color": chosen_color},
                    output_payload={"status": "SWAPPED", "product": clean_title, "color": chosen_color},
                    verdict="AUTO_APPROVE",
                    customer_id=state["customer_id"],
                    order_id=target_order.id if target_order else None
                )

                updates["reply"] = (
                    f"Awesome! I've swapped your {clean_title} to {chosen_color} at no extra cost. "
                    f"Your order remains active and will be shipped smoothly!"
                )
                updates["quick_replies"] = ["Track order", "Browse store", "Thanks!"]
                updates["pending_question"] = None
                updates["step"] = "swap_color_confirmed"
                updates["case_closed"] = True
                updates["cancel_confirmed"] = False
            elif any(w in lower for w in ["keep", "current", "stay", "don't swap", "dont swap", "cancel order: no"]):
                updates["reply"] = f"Awesome! I've kept your order active with the original color. We'll make sure it reaches you smoothly!"
                updates["quick_replies"] = ["Track order", "Browse store", "Thanks!"]
                updates["pending_question"] = None
                updates["step"] = "cancel_retained"
                updates["case_closed"] = True
            elif any(w in lower for w in ["cancel anyway", "cancel", "still cancel", "just cancel", "yes cancel"]):
                updates["cancel_confirmed"] = True
                updates["intent"] = "CANCEL"
                updates["pending_question"] = None
            else:
                updates["reply"] = f"Which colour would you like to swap your {clean_title} to? We currently have: {', '.join(colors)}."
                updates["quick_replies"] = [*colors, "Keep current color", "Cancel anyway"]
                updates["pending_question"] = "SWAP_COLOR_SELECTION"
                updates["step"] = "swap_color_offer"
        elif pending_q == "CANCEL_CONFIRM":
            has_cancel_neg = any(neg in lower for neg in ["don't cancel", "dont cancel", "no cancel", "not cancel", "never cancel", "do not cancel"])
            wants_cancel = (
                any(w in lower for w in [
                    "cancel anyway", "still cancel", "just cancel", "want to cancel",
                    "changed my mind", "change my mind", "please cancel", "cancel it",
                    "yes cancel", "confirm cancel", "proceed to cancel", "cancel please"
                ])
                or ("cancel" in lower and not has_cancel_neg)
                or lower.strip() in ["cancel", "cancel it please", "3"]
            )
            is_expedite = any(w in lower for w in ["deliver fast", "fast", "faster", "expedite", "speed up", "tomorrow", "quick"])
            is_color_change_confirm = is_color_change or any(w in lower for w in ["swap colour", "swap color", "new colour", "new color", "change colour", "change color"])

            if wants_cancel:
                # Customer explicitly insists on cancelling
                order_id = state.get("order_id") or state.get("active_order_id")
                target_order = db.query(Order).filter(Order.id == order_id).first() if order_id else None
                if not target_order:
                    target_order = db.query(Order).filter(
                        Order.customer_id == state["customer_id"],
                        Order.status.in_(["PLACED", "PACKED"])
                    ).order_by(Order.created_at.desc()).first()
                order_num = target_order.order_number if target_order else state.get("order_number", "your order")

                updates["cancel_confirmed"] = True
                updates["intent"] = "CANCEL"
                updates["pending_question"] = "CANCEL_REFUND_DEST"
                updates["reply"] = (
                    f"I understand you'd like to cancel {order_num}. "
                    f"Where would you like your refund credited?"
                )
                updates["quick_replies"] = [
                    "Refund to store wallet",
                    "Promo code (+10% bonus)",
                    "Back to original account"
                ]
                updates["step"] = "cancel_refund_dest"
                updates["case_closed"] = False
            elif is_expedite:
                # Customer asks if order can be delivered faster!
                user = db.query(User).filter(User.id == state["customer_id"]).first()
                first_name = user.full_name.split()[0] if user else "there"
                updates["reply"] = (
                    f"Yes {first_name}, there is an option! By paying a fast delivery fee of ₹90, you can get your order delivered by tomorrow. Would you like to upgrade to express delivery?"
                )
                updates["quick_replies"] = ["Upgrade to Express (₹90)", "Keep standard delivery", "Cancel anyway"]
                updates["pending_question"] = "EXPEDITE_CONFIRM"
                updates["step"] = "expedite_offer"
                updates["case_closed"] = False
            elif is_color_change_confirm:
                order_id = state.get("order_id") or state.get("active_order_id")
                target_order = db.query(Order).filter(Order.id == order_id).first() if order_id else None
                prod_title = target_order.items[0].product_title if target_order and target_order.items else "your item"
                clean_title = prod_title.split("(")[0].strip() if "(" in prod_title else prod_title
                colors = get_product_colors(clean_title)
                updates["reply"] = (
                    f"No problem at all! Instead of cancelling, I can easily swap or replace your {clean_title} "
                    f"for another colour we have in stock. Which colour would you like to choose?"
                )
                updates["quick_replies"] = [*colors, "Keep current color", "Cancel anyway"]
                updates["pending_question"] = "SWAP_COLOR_SELECTION"
                updates["step"] = "swap_color_offer"
                updates["case_closed"] = False
            elif any(w in lower for w in ["keep", "wait", "don't cancel", "dont cancel", "nevermind", "never mind", "no cancel", "cancel order: no"]):
                # Customer convinced! Retained the sale!
                updates["cancel_reason"] = None
                updates["cancel_confirmed"] = False
                updates["pending_question"] = None
                updates["reply"] = "Awesome! I've kept your order active and confirmed with our fulfillment team. We'll make sure it reaches you smoothly!"
                updates["quick_replies"] = ["Track order", "Browse store", "Thanks!"]
                updates["step"] = "cancel_retained"
                updates["case_closed"] = True
            elif any(w in lower for w in ["swap", "exchange", "replace", "size"]):
                # Customer wants to swap instead of cancelling!
                updates["intent"] = "RETURN_REFUND_EXCHANGE"
                updates["resolution_type"] = "REPLACEMENT"
                updates["pending_question"] = "REPLACEMENT_DETAILS"
                updates["reply"] = "Gladly! Which size or item would you prefer to swap to? I'll arrange it right away."
                updates["quick_replies"] = ["Size 8 UK", "Size 9 UK", "Size 10 UK"]
                updates["step"] = "replacement_flow"
            else:
                # Ambiguous message during cancel confirm — clarify rather than cancelling!
                user = db.query(User).filter(User.id == state["customer_id"]).first()
                first_name = user.full_name.split()[0] if user else "there"
                updates["reply"] = (
                    f"Just to check {first_name}, there is an option to get your order delivered by tomorrow with Express Delivery for ₹90. Would you like to upgrade to express delivery, keep standard delivery, or still cancel?"
                )
                updates["quick_replies"] = ["Upgrade to Express (₹90)", "Keep standard delivery", "Cancel anyway"]
                updates["pending_question"] = "EXPEDITE_CONFIRM"
                updates["step"] = "expedite_offer"

        elif pending_q == "EXPEDITE_CONFIRM":
            user = db.query(User).filter(User.id == state["customer_id"]).first()
            first_name = user.full_name.split()[0] if user else "there"
            order_id = state.get("order_id") or state.get("active_order_id")
            order = db.query(Order).filter(Order.id == order_id).first() if order_id else None

            has_cancel_neg = any(neg in lower for neg in ["don't cancel", "dont cancel", "no cancel", "not cancel", "never cancel", "do not cancel"])
            wants_cancel = (
                any(w in lower for w in [
                    "cancel anyway", "still cancel", "just cancel", "want to cancel",
                    "changed my mind", "change my mind", "please cancel", "cancel it",
                    "yes cancel", "confirm cancel", "proceed to cancel", "cancel please"
                ])
                or ("cancel" in lower and not has_cancel_neg)
                or lower.strip() in ["cancel", "cancel it please", "3"]
            )
            wants_upgrade = (
                any(w in lower for w in ["upgrade", "express", "90", "fast delivery", "deliver fast", "tomorrow"])
                or (any(w in lower for w in ["yes", "sure", "ok", "okay"]) and not any(w in lower for w in ["no", "cancel"]))
                or lower.strip() in ["1", "upgrade to express"]
            )
            wants_keep = (
                any(w in lower for w in ["keep standard", "keep the order", "keep order", "keep it", "standard delivery", "stay with standard", "wait for standard"])
                or lower.strip() in ["2", "keep", "standard", "keep standard delivery"]
            )

            if wants_cancel:
                order_id = state.get("order_id") or state.get("active_order_id")
                target_order = db.query(Order).filter(Order.id == order_id).first() if order_id else None
                if not target_order:
                    target_order = db.query(Order).filter(
                        Order.customer_id == state["customer_id"],
                        Order.status.in_(["PLACED", "PACKED"])
                    ).order_by(Order.created_at.desc()).first()
                order_num = target_order.order_number if target_order else state.get("order_number", "your order")

                updates["cancel_confirmed"] = True
                updates["intent"] = "CANCEL"
                updates["pending_question"] = "CANCEL_REFUND_DEST"
                updates["reply"] = (
                    f"I understand you'd like to cancel {order_num}. "
                    f"Where would you like your refund credited?"
                )
                updates["quick_replies"] = [
                    "Refund to store wallet",
                    "Promo code (+10% bonus)",
                    "Back to original account"
                ]
                updates["step"] = "cancel_refund_dest"
                updates["case_closed"] = False
            elif wants_upgrade:
                # Customer accepted express delivery upgrade!
                tomorrow_dt = datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=1)
                tomorrow_str = tomorrow_dt.strftime("%d %b, %I:%M %p")
                if order:
                    order.delivery_fee = (order.delivery_fee or 0.0) + 90.0
                    order.total_amount = order.total_amount + 90.0
                    order.expected_delivery_at = tomorrow_dt
                    db.commit()
                    order_num = order.order_number
                else:
                    order_num = state.get("order_number", "your order")

                updates["reply"] = (
                    f"Done {first_name}! Your order {order_num} has been upgraded to Express Priority Delivery for ₹90. "
                    f"It has been prioritized at our fulfillment hub and will arrive by tomorrow ({tomorrow_str})!"
                )
                updates["quick_replies"] = ["Track live", "Browse store", "Thanks!"]
                updates["tool_calls"] = [
                    *state.get("tool_calls", []),
                    {
                        "tool": "upgrade_express_delivery",
                        "status": "CONFIRMED",
                        "order": order_num,
                        "fee": 90.0,
                        "new_eta": tomorrow_str
                    }
                ]
                updates["pending_question"] = None
                updates["step"] = "expedite_confirmed"
                updates["case_closed"] = True
            elif wants_keep:
                updates["reply"] = (
                    f"No problem {first_name}! Your order remains active with standard delivery. We'll make sure it reaches you smoothly!"
                )
                updates["quick_replies"] = ["Track order", "Browse store", "Thanks!"]
                updates["pending_question"] = None
                updates["step"] = "cancel_retained"
                updates["case_closed"] = True
            else:
                updates["reply"] = (
                    f"Would you like to upgrade to express delivery for ₹90 to get it by tomorrow, keep standard delivery, or still cancel?"
                )
                updates["quick_replies"] = ["Upgrade to Express (₹90)", "Keep standard delivery", "Cancel anyway"]
                updates["pending_question"] = "EXPEDITE_CONFIRM"
                updates["step"] = "expedite_offer"

        elif pending_q == "CANCEL_REFUND_DEST":
            order_id = state.get("order_id") or state.get("active_order_id")
            target_order = db.query(Order).filter(Order.id == order_id).first() if order_id else None
            if not target_order:
                target_order = db.query(Order).filter(
                    Order.customer_id == state["customer_id"],
                    Order.status.in_(["PLACED", "PACKED"])
                ).order_by(Order.created_at.desc()).first()

            user = db.query(User).filter(User.id == state["customer_id"]).first()
            amt = get_order_refundable_amount(target_order, db)
            order_num = target_order.order_number if target_order else state.get("order_number", "your order")

            if "wallet" in lower or "store" in lower or lower.strip() == "1":
                updates["refund_destination"] = "WALLET"
                if user:
                    user.wallet_balance = (user.wallet_balance or 0.0) + amt
                tx = WalletTransaction(
                    customer_id=state["customer_id"],
                    order_id=target_order.id if target_order else None,
                    order_number=target_order.order_number if target_order else None,
                    amount=amt,
                    transaction_type="CREDIT",
                    description=f"Refund for cancelled {order_num}",
                    balance_after=user.wallet_balance if user else amt
                )
                db.add(tx)
                if target_order:
                    target_order.status = "CANCELLED"
                db.commit()
                updates["reply"] = (
                    f"Done! Order {order_num} has been cancelled before dispatch. "
                    f"A full refund of ₹{amt:,.0f} has been instantly credited to your SellerShield Wallet! 💳\n\n"
                    f"Your updated wallet balance is ₹{user.wallet_balance:,.0f}. You can view your balance or spend it at checkout anytime."
                )
                updates["quick_replies"] = ["Check my wallet", "Track my other orders", "Browse store"]
            elif any(w in lower for w in ["promo", "code", "coupon", "bonus", "voucher"]) or lower.strip() == "2":
                updates["refund_destination"] = "PROMO"
                bonus_amt = round(amt * 1.10)
                code_str = f"SHIELD-{uuid.uuid4().hex[:6].upper()}"
                promo = PromoCode(
                    code=code_str,
                    customer_id=state["customer_id"],
                    discount_type="FIXED",
                    discount_value=bonus_amt,
                    min_order_amount=0.0,
                    is_active=True
                )
                db.add(promo)
                if target_order:
                    target_order.status = "CANCELLED"
                db.commit()
                updates["reply"] = (
                    f"Done! Order {order_num} has been cancelled. As requested, here is your promo code with an extra 10% bonus: "
                    f"**{code_str}** (worth ₹{bonus_amt:,.0f})! 🎉\n\nYou can apply this code on your next order at checkout for an instant discount."
                )
                updates["quick_replies"] = ["Browse store", "Track my other orders", "Thanks!"]
            else:
                updates["refund_destination"] = "ORIGINAL"
                if target_order:
                    target_order.status = "CANCELLED"
                db.commit()
                updates["reply"] = (
                    f"Done! Order {order_num} has been cancelled before dispatch. "
                    f"Your refund of ₹{amt:,.0f} has been initiated back to your original payment method ({target_order.payment_method if target_order and target_order.payment_method else 'UPI/Bank'}). "
                    f"It will reflect in your account within 3–5 business days."
                )
                updates["quick_replies"] = ["Track my other orders", "Browse store", "Thanks!"]

            updates["intent"] = "CANCEL"
            updates["cancel_confirmed"] = True
            updates["pending_question"] = None
            updates["step"] = "cancel_done"
            updates["case_closed"] = True

        elif state.get("cancel_reason"):
            updates["cancel_reason"] = state.get("cancel_reason")
            updates["cancel_confirmed"] = state.get("cancel_confirmed")

        # Initial detection of electronic gadget technical issue
        is_gadget_issue_msg = is_electronic_gadget_issue(lower) or any(k in lower for k in (
            "electronic gadget", "electronic gadgets", "gadget issue", "gadget problem",
            "gadget not working", "technical issue with gadget"
        ))
        if is_gadget_issue_msg or (pending_q == "ASK_REASON" and any(k in lower for k in ("defective", "not working", "broken", "issue", "problem", "flicker", "battery", "charge", "bluetooth"))):
            order_id = state.get("order_id") or state.get("active_order_id")
            target_order = db.query(Order).filter(Order.id == order_id).first() if order_id else None

            # If target order is not gadget or not found, search customer's orders
            if not target_order or not (target_order.items and is_electronic_gadget_product(target_order.items[0].product_title)):
                all_cust_orders = db.query(Order).filter(Order.customer_id == state["customer_id"]).order_by(Order.created_at.desc()).all()
                for o in all_cust_orders:
                    if o.items and is_electronic_gadget_product(o.items[0].product_title):
                        target_order = o
                        break

            is_gadget = target_order and target_order.items and is_electronic_gadget_product(target_order.items[0].product_title)
            if is_gadget or any(k in lower for k in ("electronic gadget", "electronic gadgets", "gadget", "smartwatch", "earbuds", "headphones", "keyboard")):
                clean_p = target_order.items[0].product_title.split("(")[0].strip() if target_order and target_order.items else "electronic gadget"
                user = db.query(User).filter(User.id == state["customer_id"]).first()
                phone = user.phone if user and user.phone else "+91 98450 12891"

                updates["reply"] = (
                    f"For electronic gadgets like the {clean_p}, our certified customer service and technical support team is here to assist you! 🎧\n\n"
                    f"You can call our dedicated customer care helpline directly at 1800-419-7355 (Toll-Free, 9 AM – 9 PM), "
                    f"or I can schedule a priority technical callback to your registered phone ({phone}) right now. What would you prefer?"
                )
                updates["quick_replies"] = ["Schedule a call", "Call 1800-419-7355", "Proceed to return/swap"]
                updates["pending_question"] = "GADGET_CALL_OFFER"
                updates["step"] = "gadget_call_offer"
                updates["case_closed"] = False
                if target_order:
                    updates["order_id"] = target_order.id
                    updates["order_number"] = target_order.order_number

        return updates
    finally:
        db.close()


def node_resolve_order(state: SellerShieldAgentState) -> Dict[str, Any]:
    """
    Node 2: Pure Python.
    1K: Check explicitly mentioned order number or product name BEFORE using order in state.
    Defaults to most recent ACTIVE order or delivered within 7 days.
    If several match and customer says 'my order', asks ONE short clarifying question naming products.
    """
    db: Session = SessionLocal()
    try:
        # If already handled by a terminal retention or policy step, route through
        if state.get("step") in (
            "cancel_retained", "cancel_policy", "cancel_refund_dest", "cancel_done",
            "expedite_offer", "expedite_confirmed", "swap_color_offer", "swap_color_confirmed",
            "refuse_delivery_guidance", "thank_you", "check_wallet", "check_orders", "support_specialist",
            "gadget_call_offer", "gadget_call_scheduled", "gadget_call_declined",
            "gadget_call_completed", "gadget_post_call_resolution",
            "gadget_replacement_done", "gadget_wallet_refund_done", "gadget_original_refund_done"
        ) and state.get("reply"):
            return {
                "step": state.get("step"),
                "reply": state.get("reply"),
                "quick_replies": state.get("quick_replies"),
                "pending_question": state.get("pending_question"),
                "case_closed": state.get("case_closed", False),
                "order_id": state.get("order_id"),
                "order_number": state.get("order_number")
            }

        cust_id = state["customer_id"]
        user_msg = state.get("user_message", "").lower()
        orders_data = get_customer_orders(db, cust_id)
        active_orders = orders_data["active_orders"]
        all_orders = orders_data["all_orders"]
        current_ord_id = state.get("order_id") or state.get("active_order_id")
        current_ord = next((o for o in all_orders if o.id == current_ord_id or o.order_number == current_ord_id), None)

        current_pending_q = None if state.get("pending_question") == "ORDER_SELECTION" else state.get("pending_question")

        # 0A. Check if customer is asking how to refuse delivery (teach them the doorstep process!)
        is_refuse_query = any(k in user_msg for k in (
            "refuse delivery", "how do i refuse", "how to refuse", "decline delivery",
            "refuse parcel", "refuse or cancel delivery", "refuse package",
            "refuse the delivery", "refuse order", "cancel delivery"
        ))
        if is_refuse_query:
            user = db.query(User).filter(User.id == cust_id).first()
            first_name = user.full_name.split()[0] if user else "there"
            shipped_orders = [o for o in active_orders if o.status in ("SHIPPED", "OUT_FOR_DELIVERY")]
            target_ord = current_ord or (shipped_orders[0] if shipped_orders else (active_orders[0] if active_orders else (all_orders[0] if all_orders else None)))
            ord_num = target_ord.order_number if target_ord else "your order"
            item_name = (target_ord.items[0].product_title if target_ord and target_ord.items else "")

            reply_text = (
                f"Here is how to refuse delivery for {ord_num}{f' ({item_name})' if item_name else ''}, {first_name}:\n\n"
                "1. When the delivery executive calls or arrives at your doorstep, simply inform them: 'I am refusing this delivery.'\n"
                "2. Do not share any delivery OTP with the driver.\n"
                "3. The courier executive will immediately mark the parcel as 'Customer Refused / Return to Origin (RTO)' in their system.\n"
                "4. Once the package is marked RTO on its return journey, your full refund will automatically be processed back to your payment method!"
            )
            return {
                "order_id": target_ord.id if target_ord else None,
                "order_number": ord_num,
                "reply": reply_text,
                "quick_replies": ["Track my order", "Browse store", "Thanks!"],
                "pending_question": None,
                "step": "refuse_delivery_guidance",
                "case_closed": True
            }

        # 0B. Check if customer sent a thank-you or gratitude message
        clean_user_msg = user_msg.strip("!., ").lower()
        is_thanks_msg = any(t == clean_user_msg or clean_user_msg.startswith(t + " ") or clean_user_msg.endswith(" " + t) for t in [
            "thanks", "thank you", "thx", "tq", "thank u", "many thanks", "thanks a lot",
            "thank you so much", "dhanyawad", "shukriya", "nandri"
        ])
        if is_thanks_msg:
            user = db.query(User).filter(User.id == cust_id).first()
            first_name = user.full_name.split()[0] if user else "there"
            reply_text = f"You're very welcome, {first_name}! 😊 Happy to help. Let me know if you need anything else with your orders!"
            return {
                "reply": reply_text,
                "quick_replies": ["Where is my order?", "Return or swap", "Browse store"],
                "pending_question": None,
                "step": "thank_you",
                "case_closed": True
            }

        # 0C. Check if customer clicked "Check my orders"
        if any(k in user_msg for k in ("check my orders", "check orders", "my orders", "view orders", "list orders")):
            user = db.query(User).filter(User.id == cust_id).first()
            first_name = user.full_name.split()[0] if user else "there"
            if not orders_data["all_orders"]:
                return {
                    "reply": f"You don't have any orders placed yet, {first_name}! You can browse our store anytime.",
                    "quick_replies": ["Browse store"],
                    "pending_question": None,
                    "step": "check_orders",
                    "case_closed": True
                }
            order_lines = []
            qrs = []
            for ord_item in orders_data["all_orders"][:3]:
                p_title = ord_item.items[0].product_title if ord_item.items else ord_item.order_number
                st_title = ord_item.status.replace("_", " ").title()
                order_lines.append(f"• {ord_item.order_number}: {p_title} — {st_title} (₹{ord_item.total_amount:,.0f})")
                qrs.append(f"{p_title}")
            qrs.append("Browse store")
            reply_text = f"Here are your recent orders, {first_name}:\n\n" + "\n".join(order_lines) + "\n\nWhich order would you like help with?"
            return {
                "reply": reply_text,
                "quick_replies": qrs[:4],
                "pending_question": "ORDER_SELECTION",
                "step": "resolve_order"
            }

        # 0D. Check if customer clicked "Connect to support specialist"
        if any(k in user_msg for k in ("connect to support specialist", "support specialist", "speak to human", "talk to agent", "representative", "specialist")):
            user = db.query(User).filter(User.id == cust_id).first()
            first_name = user.full_name.split()[0] if user else "there"
            esc_case = f"CASE-{int(time.time()) % 100000}"
            reply_text = f"I've flagged your conversation for immediate priority support under Reference: {esc_case}, {first_name}. A senior specialist is reviewing your case and will assist you right away!"
            return {
                "reply": reply_text,
                "quick_replies": ["Track my order", "Browse store", "Thanks!"],
                "pending_question": None,
                "step": "support_specialist",
                "case_closed": True
            }

        # 0E. Check if customer clicked "Check my wallet" or asked about wallet balance / spend
        is_wallet_query = current_pending_q not in ("CANCEL_REFUND_DEST", "ASK_DESTINATION") and any(k in user_msg for k in (
            "check my wallet", "check wallet", "my wallet", "wallet balance",
            "view wallet", "wallet money", "wallet credit", "wallet activity", "wallet history",
            "wallet transaction", "wallet transactions", "spend in wallet", "spent in wallet",
            "how much in my wallet", "what is my wallet balance", "check balance",
            "balance in my wallet", "balance in wallet"
        ))
        if is_wallet_query:
            user = db.query(User).filter(User.id == cust_id).first()
            first_name = user.full_name.split()[0] if user else "there"
            balance = user.wallet_balance if user and user.wallet_balance else 0.0

            txs = db.query(WalletTransaction).filter(
                WalletTransaction.customer_id == cust_id
            ).order_by(WalletTransaction.created_at.desc()).limit(4).all()

            if txs:
                tx_lines = []
                for t in txs:
                    sign = "+" if t.transaction_type == "CREDIT" else "-"
                    tx_lines.append(f"• {sign} ₹{t.amount:,.0f} — {t.description}")
                hist_str = "\n\nRecent activity:\n" + "\n".join(tx_lines)
            else:
                hist_str = "\n\nYour store credit is ready to use on your next order at checkout."

            reply_text = (
                f"Your current SellerShield Wallet balance is ₹{balance:,.0f}, {first_name}! 💳"
                f"{hist_str}\n\nYou can click your Wallet in the navbar anytime to open the full activity ledger."
            )
            return {
                "reply": reply_text,
                "quick_replies": ["View wallet activity", "Browse store", "Check my orders", "Thanks!"],
                "pending_question": None,
                "step": "check_wallet",
                "case_closed": True
            }

        # Helper to respond with full context when an order is resolved/selected
        def respond_for_target(target: Order) -> Dict[str, Any]:
            p_name = target.items[0].product_title if target.items else target.order_number
            target_intent = state.get("intent", "GENERAL")
            user = db.query(User).filter(User.id == cust_id).first()
            first_name = user.full_name.split()[0] if user else "there"

            if target_intent == "CANCEL":
                if target.status in ("PLACED", "PACKED"):
                    return {
                        "order_id": target.id,
                        "order_number": target.order_number,
                        "reply": f"Before I cancel the {p_name} ({target.order_number}), could you tell me what changed your mind? I might be able to help.",
                        "quick_replies": [
                            "Found it cheaper elsewhere",
                            "Don't need it anymore",
                            "Ordered wrong size/item",
                            "Taking too long",
                            "Just cancel it"
                        ],
                        "pending_question": "CANCEL_REASON",
                        "step": "cancel_order"
                    }
                elif target.status in ("SHIPPED", "OUT_FOR_DELIVERY"):
                    return {
                        "order_id": target.id,
                        "order_number": target.order_number,
                        "reply": f"Order {target.order_number} ({p_name}) has already been shipped and is on the way! While it cannot be cancelled pre-dispatch, you can simply refuse delivery at your doorstep for a full refund.",
                        "quick_replies": ["How do I refuse delivery?", "Track my order", "Thanks!"],
                        "pending_question": None,
                        "step": "cancel_order",
                        "case_closed": True
                    }
                else:
                    return {
                        "order_id": target.id,
                        "order_number": target.order_number,
                        "reply": f"Order {target.order_number} ({p_name}) has already been delivered. It can't be cancelled, but eligible items can be returned or exchanged within 7 days of delivery!",
                        "quick_replies": ["Return or swap", "Browse store", "Thanks!"],
                        "pending_question": None,
                        "step": "cancel_order",
                        "case_closed": True
                    }

            elif target_intent in ("TRACKING", "EXPEDITE"):
                info = track_order(db, target.id, user)
                stage = info["current_stage"]
                stage_name = stage.replace("_", " ").lower()
                if stage == "DELIVERED":
                    reply_msg = f"Hey {first_name}, order {info['order_number']} ({p_name}) was delivered to your address on {info['last_update_time']}. Your 7-day return and exchange window is active!"
                    qrs = ["Return or swap", "Thanks!"]
                elif stage == "OUT_FOR_DELIVERY":
                    reply_msg = f"Great news {first_name}! Order {info['order_number']} ({p_name}) is currently out for delivery from {info['last_location']}. It should reach you by {info['expected_delivery']}."
                    qrs = ["How do I refuse delivery?", "Thanks!"]
                elif stage == "SHIPPED":
                    reply_msg = f"Order {info['order_number']} ({p_name}) is currently shipped at {info['last_location']} (updated {info['last_update_time']}). Expected delivery is {info['expected_delivery']}."
                    qrs = ["How do I refuse delivery?", "Thanks!"]
                else:
                    reply_msg = f"Order {info['order_number']} ({p_name}) is currently {stage_name} at {info['last_location']} (updated {info['last_update_time']}). Expected delivery is {info['expected_delivery']}."
                    qrs = ["Cancel order", "Thanks!"]
                return {
                    "order_id": target.id,
                    "order_number": target.order_number,
                    "pending_question": None,
                    "reply": reply_msg,
                    "quick_replies": qrs,
                    "step": "track",
                    "case_closed": True
                }

            elif target_intent == "RETURN_REFUND_EXCHANGE":
                return {
                    "order_id": target.id,
                    "order_number": target.order_number,
                    "reply": f"I'm here to help with {p_name} ({target.order_number})! Could you let me know what went wrong?",
                    "quick_replies": [
                        "Defective / not working",
                        "Damaged on arrival",
                        "Wrong item",
                        "Size / fit issue",
                        "Not as described",
                        "Changed my mind"
                    ],
                    "pending_question": "ASK_REASON",
                    "step": "ask_reason"
                }

            else:
                info = track_order(db, target.id, user)
                stage = info["current_stage"]
                stage_name = stage.replace("_", " ").lower()
                if stage in ("PLACED", "PACKED"):
                    qrs = ["Cancel order", "Where is my order?", "Thanks!"]
                elif stage in ("SHIPPED", "OUT_FOR_DELIVERY"):
                    qrs = ["Track package", "How do I refuse delivery?", "Thanks!"]
                elif stage == "DELIVERED":
                    qrs = ["Return or swap", "Browse store", "Thanks!"]
                else:
                    qrs = ["Track package", "Browse store", "Thanks!"]

                return {
                    "order_id": target.id,
                    "order_number": target.order_number,
                    "pending_question": None,
                    "reply": f"Got it, order {target.order_number} ({p_name}) is currently {stage_name} (ETA: {info['expected_delivery']}). How can I help you with this order?",
                    "quick_replies": qrs,
                    "step": "order_selected"
                }

        # 1. Check if customer stated a correction ("sorry I meant the other order", "the other order", "meant the other"):
        correction_text = (state.get("correction") or user_msg).lower()
        if "other order" in correction_text or "meant the other" in correction_text or "wrong order" in correction_text:
            other_active = [o for o in active_orders if o.id != current_ord_id and o.order_number != current_ord_id]
            if other_active:
                return respond_for_target(other_active[0])
            other_all = [o for o in all_orders if o.id != current_ord_id and o.order_number != current_ord_id]
            if other_all:
                return respond_for_target(other_all[0])

        # 2. Check if user explicitly mentioned order number (e.g. ORD-1001 or UUID)
        for o in all_orders:
            if o.order_number.lower() in user_msg or (len(o.id) > 6 and o.id.lower() in user_msg):
                return respond_for_target(o)

        # 3. Check referenced order from understand (e.g. "the blue shoes", "that one", "same as before")
        ref_order = (state.get("referenced_order") or "").lower()
        if ref_order and ref_order not in ("none", "null"):
            for o in all_orders:
                if o.order_number.lower() in ref_order or (o.items and any(ref_order in it.product_title.lower() for it in o.items)):
                    return respond_for_target(o)

        # 4. Check product mentions:
        # Check if user mentioned product from other orders or current order
        for o in active_orders + all_orders:
            for it in o.items:
                title_words = [w for w in it.product_title.lower().split() if len(w) > 3]
                if any(re.search(rf'\b{re.escape(w)}\b', user_msg) for w in title_words):
                    return respond_for_target(o)

        # 5. Check if user selected from pending ORDER_SELECTION question
        if state.get("pending_question") == "ORDER_SELECTION":
            for o in active_orders:
                first_item = o.items[0].product_title.lower() if o.items else ""
                title_words = [w for w in first_item.split() if len(w) > 3]
                if any(re.search(rf'\b{re.escape(w)}\b', user_msg) for w in title_words) or o.order_number.lower() in user_msg:
                    return respond_for_target(o)

        # 6. Use order already stored in state if valid (work on the same order discussed in this chat!)
        if current_ord:
            intent = state.get("intent", "GENERAL")
            if intent in ("RETURN_REFUND_EXCHANGE", "CANCEL") or any(k in user_msg for k in ("return", "replace", "replacement", "replacing", "swap", "exchange", "refund", "cancel")):
                return respond_for_target(current_ord)
            return {
                "order_id": current_ord.id,
                "order_number": current_ord.order_number,
                "pending_question": current_pending_q,
                "step": "resolve_order"
            }

        # Defaulting rule:
        # If exactly 1 active order exists: auto-select it!
        if len(active_orders) == 1:
            target = active_orders[0]
            return {
                "order_id": target.id,
                "order_number": target.order_number,
                "pending_question": current_pending_q,
                "step": "resolve_order"
            }

        # Special check for CANCEL intent:
        intent = state.get("intent", "GENERAL")
        if intent == "CANCEL":
            cancellable_orders = [o for o in active_orders if o.status in ("PLACED", "PACKED")]
            is_how_to = any(k in user_msg for k in ("how do i cancel", "how to cancel", "can i cancel", "cancellation policy", "how can i cancel"))
            if is_how_to or not cancellable_orders:
                reply_text = (
                    "Orders can be cancelled directly for an immediate full refund before dispatch (while status is Placed or Packed). "
                    "Once an order has shipped or delivered, it cannot be cancelled, but eligible items can be returned or exchanged within 7 days of delivery."
                )
                return {
                    "reply": reply_text,
                    "quick_replies": ["Where is my order?", "Return or swap", "Browse store"],
                    "pending_question": None,
                    "step": "cancel_policy"
                }
            elif len(cancellable_orders) == 1:
                target = cancellable_orders[0]
                return {
                    "order_id": target.id,
                    "order_number": target.order_number,
                    "pending_question": None,
                    "step": "resolve_order"
                }
            elif len(cancellable_orders) > 1:
                prod1 = cancellable_orders[0].items[0].product_title if cancellable_orders[0].items else cancellable_orders[0].order_number
                prod2 = cancellable_orders[1].items[0].product_title if cancellable_orders[1].items else cancellable_orders[1].order_number
                reply_text = f"Which order would you like to cancel — the {prod1} ({cancellable_orders[0].order_number}) or the {prod2} ({cancellable_orders[1].order_number})?"
                quick_replies = [f"{prod1}", f"{prod2}"]
                return {
                    "pending_question": "ORDER_SELECTION",
                    "reply": reply_text,
                    "quick_replies": quick_replies,
                    "step": "resolve_order"
                }

        # If multiple active orders: ask ONE short question naming products ONLY when customer asks about an order/claim
        is_order_intent = intent in ("TRACKING", "RETURN_REFUND_EXCHANGE", "EXPEDITE")
        is_order_word = any(k in user_msg for k in ("order", "package", "delivery", "track", "return", "refund", "exchange", "replace", "item", "shipment", "bought", "purchased", "status", "where is"))

        if len(active_orders) > 1:
            if is_order_intent or is_order_word:
                prod1 = active_orders[0].items[0].product_title if active_orders[0].items else active_orders[0].order_number
                prod2 = active_orders[1].items[0].product_title if active_orders[1].items else active_orders[1].order_number
                reply_text = f"Which order is this regarding — the {prod1} ({active_orders[0].order_number}) or the {prod2} ({active_orders[1].order_number})?"
                quick_replies = [f"{prod1}", f"{prod2}"]
                return {
                    "pending_question": "ORDER_SELECTION",
                    "reply": reply_text,
                    "quick_replies": quick_replies,
                    "step": "resolve_order"
                }
            else:
                # Customer said a general greeting/query like "hello" — set default context without asking
                target = active_orders[0]
                return {
                    "order_id": target.id,
                    "order_number": target.order_number,
                    "pending_question": current_pending_q,
                    "step": "resolve_order"
                }

        # If no active orders, check most recent order
        if all_orders:
            target = all_orders[0]
            return {
                "order_id": target.id,
                "order_number": target.order_number,
                "pending_question": current_pending_q,
                "step": "resolve_order"
            }

        return {"step": "resolve_order"}
    finally:
        db.close()


def node_track(state: SellerShieldAgentState) -> Dict[str, Any]:
    """Node 3: Tool track_order. Answers strictly from tool data (stage, last location, update time, ETA). Never guesses delivered."""
    db: Session = SessionLocal()
    try:
        user = db.query(User).filter(User.id == state["customer_id"]).first()
        order_id = state.get("order_id")
        if not order_id:
            return {
                "reply": "I couldn't find an order to track. Could you share your order number?",
                "quick_replies": ["Check my orders"],
                "step": "track"
            }

        info = track_order(db, order_id, user)
        first_name = user.full_name.split()[0] if user else "there"
        stage_name = info["current_stage"].replace("_", " ").lower()
        stage = info["current_stage"]

        # 1D: Set quick replies strictly by stage
        if stage in ("PLACED", "PACKED"):
            quick_replies = ["Cancel order", "Thanks!"]
        elif stage in ("SHIPPED", "OUT_FOR_DELIVERY"):
            quick_replies = ["How do I refuse delivery?", "Thanks!"]
        elif stage == "DELIVERED":
            quick_replies = ["Return or swap", "Thanks!"]
        else:
            quick_replies = ["Track details", "Thanks!"]

        # 1J: Handle EXPEDITE intent honestly
        if state.get("intent") == "EXPEDITE":
            if stage in ("PLACED", "PACKED"):
                reply_msg = (
                    f"Yes {first_name}, there is an option! By paying a fast delivery fee of ₹90, you can get order {info['order_number']} delivered by tomorrow! "
                    "Would you like to upgrade to express delivery?"
                )
                quick_replies = ["Upgrade to Express (₹90)", "Keep standard delivery", "Cancel order"]
                return {
                    "reply": reply_msg,
                    "quick_replies": quick_replies,
                    "pending_question": "EXPEDITE_CONFIRM",
                    "step": "expedite_offer"
                }
            else:
                reply_msg = (
                    f"I completely understand you need order {info['order_number']} as fast as possible, {first_name}! "
                    f"Your parcel is already with the courier in transit at {info['last_location']} with expected delivery by {info['expected_delivery']}. "
                    "I've flagged it as high priority for the delivery team!"
                )
                quick_replies = ["Track live", "Thanks!"]
                tool_call = {
                    "tool": "expedite_order_inquiry",
                    "status": "URGENT_FLAGGED",
                    "order_number": info["order_number"],
                    "current_stage": info["current_stage"],
                    "last_location": info["last_location"],
                    "expected_delivery": info["expected_delivery"]
                }
        else:
            # Strict compliance: never say delivered unless DELIVERED
            if stage == "DELIVERED":
                reply_msg = f"Hey {first_name}, order {info['order_number']} was delivered to your address on {info['last_update_time']}. Your 7-day return and exchange window is active!"
            elif stage == "OUT_FOR_DELIVERY":
                reply_msg = f"Great news {first_name}! Order {info['order_number']} is currently out for delivery from {info['last_location']}. It should reach you by {info['expected_delivery']}."
            else:
                reply_msg = f"Order {info['order_number']} is currently {stage_name} at {info['last_location']} (updated {info['last_update_time']}). Expected delivery is {info['expected_delivery']}."

            tool_call = {
                "tool": "track_order",
                "status": "SUCCESS",
                "order_number": info["order_number"],
                "current_stage": info["current_stage"],
                "last_location": info["last_location"],
                "expected_delivery": info["expected_delivery"]
            }

        return {
            "reply": reply_msg,
            "quick_replies": quick_replies,
            "tool_calls": [*state.get("tool_calls", []), tool_call],
            "case_closed": True,
            "step": "track"
        }
    finally:
        db.close()


def node_ask_reason(state: SellerShieldAgentState) -> Dict[str, Any]:
    """Node 4: Always ask the reason before offering anything with quick replies. Never skip."""
    reason_cat = state.get("reason_category")
    if not reason_cat or reason_cat == "NONE":
        db: Session = SessionLocal()
        try:
            ord_obj = db.query(Order).filter(Order.id == state.get("order_id")).first() if state.get("order_id") else None
            p_name = f"the {ord_obj.items[0].product_title} ({ord_obj.order_number})" if ord_obj and ord_obj.items else (state.get("order_number") or "your order")
        finally:
            db.close()

        res_type = state.get("resolution_type")
        action_word = "a replacement for" if res_type == "REPLACEMENT" else ("a refund for" if res_type == "REFUND" else "your")
        reply_msg = f"I'd be glad to help arrange {action_word} {p_name}! Could you let me know what went wrong?"
        quick_replies = [
            "Defective / not working",
            "Damaged on arrival",
            "Wrong item",
            "Size / fit issue",
            "Not as described",
            "Changed my mind",
            "Something else"
        ]
        return {
            "pending_question": "ASK_REASON",
            "reply": reply_msg,
            "quick_replies": quick_replies,
            "step": "ask_reason"
        }

    return {"pending_question": None, "step": "ask_reason"}


def node_policy_check(state: SellerShieldAgentState) -> Dict[str, Any]:
    """Node 5: Pure Python deterministic policy engine (no LLM). Checks delivery, window, hygiene, duplicates, refund limit."""
    db: Session = SessionLocal()
    try:
        order_id = state.get("order_id")
        order = db.query(Order).filter(Order.id == order_id).first() if order_id else None
        if not order:
            return {
                "verdict": PolicyVerdict.DENY,
                "reply": "I couldn't locate this order in our system.",
                "step": "policy_check"
            }

        # Node 5 checks eligibility under policy before collecting evidence & offering resolutions
        action = "ELIGIBILITY_CHECK"
        reason = state.get("reason_text") or state.get("reason_category") or "Return claim"

        policy_res = check_policy(
            db=db,
            order=order,
            action=action,
            amount=order.total_amount,
            reason=reason,
            reason_category=state.get("reason_category"),
            evidence_photo=state.get("evidence_photo")
        )

        verdict_str = policy_res["verdict"].value if hasattr(policy_res["verdict"], "value") else str(policy_res["verdict"])
        updates: Dict[str, Any] = {
            "verdict": verdict_str,
            "step": "policy_check"
        }

        if verdict_str == "DENY" or verdict_str == PolicyVerdict.DENY.value:
            updates["reply"] = f"I'm sorry, but {policy_res['reason']}"
            updates["quick_replies"] = ["Check my other orders", "Browse store"]

        return updates
    finally:
        db.close()


def node_collect_evidence(state: SellerShieldAgentState) -> Dict[str, Any]:
    """
    Node 6: Forensic vision inspection & evidence processing (Phase 2).
    - 2A: Validates, strips EXIF, downscales <=1280px, stores under order folder, base64 inlineData.
    - 2B & 2C: Deterministic decision rules via analyze_evidence (VERIFIED, UNCLEAR, MISMATCH, fail closed).
    - 2D: Claim-specific checks (damage/defect, unused with tag/box for size/fit/changed mind).
    - 2E: Fraud awareness via perceptual hashing (dHash) & reuse detection.
    - 2F: Memory of evidence (skips immediately if already VERIFIED).
    """
    # 2F: Memory of evidence - skip immediately if already VERIFIED
    if state.get("evidence_status") == "VERIFIED":
        return {
            "evidence_status": "VERIFIED",
            "pending_question": None,
            "step": "collect_evidence"
        }

    reason_cat = state.get("reason_category") or ""
    raw_photo = state.get("evidence_photo")
    raw_photos = state.get("evidence_photos") or ([raw_photo] if raw_photo else [])

    # If no photo provided yet:
    if not raw_photos:
        # Size/fit or changed mind: no photo required upfront (swapped & verified by courier at doorstep)
        if reason_cat in ("Size / fit issue", "Changed my mind"):
            return {
                "evidence_status": "NONE",
                "pending_question": None,
                "step": "collect_evidence"
            }

        # Defective / Damaged / Wrong item require photo proof
        if reason_cat == "Defective or not working" and any(k in (state.get("reason_text") or "").lower() for k in ("not working", "doesn't work", "stopped", "won't start")):
            reply_msg = "Could you please share a photo or short video showing the error indicator or display?"
            quick_replies = ["Upload photo of error"]
        else:
            reply_msg = "Could you please upload a clear photo showing the issue? You can use the camera/upload button right here."
            quick_replies = ["Upload photo"]

        return {
            "evidence_status": "PENDING",
            "pending_question": "COLLECT_EVIDENCE",
            "reply": reply_msg,
            "quick_replies": quick_replies,
            "step": "collect_evidence"
        }

    db: Session = SessionLocal()
    try:
        order = db.query(Order).filter(Order.id == state.get("order_id")).first()
        prod_title = order.items[0].product_title if order and order.items else "item"

        # 2A: Process & validate images (up to 4)
        processed_images = []
        for p in raw_photos[:4]:
            try:
                proc = validate_and_process_image(p, order_number=order.order_number if order else None)
                processed_images.append(proc)
            except Exception as e:
                print(f"[Image Processing Error]: {e}")

        # If all image processing failed:
        if not processed_images:
            return {
                "evidence_status": "UNCLEAR",
                "pending_question": "COLLECT_EVIDENCE",
                "reply": "We couldn't read the uploaded file format. Please upload a JPEG, PNG, or WebP photo under 5 MB.",
                "quick_replies": ["Upload photo"],
                "step": "collect_evidence"
            }

        # 2E: Fraud awareness via perceptual hashing (dHash)
        fraud_flags: List[str] = list(state.get("fraud_flags") or [])
        for p_img in processed_images:
            flags = check_image_fraud_and_register(
                db=db,
                order_id=order.id if order else None,
                customer_id=state.get("customer_id"),
                phash=p_img["dhash"],
                image_path=p_img["file_url"],
                quality="good",
                status="PENDING"
            )
            for f in flags:
                if f not in fraud_flags:
                    fraud_flags.append(f)

        # 2B, 2C, 2D: Run forensic vision analysis
        vision_res = analyze_evidence(
            order=order,
            claim_type=reason_cat,
            images=processed_images,
            claim_text=state.get("reason_text", ""),
            db=db
        )

        v_status = vision_res.get("status", "UNCLEAR")
        observations = vision_res.get("observations") or ""
        retake_hint = vision_res.get("retake_hint") or "could you please upload another photo in daylight?"
        image_urls = [p["file_url"] for p in processed_images]

        if v_status == "VERIFIED":
            # 2F: Store verified status & facts
            fact_packet = dict(state.get("fact_packet") or {})
            fact_packet["evidence_observations"] = observations
            fact_packet["evidence_damage_type"] = vision_res.get("damage_type")
            fact_packet["evidence_severity"] = vision_res.get("severity")
            fact_packet["evidence_status"] = "VERIFIED"

            if order:
                order.evidence_status = "VERIFIED"
                order.evidence_photos = json.dumps(image_urls)
                order.vision_analysis = json.dumps(vision_res)
                db.commit()

            return {
                "evidence_status": "VERIFIED",
                "pending_question": None,
                "vision_analysis": vision_res,
                "fraud_flags": fraud_flags,
                "evidence_photo": image_urls[0],
                "evidence_photos": image_urls,
                "fact_packet": fact_packet,
                "step": "collect_evidence"
            }

        elif v_status == "MISMATCH":
            retries = state.get("evidence_retries", 0) + 1
            if retries <= 1:
                # Polite check once without accusing customer (2C)
                return {
                    "evidence_status": "MISMATCH",
                    "evidence_retries": retries,
                    "vision_analysis": vision_res,
                    "fraud_flags": fraud_flags,
                    "evidence_photo": image_urls[0],
                    "evidence_photos": image_urls,
                    "pending_question": "COLLECT_EVIDENCE",
                    "reply": retake_hint,
                    "quick_replies": ["Upload another photo", "Talk to support"],
                    "step": "collect_evidence"
                }
            else:
                # Failed retry -> escalate to human review with vision notes
                return {
                    "evidence_status": "MISMATCH",
                    "evidence_retries": retries,
                    "vision_analysis": vision_res,
                    "fraud_flags": fraud_flags,
                    "evidence_photo": image_urls[0],
                    "evidence_photos": image_urls,
                    "verdict": PolicyVerdict.NEEDS_HUMAN,
                    "error": f"Photo condition mismatch: {observations}",
                    "step": "collect_evidence"
                }

        else:  # UNCLEAR
            retries = state.get("evidence_retries", 0) + 1
            if retries <= 1:
                # Ask once more with specific hint (2C)
                return {
                    "evidence_status": "UNCLEAR",
                    "evidence_retries": retries,
                    "vision_analysis": vision_res,
                    "fraud_flags": fraud_flags,
                    "evidence_photo": image_urls[0],
                    "evidence_photos": image_urls,
                    "pending_question": "COLLECT_EVIDENCE",
                    "reply": f"The photo is a bit difficult to see clearly — {retake_hint}",
                    "quick_replies": ["Upload clearer photo"],
                    "step": "collect_evidence"
                }
            else:
                # Retried once and still unclear -> escalate to human review
                return {
                    "evidence_status": "UNCLEAR",
                    "evidence_retries": retries,
                    "vision_analysis": vision_res,
                    "fraud_flags": fraud_flags,
                    "evidence_photo": image_urls[0],
                    "evidence_photos": image_urls,
                    "verdict": PolicyVerdict.NEEDS_HUMAN,
                    "error": f"Photo unclear after retry: {observations}",
                    "step": "collect_evidence"
                }
    finally:
        db.close()


def node_retention(state: SellerShieldAgentState) -> Dict[str, Any]:
    """Node 7: Retention. One gentle attempt to fix / swap, then present Replacement (2 days) vs Refund (4-5 days)."""
    offered = state.get("offered") or []
    declined = state.get("declined") or []
    res_type = state.get("resolution_type")

    # Only advance if we have ALREADY presented the retention choices to the customer in a previous turn
    has_offered_retention = "REPLACEMENT" in offered and state.get("pending_question") != "RETENTION_CHOICE"

    if has_offered_retention:
        if res_type == "REFUND":
            if "REPLACEMENT" not in declined and "REPLACEMENT" in offered:
                declined = list(set([*declined, "REPLACEMENT"]))
            return {
                "resolution_type": "REFUND",
                "declined": declined,
                "pending_question": None,
                "step": "retention"
            }
        if res_type == "REPLACEMENT":
            return {
                "resolution_type": "REPLACEMENT",
                "pending_question": None,
                "step": "retention"
            }

    # First pass: always present Replacement (2 days) vs Refund (4-5 working days)
    new_offered = list(set([*offered, "REPLACEMENT", "REFUND"]))
    reply_msg = (
        "I'd love to make this right for you! I can book a free doorstep replacement delivered in 2 days, "
        "or process a full refund to your account (takes 4–5 working days). Which would you prefer?"
    )
    quick_replies = ["Free Replacement (2 days)", "Refund (4-5 working days)"]

    return {
        "offered": new_offered,
        "pending_question": "RETENTION_CHOICE",
        "reply": reply_msg,
        "quick_replies": quick_replies,
        "step": "retention"
    }


def node_replacement_flow(state: SellerShieldAgentState) -> Dict[str, Any]:
    """Node 8: Same product (ask size + why, check stock, reserve) or different product (2-3 in-stock options). Needs evidence VERIFIED."""
    db: Session = SessionLocal()
    try:
        order = db.query(Order).filter(Order.id == state.get("order_id")).first()
        prod = order.items[0].product if order and order.items else None

        choice = state.get("replacement_choice")
        if not choice or not choice.get("size"):
            # Check available sizes
            sizes = []
            if prod and prod.sizes:
                try:
                    sizes = json.loads(prod.sizes)
                except Exception:
                    pass
            qrs = [f"Size {s}" for s in sizes] if sizes else ["Size 9 UK", "Size 10 UK"]
            return {
                "pending_question": "REPLACEMENT_DETAILS",
                "reply": f"What size would fit better for your {prod.title if prod else 'item'}, and is it tight around the fit or too long?",
                "quick_replies": qrs,
                "step": "replacement_flow"
            }

        return {
            "pending_question": None,
            "step": "replacement_flow"
        }
    finally:
        db.close()


def node_refund_flow(state: SellerShieldAgentState) -> Dict[str, Any]:
    """Node 9: Ask destination (wallet / promo code / original account), explain each in one line."""
    dest = state.get("refund_destination")
    if not dest or dest == "NONE":
        db: Session = SessionLocal()
        try:
            bonus_pct = int(float(get_setting_value(db, "store_credit_bonus_pct", 10.0)))
        finally:
            db.close()

        reply_msg = (
            "Where would you like your refund sent?\n"
            "1. Store wallet: Instant credit to your SellerShield wallet, ready to spend immediately.\n"
            f"2. Promo code: Instant single-use code with an extra {bonus_pct}% bonus value.\n"
            "3. Original payment method: Reaches your bank/UPI account in 4–5 working days."
        )
        quick_replies = [
            "Store wallet (Instant)",
            f"Promo code (+{bonus_pct}% bonus)",
            "Original payment method (4-5 days)"
        ]
        return {
            "pending_question": "REFUND_DESTINATION",
            "reply": reply_msg,
            "quick_replies": quick_replies,
            "step": "refund_flow"
        }

    # If original payment method chosen, check if amount exceeds refund limit
    if dest == "ORIGINAL":
        db = SessionLocal()
        try:
            refund_limit = float(get_setting_value(db, "refund_limit", 2000.0))
            order = db.query(Order).filter(Order.id == state.get("order_id")).first()
            if order and order.total_amount > refund_limit:
                return {
                    "verdict": "NEEDS_HUMAN",
                    "error": f"Refund of ₹{order.total_amount:,.0f} to original payment method exceeds automated ceiling of ₹{refund_limit:,.0f}",
                    "pending_question": None,
                    "step": "refund_flow"
                }
        finally:
            db.close()

    return {
        "pending_question": None,
        "step": "refund_flow"
    }


def node_act(state: SellerShieldAgentState) -> Dict[str, Any]:
    """Node 10: Calls create_exchange / issue_refund / issue_wallet_credit / issue_promo_code. Reachable ONLY from policy AUTO_APPROVE & evidence VERIFIED."""
    db: Session = SessionLocal()
    try:
        order = db.query(Order).filter(Order.id == state.get("order_id")).first()
        if not order:
            return {"error": "Order not found", "step": "act"}

        reason_cat = state.get("reason_category") or "General claim"
        reason_text = state.get("reason_text") or reason_cat
        ev_status = state.get("evidence_status") or "VERIFIED"
        res_type = state.get("resolution_type") or "REFUND"
        tool_calls = state.get("tool_calls", [])

        if res_type == "REPLACEMENT":
            choice = state.get("replacement_choice") or {}
            new_size = choice.get("size") or "Standard"
            res = create_exchange(
                db=db,
                order=order,
                new_size=new_size,
                reason=reason_text,
                reason_category=reason_cat,
                evidence_status=ev_status
            )
            tool_calls.append({"tool": "create_exchange", "order": order.order_number, "status": "CONFIRMED", "new_size": new_size})
            reply_msg = res["message"]
            quick_replies = ["Track my exchange", "Thanks!"]
        else:
            # Refund flow
            dest = state.get("refund_destination") or "ORIGINAL"
            amt = get_order_refundable_amount(order, db)

            if dest == "WALLET":
                res = issue_wallet_credit(
                    db=db,
                    order=order,
                    amount=amt,
                    reason=reason_text,
                    reason_category=reason_cat,
                    evidence_status=ev_status,
                    policy_verdict=state.get("verdict")
                )
                tool_calls.append({"tool": "issue_wallet_credit", "amount": amt, "status": "CREDITED"})
            elif dest == "PROMO":
                res = issue_promo_code(
                    db=db,
                    order=order,
                    amount=amt,
                    reason=reason_text,
                    reason_category=reason_cat,
                    evidence_status=ev_status,
                    policy_verdict=state.get("verdict")
                )
                tool_calls.append({"tool": "issue_promo_code", "amount": amt, "code": res.get("code")})
            else:
                res = issue_refund(
                    db=db,
                    order=order,
                    amount=amt,
                    reason=reason_text,
                    reason_category=reason_cat,
                    evidence_status=ev_status,
                    refund_destination="ORIGINAL",
                    policy_verdict=state.get("verdict")
                )
                tool_calls.append({"tool": "issue_refund", "amount": amt, "status": "DISBURSED"})

            reply_msg = res["message"]
            quick_replies = ["Browse store", "Done, thanks!"]

        return {
            "reply": reply_msg,
            "quick_replies": quick_replies,
            "tool_calls": tool_calls,
            "case_closed": True,
            "step": "act"
        }
    finally:
        db.close()


def node_verify(state: SellerShieldAgentState) -> Dict[str, Any]:
    """Node 11: Re-read the DB record; if the action isn't there, escalate."""
    db: Session = SessionLocal()
    try:
        order = db.query(Order).filter(Order.id == state.get("order_id")).first()
        if not order or order.status not in ("EXCHANGED", "REFUNDED"):
            return {
                "verdict": PolicyVerdict.NEEDS_HUMAN,
                "error": "Database record state verification failed after execution.",
                "step": "verify"
            }
        return {"step": "verify"}
    finally:
        db.close()


def node_escalate(state: SellerShieldAgentState) -> Dict[str, Any]:
    """Node 12: Creates escalation case with summary, then interrupt() until admin decides. Resume with Command(resume=decision)."""
    db: Session = SessionLocal()
    try:
        user = db.query(User).filter(User.id == state["customer_id"]).first()
        order = db.query(Order).filter(Order.id == state.get("order_id")).first() if state.get("order_id") else None

        reason_cat = state.get("reason_category") or "Customer Support Escalation"
        amt = order.total_amount if order else 0.0
        product_title = order.items[0].product_title if order and order.items else "Item"

        # Create structured escalation case with rolling summary if present
        chat_summary = state.get("summary") or state.get("user_message", "")
        esc = escalate_to_human(
            db=db,
            customer=user,
            order=order,
            product_title=product_title,
            amount=amt,
            reason=state.get("reason_text") or reason_cat,
            urgency=state.get("urgency", "HIGH"),
            evidence_photo=state.get("evidence_photo"),
            evidence_photos=state.get("evidence_photos"),
            vision_analysis=state.get("vision_analysis"),
            fraud_flags=state.get("fraud_flags"),
            chat_summary=chat_summary,
            checks_done=[{"rule": "policy_or_evidence_threshold", "passed": False, "detail": state.get("error") or "Escalated to human supervisor"}],
            escalation_reason=state.get("error") or f"Claim above limit or requires human sign-off ({reason_cat})",
            agent_recommendation="Review claim details, photo evidence, and approve or reject."
        )

        pause_info = {
            "escalation_id": esc.id,
            "case_number": esc.case_number,
            "reason": esc.escalation_reason
        }

        # Interrupt execution and wait for human decision
        admin_decision = interrupt(pause_info)

        # Resumed by admin Command(resume=decision)
        if isinstance(admin_decision, dict):
            dec_status = admin_decision.get("decision", "APPROVED").upper()
            notes = admin_decision.get("notes", "Admin sign-off")
        else:
            dec_status = str(admin_decision).upper()
            notes = "Admin sign-off"

        if dec_status == "APPROVED":
            return {
                "verdict": PolicyVerdict.AUTO_APPROVE,
                "reply": f"Case {esc.case_number} has been approved by our support team! Processing resolution now.",
                "step": "escalate"
            }
        else:
            return {
                "verdict": PolicyVerdict.DENY,
                "reply": f"Our team reviewed Case {esc.case_number} and could not approve this claim: {notes}",
                "quick_replies": ["Contact support", "Check other orders"],
                "case_closed": True,
                "step": "escalate"
            }
    finally:
        db.close()


def node_cancel_order(state: SellerShieldAgentState) -> Dict[str, Any]:
    """
    Action Node: 3-step cancellation with retention.
    Step 1: Ask WHY the customer wants to cancel.
    Step 2: Address concern + offer alternative (retention).
    Step 3: Only cancel if customer insists.
    """
    db: Session = SessionLocal()
    try:
        order = db.query(Order).filter(Order.id == state.get("order_id")).first()
        if not order:
            return {
                "reply": "I couldn't locate an active order to cancel. Could you share your order number?",
                "quick_replies": ["Check my orders"],
                "step": "cancel_order"
            }

        # Non-cancellable statuses — guide immediately, no retention needed
        if order.status in ("CANCELLED", "REFUNDED"):
            return {
                "reply": f"Order {order.order_number} is already {order.status.lower()} — no action needed on your end.",
                "quick_replies": ["Check my other orders", "Browse store"],
                "step": "cancel_order"
            }

        # Check for color change request FIRST, before refusing cancellation on shipped/packed orders!
        check_text = f"{state.get('cancel_reason') or ''} {state.get('user_message') or ''}".lower()
        if any(w in check_text for w in ["colour", "color", "different colour", "different color", "new colour", "new color", "another color", "another colour"]):
            product_name = order.items[0].product_title if order.items else "your item"
            clean_name = product_name.split("(")[0].strip() if "(" in product_name else product_name
            colors = get_product_colors(clean_name)
            return {
                "reply": (
                    f"No problem at all! Instead of cancelling, I can easily swap or replace your {clean_name} "
                    f"for another colour we have in stock. Which colour would you like to choose?"
                ),
                "quick_replies": [*colors, "Keep current color", "Cancel anyway"],
                "pending_question": "SWAP_COLOR_SELECTION",
                "step": "swap_color_offer"
            }

        if order.status in ("SHIPPED", "OUT_FOR_DELIVERY"):
            return {
                "reply": (
                    f"Order {order.order_number} has already shipped and is with the courier ({order.status.replace('_', ' ').lower()}). "
                    "It can't be cancelled at this stage, but you can refuse the delivery at your door and the refund will process automatically. "
                    "Or if you'd like, you can return it within 7 days of delivery."
                ),
                "quick_replies": ["How to refuse delivery", "Return after delivery", "Thanks!"],
                "step": "cancel_order",
                "case_closed": True
            }

        if order.status == "DELIVERED":
            return {
                "reply": (
                    f"Order {order.order_number} has already been delivered. It can't be cancelled, "
                    "but you can start a return or exchange within 7 days of delivery."
                ),
                "quick_replies": ["Return or swap", "Thanks!"],
                "step": "cancel_order",
                "case_closed": True
            }

        # === STEP 1: Ask the reason for cancellation ===
        cancel_reason = state.get("cancel_reason")
        if not cancel_reason:
            product_name = order.items[0].product_title if order.items else "your item"
            return {
                "reply": f"Before I cancel the {product_name} ({order.order_number}), could you tell me what changed your mind? I might be able to help.",
                "quick_replies": [
                    "Found it cheaper elsewhere",
                    "Don't need it anymore",
                    "Ordered wrong size/item",
                    "Taking too long",
                    "Just cancel it"
                ],
                "pending_question": "CANCEL_REASON",
                "step": "cancel_order"
            }

        # === STEP 2: Retention — address the concern ===
        cancel_confirmed = state.get("cancel_confirmed")
        if not cancel_confirmed:
            product_name = order.items[0].product_title if order.items else "your item"
            reason_lower = cancel_reason.lower()

            if "cheaper" in reason_lower or "price" in reason_lower or "expensive" in reason_lower:
                retention_msg = (
                    f"I totally get wanting the best deal! Just so you know, {product_name} comes with free delivery "
                    f"and our 7-day hassle-free return guarantee. If you find a quality issue, you're fully covered. "
                    f"Would you like to keep it, or shall I go ahead and cancel?"
                )
            elif "wrong size" in reason_lower or "wrong item" in reason_lower or "ordered wrong" in reason_lower:
                retention_msg = (
                    f"No worries — mistakes happen! Instead of cancelling, I can swap it for the right size or item "
                    f"at no extra cost, and it'll reach you within 2 days. Want me to help with that?"
                )
            elif "too long" in reason_lower or "taking long" in reason_lower or "slow" in reason_lower or "when" in reason_lower:
                user = db.query(User).filter(User.id == state["customer_id"]).first()
                first_name = user.full_name.split()[0] if user else "there"
                eta = order.expected_delivery_at
                eta_str = eta.strftime("%d %b, %I:%M %p") if eta else "within 2–3 days"
                retention_msg = (
                    f"I completely understand wanting your {product_name} sooner, {first_name}! "
                    f"By paying a fast delivery fee of ₹90, you can get your order delivered by tomorrow! "
                    f"Would you like to upgrade to express delivery, keep standard delivery (arriving {eta_str}), or still cancel?"
                )
                return {
                    "reply": retention_msg,
                    "quick_replies": ["Upgrade to Express (₹90)", "Keep standard delivery", "Cancel anyway"],
                    "pending_question": "EXPEDITE_CONFIRM",
                    "step": "cancel_order"
                }
            elif any(w in reason_lower for w in ["colour", "color", "different colour", "different color", "new colour", "new color", "another color", "another colour"]):
                clean_name = product_name.split("(")[0].strip() if "(" in product_name else product_name
                colors = get_product_colors(clean_name)
                return {
                    "reply": (
                        f"No problem at all! Instead of cancelling, I can easily swap or replace your {clean_name} "
                        f"for another colour we have in stock. Which colour would you like to choose?"
                    ),
                    "quick_replies": [*colors, "Keep current color", "Cancel anyway"],
                    "pending_question": "SWAP_COLOR_SELECTION",
                    "step": "swap_color_offer"
                }
            elif "just cancel" in reason_lower or "don't ask" in reason_lower:
                # Customer is insistent — skip retention, go directly to cancel
                cancel_confirmed = True
            else:
                # Generic retention
                retention_msg = (
                    f"Thanks for letting me know. The {product_name} hasn't shipped yet so cancellation is instant with a full refund. "
                    f"But just checking — would a size swap or a different variant work instead? "
                    f"If not, I'll cancel it right away."
                )

            if not cancel_confirmed:
                return {
                    "reply": retention_msg,
                    "quick_replies": ["Keep the order", "Swap size/item", "Cancel anyway"],
                    "pending_question": "CANCEL_CONFIRM",
                    "step": "cancel_order"
                }

        # === STEP 3: Customer insisted — proceed with cancellation & choose refund destination ===
        is_cod = order.payment_method == "COD"
        dest = state.get("refund_destination")
        amt = get_order_refundable_amount(order, db)

        if not is_cod and amt > 0 and (not dest or dest == "NONE"):
            bonus_pct = int(float(get_setting_value(db, "store_credit_bonus_pct", 10.0)))
            bonus_val = amt * (1.0 + bonus_pct / 100.0)
            user = db.query(User).filter(User.id == state["customer_id"]).first()
            first_name = user.full_name.split()[0] if user else "there"
            reply_msg = (
                f"Understood {first_name}, I will cancel order {order.order_number} for you.\n"
                f"Where would you like your refund of ₹{amt:,.0f} sent?\n"
                f"1. Store wallet: Instant credit to your SellerShield wallet, ready to spend immediately.\n"
                f"2. Promo code: Instant single-use coupon with an extra {bonus_pct}% bonus (₹{bonus_val:,.0f}) for your next order!\n"
                f"3. Back to my account: Reaches your bank/UPI account in 4–5 working days."
            )
            quick_replies = [
                "Store wallet (Instant)",
                f"Promo code (+{bonus_pct}% bonus)",
                "Back to my account (4-5 days)"
            ]
            return {
                "reply": reply_msg,
                "quick_replies": quick_replies,
                "pending_question": "CANCEL_REFUND_DEST",
                "step": "cancel_order"
            }

        res = cancel_order(db, order, cancel_reason or "Customer requested cancellation via AI")
        tool_calls = [*state.get("tool_calls", []), {"tool": "cancel_order", "status": res["action"], "order": order.order_number}]

        if is_cod or amt <= 0:
            return {
                "reply": res["message"],
                "quick_replies": ["Track my other orders", "Browse store"],
                "tool_calls": tool_calls,
                "case_closed": True,
                "pending_question": None,
                "step": "cancel_order"
            }

        user = db.query(User).filter(User.id == state["customer_id"]).first()
        first_name = user.full_name.split()[0] if user else "there"

        if dest == "WALLET":
            w_res = issue_wallet_credit(
                db=db,
                order=order,
                amount=amt,
                reason=cancel_reason or "Customer cancellation to wallet",
                reason_category="Cancellation",
                evidence_status="VERIFIED",
                policy_verdict="AUTO_APPROVE"
            )
            tool_calls.append({"tool": "issue_wallet_credit", "amount": amt, "status": "CREDITED"})
            reply_text = f"Done {first_name}! Order {order.order_number} has been cancelled before dispatch. Your full refund of ₹{amt:,.0f} has been credited to your store wallet and is ready to use!"
            quick_replies = ["Browse store", "Check my wallet", "Thanks!"]
        elif dest == "PROMO":
            bonus_pct = int(float(get_setting_value(db, "store_credit_bonus_pct", 10.0)))
            bonus_val = amt * (1.0 + bonus_pct / 100.0)
            p_res = issue_promo_code(
                db=db,
                order=order,
                amount=amt,
                reason=cancel_reason or "Customer cancellation to promo code",
                reason_category="Cancellation",
                evidence_status="VERIFIED",
                policy_verdict="AUTO_APPROVE"
            )
            code = p_res.get("code", "PROMO-EXTRA10")
            tool_calls.append({"tool": "issue_promo_code", "amount": amt, "code": code})
            reply_text = (
                f"Done {first_name}! Order {order.order_number} has been cancelled before dispatch. "
                f"Here is your single-use coupon with an extra {bonus_pct}% bonus: {code} "
                f"(Total value: ₹{bonus_val:,.0f}, valid for 30 days) to use on your next order!"
            )
            quick_replies = ["Browse store", "Copy code", "Thanks!"]
        else:
            r_res = issue_refund(
                db=db,
                order=order,
                amount=amt,
                reason=cancel_reason or "Customer cancellation to original account",
                reason_category="Cancellation",
                evidence_status="VERIFIED",
                refund_destination="ORIGINAL",
                policy_verdict="AUTO_APPROVE"
            )
            tool_calls.append({"tool": "issue_refund", "amount": amt, "status": "DISBURSED", "destination": "ORIGINAL"})
            reply_text = f"Done {first_name}! Order {order.order_number} has been cancelled before dispatch. Your refund of ₹{amt:,.0f} has been initiated back to your {order.payment_method or 'original'} account and will arrive in 4–5 working days."
            quick_replies = ["Track my other orders", "Browse store", "Thanks!"]

        return {
            "reply": reply_text,
            "quick_replies": quick_replies,
            "tool_calls": tool_calls,
            "case_closed": True,
            "pending_question": None,
            "step": "cancel_order"
        }
    finally:
        db.close()


def node_respond(state: SellerShieldAgentState) -> Dict[str, Any]:
    """Node 13: Final response formatting. Humanizes node draft or generates warm reply."""
    db: Session = SessionLocal()
    try:
        user = db.query(User).filter(User.id == state["customer_id"]).first()
        first_name = user.full_name.split()[0] if user else "there"
        reply = state.get("reply", "")
        node_buttons = state.get("quick_replies") or []

        if reply:
            if state.get("step") in (
                "swap_color_offer", "swap_color_confirmed", "expedite_offer", "expedite_confirmed",
                "refuse_delivery_guidance", "thank_you", "check_wallet", "check_orders", "support_specialist",
                "cancel_refund_dest", "cancel_done",
                "gadget_call_offer", "gadget_call_scheduled", "gadget_call_declined",
                "gadget_call_completed", "gadget_post_call_resolution",
                "gadget_replacement_done", "gadget_wallet_refund_done", "gadget_original_refund_done"
            ):
                quick_replies = node_buttons
            else:
                # 1A, 1B, 1C: Humanize draft using Gemini (temperature 0.7)
                humanized_reply, llm_buttons = humanize(db, state, reply, node_buttons)
                reply = humanized_reply
                # Keep node's own buttons when pending_question is set (so choices stay exact); otherwise use filtered LLM buttons
                if state.get("pending_question"):
                    quick_replies = node_buttons
                else:
                    quick_replies = llm_buttons if (llm_buttons and len(llm_buttons) > 0) else node_buttons
        else:
            instruction = (
                f"You are Maya speaking to customer {user.full_name if user else 'Customer'} (first name: {first_name}).\n"
                f"Customer Emotion: {state.get('emotion') or state.get('sentiment', 'calm')}.\n"
                f"Customer Language: {state.get('language', 'English')}. Register: {state.get('register', 'casual')}.\n"
                f"Customer said: '{state.get('user_message', '')}'.\n"
                f"Write a warm, empathetic 1–2 sentence human reply. Never say 'As an AI' or use stock apologies.\n"
                "Propose 2-3 dynamic quick-reply buttons. Return JSON: {\"reply\": \"...\", \"quick_replies\": [\"...\"]}"
            )
            system_prompt = get_composed_system_prompt(
                db=db,
                node_instruction=instruction,
                summary=state.get("summary"),
                customer_memory=state.get("customer_memory")
            )
            res = call_gemini(
                system_prompt=system_prompt,
                contents=[{"role": "user", "parts": [{"text": state.get("user_message", "")}]}],
                schema=RESPOND_SCHEMA,
                temperature=0.7,
                max_tokens=300
            )
            if res:
                try:
                    p = json.loads(res)
                    reply = p.get("reply") or f"Hey {first_name}, how can I help you with your order today?"
                    quick_replies = p.get("quick_replies") or ["Where is my order?", "Return or swap", "Browse store"]
                except Exception:
                    reply = res
                    quick_replies = ["Where is my order?", "Return or swap", "Browse store"]
            else:
                raw_msg = state.get("user_message", "").strip().lower()
                clean_raw = raw_msg.strip("!., ")
                if any(t == clean_raw or clean_raw.startswith(t + " ") or clean_raw.endswith(" " + t) for t in ["thanks", "thank you", "thx", "tq", "thank u", "many thanks", "thanks a lot", "thank you so much", "dhanyawad", "shukriya", "nandri"]):
                    reply = f"You're very welcome, {first_name}! 😊 Happy to help. Let me know if you need anything else with your orders!"
                    quick_replies = ["Where is my order?", "Return or swap", "Browse store"]
                elif any(g == raw_msg or raw_msg.startswith(g + " ") for g in ["hello", "hi", "hey", "good morning", "good afternoon", "good evening", "vanakkam", "namaste"]):
                    reply = f"Hey {first_name}! How can I help you today?"
                    quick_replies = ["Where is my order?", "Return or swap", "Browse store"]
                elif any(a == clean_raw for a in ["ok", "okay", "got it", "understood", "sure", "alright", "perfect", "cool", "done", "great"]):
                    reply = f"Glad I could help, {first_name}! Feel free to reach out anytime if you need more assistance."
                    quick_replies = ["Where is my order?", "Return or swap", "Browse store"]
                else:
                    # Context-aware fallback: always use order data instead of a canned error apology
                    ord_id = state.get("order_id") or state.get("active_order_id")
                    ord_obj = db.query(Order).filter(Order.id == ord_id).first() if ord_id else None
                    if ord_obj:
                        p_title = ord_obj.items[0].product_title if ord_obj.items else "your item"
                        st_clean = ord_obj.status.replace("_", " ").title()
                        reply = f"I'm here to help with your {p_title} ({ord_obj.order_number}), which is currently {st_clean}. How can I assist you with this order today?"
                        if ord_obj.status in ("PLACED", "PACKED"):
                            quick_replies = ["Cancel order", "Where is my order?", "Thanks!"]
                        elif ord_obj.status in ("SHIPPED", "OUT_FOR_DELIVERY"):
                            quick_replies = ["Track package", "How do I refuse delivery?", "Thanks!"]
                        elif ord_obj.status == "DELIVERED":
                            quick_replies = ["Return or swap", "Browse store", "Thanks!"]
                        else:
                            quick_replies = ["Where is my order?", "Browse store"]
                    else:
                        reply = f"Hey {first_name}! How can I help you today? You can ask me to track an order, start a return or exchange, or explore products."
                        quick_replies = ["Where is my order?", "Return or swap", "Browse store"]

        # Persist messages to DB
        conv_id = state.get("conv_id")
        if conv_id:
            db.add(Message(
                conversation_id=conv_id,
                sender="customer",
                text=state.get("user_message", ""),
                photo_url=state.get("evidence_photo")
            ))
            db.add(Message(
                conversation_id=conv_id,
                sender="agent",
                text=reply,
                tool_calls=json.dumps(state.get("tool_calls", [])),
                quick_replies=json.dumps(quick_replies)
            ))
            conv = db.query(Conversation).filter(Conversation.id == conv_id).first()
            if conv:
                conv.step = state.get("step")
                conv.pending_question = state.get("pending_question")
                if state.get("order_id"):
                    conv.current_order_id = state["order_id"]
                conv.intent = state.get("intent")
                conv.sentiment = state.get("sentiment")
                if state.get("offered"):
                    conv.options_offered = json.dumps(state["offered"])
                if state.get("declined"):
                    conv.declined_options = json.dumps(state["declined"])
            db.commit()

        # Update state messages via add_messages reducer
        return {
            "reply": reply,
            "quick_replies": quick_replies,
            "messages": [
                HumanMessage(id=str(uuid.uuid4()), content=state.get("user_message", "")),
                AIMessage(id=str(uuid.uuid4()), content=reply)
            ],
            "step": "respond"
        }
    finally:
        db.close()


def node_load_memory(state: SellerShieldAgentState) -> Dict[str, Any]:
    """Node 0: Reads customer_memory for the session's customer_id (never from chat text) into state."""
    customer_id = state.get("customer_id")
    if not customer_id:
        return {"customer_memory": {}}

    db: Session = SessionLocal()
    try:
        mem = db.query(CustomerMemory).filter(CustomerMemory.customer_id == customer_id).first()
        if mem:
            past_issues = []
            if mem.past_issues:
                try:
                    past_issues = json.loads(mem.past_issues)
                except Exception:
                    past_issues = [mem.past_issues]
            return {
                "customer_memory": {
                    "preferred_language": mem.preferred_language,
                    "usual_size": mem.usual_size,
                    "tone_preference": mem.tone_preference,
                    "past_issues": past_issues
                }
            }
        return {"customer_memory": {}}
    finally:
        db.close()


def node_summarize_memory(state: SellerShieldAgentState) -> Dict[str, Any]:
    """
    Node: Runs after respond.
    If len(messages) > SUMMARIZE_THRESHOLD, folds all but the last MESSAGES_TO_KEEP into the summary,
    removes folded messages with RemoveMessage, and logs audit event.
    """
    messages = state.get("messages") or []
    if len(messages) <= SUMMARIZE_THRESHOLD:
        return {"step": "summarize_memory"}

    messages_to_fold = messages[:-MESSAGES_TO_KEEP]

    # Format messages to fold into text
    folded_lines = []
    for m in messages_to_fold:
        role = "Customer" if getattr(m, "type", "human") in ("human", "user") or (isinstance(m, dict) and m.get("role") in ("user", "human")) else "Agent"
        content = getattr(m, "content", "") if hasattr(m, "content") else (m.get("text") or m.get("content") or "")
        folded_lines.append(f"{role}: {content}")
    new_messages_text = "\n".join(folded_lines)

    # Load summary prompt template
    prompts_dir = Path(__file__).parent / "prompts"
    summary_prompt_path = prompts_dir / "summary_prompt.txt"
    if summary_prompt_path.exists():
        template = summary_prompt_path.read_text(encoding="utf-8")
    else:
        template = (
            "You maintain a short memory of a customer support chat.\n"
            "PREVIOUS SUMMARY: {previous_summary}\n"
            "NEW MESSAGES TO FOLD IN: {new_messages}\n"
            "Write an updated summary in under 120 words, third person, covering only:\n"
            "- what the customer wants or is upset about, and which order/product\n"
            "- the reason they gave and the photo/evidence status\n"
            "- what the agent offered and what the customer accepted or declined\n"
            "- actions already completed (return created, refund issued, escalation sent)\n"
            "- current pending step\n"
            "Never include card numbers, OTPs, passwords, full addresses or emotional commentary. Be factual, dense, concise."
        )

    previous_summary = state.get("summary") or "None"
    prompt_filled = template.replace("{previous_summary}", previous_summary).replace("{new_messages}", new_messages_text)

    try:
        updated_summary = call_gemini(
            system_prompt="You maintain a short, dense, factual summary of a customer support chat.",
            contents=[{"role": "user", "parts": [{"text": prompt_filled}]}]
        )
    except Exception as e:
        print(f"[Summarize Memory LLM Error]: {e}")
        # If summarizing fails, keep messages unchanged without blocking
        return {"step": "summarize_memory"}

    if not updated_summary:
        # Fallback summary if LLM call returned empty
        action_desc = state.get("intent", "support inquiry")
        updated_summary = f"{previous_summary}\nCustomer discussed {action_desc} for order {state.get('order_number') or state.get('order_id') or 'N/A'}.".strip()

    # Redact sensitive data before saving
    sanitized_summary = sanitize_memory_text(updated_summary)

    # Prune folded messages using RemoveMessage
    remove_msgs = []
    for m in messages_to_fold:
        m_id = getattr(m, "id", None) or (m.get("id") if isinstance(m, dict) else None)
        if m_id:
            remove_msgs.append(RemoveMessage(id=m_id))

    # Audit log for summarize event
    db: Session = SessionLocal()
    try:
        log_audit_event(
            db=db,
            actor="AI_AGENT",
            tool="summarize_memory",
            input_payload={"folded_count": len(messages_to_fold), "previous_summary": previous_summary[:200]},
            output_payload={"new_summary": sanitized_summary[:200], "pruned_count": len(remove_msgs)},
            verdict="EXECUTED",
            status="SUCCESS",
            customer_id=state.get("customer_id"),
            order_id=state.get("order_id")
        )
    except Exception as e:
        print(f"[Summarize Audit Error]: {e}")
    finally:
        db.close()

    return {
        "summary": sanitized_summary,
        "messages": remove_msgs,
        "step": "summarize_memory"
    }


def node_save_memory(state: SellerShieldAgentState) -> Dict[str, Any]:
    """
    Node: Runs only when a case is closed.
    Extracts small facts (language, usual size, tone preference, one-line past issue with outcome)
    as a Pydantic-validated object, then merges them into customer_memory table.
    Skips the write if nothing new.
    """
    customer_id = state.get("customer_id")
    if not customer_id or not state.get("case_closed"):
        return {"step": "save_memory"}

    existing_mem = state.get("customer_memory") or {}

    summary_text = state.get("summary", "")
    recent_msgs = state.get("messages") or []
    conv_text = f"Summary: {summary_text}\n" + "\n".join([
        f"{'Customer' if getattr(m, 'type', 'human') in ('human', 'user') or (isinstance(m, dict) and m.get('role') in ('user', 'human')) else 'Agent'}: {getattr(m, 'content', '') if hasattr(m, 'content') else (m.get('text') or m.get('content') or '')}"
        for m in recent_msgs[-6:]
    ])

    extract_instruction = (
        "Extract long-term customer profile facts from this conversation.\n"
        "Rules:\n"
        "- preferred_language: Language used (English, Hinglish, Tamil, etc.)\n"
        "- usual_size: Size mentioned or exchanged (e.g. '9 UK', 'M')\n"
        "- tone_preference: Customer tone preference (e.g. 'direct', 'polite', 'urgent')\n"
        "- past_issue: Exactly one short line summarizing what happened in this closed case and the final outcome. "
        "Example: 'Damaged item: full refund to wallet' or 'Tracking status checked for order #1234'.\n"
        "- NEVER include risk scores, fraud flags, opinions, card numbers, OTPs, passwords, or full addresses.\n"
        f"Existing facts: {json.dumps(existing_mem)}"
    )

    extracted_data: Dict[str, Any] = {}
    try:
        raw_res = call_gemini(
            system_prompt=extract_instruction,
            contents=[{"role": "user", "parts": [{"text": conv_text}]}],
            schema=MEMORY_EXTRACT_SCHEMA
        )
        if raw_res:
            try:
                parsed = json.loads(raw_res)
                val = CustomerMemoryExtract(**parsed)
                extracted_data = val.model_dump(exclude_none=True)
            except Exception:
                pass
    except Exception as e:
        print(f"[Save Memory Extraction Error]: {e}")
        extracted_data = {}

    # Deterministic fallbacks
    if not extracted_data.get("preferred_language") and state.get("language"):
        extracted_data["preferred_language"] = state.get("language")

    rep_choice = state.get("replacement_choice") or {}
    if not extracted_data.get("usual_size") and rep_choice.get("size"):
        extracted_data["usual_size"] = rep_choice.get("size")

    if not extracted_data.get("past_issue"):
        order_num = state.get("order_number") or state.get("order_id") or "order"
        intent = state.get("intent")
        if intent == "TRACKING":
            extracted_data["past_issue"] = f"Tracked {order_num}: status shared"
        elif intent == "CANCEL":
            extracted_data["past_issue"] = f"Cancelled {order_num}"
        elif state.get("verdict") == "AUTO_APPROVE":
            res_type = state.get("resolution_type") or "resolution"
            extracted_data["past_issue"] = f"Order {order_num} {state.get('reason_category') or 'issue'}: {res_type.lower()} approved"

    # Merge facts
    updated_lang = extracted_data.get("preferred_language") or existing_mem.get("preferred_language")
    updated_size = extracted_data.get("usual_size") or existing_mem.get("usual_size")
    updated_tone = extracted_data.get("tone_preference") or existing_mem.get("tone_preference")

    if updated_lang:
        updated_lang = sanitize_memory_text(str(updated_lang))
    if updated_size:
        updated_size = sanitize_memory_text(str(updated_size))
    if updated_tone:
        updated_tone = sanitize_memory_text(str(updated_tone))

    past_issues = list(existing_mem.get("past_issues") or [])
    new_issue = extracted_data.get("past_issue")
    if new_issue:
        sanitized_issue = sanitize_memory_text(str(new_issue).strip())
        if sanitized_issue and sanitized_issue not in past_issues:
            past_issues.append(sanitized_issue)
            past_issues = past_issues[-5:]

    has_changed = (
        updated_lang != existing_mem.get("preferred_language") or
        updated_size != existing_mem.get("usual_size") or
        updated_tone != existing_mem.get("tone_preference") or
        past_issues != (existing_mem.get("past_issues") or [])
    )

    merged_mem = {
        "preferred_language": updated_lang,
        "usual_size": updated_size,
        "tone_preference": updated_tone,
        "past_issues": past_issues
    }

    # Skip the write if nothing new
    if not has_changed:
        return {"customer_memory": merged_mem, "step": "save_memory"}

    db: Session = SessionLocal()
    try:
        mem_row = db.query(CustomerMemory).filter(CustomerMemory.customer_id == customer_id).first()
        if not mem_row:
            mem_row = CustomerMemory(
                customer_id=customer_id,
                preferred_language=updated_lang,
                usual_size=updated_size,
                tone_preference=updated_tone,
                past_issues=json.dumps(past_issues)
            )
            db.add(mem_row)
        else:
            mem_row.preferred_language = updated_lang
            mem_row.usual_size = updated_size
            mem_row.tone_preference = updated_tone
            mem_row.past_issues = json.dumps(past_issues)
            mem_row.updated_at = datetime.datetime.utcnow()

        db.commit()

        log_audit_event(
            db=db,
            actor="AI_AGENT",
            tool="save_memory",
            input_payload={"extracted": extracted_data},
            output_payload={"merged_memory": merged_mem},
            verdict="EXECUTED",
            status="SUCCESS",
            customer_id=customer_id,
            order_id=state.get("order_id")
        )
    except Exception as e:
        print(f"[Save Memory DB Error]: {e}")
    finally:
        db.close()

    return {"customer_memory": merged_mem, "step": "save_memory"}


def node_audit(state: SellerShieldAgentState) -> Dict[str, Any]:
    """Node 14: Wrap every node and tool execution in audit trail."""
    db: Session = SessionLocal()
    try:
        latency_ms = int((time.time() - state.get("start_time", time.time())) * 1000)
        tool_calls = state.get("tool_calls", [])
        tool_name = tool_calls[-1]["tool"] if tool_calls else f"langgraph.{state.get('intent', 'CHAT')}"

        log_audit_event(
            db=db,
            actor="LANGGRAPH_AGENT",
            tool=tool_name,
            input_payload={"message": state.get("user_message", "")[:200], "step": state.get("step")},
            output_payload={"reply": state.get("reply", "")[:200], "tools": [t.get("tool") for t in tool_calls]},
            verdict=state.get("verdict") or ("AUTO_APPROVE" if tool_calls else "CHAT_ONLY"),
            status="ERROR" if state.get("error") else "SUCCESS",
            customer_id=state.get("customer_id"),
            order_id=state.get("order_id"),
            error=state.get("error")
        )
        return {"step": "audit"}
    finally:
        db.close()


# ============================================================================
# 5. CONDITIONAL ROUTERS (EDGES)
# ============================================================================

def router_after_resolve(state: SellerShieldAgentState) -> str:
    """Conditional Edge: Routes after order identification."""
    if state.get("pending_question") in (
        "ORDER_SELECTION", "EXPEDITE_CONFIRM", "SWAP_COLOR_SELECTION",
        "CANCEL_REFUND_DEST", "GADGET_CALL_OFFER", "GADGET_CALL_STATUS",
        "GADGET_DECLINED_FOLLOWUP", "GADGET_POST_CALL_RESOLUTION"
    ) or state.get("step") in (
        "cancel_policy", "cancel_retained", "cancel_refund_dest", "cancel_done",
        "expedite_offer", "expedite_confirmed", "swap_color_offer", "swap_color_confirmed",
        "refuse_delivery_guidance", "thank_you", "check_orders", "check_wallet",
        "support_specialist", "order_selected",
        "gadget_call_offer", "gadget_call_scheduled", "gadget_call_declined",
        "gadget_call_completed", "gadget_post_call_resolution",
        "gadget_replacement_done", "gadget_wallet_refund_done", "gadget_original_refund_done"
    ):
        return "node_respond"

    intent = state.get("intent", "GENERAL")
    if intent in ("TRACKING", "EXPEDITE"):
        return "node_track"
    elif intent == "CANCEL":
        return "node_cancel_order"
    elif intent == "RETURN_REFUND_EXCHANGE":
        return "node_ask_reason"
    return "node_respond"


def router_after_reason(state: SellerShieldAgentState) -> str:
    """Conditional Edge: If reason needs to be answered by customer, stop at respond. Otherwise check policy."""
    if state.get("pending_question") == "ASK_REASON":
        return "node_respond"
    return "node_policy_check"


def router_after_policy(state: SellerShieldAgentState) -> str:
    """Conditional Edge: AUTO_APPROVE -> collect_evidence, NEEDS_HUMAN -> escalate, DENY -> respond."""
    v = str(state.get("verdict") or "")
    if "DENY" in v:
        return "node_respond"
    elif "NEEDS_HUMAN" in v:
        return "node_escalate"
    return "node_collect_evidence"


def router_after_evidence(state: SellerShieldAgentState) -> str:
    """Conditional Edge: If photo pending or failed twice -> respond / escalate, else retention."""
    v = str(state.get("verdict") or "")
    if "NEEDS_HUMAN" in v:
        return "node_escalate"
    if state.get("pending_question") == "COLLECT_EVIDENCE":
        return "node_respond"
    return "node_retention"


def router_after_retention(state: SellerShieldAgentState) -> str:
    """Conditional Edge: Route based on resolution selection."""
    if state.get("pending_question") == "RETENTION_CHOICE":
        return "node_respond"
    if state.get("resolution_type") == "REPLACEMENT":
        return "node_replacement_flow"
    return "node_refund_flow"


def router_after_replacement(state: SellerShieldAgentState) -> str:
    """Conditional Edge: If replacement details pending, stop at respond; else act."""
    if state.get("pending_question") == "REPLACEMENT_DETAILS":
        return "node_respond"
    return "node_act"


def router_after_refund(state: SellerShieldAgentState) -> str:
    """Conditional Edge: If refund destination pending, stop at respond; if needs human, escalate; else act."""
    if state.get("pending_question") == "REFUND_DESTINATION":
        return "node_respond"
    v = str(state.get("verdict") or "")
    if "NEEDS_HUMAN" in v:
        return "node_escalate"
    return "node_act"


def router_after_verify(state: SellerShieldAgentState) -> str:
    """Conditional Edge: Verify DB record. If failed, escalate; else respond."""
    if state.get("verdict") == PolicyVerdict.NEEDS_HUMAN or state.get("error"):
        return "node_escalate"
    return "node_respond"


def router_after_escalate(state: SellerShieldAgentState) -> str:
    """Conditional Edge: If approved by admin, act; else respond."""
    if state.get("verdict") == PolicyVerdict.AUTO_APPROVE:
        return "node_act"
    return "node_respond"


def router_after_summarize(state: SellerShieldAgentState) -> str:
    """Conditional Edge: If case is closed, save memory; else go directly to audit."""
    if state.get("case_closed"):
        return "node_save_memory"
    return "node_audit"


# ============================================================================
# 6. BUILD & COMPILE STATEGRAPH WITH SQLITE CHECKPOINTER
# ============================================================================

def build_sellershield_graph() -> Any:
    builder = StateGraph(SellerShieldAgentState)

    # Add all nodes
    builder.add_node("node_load_memory", node_load_memory)
    builder.add_node("node_understand", node_understand)
    builder.add_node("node_resolve_order", node_resolve_order)
    builder.add_node("node_track", node_track)
    builder.add_node("node_ask_reason", node_ask_reason)
    builder.add_node("node_policy_check", node_policy_check)
    builder.add_node("node_collect_evidence", node_collect_evidence)
    builder.add_node("node_retention", node_retention)
    builder.add_node("node_replacement_flow", node_replacement_flow)
    builder.add_node("node_refund_flow", node_refund_flow)
    builder.add_node("node_act", node_act)
    builder.add_node("node_verify", node_verify)
    builder.add_node("node_escalate", node_escalate)
    builder.add_node("node_cancel_order", node_cancel_order)
    builder.add_node("node_respond", node_respond)
    builder.add_node("node_summarize_memory", node_summarize_memory)
    builder.add_node("node_save_memory", node_save_memory)
    builder.add_node("node_audit", node_audit)

    # START -> load_memory -> understand -> resolve_order
    builder.add_edge(START, "node_load_memory")
    builder.add_edge("node_load_memory", "node_understand")
    builder.add_edge("node_understand", "node_resolve_order")

    # Conditional router from resolve_order
    builder.add_conditional_edges(
        "node_resolve_order",
        router_after_resolve,
        {
            "node_respond": "node_respond",
            "node_track": "node_track",
            "node_cancel_order": "node_cancel_order",
            "node_ask_reason": "node_ask_reason"
        }
    )

    # Track -> respond
    builder.add_edge("node_track", "node_respond")

    # Cancel -> respond
    builder.add_edge("node_cancel_order", "node_respond")

    # Reason router
    builder.add_conditional_edges(
        "node_ask_reason",
        router_after_reason,
        {
            "node_respond": "node_respond",
            "node_policy_check": "node_policy_check"
        }
    )

    # Policy router
    builder.add_conditional_edges(
        "node_policy_check",
        router_after_policy,
        {
            "node_respond": "node_respond",
            "node_escalate": "node_escalate",
            "node_collect_evidence": "node_collect_evidence"
        }
    )

    # Evidence router
    builder.add_conditional_edges(
        "node_collect_evidence",
        router_after_evidence,
        {
            "node_respond": "node_respond",
            "node_escalate": "node_escalate",
            "node_retention": "node_retention"
        }
    )

    # Retention router
    builder.add_conditional_edges(
        "node_retention",
        router_after_retention,
        {
            "node_respond": "node_respond",
            "node_replacement_flow": "node_replacement_flow",
            "node_refund_flow": "node_refund_flow"
        }
    )

    # Replacement router
    builder.add_conditional_edges(
        "node_replacement_flow",
        router_after_replacement,
        {
            "node_respond": "node_respond",
            "node_act": "node_act"
        }
    )

    # Refund router
    builder.add_conditional_edges(
        "node_refund_flow",
        router_after_refund,
        {
            "node_respond": "node_respond",
            "node_escalate": "node_escalate",
            "node_act": "node_act"
        }
    )

    # Act -> Verify
    builder.add_edge("node_act", "node_verify")

    # Verify router
    builder.add_conditional_edges(
        "node_verify",
        router_after_verify,
        {
            "node_escalate": "node_escalate",
            "node_respond": "node_respond"
        }
    )

    # Escalate router
    builder.add_conditional_edges(
        "node_escalate",
        router_after_escalate,
        {
            "node_act": "node_act",
            "node_respond": "node_respond"
        }
    )

    # Respond -> Summarize Memory
    builder.add_edge("node_respond", "node_summarize_memory")

    # Summarize Memory router (case closed -> save_memory, else -> audit)
    builder.add_conditional_edges(
        "node_summarize_memory",
        router_after_summarize,
        {
            "node_save_memory": "node_save_memory",
            "node_audit": "node_audit"
        }
    )

    # Save Memory -> Audit -> END
    builder.add_edge("node_save_memory", "node_audit")
    builder.add_edge("node_audit", END)

    return builder.compile(checkpointer=checkpointer)


# Global compiled graph with SqliteSaver
sellershield_graph = build_sellershield_graph()


# ============================================================================
# 7. RUN AGENT TURN (FASTAPI / API ENTRYPOINT)
# ============================================================================

def run_agent_turn(
    db: Session,
    customer: User,
    user_message: str,
    active_order_id: Optional[str] = None,
    evidence_photo: Optional[str] = None,
    evidence_photos: Optional[List[str]] = None,
    source: Optional[str] = "text"
) -> Dict[str, Any]:
    """Execute one turn through the compiled LangGraph with SQLite checkpointer."""
    start_time = time.time()

    # Find or create conversation
    conv = db.query(Conversation).filter(
        Conversation.customer_id == customer.id
    ).order_by(Conversation.updated_at.desc()).first()

    if not conv:
        conv = Conversation(customer_id=customer.id, options_offered="[]", declined_options="[]")
        db.add(conv)
        db.commit()
        db.refresh(conv)

    config = {"configurable": {"thread_id": conv.id}}

    # Load existing state from checkpoint if available
    checkpoint_state = sellershield_graph.get_state(config)
    existing_vals = checkpoint_state.values if checkpoint_state else {}

    # If the previous claim was closed (act executed, cancelled, or case_closed),
    # reset transient claim fields for the new request while preserving rolling summary & customer memory!
    prev_step = existing_vals.get("step")
    has_pending = bool(existing_vals.get("pending_question"))
    is_prev_case_finished = bool(
        existing_vals.get("case_closed")
        or (not has_pending and prev_step in (
            "act", "cancel_order", "cancel_policy", "cancel_retained",
            "expedite_confirmed", "swap_color_confirmed", "refuse_delivery_guidance", "thank_you",
            "order_selected", "check_orders", "support_specialist"
        ))
    )

    # Resolve photos
    photos = evidence_photos or ([evidence_photo] if evidence_photo else (existing_vals.get("evidence_photos") or []))
    primary_photo = evidence_photo or (photos[0] if photos else existing_vals.get("evidence_photo"))

    # If answering an existing question/choice, preserve the active intent so the selection fulfills it!
    active_intent = existing_vals.get("intent") if (has_pending and existing_vals.get("intent")) else "GENERAL"

    # Order persistence across conversation: always remember the active order discussed in this chat
    persisted_order_id = active_order_id or existing_vals.get("order_id") or (conv.current_order_id if conv else None)
    persisted_order_number = existing_vals.get("order_number")
    if not persisted_order_number and persisted_order_id:
        db_ord = db.query(Order).filter(Order.id == persisted_order_id).first()
        if db_ord:
            persisted_order_number = db_ord.order_number

    # Merge with new turn inputs
    current_state: Dict[str, Any] = {
        "customer_id": customer.id,
        "conv_id": conv.id,
        "user_message": user_message,
        "evidence_photo": primary_photo,
        "evidence_photos": photos,
        "active_order_id": persisted_order_id,
        "summary": existing_vals.get("summary", ""),
        "customer_memory": existing_vals.get("customer_memory", {}),
        "case_closed": False,
        "language": existing_vals.get("language", "en"),
        "sentiment": "CALM",
        "urgency": "MEDIUM",
        "intent": active_intent,
        "order_id": persisted_order_id,
        "order_number": persisted_order_number,
        "reason_category": None if is_prev_case_finished else existing_vals.get("reason_category"),
        "reason_text": None if is_prev_case_finished else existing_vals.get("reason_text"),
        "evidence_status": "NONE" if is_prev_case_finished else existing_vals.get("evidence_status", "NONE"),
        "evidence_retries": 0 if is_prev_case_finished else existing_vals.get("evidence_retries", 0),
        "vision_analysis": None if is_prev_case_finished else existing_vals.get("vision_analysis"),
        "fraud_flags": [] if is_prev_case_finished else existing_vals.get("fraud_flags", []),
        "resolution_type": None if is_prev_case_finished else existing_vals.get("resolution_type"),
        "replacement_choice": None if is_prev_case_finished else existing_vals.get("replacement_choice"),
        "refund_destination": None if is_prev_case_finished else existing_vals.get("refund_destination"),
        "offered": [] if is_prev_case_finished else existing_vals.get("offered", []),
        "declined": [] if is_prev_case_finished else existing_vals.get("declined", []),
        "verdict": None if is_prev_case_finished else existing_vals.get("verdict"),
        "cancel_reason": None if is_prev_case_finished else existing_vals.get("cancel_reason"),
        "cancel_confirmed": None if is_prev_case_finished else existing_vals.get("cancel_confirmed"),
        "step": None if is_prev_case_finished else existing_vals.get("step"),
        "pending_question": None if is_prev_case_finished else existing_vals.get("pending_question"),
        "reply": "",
        "quick_replies": [],
        "tool_calls": [],
        "error": None,
        "start_time": start_time
    }

    result = sellershield_graph.invoke(current_state, config=config)

    # Check if interrupted for human escalation
    if "__interrupt__" in result:
        interrupt_val = result["__interrupt__"][0].value if result["__interrupt__"] else {}
        case_num = interrupt_val.get("case_number", "CASE-PENDING")
        reply_text = f"I've escalated this to our senior support team with all the details under Reference: {case_num}. A specialist is reviewing your request right now."
        return {
            "reply": reply_text,
            "reply_text": reply_text,
            "intent": result.get("intent", "GENERAL"),
            "sentiment": result.get("sentiment", "CALM"),
            "quick_replies": ["Thank you, waiting"],
            "tool_calls": result.get("tool_calls", []),
            "order_number": result.get("order_number"),
            "architecture": "LangGraph (StateGraph + SqliteSaver)",
            "summary": result.get("summary", ""),
            "customer_memory": result.get("customer_memory", {}),
            "evidence_status": result.get("evidence_status"),
            "vision_analysis": result.get("vision_analysis"),
            "fraud_flags": result.get("fraud_flags", []),
            "evidence_photos": result.get("evidence_photos", []),
            "escalated": True,
            "case_number": case_num
        }

    latency_ms = int((time.time() - start_time) * 1000)

    return {
        "reply": result.get("reply", "I'm here to help with your orders!"),
        "reply_text": result.get("reply", "I'm here to help with your orders!"),
        "intent": result.get("intent", "GENERAL"),
        "sentiment": result.get("sentiment", "CALM"),
        "quick_replies": result.get("quick_replies", []),
        "tool_calls": result.get("tool_calls", []),
        "order_number": result.get("order_number"),
        "pending_question": result.get("pending_question"),
        "evidence_status": result.get("evidence_status"),
        "vision_analysis": result.get("vision_analysis"),
        "fraud_flags": result.get("fraud_flags", []),
        "evidence_photos": result.get("evidence_photos", []),
        "latency_ms": latency_ms,
        "summary": result.get("summary", ""),
        "customer_memory": result.get("customer_memory", {}),
        "architecture": "LangGraph (StateGraph + SqliteSaver)"
    }


def resume_agent_escalation(
    db: Session,
    conv_id: str,
    decision: str,
    notes: str = ""
) -> Dict[str, Any]:
    """Resume a paused graph waiting at an interrupt() node after admin decision."""
    config = {"configurable": {"thread_id": conv_id}}
    resumed = sellershield_graph.invoke(Command(resume={"decision": decision, "notes": notes}), config=config)
    return {
        "reply_text": resumed.get("reply", f"Admin decision {decision} processed."),
        "tool_calls": resumed.get("tool_calls", []),
        "verdict": resumed.get("verdict"),
        "step": resumed.get("step")
    }
