import os
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.enum.shapes import MSO_SHAPE

def create_deck(output_path):
    prs = Presentation()
    # 16:9 widescreen
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    
    # Colors
    BG_DARK = RGBColor(15, 23, 42)       # #0F172A Slate 900
    CARD_BG = RGBColor(30, 41, 59)       # #1E293B Slate 800
    ACCENT_EMERALD = RGBColor(16, 185, 129) # #10B981 Emerald
    ACCENT_CYAN = RGBColor(56, 189, 248)    # #38BDF8 Cyan
    TEXT_WHITE = RGBColor(248, 250, 252)   # #F8FAFC
    TEXT_MUTED = RGBColor(148, 163, 184)   # #94A3B8
    BORDER_COLOR = RGBColor(51, 65, 85)    # #334155
    
    blank_layout = prs.slide_layouts[6]
    
    def set_slide_background(slide):
        bg = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, prs.slide_height)
        bg.fill.solid()
        bg.fill.fore_color.rgb = BG_DARK
        bg.line.fill.background()
        return bg

    def add_header(slide, tag_text, title_text, subtitle_text):
        # Tag
        tag_box = slide.shapes.add_textbox(Inches(0.8), Inches(0.5), Inches(11), Inches(0.4))
        tf = tag_box.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = tag_text.upper()
        p.font.size = Pt(11)
        p.font.bold = True
        p.font.color.rgb = ACCENT_EMERALD
        
        # Title
        title_box = slide.shapes.add_textbox(Inches(0.8), Inches(0.85), Inches(11.5), Inches(0.8))
        tf_title = title_box.text_frame
        tf_title.word_wrap = True
        p_title = tf_title.paragraphs[0]
        p_title.text = title_text
        p_title.font.size = Pt(28)
        p_title.font.bold = True
        p_title.font.color.rgb = TEXT_WHITE
        
        # Subtitle
        sub_box = slide.shapes.add_textbox(Inches(0.8), Inches(1.6), Inches(11.5), Inches(0.5))
        tf_sub = sub_box.text_frame
        tf_sub.word_wrap = True
        p_sub = tf_sub.paragraphs[0]
        p_sub.text = subtitle_text
        p_sub.font.size = Pt(14)
        p_sub.font.color.rgb = TEXT_MUTED

    # ==========================================
    # SLIDE 1: Title & Executive Summary
    # ==========================================
    s1 = prs.slides.add_slide(blank_layout)
    set_slide_background(s1)
    
    # Badge
    badge = s1.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.8), Inches(1.2), Inches(3.2), Inches(0.45))
    badge.fill.solid()
    badge.fill.fore_color.rgb = CARD_BG
    badge.line.color.rgb = ACCENT_EMERALD
    badge.line.width = Pt(1.5)
    tf = badge.text_frame
    p = tf.paragraphs[0]
    p.text = "🛡️ SELLER-SHIELD AI SYSTEM"
    p.font.size = Pt(11)
    p.font.bold = True
    p.font.color.rgb = ACCENT_EMERALD
    p.alignment = PP_ALIGN.CENTER
    
    # Main Hero Title
    hero = s1.shapes.add_textbox(Inches(0.8), Inches(1.9), Inches(11.5), Inches(1.8))
    tf = hero.text_frame
    tf.word_wrap = True
    p1 = tf.paragraphs[0]
    p1.text = "Autonomous E-Commerce Support &"
    p1.font.size = Pt(36)
    p1.font.bold = True
    p1.font.color.rgb = TEXT_WHITE
    p2 = tf.add_paragraph()
    p2.text = "Return Protection Engine"
    p2.font.size = Pt(36)
    p2.font.bold = True
    p2.font.color.rgb = ACCENT_CYAN
    
    # Subhead
    desc = s1.shapes.add_textbox(Inches(0.8), Inches(3.8), Inches(11.5), Inches(0.9))
    tf = desc.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = "Eliminating \$800B in e-commerce return friction through autonomous AI size swaps, zero-touch cancellations, instant wallet refunds, and human-in-the-loop fraud defense."
    p.font.size = Pt(16)
    p.font.color.rgb = TEXT_MUTED

    # 3 Stat Cards
    metrics = [
        ("87% Autonomous", "Support Resolution", "No human intervention needed"),
        ("100% GMV Retention", "On Size/Color Swaps", "Instant replacement preserves sales"),
        ("< 5 Seconds", "Average Turnaround", "Eliminating 48-hr email queues")
    ]
    for i, (m_val, m_lbl, m_sub) in enumerate(metrics):
        card = s1.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.8 + i * 3.9), Inches(5.1), Inches(3.6), Inches(1.6))
        card.fill.solid()
        card.fill.fore_color.rgb = CARD_BG
        card.line.color.rgb = BORDER_COLOR
        card.line.width = Pt(1)
        tf = card.text_frame
        tf.word_wrap = True
        
        p = tf.paragraphs[0]
        p.text = m_val
        p.font.size = Pt(20)
        p.font.bold = True
        p.font.color.rgb = ACCENT_EMERALD
        
        p2 = tf.add_paragraph()
        p2.text = m_lbl
        p2.font.size = Pt(13)
        p2.font.bold = True
        p2.font.color.rgb = TEXT_WHITE
        
        p3 = tf.add_paragraph()
        p3.text = m_sub
        p3.font.size = Pt(11)
        p3.font.color.rgb = TEXT_MUTED

    # ==========================================
    # SLIDE 2: The Problem - The E-Commerce Return Crisis
    # ==========================================
    s2 = prs.slides.add_slide(blank_layout)
    set_slide_background(s2)
    add_header(s2, "The Market Crisis", "Why Traditional E-Commerce Returns Are Broken",
               "Merchants lose up to 30% of gross revenue and burn customer goodwill with outdated support models.")
    
    problems = [
        ("💥 Massive Revenue Leakage", 
         "Up to 30% of fashion/apparel orders end in outright returns.",
         "Most customers simply want another size, but standard checkout forces refund cancellations that drain merchant bank accounts."),
        ("⏳ 48-Hour Support Bottlenecks", 
         "Overloaded ticket queues and manual customer service agents.",
         "Customers wait days for a response regarding damaged items, simple address updates, or pre-dispatch cancellation requests."),
        ("🚨 Return Fraud & Exploitation", 
         "Wardrobing, false damage claims, and policy bypasses.",
         "Merchants lack real-time policy engines to cross-check delivery timestamps, product non-returnability, and counterfeit claims.")
    ]
    for i, (p_title, p_stat, p_desc) in enumerate(problems):
        card = s2.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.8 + i * 3.9), Inches(2.4), Inches(3.6), Inches(4.3))
        card.fill.solid()
        card.fill.fore_color.rgb = CARD_BG
        card.line.color.rgb = BORDER_COLOR
        card.line.width = Pt(1)
        tf = card.text_frame
        tf.word_wrap = True
        
        p = tf.paragraphs[0]
        p.text = p_title
        p.font.size = Pt(16)
        p.font.bold = True
        p.font.color.rgb = ACCENT_CYAN
        
        p2 = tf.add_paragraph()
        p2.text = "\n" + p_stat
        p2.font.size = Pt(13)
        p2.font.bold = True
        p2.font.color.rgb = TEXT_WHITE
        
        p3 = tf.add_paragraph()
        p3.text = "\n" + p_desc
        p3.font.size = Pt(12)
        p3.font.color.rgb = TEXT_MUTED

    # ==========================================
    # SLIDE 3: The Solution - SellerShield Core Pillars
    # ==========================================
    s3 = prs.slides.add_slide(blank_layout)
    set_slide_background(s3)
    add_header(s3, "The SellerShield Solution", "Four Pillars of Autonomous Post-Purchase Defense",
               "Transforming costly refund liabilities into retained revenue and delighted buyers.")
    
    pillars = [
        ("🔄 1-Click Size & Color Swaps",
         "Autonomous Inventory Reallocation",
         "Detects fit issues immediately. Offers replacement stock in real time without cancelling the order or losing revenue."),
        ("⚡ Instant Pre-Dispatch Refunds",
         "Zero-Touch Order Cancellation",
         "If package is still packed/unshipped, system cancels instantly, restocks inventory, and credits store wallet automatically."),
        ("🛠️ Gadget Tech Support Gateway",
         "Deflecting False Defect Returns",
         "For electronics, troubleshooting workflows run first. High-tier issues trigger merchant technical callback tickets."),
        ("🛡️ Fraud Guard & Escalation",
         "Human-in-the-Loop Safeguard",
         "Strict 7-day policy enforcement, hygiene tag restrictions, and automated escalation to admin dashboard for edge cases.")
    ]
    for i, (title, sub, body) in enumerate(pillars):
        x = Inches(0.8 + (i % 2) * 5.9)
        y = Inches(2.4 + (i // 2) * 2.3)
        card = s3.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, x, y, Inches(5.6), Inches(2.0))
        card.fill.solid()
        card.fill.fore_color.rgb = CARD_BG
        card.line.color.rgb = BORDER_COLOR
        card.line.width = Pt(1)
        tf = card.text_frame
        tf.word_wrap = True
        
        p = tf.paragraphs[0]
        p.text = title
        p.font.size = Pt(16)
        p.font.bold = True
        p.font.color.rgb = ACCENT_EMERALD
        
        p2 = tf.add_paragraph()
        p2.text = sub
        p2.font.size = Pt(12)
        p2.font.bold = True
        p2.font.color.rgb = TEXT_WHITE
        
        p3 = tf.add_paragraph()
        p3.text = body
        p3.font.size = Pt(11)
        p3.font.color.rgb = TEXT_MUTED

    # ==========================================
    # SLIDE 4: System Architecture & Tech Stack
    # ==========================================
    s4 = prs.slides.add_slide(blank_layout)
    set_slide_background(s4)
    add_header(s4, "Engineering Excellence", "End-to-End Modern Cloud Architecture",
               "Built for high-concurrency, stateful multi-turn reasoning, and serverless edge delivery.")
    
    arch_cols = [
        ("Client Tier", "React 18 & Vite", [
            "Tailwind CSS & Lucide Icons",
            "Floating AI Chat Concierge",
            "Real-time Tracking Simulator",
            "Customer + Merchant Dashboards",
            "Vite-optimized SPA builds"
        ]),
        ("Backend Services", "FastAPI & Python", [
            "High-throughput Async API",
            "Dynamic Module Bootstrapping",
            "JWT & Bearer Authentication",
            "CORS Preflight & Edge Routing",
            "Audit Trail Logging Service"
        ]),
        ("AI Orchestration", "LangGraph Multi-Agent", [
            "Stateful Reasoning Checkpointer",
            "Deterministic Policy Engine",
            "Automated Intent Classification",
            "Contextual Memory & Memory Saver",
            "Extensible Model Connectors"
        ]),
        ("Data & Cloud", "Storage & Deployment", [
            "SQLAlchemy ORM (SQLite / PG)",
            "Serverless Temp DB Resolution",
            "Vercel Edge Functions API",
            "Google Cloud Run Docker Ready",
            "Automated Background Scheduler"
        ])
    ]
    for i, (tier, subtitle, bullets) in enumerate(arch_cols):
        card = s4.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.8 + i * 2.95), Inches(2.3), Inches(2.75), Inches(4.5))
        card.fill.solid()
        card.fill.fore_color.rgb = CARD_BG
        card.line.color.rgb = BORDER_COLOR
        card.line.width = Pt(1)
        tf = card.text_frame
        tf.word_wrap = True
        
        p = tf.paragraphs[0]
        p.text = tier.upper()
        p.font.size = Pt(11)
        p.font.bold = True
        p.font.color.rgb = ACCENT_CYAN
        
        p2 = tf.add_paragraph()
        p2.text = subtitle
        p2.font.size = Pt(14)
        p2.font.bold = True
        p2.font.color.rgb = TEXT_WHITE
        
        p3 = tf.add_paragraph()
        p3.text = "───────────────"
        p3.font.size = Pt(9)
        p3.font.color.rgb = BORDER_COLOR
        
        for b in bullets:
            pb = tf.add_paragraph()
            pb.text = f"• {b}"
            pb.font.size = Pt(11)
            pb.font.color.rgb = TEXT_MUTED

    # ==========================================
    # SLIDE 5: Dual Workflows - Customer & Merchant
    # ==========================================
    s5 = prs.slides.add_slide(blank_layout)
    set_slide_background(s5)
    add_header(s5, "Full-Lifecycle Experience", "Unified Dual-Faceted Operational Ecosystem",
               "Delivering rapid self-service for buyers while empowering sellers with command-center oversight.")
    
    # Left Card: Customer Experience
    c_card = s5.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.8), Inches(2.3), Inches(5.6), Inches(4.5))
    c_card.fill.solid()
    c_card.fill.fore_color.rgb = CARD_BG
    c_card.line.color.rgb = ACCENT_CYAN
    c_card.line.width = Pt(1.5)
    tf_c = c_card.text_frame
    tf_c.word_wrap = True
    
    p = tf_c.paragraphs[0]
    p.text = "🛍️ CUSTOMER CONCIERGE EXPERIENCE"
    p.font.size = Pt(14)
    p.font.bold = True
    p.font.color.rgb = ACCENT_CYAN
    
    c_points = [
        ("WhatsApp-Style Floating Widget", "Familiar, conversational interface embedded directly on store pages."),
        ("Context-Aware Support", "AI knows active order IDs, delivery status, and purchased SKUs instantly."),
        ("1-Click Exchange Confirmation", "Select new size (e.g., UK 9 -> UK 10) directly within chat cards."),
        ("Instant Wallet & Escrow Ledger", "Automatic refunds credited to store balance in seconds.")
    ]
    for title, desc in c_points:
        p1 = tf_c.add_paragraph()
        p1.text = f"\n✔ {title}"
        p1.font.size = Pt(12)
        p1.font.bold = True
        p1.font.color.rgb = TEXT_WHITE
        p2 = tf_c.add_paragraph()
        p2.text = f"    {desc}"
        p2.font.size = Pt(11)
        p2.font.color.rgb = TEXT_MUTED

    # Right Card: Merchant Operations
    m_card = s5.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(6.8), Inches(2.3), Inches(5.7), Inches(4.5))
    m_card.fill.solid()
    m_card.fill.fore_color.rgb = CARD_BG
    m_card.line.color.rgb = ACCENT_EMERALD
    m_card.line.width = Pt(1.5)
    tf_m = m_card.text_frame
    tf_m.word_wrap = True
    
    p = tf_m.paragraphs[0]
    p.text = "📊 MERCHANT COMMAND CENTER"
    p.font.size = Pt(14)
    p.font.bold = True
    p.font.color.rgb = ACCENT_EMERALD
    
    m_points = [
        ("Live KPI Telemetry", "Real-time tracking of active orders, retained revenue, and return rate."),
        ("Tracking Simulator Controls", "Test shipping cycles: Packed -> In Transit -> Out for Delivery -> Delivered."),
        ("Human-in-the-Loop Queue", "Review flagged escalations with 1-click Approve or Reject overrides."),
        ("Tamper-Proof Audit Trail", "Complete compliance logs of all agent decisions and financial credits.")
    ]
    for title, desc in m_points:
        p1 = tf_m.add_paragraph()
        p1.text = f"\n✔ {title}"
        p1.font.size = Pt(12)
        p1.font.bold = True
        p1.font.color.rgb = TEXT_WHITE
        p2 = tf_m.add_paragraph()
        p2.text = f"    {desc}"
        p2.font.size = Pt(11)
        p2.font.color.rgb = TEXT_MUTED

    # ==========================================
    # SLIDE 6: Business Impact & Roadmap
    # ==========================================
    s6 = prs.slides.add_slide(blank_layout)
    set_slide_background(s6)
    add_header(s6, "Business Impact & Future Vision", "Proven ROI and Expansion Roadmap",
               "Quantifiable savings for retailers with clear pathways for global multi-channel deployment.")
    
    # 3 Impact Columns
    impacts = [
        ("💰 42% Cost Reduction",
         "Support Overhead Slashed",
         "Automating tier-1 return tickets eliminates reliance on expensive outsourced call center teams, saving \$12+ per return ticket."),
        ("📈 35% Net GMV Saved",
         "Turned Returns into Exchanges",
         "By proposing frictionless size and variant replacements at point-of-friction, revenue remains securely in merchant hands."),
        ("⭐ 4.9/5 CSAT Score",
         "Delighted, Loyal Customers",
         "Immediate resolution creates exceptional post-purchase trust, driving repeat purchases and customer lifetime value (LTV).")
    ]
    for i, (val, title, body) in enumerate(impacts):
        card = s6.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.8 + i * 3.9), Inches(2.3), Inches(3.6), Inches(2.2))
        card.fill.solid()
        card.fill.fore_color.rgb = CARD_BG
        card.line.color.rgb = BORDER_COLOR
        card.line.width = Pt(1)
        tf = card.text_frame
        tf.word_wrap = True
        
        p = tf.paragraphs[0]
        p.text = val
        p.font.size = Pt(16)
        p.font.bold = True
        p.font.color.rgb = ACCENT_EMERALD
        
        p2 = tf.add_paragraph()
        p2.text = title
        p2.font.size = Pt(13)
        p2.font.bold = True
        p2.font.color.rgb = TEXT_WHITE
        
        p3 = tf.add_paragraph()
        p3.text = body
        p3.font.size = Pt(11)
        p3.font.color.rgb = TEXT_MUTED

    # Bottom Roadmap Bar
    roadmap_card = s6.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.8), Inches(4.8), Inches(11.7), Inches(2.0))
    roadmap_card.fill.solid()
    roadmap_card.fill.fore_color.rgb = CARD_BG
    roadmap_card.line.color.rgb = ACCENT_CYAN
    roadmap_card.line.width = Pt(1)
    tf_r = roadmap_card.text_frame
    tf_r.word_wrap = True
    
    p = tf_r.paragraphs[0]
    p.text = "🚀 STRATEGIC ROADMAP (NEXT PHASES)"
    p.font.size = Pt(13)
    p.font.bold = True
    p.font.color.rgb = ACCENT_CYAN
    
    phases = [
        "Phase 1 (Completed): Autonomous LangGraph Engine, Size Swaps, Wallet Refunds, Admin Telemetry.",
        "Phase 2 (Q1): Native Shopify / WooCommerce 1-Click App Store Integration & Webhook Sync.",
        "Phase 3 (Q2): Direct WhatsApp Business API Integration & Multilingual Voice Concierge.",
        "Phase 4 (Q3): Computer Vision damage verification to automate photographic fraud detection."
    ]
    for ph in phases:
        p_ph = tf_r.add_paragraph()
        p_ph.text = f"• {ph}"
        p_ph.font.size = Pt(11)
        p_ph.font.color.rgb = TEXT_MUTED

    # Save
    prs.save(output_path)
    print(f"Presentation saved successfully to {output_path}")

if __name__ == "__main__":
    out = os.path.abspath(r"c:\sellershield\SellerShield_Presentation.pptx")
    create_deck(out)
