# 🛡️ SellerShield AI — System Architecture & LangGraph Multi-Agent Deep-Dive

This document provides a comprehensive technical overview of **SellerShield AI**, explaining why each technology was chosen, how the 17-node LangGraph state machine operates, how autonomous human-like responses are generated safely, and how the customer and merchant experiences interconnect.

---

## 🖼️ Architecture Diagram

The high-resolution architecture diagram is saved locally:
- **PNG Image:** [`langgraph_architecture.png`](./langgraph_architecture.png)
- **Vector SVG:** [`langgraph_architecture.svg`](./langgraph_architecture.svg)

```
+---------------------------------------------------------------------------------------------------------------------+
|                               SELLER-SHIELD AI — AUTONOMOUS LANGGRAPH MULTI-AGENT ARCHITECTURE                       |
|   17 Stateful Nodes with Checkpointing, Policy Guardrails, 1-Click Retention, and Human-in-the-Loop Safety         |
+---------------------------------------------------------------------------------------------------------------------+

STAGE 1: INGESTION & INTENT      STAGE 2: ROUTING & POLICIES       STAGE 3: RETENTION & ACTIONS      STAGE 4: VERIFY, RESPOND & AUDIT
+---------------------------+   +----------------------------+   +-----------------------------+   +--------------------------------+
| 1. node_load_memory       |   | 4. node_track              |   | 9. node_retention [KEY]     |   | 13. node_verify [KEY]          |
|    Customer Trust & Prefs |   |    Live Transit Milestones |   |    1-Click Swap / +10% Bonus|   |     Safety & Double-Refund Guard|
+---------------------------+   +----------------------------+   +-----------------------------+   +--------------------------------+
             |                                                                 |                                   |
             v                                                                 v                                   v
+---------------------------+   +----------------------------+   +-----------------------------+   +--------------------------------+
| 2. node_understand        |   | 5. node_cancel_order       |   | 10. node_replacement_flow   |   | 14. node_escalate [KEY]        |
|    Intent & Emotion NLU   |   |    Pre-Dispatch Zero Touch |   |     Warehouse Stock Check   |   |     Human-in-the-Loop Queue    |
+---------------------------+   +----------------------------+   +-----------------------------+   +--------------------------------+
             |                                                                 |                                   |
             v                                                                 v                                   v
+---------------------------+   +----------------------------+   +-----------------------------+   +--------------------------------+
| 3. node_resolve_order     |   | 6. node_ask_reason         |   | 11. node_refund_flow        |   | 15. node_respond               |
|    Match ORD-1002/1003    |   |    Size, Defect, or Remorse|   |     Wallet Credit / Bank    |   |     Empathetic Human Reply     |
+---------------------------+   +----------------------------+   +-----------------------------+   +--------------------------------+
                                               |                               |                                   |
                                               v                               v                                   v
                                +----------------------------+   +-----------------------------+   +--------------------------------+
                                | 7. node_policy_check [KEY] |   | 12. node_act [KEY]          |   | 16. node_summarize_memory      |
                                |    7-Day & Hygiene Guard   |   |     Execute DB & Courier    |   |     Save Learned Preferences   |
                                +----------------------------+   +-----------------------------+   +--------------------------------+
                                               |                                                                   |
                                               v                                                                   v
                                +----------------------------+                                     +--------------------------------+
                                | 8. node_collect_evidence   |                                     | 17. node_audit                 |
                                |    Photo Defect Analysis   |                                     |     Immutable Compliance Log   |
                                +----------------------------+                                     +--------------------------------+
```

---

## 1. 🔄 Why We Use LangGraph (Over Traditional LLM Prompts)

Traditional LLM chatbots follow a linear sequence ($\text{Prompt} \rightarrow \text{Output}$). In e-commerce post-purchase operations, this approach fails because:
* **No Loops:** Cannot pause to ask for missing photos, analyze the image, and re-evaluate.
* **No State Persistence:** If the user refreshes their browser, conversation state is lost.
* **Hallucination Risk:** Allowing an LLM to decide financial refunds leads to unapproved merchant payouts.

### LangGraph Advantages:
1. **Cyclic Graph with Conditional Routing:** Enables loops (e.g. `ask_reason` $\rightarrow$ `policy_check` $\rightarrow$ `collect_evidence` $\rightarrow$ `retention`).
2. **Stateful Checkpointing (`SqliteSaver`):** Every turn is stored by `thread_id`. Returning customers resume seamlessly.
3. **Hard Commercial Boundaries:** Decisions are computed in deterministic Python nodes before reaching the LLM.
4. **Human-in-the-Loop Interrupts:** Flagged cases pause execution until a merchant clicks Approve or Reject in the Admin Dashboard.

---

## 2. ⚡ Why We Use FastAPI

1. **Async Performance:** Built on ASGI, non-blocking I/O allows high-volume concurrent handling of database lookups and external courier APIs.
2. **Type Safety & Data Integrity:** Pydantic schemas validate requests before business logic executes.
3. **Automated Documentation:** Instant interactive Swagger UI (`/docs`) for development and third-party integration.
4. **Serverless Scalability:** Minimal footprint, instant cold-starts on Vercel/AWS Lambda.

---

## 3. 🧩 The 17 Nodes (Grouped into 14 Functional Stages)

### The 5 Most Critical Nodes:
1. **`node_policy_check`:** Enforces 7-day return limits, checks non-returnable hygiene tags (e.g. underwear), and evaluates trust tiers.
2. **`node_retention`:** Detects fit dissatisfaction and proactively proposes a **1-click size/color swap** or **+10% store credit bonus** to retain merchant revenue.
3. **`node_act`:** The actual execution engine that updates database orders, restocks inventory, and credits wallet balances.
4. **`node_verify`:** Pre-commit safety audit preventing double refunds and policy bypasses.
5. **`node_escalate`:** Human-in-the-Loop gateway routing disputed or high-value claims to the merchant.

---

## 4. 🧠 The LLM & Persona Engineering
* **Model:** Google Gemini (Gemini Flash) called via async REST (`httpx`).
* **Prompts:** 
  - `persona_prompt.txt` (Empathy, active listening, tone calibration).
  - `knowledge_prompt.txt` (Product catalog, sizing guides, delivery SLAs).
  - `policy_prompt.txt` (Hard return rules and restrictions).

---

## 5. 👥 Customer vs. Admin Workflows

### Customer Workflow:
1. Browse catalog with high-res Unsplash imagery and real-time stock counts.
2. Automatic shipment tracker displaying live progress (Packed $\rightarrow$ Shipped $\rightarrow$ Delivered).
3. Context-aware AI chat offering instant size exchanges and pre-dispatch cancellations.

### Admin Workflow:
1. Real-time KPI telemetry (Total Revenue, Retained Revenue %, Return Rates).
2. Live shipment status simulator for testing transit milestones.
3. Human-in-the-loop escalation queue with one-click manual approvals.
4. Tamper-proof audit logs recording every automated decision.
