import sqlite3
import datetime
import uuid

con = sqlite3.connect('sellershield.db')
cur = con.cursor()

def add_col(table, col, col_type):
    try:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
        print(f"Added {col} to {table}")
    except sqlite3.OperationalError:
        pass

# Users columns
add_col('users', 'wallet_balance', 'REAL DEFAULT 0.0')
add_col('users', 'latitude', 'REAL')
add_col('users', 'longitude', 'REAL')
add_col('users', 'trust_score', 'REAL DEFAULT 75.0')
add_col('users', 'trust_tier', 'TEXT DEFAULT "NORMAL"')
add_col('users', 'store_name', 'TEXT')

# Products columns
add_col('products', 'is_active', 'BOOLEAN DEFAULT 1')
add_col('products', 'resale_value_open_box', 'REAL DEFAULT 0.0')
add_col('products', 'refurbish_cost', 'REAL DEFAULT 0.0')
add_col('products', 'parts_value', 'REAL DEFAULT 0.0')
add_col('products', 'scrap_value', 'REAL DEFAULT 0.0')

# Orders columns
add_col('orders', 'stage_entered_at', 'TIMESTAMP')
add_col('orders', 'expected_delivery_at', 'TIMESTAMP')
add_col('orders', 'delay_notified', 'BOOLEAN DEFAULT 0')
add_col('orders', 'early_notified', 'BOOLEAN DEFAULT 0')
add_col('orders', 'refund_destination', 'TEXT')
add_col('orders', 'evidence_status', 'TEXT DEFAULT "NONE"')
add_col('orders', 'evidence_photos', 'TEXT')
add_col('orders', 'vision_analysis', 'TEXT')
add_col('orders', 'reason_category', 'TEXT')
add_col('orders', 'delivery_fee', 'REAL DEFAULT 0.0')
add_col('orders', 'gift_wrap_fee', 'REAL DEFAULT 0.0')

# Escalations columns
add_col('escalations', 'evidence_photos', 'TEXT')
add_col('escalations', 'vision_analysis', 'TEXT')
add_col('escalations', 'fraud_flags', 'TEXT')

# Order items columns
add_col('order_items', 'batch_id', 'TEXT DEFAULT "BATCH-001"')

# Conversations columns
add_col('conversations', 'step', 'TEXT DEFAULT "IDENTIFY_ORDER"')
add_col('conversations', 'pending_question', 'TEXT')

# Messages columns
add_col('messages', 'source', 'TEXT DEFAULT "text"')

cur.execute("""
CREATE TABLE IF NOT EXISTS promo_codes (
    id TEXT PRIMARY KEY,
    code TEXT UNIQUE NOT NULL,
    value REAL NOT NULL,
    customer_id TEXT NOT NULL,
    expiry TIMESTAMP NOT NULL,
    is_used BOOLEAN DEFAULT 0,
    created_at TIMESTAMP
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS customer_memory (
    id TEXT PRIMARY KEY,
    customer_id TEXT UNIQUE NOT NULL,
    preferred_language TEXT,
    usual_size TEXT,
    tone_preference TEXT,
    past_issues TEXT DEFAULT '[]',
    created_at TIMESTAMP,
    updated_at TIMESTAMP
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS leakage_alerts (
    id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL,
    product_sku TEXT NOT NULL,
    batch_id TEXT NOT NULL,
    count INTEGER DEFAULT 1,
    common_reason TEXT NOT NULL,
    money_at_risk REAL DEFAULT 0.0,
    status TEXT DEFAULT 'PENDING',
    created_at TIMESTAMP
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS salvage_estimates (
    id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    resale_open_box REAL DEFAULT 0.0,
    refurbish_cost REAL DEFAULT 0.0,
    parts_value REAL DEFAULT 0.0,
    scrap_value REAL DEFAULT 0.0,
    recommended_action TEXT NOT NULL,
    net_recovery REAL DEFAULT 0.0,
    created_at TIMESTAMP
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS p2p_routings (
    id TEXT PRIMARY KEY,
    return_order_id TEXT NOT NULL,
    matched_order_id TEXT,
    product_sku TEXT NOT NULL,
    distance_km REAL NOT NULL,
    courier_task_id TEXT,
    status TEXT DEFAULT 'OFFERED',
    created_at TIMESTAMP
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS evidence_hashes (
    id TEXT PRIMARY KEY,
    order_id TEXT,
    customer_id TEXT,
    image_path TEXT,
    phash TEXT NOT NULL,
    quality TEXT DEFAULT 'good',
    status TEXT DEFAULT 'VERIFIED',
    created_at TIMESTAMP
)
""")

# Seed default settings
default_settings = [
    ("return_window_days", "7", "Number of days from delivery an item can be returned or exchanged"),
    ("replacement_delivery_days", "2", "Doorstep replacement delivery timeline in days"),
    ("refund_processing_days", "4-5", "Working days to disburse refund to original payment method"),
    ("refund_limit", "2000", "Maximum amount eligible for autonomous instant cash refund (in INR)"),
    ("store_credit_bonus_pct", "10", "Percentage bonus offered when customer accepts store wallet credit"),
    ("trust_high_refund_limit", "5000", "Instant refund limit for HIGH trust tier customers"),
    ("trust_normal_refund_limit", "2000", "Instant refund limit for NORMAL trust tier customers"),
    ("trust_risky_refund_limit", "0", "Instant refund limit for RISKY trust tier customers (always requires human)"),
    ("p2p_radius_km", "25", "Maximum radius in km for Hyperlocal Peer-to-Peer return matching"),
    ("leakage_threshold", "5", "Threshold count of returns within leakage window triggering alert"),
    ("leakage_window_hours", "48", "Time window in hours for detecting batch return leakage"),
    ("reservation_hours", "48", "Time inventory is held reserved during return/swap process"),
    ("auto_pause_listings", "false", "Automatically pause product listing when leakage threshold is exceeded"),
    ("p2p_enabled", "true", "Enable Hyperlocal P2P return routing"),
    ("tracking_interval_sec", "25", "Interval in seconds for background shipment status advancement")
]

for key, val, desc in default_settings:
    row = cur.execute("SELECT id FROM settings WHERE key = ?", (key,)).fetchone()
    if not row:
        cur.execute(
            "INSERT INTO settings (id, key, value, description, updated_at) VALUES (?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), key, val, desc, datetime.datetime.utcnow())
        )
        print(f"Inserted default setting: {key} = {val}")

cur.execute("UPDATE orders SET stage_entered_at = created_at WHERE stage_entered_at IS NULL")
cur.execute("UPDATE orders SET expected_delivery_at = datetime(created_at, '+2 days') WHERE expected_delivery_at IS NULL")

# Populate product salvage defaults if 0
cur.execute("""
UPDATE products 
SET resale_value_open_box = round(price * 0.7, 2),
    refurbish_cost = round(price * 0.1, 2),
    parts_value = round(price * 0.15, 2),
    scrap_value = round(price * 0.05, 2)
WHERE resale_value_open_box = 0.0
""")

# Populate user lat/long defaults if null
cur.execute("UPDATE users SET latitude = 12.9716, longitude = 77.5946, trust_tier = 'HIGH', trust_score = 90.0 WHERE role = 'ADMIN'")
cur.execute("UPDATE users SET latitude = 12.9352, longitude = 77.6245, trust_tier = 'HIGH', trust_score = 85.0 WHERE email = 'rahul@gmail.com'")
cur.execute("UPDATE users SET latitude = 12.9784, longitude = 77.6408, trust_tier = 'NORMAL', trust_score = 70.0 WHERE email = 'ananya@gmail.com'")

con.commit()
con.close()
print("Migration completed successfully!")
