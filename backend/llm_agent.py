import os
import json
import time
from pathlib import Path
from typing import Dict, Any, List, Optional
import datetime
import httpx
from dotenv import load_dotenv

env_path = Path(__file__).parent / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    load_dotenv()

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .models import User, Order, Product, Conversation, Message, TrackingEvent, Setting
from .policy_engine import check_policy, PolicyVerdict, get_setting_value
from .return_api import create_exchange, create_return, list_alternatives, cancel_order
from .refund_api import issue_refund, issue_wallet_credit
from .escalation import escalate_to_human
from .audit_log import log_audit_event

# Persistent HTTP client with connection pooling (eliminates TLS handshake delay on every chat turn)
_http_client = httpx.Client(
    timeout=httpx.Timeout(12.0, connect=4.0),
    limits=httpx.Limits(max_keepalive_connections=10, max_connections=20)
)


class AgentStructuredOutput(BaseModel):
    reply_text: str = Field(description="1 to 3 short, warm, human sentences.")
    intent: Optional[str] = Field(default="GENERAL")
    sentiment: Optional[str] = Field(default="CALM")
    urgency: Optional[str] = Field(default="MEDIUM")
    identified_order_number: Optional[str] = Field(default=None)
    reason: Optional[str] = Field(default=None)
    tool_action: Optional[str] = Field(default="NONE")
    new_size: Optional[str] = Field(default=None)
    quick_replies: Optional[List[str]] = Field(default_factory=list)


RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "reply_text": {"type": "STRING"},
        "intent": {
            "type": "STRING",
            "enum": ["TRACKING", "CANCEL", "EXCHANGE", "REFUND", "DAMAGE", "HOW_TO_GUIDE", "GENERAL"]
        },
        "sentiment": {
            "type": "STRING",
            "enum": ["CALM", "FRUSTRATED", "CONFUSED", "HAPPY"]
        },
        "urgency": {
            "type": "STRING",
            "enum": ["LOW", "MEDIUM", "HIGH"]
        },
        "identified_order_number": {"type": "STRING", "nullable": True},
        "reason": {"type": "STRING", "nullable": True},
        "tool_action": {
            "type": "STRING",
            "enum": ["TRACK", "CANCEL", "SWAP", "CREDIT", "REFUND", "ESCALATE", "NONE"]
        },
        "new_size": {"type": "STRING", "nullable": True},
        "quick_replies": {
            "type": "ARRAY",
            "items": {"type": "STRING"}
        }
    },
    "required": ["reply_text", "intent", "sentiment", "tool_action", "quick_replies"]
}


def get_llm_api_key() -> str:
    return (
        os.environ.get("LLM_API_KEY") or
        os.environ.get("GEMINI_API_KEY") or
        ""
    ).strip()


def build_system_prompt(
    customer: User,
    orders_summary: List[dict],
    conv: Conversation,
    active_order_id: Optional[str],
    declined_opts: list,
    offered_opts: list,
    refund_limit: float,
    return_window_days: int
) -> str:
    first_name = customer.full_name.split()[0]

    return f"""You are a warm, smart, real human customer support executive at SellerShield (an online store). You are NOT a robotic chatbot.

CUSTOMER: {customer.full_name} (first name: {first_name})
POLICY LIMITS: Return window = {return_window_days} days from delivery. Instant cash refund limit = ₹{int(refund_limit)} (orders above ₹{int(refund_limit)} need quick manager approval, though size swaps and +10% store credit are instant). Hygiene items (is_returnable=false) cannot be returned.

CUSTOMER'S LIVE ORDERS & REAL TRACKING DATA:
{json.dumps(orders_summary, ensure_ascii=False)}

MEMORY STATE:
- Active Order Focus: {conv.current_order_id or active_order_id or 'Auto-detect'}
- Prior Intent: {conv.intent or 'None'} | Sentiment: {conv.sentiment or 'CALM'}
- Options already offered: {json.dumps(offered_opts)}
- Options customer DECLINED (NEVER offer again!): {json.dumps(declined_opts)}

HOW TO THINK & REPLY LIKE A REAL HUMAN:
1. UNDERSTAND MESSY GRAMMAR, TYPOS & MIXED LANGUAGES: Customers make spelling mistakes, grammar errors, slang, Hinglish ("paisa wapas chahiye", "order kaha hai"), or Tamil ("order enga iruku"). Understand their true intent effortlessly without pointing out grammar mistakes. Reply naturally in the same language/vibe!
2. NATURAL TONE (1-3 SENTENCES MAX): Sound like a helpful friend working support. Warm, direct, empathetic. NEVER say "I understand your concern", "As an AI", "I apologize for the inconvenience caused", or give bulleted policy walls. Use "{first_name}" occasionally, not every reply.
3. RESOLVE REFERENCES NATURALLY: Match "it", "the shoes", "my order", "that second one" to their live orders. If they have multiple orders and it's genuinely unclear which one they mean, ask ONE short question ("Is this about the running shoes or the earbuds?"). Never ask for info you already see above!
4. ORDER TRACKING (tool_action="TRACK"): When they ask where their order is / delivery status / ETA, ALWAYS look at `latest_tracking` in their order JSON and reply naturally with the real status, exact last location, and what happens next. Set tool_action="TRACK".
5. GUIDE CONFUSED CUSTOMERS (tool_action="NONE", intent="HOW_TO_GUIDE"): If they don't know HOW to cancel, return, or get a refund (e.g. "how to refund?", "i dont know how cancel", "tell me process"):
   - Guide them warmly in 2 plain sentences tailored to their actual order!
   - If their order is PLACED/PACKED: explain we can cancel it right here in 1 second (or if SHIPPED, explain they can simply refuse delivery at the door for an automatic refund).
   - If DELIVERED: explain they don't need to fill any complicated forms — they can tell you right here in chat OR tap "Return / Swap with AI" in "My Orders", and ask which option they want.
   - Do NOT run CANCEL/REFUND until they actually ask to proceed or clarify which order!
6. CANCELLING AN ORDER (tool_action="CANCEL"): If they explicitly ask to cancel a PLACED/PACKED order, set tool_action="CANCEL". If it's already SHIPPED or DELIVERED, explain honestly and guide them (refuse at door / start return) with tool_action="NONE".
7. RETAIN THEN RESOLVE (Returns / Fit / Damage):
   - Step A: Empathize briefly and check what's wrong (if unclear). If damage/defect is claimed and no photo is attached yet, warmly ask them to tap the camera icon to share a quick photo.
   - Step B: Solve the real problem first! If shoes/clothes don't fit, offer a free doorstep size swap (name an available size from `available_sizes`!) — only set tool_action="SWAP" and `new_size` once they agree or specify the size!
   - Step C: If swap isn't wanted (or they didn't like the item), offer instant Store Credit with a +10% bonus (faster than bank refund, works even above ₹{int(refund_limit)}). Only set tool_action="CREDIT" once they say yes!
   - Step D: If they decline swap/credit or firmly insist on cash refund, stop persuading and set tool_action="REFUND" politely. Never guilt or pressure.
8. HONESTY: Never claim a refund, swap, or cancellation is completed unless you are setting the corresponding tool_action right now (and never promise auto-refund if `is_returnable=false` or `total_amount > {int(refund_limit)}` — explain honestly!).
9. QUICK REPLIES: Include 2-3 short, natural clickable options matching what the customer would likely say next."""


def call_gemini_fast(api_key: str, model_name: str, system_prompt: str, contents: List[dict]) -> Optional[dict]:
    """Call Gemini REST API with thinkingBudget=0 and strict responseSchema for ~1.5s latency."""
    payload = {
        "contents": contents,
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": RESPONSE_SCHEMA,
            "temperature": 0.25,
            "maxOutputTokens": 450,
            "thinkingConfig": {"thinkingBudget": 0}
        }
    }

    models_to_try = [model_name]
    if model_name != "gemini-3-flash-preview":
        models_to_try.append("gemini-3-flash-preview")

    for m in models_to_try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={api_key}"
        try:
            resp = _http_client.post(url, json=payload)
            if resp.status_code == 200:
                res_json = resp.json()
                text = res_json["candidates"][0]["content"]["parts"][0]["text"]
                return json.loads(text)
            else:
                print(f"[LLM Warning] {m} returned HTTP {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            print(f"[LLM Error] {m} failed: {e}")

    return None


def run_agent_turn(
    db: Session,
    customer: User,
    user_message: str,
    active_order_id: Optional[str] = None,
    evidence_photo: Optional[str] = None
) -> Dict[str, Any]:
    t_start = time.time()
    api_key = get_llm_api_key()
    model_name = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")

    refund_limit = float(get_setting_value(db, "refund_limit", 2000.0))
    return_window_days = int(get_setting_value(db, "return_window_days", 7))

    # 1. Retrieve or create Conversation & load state
    conv = db.query(Conversation).filter(
        Conversation.customer_id == customer.id
    ).order_by(Conversation.updated_at.desc()).first()

    if not conv:
        conv = Conversation(customer_id=customer.id, options_offered="[]", declined_options="[]")
        db.add(conv)
        db.commit()
        db.refresh(conv)

    # 2. Fetch all customer orders with live tracking events & product details
    customer_orders = db.query(Order).filter(
        Order.customer_id == customer.id
    ).order_by(Order.created_at.desc()).all()

    orders_summary = []
    for o in customer_orders:
        item_details = []
        is_returnable = True
        available_sizes = []

        for it in o.items:
            product = db.query(Product).filter(Product.id == it.product_id).first()
            if product:
                if not product.is_returnable:
                    is_returnable = False
                if product.sizes:
                    try:
                        available_sizes = json.loads(product.sizes)
                    except Exception:
                        pass
            item_details.append(f"{it.product_title} ({it.selected_size or 'Standard'}) x{it.quantity}")

        # Latest tracking event
        events = db.query(TrackingEvent).filter(
            TrackingEvent.order_id == o.id
        ).order_by(TrackingEvent.created_at.desc()).all()

        latest_ev = events[0] if events else None
        days_since_delivery = None
        if o.delivered_at:
            days_since_delivery = (datetime.datetime.utcnow() - o.delivered_at).days

        # Allowed actions hint for the AI brain
        if o.status in ("PLACED", "PACKED"):
            allowed = ["TRACK", "CANCEL"]
        elif o.status in ("SHIPPED", "OUT_FOR_DELIVERY"):
            allowed = ["TRACK", "GUIDE_REFUSE_AT_DOOR"]
        elif o.status == "DELIVERED":
            if not is_returnable:
                allowed = ["NON_RETURNABLE_HYGIENE_ITEM"]
            elif days_since_delivery is not None and days_since_delivery > return_window_days:
                allowed = ["PAST_RETURN_WINDOW_ESCALATE"]
            else:
                allowed = ["SWAP", "CREDIT (+10% bonus)", "REFUND" if o.total_amount <= refund_limit else f"REFUND (needs admin approval > ₹{int(refund_limit)})"]
        else:
            allowed = [f"ALREADY_{o.status}"]

        orders_summary.append({
            "order_number": o.order_number,
            "status": o.status,
            "items": ", ".join(item_details),
            "available_sizes": available_sizes,
            "total_amount": o.total_amount,
            "payment_method": o.payment_method,
            "is_returnable": is_returnable,
            "days_since_delivery": days_since_delivery,
            "allowed_actions": allowed,
            "latest_tracking": {
                "title": latest_ev.title,
                "location": latest_ev.location,
                "description": latest_ev.description,
                "updated_at": latest_ev.created_at.strftime("%b %d, %I:%M %p")
            } if latest_ev else None
        })

    # 3. Recent chat history (last 8 messages for context without bloat)
    recent_messages = db.query(Message).filter(
        Message.conversation_id == conv.id
    ).order_by(Message.created_at.desc()).limit(8).all()

    contents = []
    for m in reversed(recent_messages):
        contents.append({
            "role": "user" if m.sender == "customer" else "model",
            "parts": [{"text": m.text}]
        })

    user_text_with_meta = user_message
    if evidence_photo:
        user_text_with_meta += f" [Customer just uploaded a photo of the item: {evidence_photo}]"
    contents.append({"role": "user", "parts": [{"text": user_text_with_meta}]})

    try:
        declined_opts = json.loads(conv.declined_options or "[]")
    except Exception:
        declined_opts = []
    try:
        offered_opts = json.loads(conv.options_offered or "[]")
    except Exception:
        offered_opts = []

    # 4. Build prompt & call Gemini
    system_prompt = build_system_prompt(
        customer=customer,
        orders_summary=orders_summary,
        conv=conv,
        active_order_id=active_order_id,
        declined_opts=declined_opts,
        offered_opts=offered_opts,
        refund_limit=refund_limit,
        return_window_days=return_window_days
    )

    llm_output_data = None
    if api_key:
        llm_output_data = call_gemini_fast(api_key, model_name, system_prompt, contents)

    # 5. Smart fallback if API failed or no key
    if not llm_output_data:
        llm_output_data = fallback_agent_logic(user_message, customer_orders, orders_summary, conv, customer)

    try:
        parsed = AgentStructuredOutput(**llm_output_data)
    except Exception:
        parsed = AgentStructuredOutput(
            reply_text=llm_output_data.get("reply_text") or "Let me help you with that — which order is this about?",
            intent=llm_output_data.get("intent") or "GENERAL",
            tool_action="NONE",
            quick_replies=llm_output_data.get("quick_replies") or []
        )

    # 6. Resolve Target Order (from LLM identification -> explicit active_order_id -> conversation memory -> single order)
    target_order = None
    if parsed.identified_order_number:
        target_order = next((o for o in customer_orders if o.order_number == parsed.identified_order_number), None)
    if not target_order and active_order_id:
        target_order = next((o for o in customer_orders if o.id == active_order_id or o.order_number == active_order_id), None)
    if not target_order and conv.current_order_id:
        target_order = next((o for o in customer_orders if o.id == conv.current_order_id), None)
    if not target_order and len(customer_orders) == 1:
        target_order = customer_orders[0]
    if not target_order and customer_orders and parsed.tool_action in ("TRACK", "CANCEL", "SWAP", "CREDIT", "REFUND"):
        target_order = customer_orders[0]

    # 7. Execute Backend Tools (Deterministic Enforcement)
    executed_tools = []
    final_reply = parsed.reply_text
    quick_replies = parsed.quick_replies or []

    if parsed.tool_action == "TRACK" and target_order:
        last_event = db.query(TrackingEvent).filter(
            TrackingEvent.order_id == target_order.id
        ).order_by(TrackingEvent.created_at.desc()).first()
        executed_tools.append({
            "tool": "track_order",
            "status": "SUCCESS",
            "order": target_order.order_number,
            "location": last_event.location if last_event else "Warehouse"
        })
        if target_order.order_number not in final_reply:
            status_text = target_order.status.replace("_", " ").lower()
            loc = last_event.location if last_event else "our fulfillment center"
            final_reply = f"Your order {target_order.order_number} is currently {status_text} at {loc}. {last_event.description if last_event else ''}"

    elif parsed.tool_action == "CANCEL" and target_order:
        cancel_res = cancel_order(db, target_order, parsed.reason or "Customer requested cancellation")
        executed_tools.append({
            "tool": "cancel_order",
            "status": cancel_res["action"],
            "order": target_order.order_number
        })
        final_reply = cancel_res["message"]
        quick_replies = ["Track my other orders", "Browse store"]

    elif parsed.tool_action == "SWAP" and target_order:
        policy_res = check_policy(
            db, target_order, "EXCHANGE",
            target_order.total_amount,
            parsed.reason or "fit",
            evidence_photo
        )
        if policy_res["verdict"] == PolicyVerdict.AUTO_APPROVE:
            new_size = parsed.new_size or "9.5 UK"
            create_exchange(db, target_order, new_size, parsed.reason or "Size swap")
            final_reply = f"All set, {customer.full_name.split()[0]}! I've booked your free doorstep exchange on {target_order.order_number} for Size {new_size}. The courier will bring the new size and pick up the old one together."
            executed_tools.append({"tool": "create_exchange", "status": "CONFIRMED", "new_size": new_size})
            quick_replies = ["Track exchange", "Thanks!"]
        elif policy_res["verdict"] == PolicyVerdict.NEEDS_HUMAN:
            esc = escalate_to_human(
                db, customer, target_order,
                target_order.items[0].product_title if target_order.items else "Item",
                target_order.total_amount,
                parsed.reason or "Exchange requested",
                parsed.urgency or "MEDIUM",
                evidence_photo, user_message,
                policy_res["checks"],
                policy_res["reason"],
                "Recommend approve size exchange."
            )
            executed_tools.append({"tool": "escalate_to_human", "case": esc.case_number})
            final_reply = f"I've forwarded your exchange request for {target_order.order_number} to our team (Case {esc.case_number}) since it needs a quick verification. We'll update you right here soon!"
            quick_replies = ["Got it, thanks"]
        else:
            executed_tools.append({"tool": "check_policy", "status": "DENIED"})
            final_reply = policy_res["reason"]
            quick_replies = ["What are my options?", "Ask support manager"]

    elif parsed.tool_action == "CREDIT" and target_order:
        policy_res = check_policy(
            db, target_order, "STORE_CREDIT",
            target_order.total_amount,
            parsed.reason or "store credit",
            evidence_photo
        )
        if policy_res["verdict"] in (PolicyVerdict.AUTO_APPROVE, PolicyVerdict.NEEDS_HUMAN):
            credit_res = issue_store_credit(db, target_order, target_order.total_amount, bonus_pct=10.0)
            final_reply = f"Done! ₹{credit_res['total_credit']:,.0f} (including a 10% bonus of ₹{credit_res['bonus_amount']:,.0f}) is now in your SellerShield wallet under code {credit_res.get('coupon_code', 'WALLET')}. Ready to use anytime!"
            executed_tools.append({"tool": "issue_store_credit", "amount": credit_res["total_credit"]})
            quick_replies = ["Browse the store", "Thanks!"]
        else:
            executed_tools.append({"tool": "check_policy", "status": "DENIED"})
            final_reply = policy_res["reason"]

    elif parsed.tool_action == "REFUND" and target_order:
        policy_res = check_policy(
            db, target_order, "REFUND",
            target_order.total_amount,
            parsed.reason or "refund requested",
            evidence_photo
        )
        if policy_res["verdict"] == PolicyVerdict.AUTO_APPROVE:
            issue_refund(
                db, target_order, target_order.total_amount,
                parsed.reason or "Return refund",
                PolicyVerdict.AUTO_APPROVE
            )
            final_reply = f"Your refund of ₹{target_order.total_amount:,.0f} for {target_order.order_number} is confirmed and heading back to your original payment method (3-5 business days)."
            executed_tools.append({"tool": "issue_refund", "amount": target_order.total_amount, "status": "DISBURSED"})
            quick_replies = ["Done, thanks!", "Browse store"]
        elif policy_res["verdict"] == PolicyVerdict.NEEDS_HUMAN:
            esc = escalate_to_human(
                db, customer, target_order,
                target_order.items[0].product_title if target_order.items else "Item",
                target_order.total_amount,
                parsed.reason or "Refund requested",
                parsed.urgency or "MEDIUM",
                evidence_photo, user_message,
                policy_res["checks"],
                policy_res["reason"],
                "Review customer refund request."
            )
            executed_tools.append({"tool": "escalate_to_human", "case": esc.case_number})
            final_reply = f"Because order {target_order.order_number} is ₹{target_order.total_amount:,.0f} (above our ₹{int(refund_limit)} instant refund cap), I've opened priority Case {esc.case_number} for our manager to approve — or I can give you instant ₹{int(target_order.total_amount * 1.1)} store credit right now if you'd prefer!"
            quick_replies = ["Wait for manager approval", "Give me 10% bonus store credit instead"]
        else:
            executed_tools.append({"tool": "check_policy", "status": "DENIED"})
            final_reply = policy_res["reason"]
            quick_replies = ["How can I cancel or exchange?"]

    elif parsed.tool_action == "ESCALATE" and target_order:
        esc = escalate_to_human(
            db, customer, target_order,
            target_order.items[0].product_title if target_order.items else "Item",
            target_order.total_amount,
            parsed.reason or "Customer requested support review",
            "HIGH",
            evidence_photo, user_message,
            [],
            "Escalated at customer's request",
            "Please review and assist customer."
        )
        executed_tools.append({"tool": "escalate_to_human", "case": esc.case_number})
        if esc.case_number not in final_reply:
            final_reply = f"I've escalated this to our seller team under Case {esc.case_number}. A specialist will review it and reply right here shortly."

    # 8. Persist messages in DB
    db.add(Message(
        conversation_id=conv.id,
        sender="customer",
        text=user_message,
        photo_url=evidence_photo
    ))
    db.add(Message(
        conversation_id=conv.id,
        sender="agent",
        text=final_reply,
        tool_calls=json.dumps(executed_tools),
        quick_replies=json.dumps(quick_replies)
    ))

    # 9. Update conversation state & track offered/declined options
    if target_order:
        conv.current_order_id = target_order.id
    conv.intent = parsed.intent
    conv.sentiment = parsed.sentiment
    if parsed.reason:
        conv.reason_given = parsed.reason

    lower_msg = user_message.lower()
    lower_rep = final_reply.lower()
    if "store credit" in lower_rep and "STORE_CREDIT" not in offered_opts:
        offered_opts.append("STORE_CREDIT")
    if ("exchange" in lower_rep or "swap" in lower_rep) and "EXCHANGE" not in offered_opts:
        offered_opts.append("EXCHANGE")
    if any(n in lower_msg for n in ["no", "don't want", "dont want", "nahi", "vendam", "just refund", "only refund"]):
        if "STORE_CREDIT" in offered_opts and "STORE_CREDIT" not in declined_opts and "credit" not in lower_msg:
            declined_opts.append("STORE_CREDIT")
        if "EXCHANGE" in offered_opts and "EXCHANGE" not in declined_opts and "exchange" not in lower_msg and "swap" not in lower_msg:
            declined_opts.append("EXCHANGE")

    conv.options_offered = json.dumps(offered_opts)
    conv.declined_options = json.dumps(declined_opts)
    db.commit()

    elapsed_ms = int((time.time() - t_start) * 1000)

    log_audit_event(
        db=db,
        actor="AI_AGENT",
        tool=f"llm_agent.{parsed.tool_action or 'CHAT'}",
        input_payload={"message": user_message[:200], "intent": parsed.intent, "latency_ms": elapsed_ms},
        output_payload={"reply": final_reply[:200], "tools": [t["tool"] for t in executed_tools]},
        verdict="AUTO_APPROVE" if executed_tools else "CHAT_ONLY",
        customer_id=customer.id,
        order_id=target_order.id if target_order else None
    )

    return {
        "reply_text": final_reply,
        "intent": parsed.intent,
        "sentiment": parsed.sentiment,
        "quick_replies": quick_replies,
        "tool_calls": executed_tools,
        "order_number": target_order.order_number if target_order else None,
        "latency_ms": elapsed_ms
    }


def fallback_agent_logic(
    user_message: str,
    orders: List[Order],
    orders_summary: List[dict],
    conv: Conversation,
    customer: User
) -> Dict[str, Any]:
    """Smart typo-tolerant fallback if LLM API is temporarily unreachable."""
    lower = user_message.lower()
    first_name = customer.full_name.split()[0]
    target_ord = orders[0] if orders else None
    target_sum = orders_summary[0] if orders_summary else None

    if not orders:
        return {
            "reply_text": f"Hey {first_name}! I checked your account and don't see any orders yet. Once you place an order in the Store, you can track, swap sizes, cancel, or request refunds right here!",
            "intent": "GENERAL",
            "tool_action": "NONE",
            "quick_replies": ["How do returns work?", "Browse the store"]
        }

    # Guidance questions ("how to cancel", "dont know how refund")
    if any(p in lower for p in ["how to", "how do i", "how can i", "hw to", "dont know", "don't know", "dnt knw", "guide", "steps", "process"]):
        if target_sum and target_sum["status"] in ("PLACED", "PACKED"):
            return {
                "reply_text": f"Super easy, {first_name}! Your order {target_sum['order_number']} hasn't left our warehouse yet, so I can cancel it right here in one click if you tell me 'cancel my order' — or you can check its status in My Orders anytime.",
                "intent": "HOW_TO_GUIDE",
                "tool_action": "NONE",
                "quick_replies": [f"Cancel {target_sum['order_number']}", "Keep my order"]
            }
        elif target_sum and target_sum["status"] in ("SHIPPED", "OUT_FOR_DELIVERY"):
            return {
                "reply_text": f"No worries, {first_name}! Since {target_sum['order_number']} is already on its way, just refuse delivery when the courier arrives (or accept it and tap 'Return / Swap with AI' in My Orders) and your refund starts right away.",
                "intent": "HOW_TO_GUIDE",
                "tool_action": "NONE",
                "quick_replies": ["Track my order", "Got it, thanks!"]
            }
        else:
            return {
                "reply_text": f"It's really simple, {first_name}! You don't have to fill any forms — just tell me right here what went wrong with {target_sum['order_number']} (or tap 'Return / Swap with AI' in My Orders), and I'll arrange a free size swap, +10% store credit, or a refund for you.",
                "intent": "HOW_TO_GUIDE",
                "tool_action": "NONE",
                "quick_replies": ["Swap size", "I want a refund", "Store credit (+10%)"]
            }

    if any(w in lower for w in ["where", "whr", "track", "trak", "status", "staus", "deliver", "arrive", "when", "enga", "kaha"]):
        trk = target_sum.get("latest_tracking") if target_sum else None
        loc_info = f" at {trk['location']}" if trk else ""
        return {
            "reply_text": f"Your order {target_ord.order_number} is currently {target_ord.status.replace('_', ' ').lower()}{loc_info}. {trk['description'] if trk else ''}",
            "intent": "TRACKING",
            "tool_action": "TRACK",
            "identified_order_number": target_ord.order_number,
            "quick_replies": ["How do I cancel?", "Need help with another order"]
        }

    if any(w in lower for w in ["cancel", "cancl", "cncl"]):
        return {
            "reply_text": f"Let me check if we can cancel {target_ord.order_number} right away.",
            "intent": "CANCEL",
            "tool_action": "CANCEL",
            "identified_order_number": target_ord.order_number,
            "quick_replies": []
        }

    if any(w in lower for w in ["swap", "exchange", "size", "tight", "tite", "loose", "fit"]):
        return {
            "reply_text": f"Sorry the fit feels off, {first_name}! We can do a free doorstep size swap on {target_ord.order_number} — what size would fit better?",
            "intent": "EXCHANGE",
            "tool_action": "NONE",
            "identified_order_number": target_ord.order_number,
            "quick_replies": ["Swap to 9.5 UK", "Swap to 10 UK", "Just want a refund"]
        }

    if any(w in lower for w in ["credit", "wallet", "bonus"]):
        return {
            "reply_text": f"I can add ₹{int(target_ord.total_amount * 1.1)} (with a 10% bonus) straight to your store wallet right now!",
            "intent": "REFUND",
            "tool_action": "CREDIT",
            "identified_order_number": target_ord.order_number,
            "quick_replies": []
        }

    if any(w in lower for w in ["refund", "refnd", "return", "retrun", "money back", "wapas"]):
        return {
            "reply_text": f"Got it, {first_name}. Let me check eligibility and process that return for {target_ord.order_number}.",
            "intent": "REFUND",
            "tool_action": "REFUND",
            "identified_order_number": target_ord.order_number,
            "quick_replies": []
        }

    return {
        "reply_text": f"Hey {first_name}! I see your order {target_ord.order_number} ({target_sum['items']}). Tell me if you want to track it, swap a size, cancel, or get a refund!",
        "intent": "GENERAL",
        "tool_action": "NONE",
        "quick_replies": ["Where is my order?", "How do I cancel or refund?", "Size exchange"]
    }
