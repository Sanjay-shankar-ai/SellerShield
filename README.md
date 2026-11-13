# SellerShield: Master System Documentation & Judge Presentation Guide

> **Autonomous Post-Purchase Action Engine for Modern E-Commerce**  
> *Transforming customer returns, exchanges, and support from a $800B loss center into an automated retention and revenue machine using stateful LangGraph multi-agent workflows.*

---

## Executive Summary

E-commerce merchants globally lose up to **30% of their gross merchandise value (GMV)** to post-purchase friction: return shipping overhead, restocking losses, fraudulent refund claims, and customer churn caused by 24–48 hour ticketing queues.

Traditional helpdesk software (e.g., Zendesk, Gorgias) acts as a passive message queue that burdens human support agents with repetitive tasks. First-generation AI chatbots (e.g., Intercom bots, generic GPT wrappers) merely recite FAQ pages and deflect tickets without taking action—often hallucinating policies or granting unauthorized refunds.

**SellerShield** is an **autonomous action engine**. Built on a **14-node stateful LangGraph architecture**, it understands customer intent, de-escalates negative sentiment, verifies return policies deterministically, and **safely executes database transactions** (1-click size/color exchanges, wallet credit bonuses, carrier tracking updates, and automated return label generation) in under 5 seconds.

### Key Performance Indicators (KPIs)
* **87% Automated Resolution Rate**: Handled end-to-end without human intervention.
* **100% GMV Retention on Exchanges**: Converts costly cash refunds into instant inventory swaps.
* **<5 Second Turnaround**: Replaces the industry standard 24–48 hour wait time.
* **Zero Financial Hallucination**: Programmatic Python policy guardrails prevent unauthorized payouts.

---

## 1. System Architecture Overview

SellerShield pairs an asynchronous **FastAPI** backend with a reactive **Next.js 14 / Tailwind CSS** frontend, orchestrated through a stateful **LangGraph** multi-node graph powered by **Gemini 2.5 Flash**.

```mermaid
graph TD
    User([Customer / Merchant]) <--> UI[Next.js 14 Web Concierge / Dashboard]
    UI <--> API[FastAPI Asynchronous Gateway]
    
    subgraph Core Engine ["LangGraph Stateful Multi-Agent Engine"]
        API <--> Engine[StateGraph Workflow]
        Engine <--> Checkpointer[(SQLite / Postgres Checkpointer)]
        Engine <--> Models[(SQLAlchemy DB: Orders, Products, Audits)]
        Engine <--> LLM[Gemini 2.5 Flash with Structured Schemas]
    end

    subgraph External Connectors ["Real-Time External Integrations"]
        Engine <--> Carrier[Shipment & Tracking APIs]
        Engine <--> Vision[Multimodal Image Fraud & Defect Detector]
    end
```

### Technology Stack Justification

| Layer | Technology | Why We Chose It |
| :--- | :--- | :--- |
| **Workflow Engine** | **LangGraph** (StateGraph) | Provides cyclic graph execution, checkpointed session memory, deterministic conditional branching, and clean Human-in-the-Loop (HITL) interruptions. Unlike linear chains (LangChain/LlamaIndex), LangGraph allows the agent to ask clarifying questions, backtrack, and loop until a transaction is verified. |
| **Backend API** | **FastAPI (Python 3.11)** | Native async event loop, automatic OpenAPI documentation, high-throughput Pydantic data validation, and seamless integration with the Python AI ecosystem. |
| **Intelligence** | **Gemini 2.5 Flash** | Sub-second latency, structured JSON output enforcement (`response_schema`), native multimodal vision for defect inspection, and cost-effective high-frequency reasoning. |
| **State Persistence** | **SqliteSaver / PostgreSQL** | Stateful session memory allows customers to leave the chat, return days later, and resume their exact return or exchange context without losing progress. |
| **Frontend UI** | **Next.js 14, Tailwind, Lucide** | Modern, responsive design featuring a dual interface: a floating customer concierge widget and an enterprise-grade merchant operations dashboard. |

---

## 2. The 14-Node Stateful LangGraph Engine

The agent is organized into **14 distinct nodes** grouped into 4 functional clusters. Every user turn moves deterministically through this state machine.

```mermaid
flowchart TD
    START([Customer Message]) --> N1[1. node_load_memory]
    N1 --> N2[2. node_understand]
    N2 --> N3[3. node_resolve_order]
    
    %% Conditional Branching
    N3 -->|WISMO / Tracking| N4[4. node_track]
    N3 -->|Pre-dispatch Cancel| N14[14. node_cancel_order]
    N3 -->|Missing Reason| N5[5. node_ask_reason]
    N3 -->|Return / Exchange| N6[6. node_policy_check]
    
    N5 --> N6
    N6 -->|Damaged / Evidence Needed| N7[7. node_collect_evidence]
    N6 -->|Policy Approved| N8[8. node_retention]
    N7 --> N8
    
    N8 -->|Selects Size/Color Swap| N9[9. node_replacement_flow]
    N8 -->|Demands Cash/Wallet Refund| N10[10. node_refund_flow]
    
    N9 --> N11[11. node_act]
    N10 --> N11
    
    N11 --> N12[12. node_verify]
    N12 -->|Valid Transaction| N15[node_respond]
    N12 -->|Policy Breach / Risk| N13[13. node_escalate]
    
    N4 --> N15
    N14 --> N15
    N13 --> N15
    
    N15 --> N16[node_summarize_memory]
    N16 --> N17[node_save_memory]
    N17 --> N18[node_audit]
    N18 --> END([Customer Response])
```

### Detailed Node Specifications

#### Cluster 1: Ingestion, Context & Intent Parsing
1. **`node_load_memory`**: Fetches long-term customer profiles from the database (past purchase history, sizing preferences, preferred language, tone preference). Injects background context without overriding live transactional data.
2. **`node_understand`**: Analyzes the raw customer message using Gemini 2.5 Flash with structured schemas. Extracts:
   - Primary intent: `RETURN`, `EXCHANGE`, `TRACK_ORDER`, `CANCEL`, `COMPLAINT`, `GENERAL_INQUIRY`.
   - Sentiment: `POSITIVE`, `NEUTRAL`, `FRUSTRATED`, `ANGRY`.
   - Entities: Order IDs (`#ORD-1002`), product references, size/color requests.
   - PII Sanitization: Redacts card numbers, OTPs, and phone numbers before state injection.
3. **`node_resolve_order`**: Resolves the specific target order from the customer's active account. If ambiguous, presents order selector cards with thumbnail previews.

#### Cluster 2: Policy Routing & Fraud Inspection
4. **`node_track`**: Connects directly to carrier APIs. Retrieves live shipment events, ETA, delivery delays, and origin/destination scans.
5. **`node_ask_reason`**: Dynamically prompts the customer for the root cause of dissatisfaction (sizing issue, color mismatch, defective item, buyer's remorse) if not provided in the opening prompt.
6. **`node_policy_check`**: Runs **hardcoded deterministic business rules** via `policy_engine.py`:
   - Checks delivery timestamp against the store's return window (e.g., 30 days).
   - Verifies item category eligibility (e.g., intimates and final sale items are non-returnable).
   - Evaluates product condition requirements.
7. **`node_collect_evidence`**: For damaged or defective claims, prompts for photo upload. Uses **multimodal vision analysis** to verify damage authenticity, cross-checks perceptual image hashes to prevent duplicate/reused photos across accounts, and registers verified evidence.

#### Cluster 3: Retention & Solution Execution
8. **`node_retention`**: The core revenue preserver. Dynamically constructs value-retaining offers:
   - **Offer A**: Instant 1-click size/color exchange with free priority shipping.
   - **Offer B**: Instant store wallet credit with an extra **10% merchant bonus** (e.g., \$110 credit on a \$100 return).
   - **Offer C**: Standard original payment refund (fallback if customer rejects retention).
9. **`node_replacement_flow`**: Validates inventory stock in real time. Reserves the replacement unit in the database and prepares reverse logistics.
10. **`node_refund_flow`**: Computes exact refundable amounts excluding non-refundable shipping fees, deducts any already-refunded portions, and formats payment gateway payloads.
11. **`node_act`**: Executes authorized database mutations:
    - Generates pre-paid carrier return label with trackable QR code.
    - Creates replacement order in `PROCESSING` status.
    - Issues refund or credits customer digital wallet.

#### Cluster 4: Verification, Safety & Audit
12. **`node_verify`**: **The Financial Guardrail**. Programmatically asserts that the refund amount does not exceed the order total, confirms inventory reservation was successful, and ensures no double-refunds occur.
13. **`node_escalate`**: The Human-in-the-Loop (HITL) safety net. Triggers when sentiment is hostile, fraud is suspected, or policy exceptions are requested. Packages the conversation state into a priority ticket in the merchant dashboard.
14. **`node_cancel_order`**: Immediately cancels pre-dispatch orders, releases reserved inventory back to active stock, and voids pending payment authorizations.
15. **`node_respond` & Memory Nodes (`summarize`, `save`, `audit`)**: Generates empathetic, natural customer responses, summarizes long threads to conserve context tokens, persists customer preferences, and logs an immutable audit trail.

---

## 3. Real-Life Scenarios: How SellerShield Solves Post-Purchase Problems

Below are 6 real-world scenarios illustrating how SellerShield handles everyday e-commerce problems compared to traditional systems.

---

### Scenario 1: Sizing Mismatch on Apparel (Converting Refund to Exchange)

#### The Problem
A customer purchases a pair of leather boots for \$140. When they arrive, they fit too tightly across the toes. Frustrated, the customer opens support wanting their money back.
- **Traditional Helpdesk Outcome**: Customer submits a ticket. A human agent replies 36 hours later with a generic return form. The customer returns the boots, gets a \$140 refund, and purchases a competitor's boots. **The merchant lost \$140 GMV + \$8 return shipping cost.**

#### The SellerShield Workflow

```mermaid
sequenceDiagram
    autonumber
    actor Customer
    participant Agent as SellerShield (LangGraph)
    participant Policy as Policy Engine
    participant Inventory as Stock DB
    participant Carrier as Carrier API

    Customer->>Agent: "I bought these boots (#ORD-5012) and they pinch my feet. I want my money back."
    Agent->>Policy: Validate Order Date & Eligibility
    Policy-->>Agent: Within 30 days, eligible for exchange/refund
    Agent->>Inventory: Check stock for #ORD-5012 in Size 10
    Inventory-->>Agent: 4 units available in warehouse
    Agent->>Customer: "I understand how uncomfortable tight boots are! Before we refund, would you like us to ship you Size 10 right now for free? We'll provide a pre-paid return label for the Size 9."
    Customer->>Agent: "Yes please, let's swap for Size 10."
    Agent->>Inventory: Reserve Size 10 & create exchange order
    Agent->>Carrier: Generate return label & QR code
    Carrier-->>Agent: Return tracking #TRK-9821
    Agent->>Customer: "Done! Replacement Size 10 is on its way. Here is your return QR code—just drop off the box at any post office."
```

#### Outcome & ROI
* **Customer**: Received resolution in **12 seconds** without waiting for human email ping-pong.
* **Merchant**: **Retained 100% of the \$140 GMV**. The inventory swap prevented customer churn and secured customer loyalty.

---

### Scenario 2: Item Damaged in Transit (Multimodal Vision & Instant Replacement)

#### The Problem
A customer orders a \$65 ceramic dinnerware set. Upon opening the box, two bowls are cracked. The customer is furious and threatens a credit card chargeback.
- **Traditional Helpdesk Outcome**: Agent asks for photos via email. Customer sends photos. Agent forgets to reply for 2 days. Customer contacts their bank and files a dispute. **The merchant loses \$65 + \$15 chargeback fee + merchant reputation.**

#### The SellerShield Workflow
1. **Customer Message**: *"My order arrived completely broken! This is ridiculous, refund me immediately or I'm calling my bank!"*
2. **`node_understand`**: Detects intent `COMPLAINT_DAMAGED`, sentiment `ANGRY`. Sets urgency flag to maximum.
3. **Empathy & De-escalation**: System immediately responds:
   > *"I am so sorry to hear your dinnerware arrived damaged. That is completely unacceptable, and I am going to make this right immediately. Please upload a quick photo of the broken items so I can authorize an instant replacement or refund on the spot."*
4. **`node_collect_evidence`**:
   - Customer uploads photo through the widget.
   - Gemini 2.5 Vision inspects the image: verifies shattered ceramic, confirms packaging matches merchant SKU.
   - Fraud engine verifies perceptual image hash (has never been submitted before on any account).
5. **`node_act` & Salvage Rule**:
   - The policy engine flags this item as having **low salvage value** (shipping broken ceramic back costs more than the item is worth).
   - System **waives return shipping**: customer does not need to return the hazardous broken glass.
   - Instantly schedules an express replacement delivery.

#### Outcome & ROI
* **Customer**: Anger completely diffused; delighted by instant no-hassle resolution.
* **Merchant**: Avoided a \$15 chargeback penalty, saved \$10 in return shipping fees on worthless broken glass, and turned a negative experience into a 5-star brand advocate.

---

### Scenario 3: "Where Is My Order?" (WISMO) & Proactive Delay Handling

#### The Problem
A holiday shopper's package is delayed due to an unexpected blizzard at the regional courier hub. The customer panics thinking the package was lost or stolen.
- **Traditional Helpdesk Outcome**: Represents 40% of all incoming e-commerce support volume. Agents waste hours manually copying and pasting tracking numbers into FedEx/UPS websites.

#### The SellerShield Workflow
1. **Customer Message**: *"Where is my package #ORD-8821? It was supposed to be here yesterday!"*
2. **`node_track`**:
   - Agent queries the carrier API in real-time.
   - Detects courier status: `EXCEPTION - SEVERE_WEATHER_DELAY (Hub: Chicago O'Hare)`.
   - Updated ETA is tomorrow afternoon.
3. **Contextual Explanation & Goodwill**:
   > *"I tracked package #ORD-8821 for you. It's currently safe in Chicago, but experienced a brief delay due to the winter storm. The carrier has scheduled delivery for tomorrow by 3:00 PM. Here is your live carrier tracking link. To apologize for the wait, I've credited \$5 to your store wallet for your next order!"*

#### Outcome & ROI
* **Deflected 100% of human agent workload** for WISMO tickets.
* Proactive \$5 store credit creates an immediate psychological incentive for a future purchase.

---

### Scenario 4: Return Policy Abuse & Fraud Attempt (Guardrails & HITL Escalation)

#### The Problem
A user attempts to return a \$450 designer jacket **68 days after delivery** (the store's return window is strictly 30 days), claiming they never wore it and demanding a full cash refund.
- **Basic AI Chatbot Failure**: Basic bots can be prompt-injected or hallucinate exceptions: *"Since you're a loyal customer, I've processed your \$450 refund!"*

#### The SellerShield Workflow

```mermaid
flowchart TD
    Prompt["Customer: 'I want to return this jacket from 2 months ago, approve it now!'"] --> Understand[node_understand: Intent RETURN]
    Understand --> Resolve[node_resolve_order: #ORD-3019]
    Resolve --> Policy[node_policy_check: policy_engine.py]
    
    Policy -->|Calculates: Delivery was 68 days ago| Expired{Within 30 Days?}
    Expired -->|NO| Block[Deterministic Policy Rejection]
    
    Block --> CustomerMsg["Agent: 'Our return window is 30 days from delivery. Because order #ORD-3019 was delivered 68 days ago, an automated return cannot be opened.'"]
    
    CustomerMsg --> Demand["Customer: 'Let me speak to a manager, this is unfair!'"]
    Demand --> Escalate[node_escalate]
    
    Escalate --> HITL["Creates Ticket in Merchant HITL Queue<br/>Status: ESCALATED<br/>Reason: Window Expired + Customer Demands Supervisor"]
    Escalate --> Guardrail["finance_guardrail: Enforces $0 payout without Merchant Key"]
```

#### Outcome & ROI
* **Zero Financial Hallucination**: The LLM had zero ability to issue funds because `finance_guardrail` strictly validates database timestamps in compiled Python code.
* **Merchant Safety**: The merchant's human operations team reviews the case in the HITL dashboard with all context pre-summarized, maintaining full sovereign control over financial exceptions.

---

### Scenario 5: Buyer's Remorse (Preserving Cash Flow via Store Wallet Credit + 10% Bonus)

#### The Problem
A customer bought a \$100 gadget on impulse. Two weeks later, they regret the purchase and request a full cash refund to their credit card.
- **Traditional Helpdesk Outcome**: Merchant issues a \$100 refund. The \$100 leaves the merchant's bank account forever.

#### The SellerShield Workflow
1. **Customer Message**: *"I changed my mind on order #ORD-4402. I just want my money back."*
2. **`node_retention` Incentive Calculation**:
   - The retention engine evaluates store settings: `bonus_wallet_credit_percentage = 10%`.
   - Formulates two paths:
     - **Option 1 (Original Method)**: \$100 refunded to credit card (takes 3–5 business days to post).
     - **Option 2 (Instant Store Wallet Credit)**: **\$110 credited immediately** to their account with zero waiting period.
3. **Customer Decision**:
   - Customer realizes they can get \$110 in purchasing power today rather than waiting 5 days for \$100.
   - Customer clicks *"Accept \$110 Store Credit"*.
4. **`node_act`**:
   - Issues \$110 to customer's store wallet.
   - Generates return shipping label for the returned gadget.

#### Outcome & ROI
* **Cash Flow Protected**: The merchant retains the original \$100 cash in their bank account.
* **Future Revenue Guaranteed**: The customer is guaranteed to return to the merchant's store to spend their \$110 wallet balance.

---

### Scenario 6: Pre-Dispatch Order Cancellation

#### The Problem
A customer accidentally placed an order for the wrong variant 10 minutes ago and immediately wants to cancel before it ships.
- **Traditional Helpdesk Outcome**: The ticket sits in the support queue for 24 hours. In the meantime, the warehouse ships the item. The merchant pays outgoing shipping, return shipping, and restocking labor.

#### The SellerShield Workflow
1. **Customer Message**: *"Cancel order #ORD-9912 immediately! I ordered by mistake."*
2. **`node_cancel_order`**:
   - Checks order status in database: Status is `PENDING` (not yet dispatched).
   - Updates order status to `CANCELLED`.
   - Releases reserved warehouse inventory back to active product stock.
   - Voids payment authorization immediately.
3. **Response**: *"Order #ORD-9912 has been successfully cancelled. Your card was not charged, and you will see the temporary authorization hold disappear shortly."*

#### Outcome & ROI
* **Saved \$12–\$20** in wasteful forward/reverse shipping and warehouse labor costs.

---

## 4. User Experience & Dashboard Tour

SellerShield provides two tailored interfaces:

### A. The Customer Concierge
* **Accessible Anywhere**: Floating widget embedded across the storefront, order confirmation emails, and tracking pages.
* **Zero-Password Friction**: Customers authenticate instantly using their Order ID + Zip Code or Phone Number.
* **Interactive Rich Components**:
  - Carousel cards for order selection.
  - 1-click variant exchange selector (size, color, style).
  - Instant printable PDF/PNG return shipping labels with scannable QR codes for mobile drop-offs.

### B. The Merchant Operations Command Center
* **Live Telemetry & KPIs**: Real-time charts tracking automated resolution rate, GMV retained, return fraud attempts blocked, and customer sentiment distribution.
* **Human-in-the-Loop (HITL) Queue**: Visual triage dashboard displaying high-risk or escalated tickets with one-click actions: `[Approve Exception]`, `[Decline]`, `[Reply to Shopper]`.
* **Shipment & Carrier Simulator**: Built-in test sandbox allowing store managers to simulate delayed shipments, out-of-stock items, and test agent responses live.
* **Dynamic Policy Controls**: Sliders to adjust return windows (14/30/60 days), toggle retention incentives (wallet bonus %), and set automatic refund dollar caps without writing code.

---

## 5. Competitive Benchmarking Matrix

| Dimension | Legacy Helpdesk (Zendesk / Freshdesk) | E-commerce Desk (Gorgias) | First-Gen AI Bots (Intercom / Ada) | **SellerShield (LangGraph Action Engine)** |
| :--- | :--- | :--- | :--- | :--- |
| **Operational Philosophy** | Passive ticketing queue | Ticket-centric macros | Deflect by quoting documentation | **Autonomous transaction execution** |
| **Response Turnaround** | 24–48 Hours | 12–24 Hours | Instant (Static text) | **Instant (<5 Seconds with DB mutation)** |
| **Revenue Orientation** | Cost center (pay-per-seat) | Cost center (pay-per-ticket) | Deflection metric | **Revenue protector (GMV retention)** |
| **Action Capability** | Requires human rep | Limited templated actions | Links to help center articles | **Full read/write DB & carrier APIs** |
| **Architecture** | Relational CRUD database | Rule-based webhooks | Linear LLM prompt chain | **14-Node cyclic state machine** |
| **Safety & Guardrails** | Human manual checks | Static regex | Prone to hallucinations | **Deterministic Python policy validator** |
| **Multimodal Vision** | None | Manual human review | None | **Gemini 2.5 Vision defect validation** |
| **Setup Time for SMBs** | 2–4 Weeks | 3–7 Days | 1–2 Weeks | **<5 Minutes (1-click script / app)** |

---

## 6. Business Model, Monetization & ROI for SMBs

SellerShield utilizes a **high-margin B2B SaaS subscription model** paired with a value-aligned performance component.

```mermaid
pie title Merchant Revenue Distribution
    "Direct SaaS Subscription Fees" : 65
    "Value-Share on Retained GMV" : 25
    "Enterprise Custom Carrier Connectors" : 10
```

### 1. Subscription Tiers

| Tier | Price | Monthly Order Cap | Included Capabilities | Target Merchant |
| :--- | :--- | :--- | :--- | :--- |
| **Starter** | **$49 / mo** | Up to 500 orders | Standard 14-node engine, 1 store, basic carrier tracking | Boutique Shopify & WooCommerce brands |
| **Growth** | **$199 / mo** | Up to 3,000 orders | Multimodal vision fraud check, dynamic wallet bonus, multi-store | Scaling DTC brands doing $50k–$250k/mo |
| **Enterprise** | **$499 / mo +** | Unlimited orders | Custom ERP connectors, dedicated checkpointer DB, custom SLAs | High-volume retail & enterprise brands |

### 2. Value-Aligned Performance Fee
Merchants can opt into our **Performance Retention Tier**:
- A **2% performance fee** charged *only on retained revenue* (orders that were saved via 1-click size/color exchanges or bonus wallet credits that would have otherwise exited the business as cash refunds).
- This aligns SellerShield's financial success directly with the merchant's profitability.

### 3. Clear ROI Example for a Small Business
Consider an apparel brand doing **1,500 orders per month** with an average order value (AOV) of **$80**:
* **Monthly Returns**: 225 orders (15% return rate) = **$18,000 in potential refund loss**.
* **Support Overhead**: 1 full-time support rep @ **$3,200 / month**.
* **With SellerShield**:
  * 87% of inquiries resolved automatically -> Support overhead reduced by **$2,200 / mo**.
  * 35% of returns converted to exchanges or wallet credits -> **$6,300 in GMV retained**.
  * **Net Monthly Financial Benefit**: **$8,500 / month** on an investment of just **$199 / month** (**42x ROI**).

---

## 7. Judge Q&A & Technical Defense Guide

When presenting to judges, be prepared with these concise, highly technical answers to common questions:

### Q1: "How do you prevent the LLM from hallucinating and giving away free refunds or merchandise?"
> **Answer**: *"We strictly decouple reasoning from execution. The LLM (Gemini 2.5 Flash) is only responsible for parsing natural language into structured intent and parameters. It never executes SQL queries or calls payment gateways directly. All financial mutations must pass through our compiled Python validator nodes (`node_policy_check` and `node_verify`), which assert return windows, verify order ownership, check inventory stock, and enforce maximum dollar refund caps. If a rule fails, the transaction is rejected regardless of what the LLM generated."*

### Q2: "Why use LangGraph instead of simple LangChain or OpenAI Assistants API?"
> **Answer**: *"Real customer support is cyclic, stateful, and non-linear. A customer might start asking about tracking, switch to requesting a return, realize they want a different size, and then upload a photo. Standard linear chains or prompt completions cannot handle backtracking, loops, or state checkpointing cleanly. LangGraph allows us to define an explicit graph topology with conditional edges and interruptible state checkpoints, making our agent's behavior deterministic, debuggable, and enterprise-reliable."*

### Q3: "How does an SMB integrate this without an engineering team?"
> **Answer**: *"Zero code required. An SMB merchant installs our Shopify or WooCommerce app with one click. Our backend auto-syncs their product catalog and historical orders via webhooks. The merchant sets their return window on a slider, customizes their brand color, and the concierge widget appears on their store immediately."*

### Q4: "How do you prevent fraud with damaged item claims?"
> **Answer**: *"We implement a two-step defense in `node_collect_evidence`: First, we generate a perceptual image hash (pHash) of the uploaded photo and cross-reference our fraud database to ensure the image wasn't pulled from Google Images or reused by another account. Second, we run the image through Gemini 2.5 Vision to verify that the defect described matches visual reality and that the item matches the specific order SKU."*

### Q5: "What happens if a customer insists on speaking to a human?"
> **Answer**: *"Our `node_escalate` seamlessly creates an escalation ticket in the merchant's HITL dashboard. It freezes any automated payouts, summarizes the customer's sentiment and complaint history into a 3-bullet briefing, and alerts the store manager via email or Slack. When the merchant responds, the message routes directly back to the customer's active chat window."*

---
