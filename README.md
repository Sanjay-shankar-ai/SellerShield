<<<<<<< HEAD
<<<<<<< HEAD
# SellerShield AI 🛡️

> **Autonomous E-Commerce Store & AI Concierge Operations Center**  
> An end-to-end, full-stack intelligent commerce platform featuring an autonomous AI customer support concierge, instant size swaps, wallet & refund automation, live logistics tracking, and an admin operations command center.

---

## 🌟 What is SellerShield?

Traditional e-commerce return and support processes are slow, frustrating, and expensive. Customers fill out long forms and wait days for support tickets, while sellers deal with return fraud and lost revenue.

**SellerShield AI** solves this by providing:
1. **A Full Modern E-Commerce Store** with a curated product catalog, instant checkout, promo code discounts, and wallet balances.
2. **An Autonomous AI Support Concierge** that instantly resolves customer issues in real-time — processing 1-click size swaps, order cancellations, doorstep pick-ups, wallet refunds, and technical gadget diagnostics.
3. **An Operations Command Center for Admins** to oversee live KPIs, review escalated claims, manually update shipment milestones, and enforce return policies.

---

## ✨ Key Features

### 🛍️ 1. Customer Storefront (`Shop`)
- **Curated Catalog**: Premium apparel, gadgets, footwear, audio gear, and lifestyle products.
- **Smart Cart & Checkout**: Slide-out cart drawer supporting promo codes (e.g. `WELCOME150`), wallet balance deduction, and instant UPI checkout.
- **Dynamic Policy Badges**: Highlights returnable items (7-day window) and clearly tags non-returnable hygiene items (e.g. innerwear).

### 📦 2. Orders & Live Logistics Tracking
- **Interactive Orders Portal**: Filter between active and past delivered orders.
- **Live Shipment Timeline**: Real-time progress through 4 fulfillment stages:
  1. *Order Received & Confirmed*
  2. *Packed & Sealed at Central Hub*
  3. *Dispatched on Linehaul Transit*
  4. *Out for Delivery & Delivered*
- **1-Click AI Return / Swap**: Every order has an embedded AI trigger to initiate exchanges or returns immediately.

### 💬 3. Autonomous AI Support Concierge
- **Floating & Dedicated Chat**: Interactive chat assistant available across the store.
- **1-Click Size & Color Swaps**: If footwear or apparel doesn't fit, the AI automatically checks stock, confirms alternative sizes/colors, and books a zero-cost doorstep exchange without cancelling the sale.
- **Instant Pre-Dispatch Cancellations & Refunds**: Orders cancelled before dispatch receive 100% full value refunds back to the store wallet or bank account immediately.
- **Photo Evidence Inspection**: For damaged items, customers can upload photo evidence; the AI inspects the claim against policy thresholds.
- **Electronic Gadget Technical Callback System**:
  - Automatically identifies technical gadget issues (e.g. audio dropouts, battery drain, smartwatch pairing failures).
  - Offers immediate scheduled callback from a technical support specialist.
  - Simulates the specialist call with live call simulation cards (Answer & Complete vs. Declined/Missed).
  - Automatically transitions to doorstep replacement or refund once the call concludes.

### 👛 4. SellerShield Wallet & Activity Ledger
- **Instant Credits**: Refunded and cancelled orders credit directly into the user's wallet with zero waiting time.
- **Transaction Ledger**: Complete history showing credits (`+`) and debits (`-`), order references, and live running balance.
- **Checkout Integration**: Spend wallet balances directly at checkout with 1 click.

### 📊 5. Admin Command Center (`Operations Dashboard`)
- **Real-Time KPIs**: Total revenue, average order value (AOV), auto-resolved case rate (% handled autonomously by AI), and refund quota limits.
- **Manual Shipment Management**: Admin controls to progress shipment milestones or push orders through delivery stages.
- **Escalation Case Queue**: Human-in-the-loop review for high-risk claims, policy exceptions, or non-returnable dispute resolutions.
- **Audit Logging**: Immutable event log tracking every tool call, policy decision, refund issuance, and timestamp.

---

## 🛠️ Tech Stack & Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      React 18 + Vite                        │
│   Tailwind CSS • Framer Motion • Lucide Icons • TypeScript  │
└──────────────────────────────┬──────────────────────────────┘
                               │ HTTP / REST API (Port 8000)
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                    Python FastAPI Backend                   │
│   SQLAlchemy ORM • SQLite • APScheduler • Pydantic v2       │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│              Autonomous AI Concierge Engine                 │
│   LangGraph / LLM Agent • Policy Engine • Vision Analysis   │
└─────────────────────────────────────────────────────────────┘
```

- **Frontend**: React 18, Vite, TypeScript, Tailwind CSS, Framer Motion, Lucide React.
- **Backend**: Python 3.10+, FastAPI, Uvicorn, SQLAlchemy ORM, SQLite.
- **Scheduler**: APScheduler for background delivery tracking and automated order milestone updates.
- **AI Models Supported**: Google Gemini API (`gemini-1.5-flash`), OpenAI API, or the integrated autonomous policy rules engine fallback.

---

## 🚀 Quick Start Guide

### Prerequisites
Make sure you have installed:
- [Node.js](https://nodejs.org/) (version 18 or higher)
- [Python](https://www.python.org/) (version 3.10, 3.11, or 3.12)
- Git

---

### Step 1: Clone the Repository
```bash
git clone https://github.com/Sanjay-shankar-ai/SellerShield.git
cd SellerShield
```

---

### Step 2: Set Up the Backend

1. Navigate to the `backend` directory (or stay in root):
```bash
pip install -r backend/requirements.txt
```

2. Configure environment variables:
   Copy `backend/.env.example` to `backend/.env`:
   ```bash
   cp backend/.env.example backend/.env
   ```
   *(Optional)* Add your Gemini or OpenAI API key in `backend/.env`. If left empty, the built-in autonomous policy engine runs all scenarios seamlessly.

3. Start the FastAPI backend server:
```bash
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```
The backend will be running at: **`http://127.0.0.1:8000`**  
Interactive Swagger API docs: **`http://127.0.0.1:8000/docs`**

---

### Step 3: Set Up the Frontend

1. In a new terminal window, install frontend dependencies:
```bash
npm install
```

2. Start the Vite development server:
```bash
npm run dev
```
The frontend will be running at: **`http://localhost:5173`**

---

## 👥 Demo Login Credentials

The database comes pre-seeded with sample customer orders and admin credentials:

| Role | Email | Password | Access / Capabilities |
| :--- | :--- | :--- | :--- |
| **Customer** | `rahul@gmail.com` | `rahul123` | Store shopping, cart checkout, wallet ledger, active orders, AI concierge chat |
| **Admin** | `admin@sellershield.com` | `admin123` | Full operations dashboard, KPI metrics, escalation queue, shipment controls |

---

## 📁 Project Directory Structure

```
SellerShield/
├── backend/
│   ├── main.py                 # FastAPI application & REST route definitions
│   ├── models.py               # SQLAlchemy database models (Users, Orders, SupportCalls, etc.)
│   ├── database.py             # SQLite connection & database session management
│   ├── seed.py                 # Initial database seeding (products, demo accounts, orders)
│   ├── langgraph_agent.py      # Autonomous AI support concierge decision graph
│   ├── policy_engine.py        # Return/refund eligibility rules & fraud risk scoring
│   ├── tracking_scheduler.py   # Background scheduler for automatic order delivery progression
│   ├── requirements.txt        # Python backend dependencies
│   └── prompts/                # System instructions & policy prompt files
├── src/
│   ├── api/                    # Frontend API services (authService, apiClient, etc.)
│   ├── components/
│   │   ├── admin/              # Admin operations dashboard, escalation queue, shipment tools
│   │   ├── auth/               # Customer & Admin login interfaces
│   │   ├── cart/               # Slide-over shopping cart, promo codes & checkout
│   │   ├── chat/               # Floating AI concierge widget & dedicated support page
│   │   ├── common/             # Navigation bar, wallet balance pill, modals
│   │   ├── orders/             # Customer orders list, shipment tracking timeline modal
│   │   └── store/              # Product catalog grid, category filters, product details modal
│   ├── types/                  # TypeScript data interfaces & types
│   ├── App.tsx                 # Root application routing & role switcher
│   └── main.tsx                # React DOM entry point
├── package.json                # Frontend dependencies & scripts
├── tailwind.config.js          # Tailwind styling configuration
├── tsconfig.json               # TypeScript configuration
└── README.md                   # Project documentation
```

---

## 📄 License
This project is open-source and available under the [MIT License](LICENSE).
=======
# SellerShield
>>>>>>> 5c4259b72b4f010f078eae2e6f83aba283cfeffd
=======
# SellerShield
>>>>>>> origin/main
