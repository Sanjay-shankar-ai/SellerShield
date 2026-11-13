import datetime
import json
from sqlalchemy.orm import Session
from .database import SessionLocal, engine, Base
from .models import User, Product, Order, OrderItem, TrackingEvent, Setting, AuditLog, Plan, Subscription, Invoice
from .auth import get_password_hash

def seed_plans_and_subscriptions(db: Session):
    """Seed or update subscription plans and default admin subscription."""
    if db.query(Plan).count() == 0:
        starter = Plan(
            id="starter",
            name="Starter",
            price_monthly=0.0,
            price_yearly=0.0,
            chat_limit=50,
            features=json.dumps({
                "keys": ["order_tracking", "basic_audit"],
                "display": [
                    "50 AI chats a month",
                    "Order tracking",
                    "Basic audit log"
                ]
            }),
            is_active=True
        )
        growth = Plan(
            id="growth",
            name="Growth",
            price_monthly=999.0,
            price_yearly=9990.0,
            chat_limit=1000,
            features=json.dumps({
                "keys": ["order_tracking", "basic_audit", "returns_refunds", "escalation_queue", "csv_export"],
                "display": [
                    "1,000 AI chats a month",
                    "Returns/refunds/exchanges",
                    "Escalation queue",
                    "CSV export"
                ]
            }),
            is_active=True
        )
        pro = Plan(
            id="pro",
            name="Pro",
            price_monthly=2999.0,
            price_yearly=29990.0,
            chat_limit=-1,
            features=json.dumps({
                "keys": [
                    "order_tracking",
                    "basic_audit",
                    "returns_refunds",
                    "escalation_queue",
                    "csv_export",
                    "image_defect_analysis",
                    "voice_assistant",
                    "leakage_salvage",
                    "priority_support"
                ],
                "display": [
                    "Unlimited AI chats",
                    "Image defect analysis",
                    "Voice assistant",
                    "Leakage detector and salvage",
                    "Trust tiers and priority support"
                ]
            }),
            is_active=True
        )
        db.add_all([starter, growth, pro])
        db.commit()

    admin_user = db.query(User).filter(User.role == "ADMIN").first()
    if admin_user:
        existing_sub = db.query(Subscription).filter(Subscription.admin_id == admin_user.id).first()
        if not existing_sub:
            now = datetime.datetime.utcnow()
            trial_sub = Subscription(
                admin_id=admin_user.id,
                plan_id="pro",
                status="trial",
                billing_cycle="monthly",
                started_at=now,
                renew_at=now + datetime.timedelta(days=14),
                trial_ends_at=now + datetime.timedelta(days=14),
                chats_used=0,
                cancel_at_period_end=False
            )
            db.add(trial_sub)
            db.commit()

def seed_database():
    Base.metadata.create_all(bind=engine)
    db: Session = SessionLocal()

    # Always ensure plans & admin subscription exist
    seed_plans_and_subscriptions(db)

    # If already seeded other tables, skip
    if db.query(User).count() > 0:
        db.close()
        return

    print("[Seed] Seeding production database...")

    # 1. Settings
    settings = [
        Setting(key="return_window_days", value="7", description="Number of days from delivery an item can be returned or exchanged"),
        Setting(key="replacement_delivery_days", value="2", description="Doorstep replacement delivery timeline in days"),
        Setting(key="refund_processing_days", value="4-5", description="Working days to disburse refund to original payment method"),
        Setting(key="refund_limit", value="2000", description="Maximum amount eligible for autonomous instant cash refund (in INR)"),
        Setting(key="store_credit_bonus_pct", value="10", description="Percentage bonus offered when customer accepts store wallet credit"),
        Setting(key="trust_high_refund_limit", value="5000", description="Instant refund limit for HIGH trust tier customers"),
        Setting(key="trust_normal_refund_limit", value="2000", description="Instant refund limit for NORMAL trust tier customers"),
        Setting(key="trust_risky_refund_limit", value="0", description="Instant refund limit for RISKY trust tier customers (always requires human)"),
        Setting(key="p2p_radius_km", value="25", description="Maximum radius in km for Hyperlocal Peer-to-Peer return matching"),
        Setting(key="leakage_threshold", value="5", description="Threshold count of returns within leakage window triggering alert"),
        Setting(key="leakage_window_hours", value="48", description="Time window in hours for detecting batch return leakage"),
        Setting(key="reservation_hours", value="48", description="Time inventory is held reserved during return/swap process"),
        Setting(key="auto_pause_listings", value="false", description="Automatically pause product listing when leakage threshold is exceeded"),
        Setting(key="p2p_enabled", value="true", description="Enable Hyperlocal P2P return routing"),
        Setting(key="tracking_interval_sec", value="25", description="Interval in seconds for background shipment status advancement")
    ]
    db.add_all(settings)

    # 2. Users (1 Admin, 2 Customers, 1 Risky Customer) with fixed IDs for serverless consistency
    admin = User(
        id="user-admin-001",
        email="admin@sellershield.com",
        hashed_password=get_password_hash("admin123"),
        full_name="Sarah Connor (Store Admin)",
        phone="+91 98000 11223",
        role="ADMIN",
        latitude=12.9716,
        longitude=77.5946,
        trust_score=100.0,
        trust_tier="HIGH"
    )

    cust1 = User(
        id="user-customer-rahul-001",
        email="rahul@gmail.com",
        hashed_password=get_password_hash("rahul123"),
        full_name="Rahul Sharma",
        phone="+91 98450 12891",
        role="CUSTOMER",
        latitude=12.9352,
        longitude=77.6245,
        trust_score=85.0,
        trust_tier="HIGH"
    )

    cust2 = User(
        id="user-customer-ananya-002",
        email="ananya@gmail.com",
        hashed_password=get_password_hash("ananya123"),
        full_name="Ananya Iyer",
        phone="+91 99012 34567",
        role="CUSTOMER",
        latitude=12.9784,
        longitude=77.6408,
        trust_score=70.0,
        trust_tier="NORMAL"
    )

    cust3 = User(
        id="user-customer-vikram-003",
        email="vikram@gmail.com",
        hashed_password=get_password_hash("vikram123"),
        full_name="Vikram Verma",
        phone="+91 98111 22334",
        role="CUSTOMER",
        latitude=12.9141,
        longitude=77.6109,
        trust_score=25.0,
        trust_tier="RISKY"
    )

    db.add_all([admin, cust1, cust2, cust3])
    db.commit()
    db.refresh(admin)
    db.refresh(cust1)
    db.refresh(cust2)
    db.refresh(cust3)

    # 3. 10 Products (with 1 non-returnable hygiene item!)
    products = [
        Product(
            title="AeroFly Pro Running Shoes",
            sku="SHOE-AF-BLK-9",
            category="Footwear",
            description="Engineered marathon carbon plate running sneakers with breathable micro-mesh and dual-density foam sole.",
            price=3499.0,
            original_price=4999.0,
            rating=4.8,
            review_count=320,
            image="https://images.unsplash.com/photo-1542291026-7eec264c27ff?auto=format&fit=crop&w=600&q=80",
            stock_count=45,
            is_returnable=True,
            sizes=json.dumps(["8 UK", "8.5 UK", "9 UK", "9.5 UK", "10 UK"]),
            features=json.dumps(["Carbon propulsion plate", "Responsive foam sole", "10-day doorstep exchange"])
        ),
        Product(
            title="SonicWave ANC Wireless Earbuds",
            sku="AUDIO-SW-01-WHT",
            category="Audio",
            description="Active Noise Cancellation earbuds with 42dB ambient reduction, quad-mic clarity, and 36-hour charging case.",
            price=2899.0,
            original_price=3999.0,
            rating=4.4,
            review_count=412,
            image="https://images.unsplash.com/photo-1590658268037-6bf12165a8df?auto=format&fit=crop&w=600&q=80",
            stock_count=60,
            is_returnable=True,
            sizes=None,
            features=json.dumps(["42dB Hybrid ANC", "Qi wireless charging", "IPX5 water-resistance"])
        ),
        Product(
            title="Imperial Linen Slim-Fit Blazer",
            sku="APP-BLZ-NVY-42",
            category="Apparel",
            description="Tailored from 100% Normandy flax linen. Unstructured soft shoulder, buggy lining for tropical breathability.",
            price=6499.0,
            original_price=8999.0,
            rating=4.7,
            review_count=185,
            image="https://images.unsplash.com/photo-1594938298603-c8148c4dae35?auto=format&fit=crop&w=600&q=80",
            stock_count=18,
            is_returnable=True,
            sizes=json.dumps(["38 Regular", "40 Regular", "42 Slim", "44 Slim"]),
            features=json.dumps(["100% Normandy Flax", "Genuine horn buttons", "Tailored slim fit"])
        ),
        Product(
            title="Chronos X AMOLED Smartwatch",
            sku="TECH-CX-BLK-01",
            category="Gadgets",
            description="1.43-inch Always-on Ultra HD AMOLED screen, aircraft-grade titanium bezel, and continuous health monitoring.",
            price=4299.0,
            original_price=5999.0,
            rating=4.6,
            review_count=290,
            image="https://images.unsplash.com/photo-1523275335684-37898b6baf30?auto=format&fit=crop&w=600&q=80",
            stock_count=32,
            is_returnable=True,
            sizes=None,
            features=json.dumps(["Titanium alloy bezel", "ECG & SpO2 sensors", "12-day battery life"])
        ),
        Product(
            title="Carbon Tactical EDC Box",
            sku="GEAR-EDC-09",
            category="Gadgets",
            description="Shockproof carbon composite case for EDC tech, cables, passports, and delicate electronics with custom cut foam.",
            price=1899.0,
            original_price=2499.0,
            rating=4.9,
            review_count=140,
            image="https://images.unsplash.com/photo-1549465220-1a8b9238cd48?auto=format&fit=crop&w=600&q=80",
            stock_count=55,
            is_returnable=True,
            sizes=None,
            features=json.dumps(["Mil-spec crush resistance", "Waterproof rubber gasket seal", "Custom pluck foam"])
        ),
        # NON-RETURNABLE HYGIENE ITEM:
        Product(
            title="Pure Bamboo Fiber Underwear Pack (3-Pack)",
            sku="HYG-BAM-UND-M",
            category="Hygiene & Essentials",
            description="Ultra-soft antimicrobial bamboo viscose boxer briefs. Breathable, moisture-wicking and hypoallergenic.",
            price=999.0,
            original_price=1499.0,
            rating=4.9,
            review_count=520,
            image="https://images.unsplash.com/photo-1583496661160-fb5886a0aaaa?auto=format&fit=crop&w=600&q=80",
            stock_count=80,
            is_returnable=False,  # Non-returnable hygiene item!
            sizes=json.dumps(["S", "M", "L", "XL"]),
            features=json.dumps(["100% Organic Bamboo", "Antimicrobial & Hypoallergenic", "Strictly Non-Returnable for Hygiene"])
        ),
        Product(
            title="TrailMaster Water-Repellent Backpack (30L)",
            sku="BAG-TRL-30L",
            category="Travel",
            description="Rugged 900D ballistic cordura travel backpack with padded 16\" laptop sleeve and ergonomic airflow back panel.",
            price=2499.0,
            original_price=3499.0,
            rating=4.7,
            review_count=210,
            image="https://images.unsplash.com/photo-1553062407-98eeb64c6a62?auto=format&fit=crop&w=600&q=80",
            stock_count=35,
            is_returnable=True,
            sizes=None,
            features=json.dumps(["Water-repellent Cordura", "Anti-theft rear pocket", "16\" padded laptop compartment"])
        ),
        Product(
            title="Artisan Mechanical Keyboard (RGB)",
            sku="TECH-KB-ART-75",
            category="Tech",
            description="75% compact hot-swappable mechanical keyboard with pre-lubed Gateron switches and solid CNC aluminum chassis.",
            price=4899.0,
            original_price=6499.0,
            rating=4.9,
            review_count=175,
            image="https://images.unsplash.com/photo-1587829741301-dc798b83add3?auto=format&fit=crop&w=600&q=80",
            stock_count=22,
            is_returnable=True,
            sizes=None,
            features=json.dumps(["Gateron Pro Yellow switches", "Gasket mount sound dampening", "South-facing RGB"])
        ),
        Product(
            title="Nordic Minimalist Ceramic Desk Lamp",
            sku="HOME-LAMP-WHT",
            category="Home",
            description="Handmade matte ceramic base with linen drum shade and warm touch-dimmable LED lighting.",
            price=1699.0,
            original_price=2299.0,
            rating=4.5,
            review_count=98,
            image="https://images.unsplash.com/photo-1507473885765-e6ed057f782c?auto=format&fit=crop&w=600&q=80",
            stock_count=40,
            is_returnable=True,
            sizes=None,
            features=json.dumps(["3-step touch dimming", "Flicker-free warm LED", "Hand-thrown matte ceramic"])
        ),
        Product(
            title="ActiveFlex Compression Gym Leggings",
            sku="APP-ACT-LEG-S",
            category="Apparel",
            description="High-waisted squat-proof four-way stretch compression tights with dual deep side pockets for phones.",
            price=1499.0,
            original_price=1999.0,
            rating=4.8,
            review_count=310,
            image="https://images.unsplash.com/photo-1506152983158-b4a74a01c721?auto=format&fit=crop&w=600&q=80",
            stock_count=50,
            is_returnable=True,
            sizes=json.dumps(["XS", "S", "M", "L"]),
            features=json.dumps(["Zero-transparency squat proof", "Seamless waistband", "Dual phone drop-in pockets"])
        )
    ]
    db.add_all(products)
    db.commit()

    # 4. Sample Orders across different statuses
    now = datetime.datetime.utcnow()

    # Order 1: Rahul Sharma, AeroFly Shoes, DELIVERED 3 days ago (eligible for size swap!)
    ord1 = Order(
        order_number="ORD-1001",
        customer_id=cust1.id,
        customer_name=cust1.full_name,
        customer_email=cust1.email,
        customer_phone=cust1.phone,
        shipping_address="Flat 402, Green Glen Layout, Bellandur, Bengaluru 560103",
        payment_method="MOCK_UPI",
        total_amount=3499.0,
        status="DELIVERED",
        delivered_at=now - datetime.timedelta(days=3),
        created_at=now - datetime.timedelta(days=5)
    )
    db.add(ord1)
    db.commit()
    db.refresh(ord1)

    item1 = OrderItem(
        order_id=ord1.id,
        product_id=products[0].id,
        product_title=products[0].title,
        product_sku=products[0].sku,
        selected_size="9 UK",
        quantity=1,
        unit_price=3499.0,
        subtotal=3499.0
    )
    db.add(item1)

    # Tracking events for Order 1
    db.add_all([
        TrackingEvent(order_id=ord1.id, status="PLACED", title="Order Placed", location="Bengaluru", description="Payment confirmed via UPI.", created_at=now - datetime.timedelta(days=5)),
        TrackingEvent(order_id=ord1.id, status="PACKED", title="Packed & Sealed", location="Whitefield Hub", description="Packed in secure carton.", created_at=now - datetime.timedelta(days=4)),
        TrackingEvent(order_id=ord1.id, status="SHIPPED", title="Dispatched", location="Bengaluru South", description="In transit via Delhivery Express.", created_at=now - datetime.timedelta(days=4)),
        TrackingEvent(order_id=ord1.id, status="DELIVERED", title="Delivered at Doorstep", location="Bellandur", description="Delivered to recipient Rahul Sharma. 7-day swap window active.", created_at=now - datetime.timedelta(days=3))
    ])

    # Order 2: Rahul Sharma, SonicWave Earbuds, SHIPPED (currently in automatic transit)
    ord2 = Order(
        order_number="ORD-1002",
        customer_id=cust1.id,
        customer_name=cust1.full_name,
        customer_email=cust1.email,
        customer_phone=cust1.phone,
        shipping_address="Flat 402, Green Glen Layout, Bellandur, Bengaluru 560103",
        payment_method="COD",
        total_amount=2899.0,
        status="SHIPPED",
        created_at=now - datetime.timedelta(hours=14)
    )
    db.add(ord2)
    db.commit()
    db.refresh(ord2)

    db.add(OrderItem(order_id=ord2.id, product_id=products[1].id, product_title=products[1].title, product_sku=products[1].sku, quantity=1, unit_price=2899.0, subtotal=2899.0))
    db.add_all([
        TrackingEvent(order_id=ord2.id, status="PLACED", title="Order Placed", location="Bengaluru", description="Cash on delivery order confirmed.", created_at=now - datetime.timedelta(hours=14)),
        TrackingEvent(order_id=ord2.id, status="PACKED", title="Packed at Facility", location="Whitefield Hub", description="Sealed with security tape.", created_at=now - datetime.timedelta(hours=10)),
        TrackingEvent(order_id=ord2.id, status="SHIPPED", title="In Transit on Linehaul", location="Hosur Road Gateway", description="Express transit to delivery station.", created_at=now - datetime.timedelta(hours=4))
    ])

    # Order 3: Rahul Sharma, Non-Returnable Hygiene Underwear, DELIVERED
    ord3 = Order(
        order_number="ORD-1003",
        customer_id=cust1.id,
        customer_name=cust1.full_name,
        customer_email=cust1.email,
        customer_phone=cust1.phone,
        shipping_address="Flat 402, Green Glen Layout, Bellandur, Bengaluru 560103",
        payment_method="MOCK_UPI",
        total_amount=999.0,
        status="DELIVERED",
        delivered_at=now - datetime.timedelta(days=1),
        created_at=now - datetime.timedelta(days=3)
    )
    db.add(ord3)
    db.commit()
    db.refresh(ord3)

    db.add(OrderItem(order_id=ord3.id, product_id=products[5].id, product_title=products[5].title, product_sku=products[5].sku, selected_size="M", quantity=1, unit_price=999.0, subtotal=999.0))
    db.add(TrackingEvent(order_id=ord3.id, status="DELIVERED", title="Delivered", location="Bellandur", description="Delivered to customer.", created_at=now - datetime.timedelta(days=1)))

    # Order 4: Ananya Iyer, Smartwatch, PACKED (in automatic scheduler)
    ord4 = Order(
        order_number="ORD-1004",
        customer_id=cust2.id,
        customer_name=cust2.full_name,
        customer_email=cust2.email,
        customer_phone=cust2.phone,
        shipping_address="12th Main, Indiranagar, Bengaluru 560038",
        payment_method="MOCK_UPI",
        total_amount=4299.0,
        status="PACKED",
        created_at=now - datetime.timedelta(minutes=45)
    )
    db.add(ord4)
    db.commit()
    db.refresh(ord4)

    db.add(OrderItem(order_id=ord4.id, product_id=products[3].id, product_title=products[3].title, product_sku=products[3].sku, quantity=1, unit_price=4299.0, subtotal=4299.0))
    db.add(TrackingEvent(order_id=ord4.id, status="PACKED", title="Packed at Facility", location="Whitefield Hub", description="Ready for courier pickup.", created_at=now - datetime.timedelta(minutes=20)))

    # Order 5: Ananya Iyer, High Value Blazer ₹6,499 (DELIVERED, > ₹2,000 limit -> escalates to human)
    ord5 = Order(
        order_number="ORD-1005",
        customer_id=cust2.id,
        customer_name=cust2.full_name,
        customer_email=cust2.email,
        customer_phone=cust2.phone,
        shipping_address="12th Main, Indiranagar, Bengaluru 560038",
        payment_method="MOCK_UPI",
        total_amount=6499.0,
        status="DELIVERED",
        delivered_at=now - datetime.timedelta(days=2),
        created_at=now - datetime.timedelta(days=4)
    )
    db.add(ord5)
    db.commit()
    db.refresh(ord5)

    db.add(OrderItem(order_id=ord5.id, product_id=products[2].id, product_title=products[2].title, product_sku=products[2].sku, selected_size="42 Slim", quantity=1, unit_price=6499.0, subtotal=6499.0))
    db.add(TrackingEvent(order_id=ord5.id, status="DELIVERED", title="Delivered at Doorstep", location="Indiranagar", description="Delivered to Ananya Iyer.", created_at=now - datetime.timedelta(days=2)))

    # Initial Audit Logs
    db.add_all([
        AuditLog(actor="SYSTEM", tool="seed.init", input_payload='{"products": 10, "orders": 5}', output_payload='{"status": "INITIALIZED"}', verdict="AUTO_APPROVE", status="SUCCESS"),
        AuditLog(actor="CUSTOMER:Rahul Sharma", tool="checkout.place_order", input_payload='{"order_number": "ORD-1001", "amount": 3499}', output_payload='{"status": "CONFIRMED"}', verdict="AUTO_APPROVE", customer_id=cust1.id, order_id=ord1.id)
    ])

    db.commit()
    db.close()
    print("[Seed] Successfully seeded 10 products, 3 users, 5 orders, and settings!")
