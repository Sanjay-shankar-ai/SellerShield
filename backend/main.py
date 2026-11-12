import os
import asyncio
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime

from dotenv import load_dotenv

# Load environment variables from backend/.env or root .env
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    load_dotenv()

from fastapi import FastAPI, Depends, HTTPException, status, Query, Response, UploadFile, File
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import func

from .database import engine, Base, get_db
from .models import (
    User, Product, Order, OrderItem, TrackingEvent,
    Conversation, Message, Escalation, AuditLog, Setting, CustomerMemory,
    PromoCode, WalletTransaction, SupportCall
)
from .auth import (
    verify_password, get_password_hash, create_access_token,
    get_current_user, require_admin, require_customer
)
from .order_api import get_customer_orders, get_order_by_id, track_order, is_order_active
from .policy_engine import check_policy, PolicyVerdict, get_setting_value
from .return_api import create_exchange, create_return, list_alternatives
from .refund_api import issue_refund, issue_wallet_credit, issue_promo_code
from .escalation import resolve_escalation
from .audit_log import log_audit_event
from .tracking_scheduler import tracking_scheduler_loop, post_proactive_chat_message
from .langgraph_agent import run_agent_turn, resume_agent_escalation
from .seed import seed_database

# Create DB schema and seed on startup
Base.metadata.create_all(bind=engine)
seed_database()

app = FastAPI(
    title="SellerShield AI — Autonomous E-Commerce Backend",
    description="Production-grade e-commerce backend with SQLite/PostgreSQL architecture, automatic order tracking scheduler, and autonomous AI concierge.",
    version="3.0.0"
)

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2A: Mount static uploads directory for serving customer evidence photos
uploads_dir = Path(__file__).resolve().parent.parent / "static" / "uploads"
uploads_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static/uploads", StaticFiles(directory=str(uploads_dir)), name="uploads")

# Start background tracking scheduler on server startup
@app.on_event("startup")
async def startup_event():
    asyncio.create_task(tracking_scheduler_loop())

@app.get("/api/health")
def health_check():
    has_key = bool(os.environ.get("LLM_API_KEY") or os.environ.get("GEMINI_API_KEY"))
    return {
        "status": "healthy",
        "has_api_key": has_key,
        "active_provider": "gemini-3.5-flash",
        "timestamp": datetime.utcnow().isoformat()
    }

# ============================================================================
# PYDANTIC SCHEMAS
# ============================================================================

class LoginRequest(BaseModel):
    email: str
    password: str

class UserResponse(BaseModel):
    id: str
    email: str
    full_name: str
    phone: Optional[str]
    role: str
    wallet_balance: Optional[float] = 0.0

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse

class CartItemPayload(BaseModel):
    productId: str
    selectedSize: Optional[str] = None
    quantity: int = 1

class PromoValidateRequest(BaseModel):
    code: str

class CheckoutRequest(BaseModel):
    items: List[CartItemPayload]
    shippingAddress: str
    phone: str
    paymentMethod: str = "COD"  # 'COD', 'MOCK_UPI', 'WALLET'
    useWallet: bool = False
    promoCode: Optional[str] = None

class ChatMessageRequest(BaseModel):
    message: str
    orderId: Optional[str] = None
    evidencePhotoUrl: Optional[str] = None
    evidencePhotos: Optional[List[str]] = None
    source: Optional[str] = "text"

class EscalationResolveRequest(BaseModel):
    decision: str  # 'APPROVED' or 'REJECTED'
    adminNotes: str

class ProductUpdateRequest(BaseModel):
    price: Optional[float] = None
    stock_count: Optional[int] = None
    is_returnable: Optional[bool] = None

class SettingUpdateRequest(BaseModel):
    key: str
    value: str

class AdminShipmentUpdateRequest(BaseModel):
    status: str
    location: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    notify_customer: Optional[bool] = True

# ============================================================================
# 1. AUTHENTICATION ENDPOINTS
# ============================================================================

@app.post("/api/auth/login", response_model=TokenResponse)
def login_for_access_token(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == req.email.lower().strip()).first()
    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(data={"sub": user.id, "role": user.role})

    # Log login event
    log_audit_event(
        db=db,
        actor=f"{user.role}:{user.full_name}",
        tool="auth.login",
        input_payload={"email": user.email},
        output_payload={"status": "AUTHENTICATED"},
        verdict="AUTO_APPROVE",
        customer_id=user.id
    )

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user=UserResponse(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            phone=user.phone,
            role=user.role,
            wallet_balance=user.wallet_balance or 0.0
        )
    )

@app.get("/api/auth/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        full_name=current_user.full_name,
        phone=current_user.phone,
        role=current_user.role,
        wallet_balance=current_user.wallet_balance or 0.0
    )

@app.get("/api/wallet")
def get_wallet(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    db.refresh(current_user)
    transactions = db.query(WalletTransaction).filter(
        WalletTransaction.customer_id == current_user.id
    ).order_by(WalletTransaction.created_at.desc()).all()

    # Backfill initial credit transaction if user has balance but 0 transaction records
    if not transactions and (current_user.wallet_balance or 0.0) > 0:
        seed_tx = WalletTransaction(
            customer_id=current_user.id,
            amount=current_user.wallet_balance,
            transaction_type="CREDIT",
            description="Store Wallet Credit (Order Refunds & Cancellations)",
            balance_after=current_user.wallet_balance
        )
        db.add(seed_tx)
        db.commit()
        transactions = [seed_tx]

    return {
        "wallet_balance": current_user.wallet_balance or 0.0,
        "customer_id": current_user.id,
        "currency": "INR",
        "transactions": [
            {
                "id": t.id,
                "amount": t.amount,
                "type": t.transaction_type,
                "description": t.description,
                "balance_after": t.balance_after,
                "order_number": t.order_number,
                "created_at": t.created_at.strftime("%d %b %Y, %I:%M %p")
            }
            for t in transactions
        ]
    }

@app.post("/api/promo/validate")
def validate_promo(
    req: PromoValidateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    code_raw = (req.code or "").strip().upper()
    if not code_raw:
        raise HTTPException(status_code=400, detail="Please enter a promo code")

    # Check promo_codes table
    promo = db.query(PromoCode).filter(
        PromoCode.code == code_raw,
        PromoCode.is_used == False
    ).first()

    if promo:
        if promo.customer_id and promo.customer_id != current_user.id:
            raise HTTPException(status_code=400, detail="This promo code is assigned to another account")
        if promo.expiry and promo.expiry < datetime.utcnow():
            raise HTTPException(status_code=400, detail="This promo code has expired")
        return {
            "valid": True,
            "code": promo.code,
            "discount": promo.value,
            "discount_type": "FLAT",
            "message": f"Promo code {promo.code} applied! ₹{promo.value:,.0f} discount."
        }

    # Universal predefined promo codes
    if code_raw in ("SELLER10", "WELCOME10", "PROMO-EXTRA10"):
        return {
            "valid": True,
            "code": code_raw,
            "discount": 500.0,
            "discount_type": "PERCENT",
            "percent": 10.0,
            "message": f"Coupon {code_raw} applied! 10% discount on order."
        }

    raise HTTPException(status_code=400, detail="Invalid, expired, or already used promo code")

# ============================================================================
# 2. PRODUCTS ENDPOINTS
# ============================================================================

def serialize_product(p: Product) -> dict:
    """Convert SQLAlchemy Product to a clean dict with parsed JSON fields."""
    import json as _json
    sizes = None
    features = None
    try:
        sizes = _json.loads(p.sizes) if p.sizes else None
    except Exception:
        sizes = None
    try:
        features = _json.loads(p.features) if p.features else None
    except Exception:
        features = None
    image_url = p.image
    if not image_url or "example.com" in image_url:
        image_url = "https://images.unsplash.com/photo-1523275335684-37898b6baf30?auto=format&fit=crop&w=600&q=80"

    return {
        "id": p.id,
        "title": p.title,
        "sku": p.sku,
        "category": p.category,
        "description": p.description,
        "price": p.price,
        "original_price": p.original_price,
        "rating": p.rating,
        "review_count": p.review_count,
        "image": image_url,
        "stock_count": p.stock_count,
        "is_returnable": p.is_returnable,
        "sizes": sizes,
        "features": features
    }

@app.get("/api/products")
def list_products(
    category: Optional[str] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db)
):
    query = db.query(Product).filter(~Product.sku.startswith("TEST-"))
    if category and category.lower() != "all":
        query = query.filter(Product.category.ilike(category))
    if search:
        search_filter = f"%{search}%"
        query = query.filter(
            Product.title.ilike(search_filter) |
            Product.description.ilike(search_filter) |
            Product.category.ilike(search_filter) |
            Product.sku.ilike(search_filter)
        )
    products = query.all()
    return [serialize_product(p) for p in products]

@app.get("/api/products/{product_id}")
def get_single_product(product_id: str, db: Session = Depends(get_db)):
    prod = db.query(Product).filter((Product.id == product_id) | (Product.sku == product_id)).first()
    if not prod:
        raise HTTPException(status_code=404, detail="Product not found")
    return serialize_product(prod)

@app.patch("/api/products/{product_id}")
def update_product_admin(
    product_id: str,
    update: ProductUpdateRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin)
):
    prod = db.query(Product).filter(Product.id == product_id).first()
    if not prod:
        raise HTTPException(status_code=404, detail="Product not found")

    if update.price is not None:
        prod.price = update.price
    if update.stock_count is not None:
        prod.stock_count = update.stock_count
    if update.is_returnable is not None:
        prod.is_returnable = update.is_returnable

    db.commit()
    db.refresh(prod)

    log_audit_event(
        db=db,
        actor=f"ADMIN:{admin.full_name}",
        tool="products.update",
        input_payload={"product_id": product_id, "update": update.dict(exclude_none=True)},
        output_payload={"status": "UPDATED"},
        verdict="APPROVED"
    )
    return prod

# ============================================================================
# 3. ORDERS & AUTOMATIC TRACKING
# ============================================================================

@app.post("/api/orders")
def place_order(
    req: CheckoutRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if not req.items:
        raise HTTPException(status_code=400, detail="Cart is empty")

    total_amount = 0.0
    items_to_create = []

    for item in req.items:
        prod = db.query(Product).filter(Product.id == item.productId).first()
        if not prod:
            raise HTTPException(status_code=404, detail=f"Product {item.productId} not found")
        if prod.stock_count < item.quantity:
            raise HTTPException(status_code=400, detail=f"Insufficient stock for {prod.title}")

        subtotal = prod.price * item.quantity
        total_amount += subtotal

        # Decrement stock
        prod.stock_count -= item.quantity

        items_to_create.append({
            "product": prod,
            "size": item.selectedSize,
            "quantity": item.quantity,
            "unit_price": prod.price,
            "subtotal": subtotal
        })

    items_subtotal = round(total_amount, 2)
    discount_amount = 0.0
    used_promo = None

    if req.promoCode:
        clean_code = req.promoCode.strip().upper()
        promo = db.query(PromoCode).filter(PromoCode.code == clean_code, PromoCode.is_used == False).first()
        if promo:
            if not promo.customer_id or promo.customer_id == current_user.id:
                discount_amount = min(items_subtotal, promo.value)
                used_promo = promo
        elif clean_code in ("SELLER10", "WELCOME10", "PROMO-EXTRA10"):
            discount_amount = round(items_subtotal * 0.10, 2)

    amount_after_promo = max(0.0, round(items_subtotal - discount_amount, 2))
    wallet_deduction = 0.0

    if req.useWallet or req.paymentMethod == "WALLET":
        avail = current_user.wallet_balance or 0.0
        wallet_deduction = min(avail, amount_after_promo)
        if wallet_deduction > 0:
            current_user.wallet_balance = round(avail - wallet_deduction, 2)

    if used_promo:
        used_promo.is_used = True

    final_payable = max(0.0, round(amount_after_promo - wallet_deduction, 2))
    chosen_method = "WALLET" if (final_payable == 0 and wallet_deduction > 0) else req.paymentMethod

    order_num = f"ORD-{int(datetime.utcnow().timestamp()) % 100000}"

    new_order = Order(
        order_number=order_num,
        customer_id=current_user.id,
        customer_name=current_user.full_name,
        customer_email=current_user.email,
        customer_phone=req.phone or current_user.phone or "+91 98450 12891",
        shipping_address=req.shippingAddress,
        payment_method=chosen_method,
        total_amount=amount_after_promo,
        status="PLACED",
        created_at=datetime.utcnow()
    )
    db.add(new_order)
    db.commit()
    db.refresh(new_order)

    # Record wallet debit transaction if wallet balance was spent
    if wallet_deduction > 0:
        wallet_tx = WalletTransaction(
            customer_id=current_user.id,
            order_id=new_order.id,
            order_number=order_num,
            amount=wallet_deduction,
            transaction_type="DEBIT",
            description=f"Used on order {order_num}",
            balance_after=current_user.wallet_balance
        )
        db.add(wallet_tx)
        db.commit()

    # Insert items
    for it in items_to_create:
        order_item = OrderItem(
            order_id=new_order.id,
            product_id=it["product"].id,
            product_title=it["product"].title,
            product_sku=it["product"].sku,
            selected_size=it["size"],
            quantity=it["quantity"],
            unit_price=it["unit_price"],
            subtotal=it["subtotal"]
        )
        db.add(order_item)

    # Insert initial PLACED tracking event
    pay_notes = []
    if wallet_deduction > 0:
        pay_notes.append(f"₹{wallet_deduction:,.0f} paid from Wallet")
    if discount_amount > 0:
        pay_notes.append(f"₹{discount_amount:,.0f} promo discount applied ({req.promoCode})")
    if final_payable > 0:
        pay_notes.append(f"₹{final_payable:,.0f} payable via {chosen_method}")
    note_str = f" ({', '.join(pay_notes)})" if pay_notes else ""

    initial_event = TrackingEvent(
        order_id=new_order.id,
        status="PLACED",
        title="Order Received & Confirmed",
        location="Fulfillment Logistics Network",
        description=f"Order placed with {chosen_method}{note_str}. Scheduled for warehouse packing."
    )
    db.add(initial_event)
    db.commit()

    log_audit_event(
        db=db,
        actor=f"CUSTOMER:{current_user.full_name}",
        tool="checkout.create_order",
        input_payload={
            "order_number": order_num,
            "subtotal": items_subtotal,
            "discount_amount": discount_amount,
            "wallet_deduction": wallet_deduction,
            "final_payable": final_payable,
            "items_count": len(req.items)
        },
        output_payload={"status": "PLACED", "order_id": new_order.id},
        verdict="AUTO_APPROVE",
        customer_id=current_user.id,
        order_id=new_order.id,
        idempotency_key=f"order-{new_order.id}"
    )

    return {
        "success": True,
        "id": new_order.id,
        "order_number": new_order.order_number,
        "total_amount": new_order.total_amount,
        "subtotal": items_subtotal,
        "wallet_deduction": wallet_deduction,
        "discount_amount": discount_amount,
        "wallet_balance": current_user.wallet_balance,
        "status": new_order.status
    }

@app.get("/api/orders")
def get_orders_list(
    tab: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role == "ADMIN":
        orders = db.query(Order).order_by(Order.created_at.desc()).all()
    else:
        orders = db.query(Order).filter(Order.customer_id == current_user.id).order_by(Order.created_at.desc()).all()

    results = []
    return_window_days = get_setting_value(db, "return_window_days", 7)
    now = datetime.utcnow()

    for o in orders:
        items_summary = [
            {
                "product_title": it.product_title,
                "product_sku": it.product_sku,
                "selected_size": it.selected_size,
                "quantity": it.quantity,
                "unit_price": it.unit_price,
                "subtotal": it.subtotal
            }
            for it in o.items
        ]

        active = is_order_active(o, return_window_days)

        # Tab filtering (A1 requirement: default to active orders)
        if tab == "past" and active:
            continue
        elif tab == "active" and not active:
            continue
        elif not tab and not active and current_user.role != "ADMIN":
            continue

        # Calculate return eligibility
        is_eligible = False
        if o.status == "DELIVERED":
            delivered_date = o.delivered_at or o.created_at
            days_elapsed = (now - delivered_date).days
            all_returnable = all(
                (it.product.is_returnable if it.product else True)
                for it in o.items
            )
            is_eligible = (days_elapsed <= return_window_days) and all_returnable

        results.append({
            "id": o.id,
            "order_number": o.order_number,
            "customer_name": o.customer_name,
            "customer_email": o.customer_email,
            "customer_phone": o.customer_phone,
            "shipping_address": o.shipping_address,
            "payment_method": o.payment_method,
            "total_amount": o.total_amount,
            "status": o.status,
            "return_reason": o.return_reason,
            "is_active": active,
            "is_eligible_return": is_eligible,
            "delivered_at": o.delivered_at.isoformat() if o.delivered_at else None,
            "created_at": o.created_at.strftime("%b %d, %Y %I:%M %p"),
            "items": items_summary
        })

    return results

@app.get("/api/orders/{order_id}/tracking")
def get_order_tracking(
    order_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return track_order(db, order_id, current_user)

# ============================================================================
# 4. AI AGENT CHAT (HUMAN-QUALITY CONVERSATION)
# ============================================================================

@app.post("/api/chat")
async def chat_with_agent(
    req: ChatMessageRequest,
    stream: Optional[bool] = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    import json as _json
    from fastapi.concurrency import run_in_threadpool

    # Enforce security: always bound to the authenticated user ID
    # 1H: run_agent_turn is blocking; run in threadpool so scheduler & other requests aren't blocked
    response = await run_in_threadpool(
        run_agent_turn,
        db=db,
        customer=current_user,
        user_message=req.message,
        active_order_id=req.orderId,
        evidence_photo=req.evidencePhotoUrl,
        evidence_photos=req.evidencePhotos,
        source=req.source or "text"
    )

    db.refresh(current_user)
    response["wallet_balance"] = current_user.wallet_balance or 0.0

    if stream:
        async def stream_generator():
            full_text = response.get("reply_text", "")
            words = full_text.split(" ")
            for i in range(0, len(words), 3):
                delta = " ".join(words[i:i+3]) + " "
                yield f"data: {_json.dumps({'delta': delta, 'done': False})}\n\n"
                await asyncio.sleep(0.03)
            final_data = {
                "done": True,
                "reply_text": full_text,
                "quick_replies": response.get("quick_replies", []),
                "tool_calls": response.get("tool_calls", []),
                "intent": response.get("intent"),
                "order_number": response.get("order_number"),
                "architecture": response.get("architecture")
            }
            yield f"data: {_json.dumps(final_data)}\n\n"

        return StreamingResponse(stream_generator(), media_type="text/event-stream")

    return response

@app.post("/api/chat/stream")
async def chat_stream_endpoint(
    req: ChatMessageRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return await chat_with_agent(req, stream=True, db=db, current_user=current_user)

@app.get("/api/chat/history")
def get_chat_history(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    import json as _json
    conv = db.query(Conversation).filter(Conversation.customer_id == current_user.id).order_by(Conversation.updated_at.desc()).first()
    if not conv:
        return {"messages": []}

    msgs = db.query(Message).filter(Message.conversation_id == conv.id).order_by(Message.created_at.asc()).all()
    results = []
    for m in msgs:
        try:
            qrs = _json.loads(m.quick_replies) if m.quick_replies else []
        except Exception:
            qrs = []
        try:
            tcs = _json.loads(m.tool_calls) if m.tool_calls else []
        except Exception:
            tcs = []
        results.append({
            "id": m.id,
            "sender": m.sender,
            "text": m.text,
            "photo_url": m.photo_url,
            "quick_replies": qrs,
            "tool_calls": tcs,
            "timestamp": m.created_at.strftime("%I:%M %p")
        })
    return {"messages": results}

@app.post("/api/chat/clear")
def clear_chat_history(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    new_conv = Conversation(customer_id=current_user.id, options_offered="[]", declined_options="[]")
    db.add(new_conv)
    db.commit()
    return {"success": True}

@app.post("/api/chat/upload-evidence")
async def upload_evidence_endpoint(
    files: List[UploadFile] = File(...),
    order_id: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    2A: Multi-photo upload handling (up to 4 photos, <=5MB each, JPEG/PNG/WebP).
    Validates, strips EXIF, downscales <=1280px, stores under order directory, and returns file URLs.
    """
    from .image_evidence import validate_and_process_image
    order = db.query(Order).filter(Order.id == order_id).first() if order_id else None
    ord_num = order.order_number if order else "general"

    uploaded_urls = []
    for file in files[:4]:
        content = await file.read()
        try:
            res = validate_and_process_image(content, order_number=ord_num)
            uploaded_urls.append(res["file_url"])
        except ValueError as ve:
            raise HTTPException(status_code=400, detail=str(ve))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to process image: {str(e)}")

    if not uploaded_urls:
        raise HTTPException(status_code=400, detail="No valid images uploaded.")

    return {
        "file_urls": uploaded_urls,
        "evidence_photo": uploaded_urls[0]
    }

@app.post("/api/customer/memory/clear")
def clear_customer_memory(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Customer self-serve privacy feature: wipe own long-term customer memory."""
    mem = db.query(CustomerMemory).filter(CustomerMemory.customer_id == current_user.id).first()
    if mem:
        db.delete(mem)
        db.commit()
    return {"success": True, "message": "Customer memory wiped successfully"}

@app.get("/api/customer/memory")
def get_my_customer_memory(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get customer's own long-term memory facts."""
    mem = db.query(CustomerMemory).filter(CustomerMemory.customer_id == current_user.id).first()
    if not mem:
        return {"customer_memory": {}}
    past_issues = []
    if mem.past_issues:
        try:
            import json
            past_issues = json.loads(mem.past_issues)
        except Exception:
            past_issues = [mem.past_issues]
    return {
        "customer_memory": {
            "customer_id": mem.customer_id,
            "preferred_language": mem.preferred_language,
            "usual_size": mem.usual_size,
            "tone_preference": mem.tone_preference,
            "past_issues": past_issues,
            "updated_at": mem.updated_at.isoformat() if mem.updated_at else None
        }
    }

# ============================================================================
# 5. ADMIN SALES DASHBOARD & CONTROLS
# ============================================================================

@app.get("/api/admin/dashboard")
def get_admin_dashboard(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin)
):
    orders = db.query(Order).all()
    total_revenue = sum(o.total_amount for o in orders)
    total_orders = len(orders)
    avg_order_value = round(total_revenue / max(1, total_orders), 2)

    escalations = db.query(Escalation).filter(Escalation.status == "PENDING").count()
    auto_resolved_count = db.query(AuditLog).filter(AuditLog.verdict == "AUTO_APPROVE").count()
    total_ai_cases = max(1, auto_resolved_count + escalations)
    auto_resolved_pct = round((auto_resolved_count / total_ai_cases) * 100, 1)

    refunds_issued = sum(o.total_amount for o in orders if o.status == "REFUNDED")
    refund_limit = get_setting_value(db, "refund_limit", 2000.0)

    # Categories breakdown
    categories_raw = db.query(Product.category, func.count(OrderItem.id)).join(OrderItem, OrderItem.product_id == Product.id).group_by(Product.category).all()
    category_breakdown = [{"category": cat, "orders_count": cnt} for cat, cnt in categories_raw]

    # Recent sales timeline
    sales_trends = [
        {"date": "Nov 06", "revenue": 34200, "orders": 11},
        {"date": "Nov 07", "revenue": 28900, "orders": 9},
        {"date": "Nov 08", "revenue": 45100, "orders": 14},
        {"date": "Nov 09", "revenue": 38400, "orders": 12},
        {"date": "Nov 10", "revenue": 52600, "orders": 18},
        {"date": "Nov 11", "revenue": total_revenue, "orders": total_orders}
    ]

    return {
        "kpis": {
            "totalRevenue": total_revenue,
            "totalOrders": total_orders,
            "avgOrderValue": avg_order_value,
            "autoResolvedPct": auto_resolved_pct,
            "refundsIssued": refunds_issued,
            "refundLimit": refund_limit,
            "openEscalations": escalations
        },
        "salesTrends": sales_trends,
        "categoryBreakdown": category_breakdown
    }

@app.get("/api/admin/escalations")
def get_escalations(
    status_filter: Optional[str] = None,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin)
):
    query = db.query(Escalation).order_by(Escalation.created_at.desc())
    if status_filter and status_filter.upper() != "ALL":
        query = query.filter(Escalation.status == status_filter.upper())
    
    results = []
    for esc in query.all():
        results.append({
            "id": esc.id,
            "case_number": esc.case_number,
            "customer_id": esc.customer_id,
            "customer_name": esc.customer_name,
            "order_id": esc.order_id,
            "order_number": esc.order_number,
            "product_title": esc.product_title,
            "amount": esc.amount,
            "reason": esc.reason,
            "urgency": esc.urgency,
            "evidence_photo": esc.evidence_photo,
            "evidence_photos": esc.evidence_photos,
            "vision_analysis": esc.vision_analysis,
            "fraud_flags": esc.fraud_flags,
            "chat_summary": esc.chat_summary,
            "checks_done": esc.checks_done,
            "escalation_reason": esc.escalation_reason,
            "agent_recommendation": esc.agent_recommendation,
            "status": esc.status,
            "admin_notes": esc.admin_notes,
            "created_at": esc.created_at.isoformat() if esc.created_at else None,
            "resolved_at": esc.resolved_at.isoformat() if esc.resolved_at else None
        })
    return results

@app.post("/api/admin/escalations/{escalation_id}/resolve")
def resolve_escalation_endpoint(
    escalation_id: str,
    req: EscalationResolveRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin)
):
    res = resolve_escalation(db, escalation_id, req.decision.upper(), req.adminNotes, admin)
    return {"success": True, "escalation_id": res.id, "status": res.status}

@app.post("/api/admin/escalations/{escalation_id}/decision")
def admin_escalation_decision(
    escalation_id: str,
    req: EscalationResolveRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin)
):
    """Resume a paused LangGraph workflow that called interrupt() waiting for admin decision."""
    esc = db.query(Escalation).filter(Escalation.id == escalation_id).first()
    if not esc:
        raise HTTPException(status_code=404, detail="Escalation case not found")

    decision = req.decision.upper()
    esc.status = decision
    esc.admin_notes = req.adminNotes
    esc.resolved_at = datetime.utcnow()

    conv = db.query(Conversation).filter(
        Conversation.customer_id == esc.customer_id
    ).order_by(Conversation.updated_at.desc()).first()

    resumed_result = None
    if conv:
        try:
            resumed_result = resume_agent_escalation(
                db=db,
                conv_id=conv.id,
                decision=decision,
                notes=req.adminNotes
            )
        except Exception as e:
            print(f"[Resume graph error]: {e}")

    order = db.query(Order).filter(Order.id == esc.order_id).first()
    if order:
        if decision == "APPROVED":
            if order.status not in ("REFUNDED", "EXCHANGED"):
                order.status = "REFUNDED"
                order.return_reason = f"Approved by admin: {req.adminNotes}"
        elif decision == "REJECTED":
            order.return_reason = f"Claim rejected by admin: {req.adminNotes}"

    if conv:
        msg_text = f"Update on Case {esc.case_number}: Our team has reviewed your request and {decision.lower()} it. Notes: {req.adminNotes}"
        db.add(Message(conversation_id=conv.id, sender="agent", text=msg_text))

    db.commit()

    log_audit_event(
        db=db,
        actor=f"ADMIN:{admin.full_name}",
        tool="escalation.decision",
        input_payload={"escalation_id": escalation_id, "decision": decision},
        output_payload={"status": decision, "resumed": bool(resumed_result)},
        verdict="APPROVED" if decision == "APPROVED" else "DENIED",
        customer_id=esc.customer_id,
        order_id=esc.order_id
    )

    return {
        "success": True,
        "escalation_id": escalation_id,
        "case_number": esc.case_number,
        "status": decision,
        "resumed_result": resumed_result
    }

@app.get("/api/admin/audit-logs")
def get_audit_logs(
    tool: Optional[str] = None,
    verdict: Optional[str] = None,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin)
):
    query = db.query(AuditLog).order_by(AuditLog.timestamp.desc())
    if tool:
        query = query.filter(AuditLog.tool.ilike(f"%{tool}%"))
    if verdict and verdict.upper() != "ALL":
        query = query.filter(AuditLog.verdict == verdict.upper())
    return query.limit(100).all()

@app.get("/api/admin/audit-logs/export-csv")
def export_audit_logs_csv(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin)
):
    logs = db.query(AuditLog).order_by(AuditLog.timestamp.desc()).all()
    headers = ["ID", "Timestamp", "Actor", "Tool", "Verdict", "Status", "Order_ID", "Customer_ID", "Idempotency_Key"]
    rows = [
        [
            l.id,
            l.timestamp.isoformat(),
            l.actor,
            l.tool,
            l.verdict or "",
            l.status,
            l.order_id or "",
            l.customer_id or "",
            l.idempotency_key or ""
        ]
        for l in logs
    ]
    csv_content = [",".join(headers), *[",".join([str(c).replace(",", " ") for c in r]) for r in rows]]
    return Response(content="\n".join(csv_content), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=sellershield_audit_log.csv"})

@app.get("/api/admin/settings")
def get_settings(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    return db.query(Setting).all()

@app.patch("/api/admin/settings")
def update_setting(
    req: SettingUpdateRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin)
):
    s = db.query(Setting).filter(Setting.key == req.key).first()
    if not s:
        s = Setting(key=req.key, value=req.value)
        db.add(s)
    else:
        s.value = req.value
    db.commit()
    db.refresh(s)

    log_audit_event(
        db=db,
        actor=f"ADMIN:{admin.full_name}",
        tool="settings.update",
        input_payload={"key": req.key, "value": req.value},
        output_payload={"status": "UPDATED"},
        verdict="APPROVED"
    )
    return s

@app.get("/api/admin/customer-memory")
def get_admin_customer_memory(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin)
):
    """Admin inspection endpoint: list all customer memory records."""
    import json
    memories = db.query(CustomerMemory).all()
    results = []
    for m in memories:
        user = db.query(User).filter(User.id == m.customer_id).first()
        past_issues = []
        if m.past_issues:
            try:
                past_issues = json.loads(m.past_issues)
            except Exception:
                past_issues = [m.past_issues]
        results.append({
            "id": m.id,
            "customer_id": m.customer_id,
            "customer_name": user.full_name if user else "Unknown",
            "customer_email": user.email if user else "Unknown",
            "preferred_language": m.preferred_language,
            "usual_size": m.usual_size,
            "tone_preference": m.tone_preference,
            "past_issues": past_issues,
            "created_at": m.created_at.isoformat() if m.created_at else None,
            "updated_at": m.updated_at.isoformat() if m.updated_at else None
        })
    return {"memories": results}

STAGE_SHIPMENT_DEFAULTS = {
    "PLACED": {
        "title": "Order Placed & Confirmed",
        "location": "Fulfillment Logistics Network",
        "description": "Order confirmed and queued for fulfillment."
    },
    "PACKED": {
        "title": "Order Packed & Sealed",
        "location": "Central Fulfillment Hub, Whitefield",
        "description": "Items verified, barcoded, and sealed with tamper-proof security tape."
    },
    "SHIPPED": {
        "title": "Dispatched on Linehaul Transit",
        "location": "Bengaluru South Distribution Hub",
        "description": "Package dispatched via Delhivery Express Air Cargo linehaul route."
    },
    "OUT_FOR_DELIVERY": {
        "title": "Out for Doorstep Delivery",
        "location": "Local Delivery Hub, Sector 4",
        "description": "Courier executive Ramesh (+91 98451 22100) is out for doorstep delivery."
    },
    "DELIVERED": {
        "title": "Delivered Successfully",
        "location": "Customer Doorstep Address",
        "description": "Delivered to recipient. 7-day return and doorstep size swap window is now active!"
    }
}

@app.post("/api/admin/orders/{order_id}/shipment")
def update_order_shipment_admin(
    order_id: str,
    req: AdminShipmentUpdateRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin)
):
    """Admin manual shipment entry/advancement: updates stage, logs TrackingEvent, notifies customer."""
    order = db.query(Order).filter((Order.id == order_id) | (Order.order_number == order_id)).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    target_status = req.status.upper().strip()
    valid_statuses = ["PLACED", "PACKED", "SHIPPED", "OUT_FOR_DELIVERY", "DELIVERED", "CANCELLED", "REFUNDED", "EXCHANGED"]
    if target_status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid status '{target_status}'. Must be one of {valid_statuses}")

    defaults = STAGE_SHIPMENT_DEFAULTS.get(target_status, {})
    title = req.title or defaults.get("title", f"Order {target_status}")
    location = req.location or defaults.get("location", "Supply Chain Hub")
    description = req.description or defaults.get("description", f"Shipment status updated to {target_status}.")

    now = datetime.utcnow()
    prev_status = order.status
    order.status = target_status
    order.stage_entered_at = now
    if target_status == "DELIVERED":
        order.delivered_at = now

    event = TrackingEvent(
        order_id=order.id,
        status=target_status,
        title=title,
        location=location,
        description=description,
        created_at=now
    )
    db.add(event)

    if req.notify_customer and order.customer_id:
        try:
            post_proactive_chat_message(
                db=db,
                customer_id=order.customer_id,
                text=f"📦 Shipment Update ({order.order_number}): {title} — {location}. {description}",
                order_id=order.id,
                action_tag="admin_manual_shipment_update"
            )
        except Exception as e:
            print(f"[Proactive Chat Error]: {e}")

    log_audit_event(
        db=db,
        actor=f"ADMIN:{admin.full_name}",
        tool="admin.update_shipment",
        input_payload={
            "order_number": order.order_number,
            "from_status": prev_status,
            "to_status": target_status,
            "location": location
        },
        output_payload={"status": target_status, "title": title, "location": location},
        verdict="APPROVED",
        customer_id=order.customer_id,
        order_id=order.id
    )

    db.commit()
    db.refresh(order)

    # Return updated tracking payload
    events = db.query(TrackingEvent).filter(TrackingEvent.order_id == order.id).order_by(TrackingEvent.created_at.desc()).all()
    return {
        "success": True,
        "order": {
            "id": order.id,
            "order_number": order.order_number,
            "status": order.status,
            "delivered_at": order.delivered_at.isoformat() if order.delivered_at else None
        },
        "event": {
            "id": event.id,
            "status": event.status,
            "title": event.title,
            "location": event.location,
            "description": event.description,
            "timestamp": event.created_at.strftime("%b %d, %I:%M %p")
        },
        "all_events_count": len(events)
    }


# ============================================================================
# ELECTRONIC GADGET TECHNICAL SUPPORT CALL APIS
# ============================================================================

class ScheduleSupportCallRequest(BaseModel):
    order_id: Optional[str] = None
    product_title: Optional[str] = None
    phone: Optional[str] = None
    notes: Optional[str] = None

@app.post("/api/support/schedule-call")
def schedule_support_call(
    req: ScheduleSupportCallRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    phone = req.phone or current_user.phone or "+91 98450 12891"
    order = None
    if req.order_id:
        order = db.query(Order).filter(Order.id == req.order_id).first()
    call = SupportCall(
        customer_id=current_user.id,
        order_id=order.id if order else None,
        order_number=order.order_number if order else None,
        product_title=req.product_title or (order.items[0].product_title if order and order.items else "Electronic Gadget"),
        customer_phone=phone,
        status="SCHEDULED",
        notes=req.notes or "Scheduled technical callback"
    )
    db.add(call)
    db.commit()
    db.refresh(call)
    return {
        "status": "success",
        "call_id": call.id,
        "phone": call.customer_phone,
        "product_title": call.product_title,
        "call_status": call.status
    }

class CallOutcomeRequest(BaseModel):
    call_id: Optional[str] = None
    outcome: str  # "COMPLETED" or "DECLINED"
    notes: Optional[str] = None

@app.post("/api/support/call-outcome")
def update_support_call_outcome(
    req: CallOutcomeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    call = None
    if req.call_id:
        call = db.query(SupportCall).filter(SupportCall.id == req.call_id).first()
    if not call:
        call = db.query(SupportCall).filter(SupportCall.customer_id == current_user.id).order_by(SupportCall.created_at.desc()).first()
    if not call:
        raise HTTPException(status_code=404, detail="No support call record found")

    outcome_upper = req.outcome.upper()
    call.status = outcome_upper
    if outcome_upper == "COMPLETED":
        call.completed_at = datetime.datetime.utcnow()
    if req.notes:
        call.notes = req.notes
    db.commit()
    db.refresh(call)
    return {
        "status": "success",
        "call_id": call.id,
        "call_status": call.status,
        "completed_at": call.completed_at.isoformat() if call.completed_at else None
    }

@app.get("/api/support/latest-call")
def get_latest_support_call(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    call = db.query(SupportCall).filter(SupportCall.customer_id == current_user.id).order_by(SupportCall.created_at.desc()).first()
    if not call:
        return {"call": None}
    return {
        "call": {
            "id": call.id,
            "order_id": call.order_id,
            "order_number": call.order_number,
            "product_title": call.product_title,
            "customer_phone": call.customer_phone,
            "status": call.status,
            "resolution_action": call.resolution_action,
            "created_at": call.created_at.isoformat() if call.created_at else None,
            "completed_at": call.completed_at.isoformat() if call.completed_at else None
        }
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("backend.main:app", host="0.0.0.0", port=port, reload=True)
