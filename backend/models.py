import datetime
import uuid
from sqlalchemy import (
    Column,
    String,
    Integer,
    Float,
    Boolean,
    DateTime,
    Text,
    ForeignKey,
    Enum as SQLEnum
)
from sqlalchemy.orm import relationship
from .database import Base

def generate_uuid():
    return str(uuid.uuid4())

class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    email = Column(String(120), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(100), nullable=False)
    phone = Column(String(30), nullable=True)
    role = Column(String(20), default="CUSTOMER", nullable=False)  # 'ADMIN' or 'CUSTOMER'
    wallet_balance = Column(Float, default=0.0, nullable=False)  # Customer store wallet balance
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    trust_score = Column(Float, default=75.0, nullable=False)
    trust_tier = Column(String(20), default="NORMAL", nullable=False)  # 'HIGH', 'NORMAL', 'RISKY'
    store_name = Column(String(120), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    orders = relationship("Order", back_populates="customer", cascade="all, delete-orphan")
    conversations = relationship("Conversation", back_populates="customer", cascade="all, delete-orphan")
    customer_memory = relationship("CustomerMemory", back_populates="customer", uselist=False, cascade="all, delete-orphan")
    subscription = relationship("Subscription", back_populates="admin", uselist=False, cascade="all, delete-orphan")

class Product(Base):
    __tablename__ = "products"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    title = Column(String(200), nullable=False, index=True)
    sku = Column(String(60), unique=True, index=True, nullable=False)
    category = Column(String(60), index=True, nullable=False)
    description = Column(Text, nullable=False)
    price = Column(Float, nullable=False)
    original_price = Column(Float, nullable=True)
    rating = Column(Float, default=4.8)
    review_count = Column(Integer, default=120)
    image = Column(String(500), nullable=False)
    stock_count = Column(Integer, default=50, nullable=False)
    is_returnable = Column(Boolean, default=True, nullable=False)  # False for hygiene items!
    is_active = Column(Boolean, default=True, nullable=False)
    resale_value_open_box = Column(Float, default=0.0, nullable=False)
    refurbish_cost = Column(Float, default=0.0, nullable=False)
    parts_value = Column(Float, default=0.0, nullable=False)
    scrap_value = Column(Float, default=0.0, nullable=False)
    sizes = Column(Text, nullable=True)  # JSON list string e.g. '["8 UK", "9 UK", "10 UK"]'
    features = Column(Text, nullable=True)  # JSON list string
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class Order(Base):
    __tablename__ = "orders"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    order_number = Column(String(40), unique=True, index=True, nullable=False)
    customer_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    customer_name = Column(String(100), nullable=False)
    customer_email = Column(String(120), nullable=False)
    customer_phone = Column(String(30), nullable=False)
    shipping_address = Column(Text, nullable=False)
    payment_method = Column(String(40), default="COD")  # 'COD' or 'MOCK_UPI'
    total_amount = Column(Float, nullable=False)
    delivery_fee = Column(Float, default=0.0, nullable=False)
    gift_wrap_fee = Column(Float, default=0.0, nullable=False)
    status = Column(
        String(40),
        default="PLACED",
        index=True,
        nullable=False
    )  # PLACED, PACKED, SHIPPED, OUT_FOR_DELIVERY, DELIVERED, RETURN_REQUESTED, EXCHANGED, REFUNDED
    return_reason = Column(String(255), nullable=True)
    reason_category = Column(String(50), nullable=True)  # DEFECTIVE, DAMAGED, WRONG_ITEM, SIZE_FIT, NOT_AS_DESCRIBED, CHANGED_MIND, OTHER
    evidence_status = Column(String(30), default="NONE", nullable=False)  # NONE, PENDING, VERIFIED, UNCLEAR, MISMATCH
    evidence_photos = Column(Text, nullable=True)  # JSON array of URLs / file paths
    vision_analysis = Column(Text, nullable=True)  # JSON object
    refund_destination = Column(String(30), nullable=True)  # WALLET, PROMO, ORIGINAL
    stage_entered_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    expected_delivery_at = Column(DateTime, nullable=True)
    delay_notified = Column(Boolean, default=False, nullable=False)
    early_notified = Column(Boolean, default=False, nullable=False)
    delivered_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    customer = relationship("User", back_populates="orders")
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")
    tracking_events = relationship("TrackingEvent", back_populates="order", order_by="TrackingEvent.created_at", cascade="all, delete-orphan")

class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    order_id = Column(String(36), ForeignKey("orders.id"), nullable=False, index=True)
    product_id = Column(String(36), ForeignKey("products.id"), nullable=False)
    product_title = Column(String(200), nullable=False)
    product_sku = Column(String(60), nullable=False)
    selected_size = Column(String(30), nullable=True)
    batch_id = Column(String(40), default="BATCH-001", nullable=False)
    quantity = Column(Integer, default=1, nullable=False)
    unit_price = Column(Float, nullable=False)
    subtotal = Column(Float, nullable=False)

    order = relationship("Order", back_populates="items")
    product = relationship("Product")

class TrackingEvent(Base):
    __tablename__ = "tracking_events"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    order_id = Column(String(36), ForeignKey("orders.id"), nullable=False, index=True)
    status = Column(String(40), nullable=False)
    title = Column(String(120), nullable=False)
    location = Column(String(150), nullable=False)
    description = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)

    order = relationship("Order", back_populates="tracking_events")

class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    customer_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    current_order_id = Column(String(36), ForeignKey("orders.id"), nullable=True)
    intent = Column(String(80), nullable=True)  # 'RETURN', 'EXCHANGE', 'TRACKING', 'GENERAL'
    sentiment = Column(String(40), default="NEUTRAL")  # 'CALM', 'FRUSTRATED', 'HAPPY'
    reason_given = Column(String(255), nullable=True)
    options_offered = Column(Text, default="[]")  # JSON array
    declined_options = Column(Text, default="[]")  # JSON array
    pending_action = Column(String(80), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    customer = relationship("User", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", order_by="Message.created_at", cascade="all, delete-orphan")

class Message(Base):
    __tablename__ = "messages"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    conversation_id = Column(String(36), ForeignKey("conversations.id"), nullable=False, index=True)
    sender = Column(String(20), nullable=False)  # 'customer', 'agent', 'system'
    text = Column(Text, nullable=False)
    tool_calls = Column(Text, nullable=True)  # JSON array
    quick_replies = Column(Text, nullable=True)  # JSON array
    photo_url = Column(String(500), nullable=True)
    source = Column(String(20), default="text")
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)

    conversation = relationship("Conversation", back_populates="messages")

class Escalation(Base):
    __tablename__ = "escalations"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    case_number = Column(String(40), unique=True, index=True, nullable=False)
    customer_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    customer_name = Column(String(100), nullable=False)
    order_id = Column(String(36), ForeignKey("orders.id"), nullable=False, index=True)
    order_number = Column(String(40), nullable=False)
    product_title = Column(String(200), nullable=False)
    amount = Column(Float, nullable=False)
    reason = Column(String(255), nullable=False)
    urgency = Column(String(20), default="MEDIUM")  # 'LOW', 'MEDIUM', 'HIGH'
    evidence_photo = Column(String(500), nullable=True)
    evidence_photos = Column(Text, nullable=True)  # JSON array of URLs / paths
    vision_analysis = Column(Text, nullable=True)  # JSON object
    fraud_flags = Column(Text, nullable=True)  # JSON array of strings
    chat_summary = Column(Text, nullable=False)
    checks_done = Column(Text, default="[]")  # JSON array of checks
    escalation_reason = Column(String(255), nullable=False)
    agent_recommendation = Column(Text, nullable=False)
    status = Column(String(20), default="PENDING", index=True)  # 'PENDING', 'APPROVED', 'REJECTED'
    admin_notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    resolved_at = Column(DateTime, nullable=True)

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    actor = Column(String(60), nullable=False)  # 'AI_AGENT', 'CUSTOMER', 'ADMIN'
    customer_id = Column(String(36), nullable=True, index=True)
    order_id = Column(String(36), nullable=True, index=True)
    tool = Column(String(80), nullable=False)
    input_payload = Column(Text, nullable=True)  # JSON
    output_payload = Column(Text, nullable=True)  # JSON
    verdict = Column(String(40), nullable=True)  # 'AUTO_APPROVE', 'NEEDS_HUMAN', 'DENY', 'EXECUTED'
    status = Column(String(30), default="SUCCESS")
    error = Column(Text, nullable=True)
    idempotency_key = Column(String(100), nullable=True, index=True)

class Setting(Base):
    __tablename__ = "settings"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    key = Column(String(60), unique=True, index=True, nullable=False)
    value = Column(String(255), nullable=False)
    description = Column(String(255), nullable=True)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

class PromoCode(Base):
    __tablename__ = "promo_codes"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    code = Column(String(40), unique=True, index=True, nullable=False)
    value = Column(Float, nullable=False)
    customer_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    expiry = Column(DateTime, nullable=False)
    is_used = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class CustomerMemory(Base):
    __tablename__ = "customer_memory"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    customer_id = Column(String(36), ForeignKey("users.id"), unique=True, nullable=False, index=True)
    preferred_language = Column(String(50), nullable=True)
    usual_size = Column(String(30), nullable=True)
    tone_preference = Column(String(50), nullable=True)
    past_issues = Column(Text, default="[]", nullable=False)  # JSON array
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    customer = relationship("User", back_populates="customer_memory")

class LeakageAlert(Base):
    __tablename__ = "leakage_alerts"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    product_id = Column(String(36), ForeignKey("products.id"), nullable=False, index=True)
    product_sku = Column(String(60), nullable=False)
    batch_id = Column(String(40), nullable=False, index=True)
    count = Column(Integer, default=1, nullable=False)
    common_reason = Column(String(255), nullable=False)
    money_at_risk = Column(Float, default=0.0, nullable=False)
    status = Column(String(30), default="PENDING", nullable=False)  # 'PENDING', 'RESOLVED', 'PAUSED'
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)

    product = relationship("Product")

class SalvageEstimate(Base):
    __tablename__ = "salvage_estimates"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    order_id = Column(String(36), ForeignKey("orders.id"), nullable=False, index=True)
    product_id = Column(String(36), ForeignKey("products.id"), nullable=False, index=True)
    resale_open_box = Column(Float, default=0.0, nullable=False)
    refurbish_cost = Column(Float, default=0.0, nullable=False)
    parts_value = Column(Float, default=0.0, nullable=False)
    scrap_value = Column(Float, default=0.0, nullable=False)
    recommended_action = Column(String(40), nullable=False)  # 'RESTOCK', 'OPEN_BOX', 'PARTS', 'LIQUIDATE', 'SCRAP'
    net_recovery = Column(Float, default=0.0, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)

    order = relationship("Order")
    product = relationship("Product")

class P2PRouting(Base):
    __tablename__ = "p2p_routings"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    return_order_id = Column(String(36), ForeignKey("orders.id"), nullable=False, index=True)
    matched_order_id = Column(String(36), ForeignKey("orders.id"), nullable=True, index=True)
    product_sku = Column(String(60), nullable=False)
    distance_km = Column(Float, nullable=False)
    courier_task_id = Column(String(60), nullable=True)
    status = Column(String(30), default="OFFERED", nullable=False)  # 'OFFERED', 'ACCEPTED', 'IN_TRANSIT', 'DELIVERED', 'FAILED'
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)

    return_order = relationship("Order", foreign_keys=[return_order_id])
    matched_order = relationship("Order", foreign_keys=[matched_order_id])

class EvidenceHash(Base):
    __tablename__ = "evidence_hashes"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    order_id = Column(String(36), ForeignKey("orders.id"), nullable=True, index=True)
    customer_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    image_path = Column(String(500), nullable=True)
    phash = Column(String(64), nullable=False, index=True)
    quality = Column(String(20), default="good")
    status = Column(String(20), default="VERIFIED")
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)

class WalletTransaction(Base):
    __tablename__ = "wallet_transactions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    customer_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    order_id = Column(String(36), ForeignKey("orders.id"), nullable=True, index=True)
    order_number = Column(String(50), nullable=True)
    amount = Column(Float, nullable=False)
    transaction_type = Column(String(20), nullable=False)  # 'CREDIT' (+) or 'DEBIT' (-)
    description = Column(String(255), nullable=False)
    balance_after = Column(Float, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)

    customer = relationship("User")
    order = relationship("Order")

class SupportCall(Base):
    __tablename__ = "support_calls"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    customer_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    order_id = Column(String(36), ForeignKey("orders.id"), nullable=True, index=True)
    order_number = Column(String(50), nullable=True)
    product_title = Column(String(200), nullable=True)
    customer_phone = Column(String(30), nullable=False)
    status = Column(String(30), default="SCHEDULED", nullable=False)  # 'SCHEDULED', 'COMPLETED', 'DECLINED', 'MISSED'
    notes = Column(String(500), nullable=True)
    resolution_action = Column(String(40), nullable=True)  # 'REPLACEMENT', 'REFUND_WALLET', 'REFUND_ORIGINAL'
    scheduled_for = Column(DateTime, default=datetime.datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)

    customer = relationship("User")
    order = relationship("Order")

class Plan(Base):
    __tablename__ = "plans"

    id = Column(String(50), primary_key=True)  # 'starter', 'growth', 'pro'
    name = Column(String(100), nullable=False)
    price_monthly = Column(Float, default=0.0, nullable=False)
    price_yearly = Column(Float, default=0.0, nullable=False)
    chat_limit = Column(Integer, default=50, nullable=False)  # -1 for unlimited
    features = Column(Text, nullable=False)  # JSON string
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    admin_id = Column(String(36), ForeignKey("users.id"), index=True, nullable=False)
    plan_id = Column(String(50), ForeignKey("plans.id"), index=True, nullable=False)
    status = Column(String(30), default="active", nullable=False)  # 'trial', 'active', 'past_due', 'cancelled', 'expired'
    billing_cycle = Column(String(20), default="monthly", nullable=False)  # 'monthly', 'yearly'
    started_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    renew_at = Column(DateTime, nullable=True)
    trial_ends_at = Column(DateTime, nullable=True)
    chats_used = Column(Integer, default=0, nullable=False)
    cancel_at_period_end = Column(Boolean, default=False, nullable=False)
    downgrade_plan_id = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    admin = relationship("User", back_populates="subscription")
    plan = relationship("Plan")
    invoices = relationship("Invoice", back_populates="subscription", cascade="all, delete-orphan", order_by="Invoice.issued_at.desc()")

class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    subscription_id = Column(String(36), ForeignKey("subscriptions.id"), index=True, nullable=False)
    amount = Column(Float, nullable=False)
    status = Column(String(30), default="PAID", nullable=False)  # 'PAID', 'FAILED', 'PENDING'
    issued_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    invoice_no = Column(String(60), unique=True, index=True, nullable=False)
    payment_method = Column(String(50), default="TEST_CARD", nullable=False)

    subscription = relationship("Subscription", back_populates="invoices")





