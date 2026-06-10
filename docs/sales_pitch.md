# BZS Software AI Workflow Pitch And Demo Runbook

Use this as a call track for prospects who need AI to save time, reduce missed work, and improve operational efficiency. Customers should see **BZS Software**, not EasyAgent. EasyAgent is the internal reusable framework that proves BZS can build portable, grounded, tool-using AI workflows.

## Core Pitch

BZS Software helps businesses identify where AI can save time and money, then builds practical workflow systems around the highest-leverage opportunities.

The value is not "an AI chatbot." The value is a faster business process:

- BZS maps how leads, jobs, messages, documents, approvals, and follow-ups actually move through the business.
- BZS identifies where manual work creates delay, missed revenue, duplicated effort, or inconsistent customer experience.
- BZS builds AI-assisted workflows that draft, retrieve, calculate, qualify, route, and prepare next steps while humans approve the decisions that matter.
- BZS works around the client's existing tools instead of forcing a rip-and-replace rollout.
- BZS can start small with one workflow, one source of truth, and one or two safe tools, then expand only after the first result is measurable.

Internal proof point:

- EasyAgent is the reusable engine underneath the demo work. It supports scoped profiles, knowledge bases, tool allowlists, provider flexibility, server-side credentials, streaming chat, rate limits, budgets, status endpoints, and evals.
- Do not lead with the EasyAgent name in customer copy. Use it as technical evidence when a buyer asks how BZS can deliver the workflow safely.

## Business Pain Points To Lead With

1. Leads sit in inboxes, forms, texts, or DMs too long, and fast competitors win the job.
2. Staff spend hours drafting the same replies, chasing the same follow-ups, and hunting for the same files.
3. Quotes, approvals, job details, and customer context are scattered across tools with no clear owner.
4. The business wants AI efficiency, but does not know which workflow is worth automating first.
5. The owner needs a safe system where AI accelerates work without silently sending risky customer-facing messages.

## Buyer-Safe Positioning

Say:

> BZS Software maps where work slows down in your business, finds the highest-leverage AI opportunities, and builds the workflow system that helps your team move faster while staying in control.

Avoid claiming:

- "Fully autonomous employee replacement."
- "AI sends everything for you."
- "Guaranteed ROI."
- "Works with every system out of the box."
- "Live CRM writes, Stripe checkout, or production deployment" unless those integrations are actually configured for the client.

## Offer Ladder

Use the BZS website's public structure as the starting offer menu:

| Offer | Best fit | Demo proof |
| --- | --- | --- |
| Workflow Review | A business wants to find the three highest-leverage AI opportunities before committing to a build. | Sales Concierge qualification flow. |
| Build | A team has one clear workflow to improve: lead response, support deflection, quote follow-up, scheduling, or document triage. | Sales Concierge and Customer Service profiles. |
| Run | A business wants BZS to keep the system tuned, measured, and expanded over time. | Production guardrails, evals, status endpoints. |
| Lead Reply & Qualification System | A service business needs faster inbound response and cleaner follow-up. | Catalog lookup, lead qualification, preview-only lead capture. |
| Custom Workflow Integration | A workflow needs CRM, calendar, inbox, payment, document-store, or internal API actions. | Tool registry and preview-tool pattern. |

## Demo Setup

Run the backend and dashboard locally:

```bash
.venv/bin/python -m uvicorn backend.app:app --reload --port 8001
.venv/bin/python -m http.server 8000 --directory web
```

Open `http://localhost:8000`, confirm the API base points at `http://127.0.0.1:8001`, then switch profiles in the dashboard/chat client. If the Customer Service semantic index is missing, either rebuild it for the cleanest RAG demo or use literal KB questions that work through `search_kb`.

```bash
.venv/bin/python -m backend.rag.cli --backend fake build customer-service
```

## Demo 1: BZS Lead Workflow For Revenue Capture

Pain point: website visitors and inbound leads do not get fast, consistent replies, so revenue leaks before the business even knows what happened.

Internal profile: `sales-concierge`

Customer-facing framing: BZS Software workflow assistant.

What it proves:

- The assistant follows a business workflow: catalog lookup, fit qualification, then optional preview action.
- Recommendations are backed by `profiles/sales-concierge/data/catalog.json`.
- Tool calls are safe demos: no CRM record, invoice, Stripe session, or payment link is created.
- The same engine can become a BZS sales or lead-response assistant by changing profile config and tools, not the core loop.

Suggested script:

1. Set the profile to Sales Concierge.
2. Ask: `I run a small agency and lose time replying to leads and chasing follow-ups. Where could AI save us time and money?`
3. Point out that it should use `catalog_lookup` and `qualify_lead`, recommend the closest BZS workflow or a workflow review, and ask only high-value missing questions.
4. Ask: `Capture me as a lead: Ada Lovelace, ada@example.com, Analytical Engines. I need help with lead response.`
5. Point out that `lead_capture_preview` normalizes contact details and returns a mock lead id while clearly saying no CRM record was created.
6. Ask: `Show me a checkout preview for the workflow review.`
7. Point out that `checkout_link_preview` returns a fake checkout URL and line item summary while clearly saying no Stripe session was created.

Talk track:

> This is the difference between generic AI advice and a BZS workflow system. The assistant is not just writing a persuasive paragraph; it is identifying the workflow, qualifying the buyer, and preparing the next action inside strict preview boundaries. For a real client, the preview tools become production CRM, inbox, calendar, or payment tools only after we define allowed actions, credentials, failure handling, and tests.

## Demo 2: Support Deflection For Fewer Repetitive Questions

Pain point: customers need fast answers about hours, pricing, ordering, and policies, but the business cannot afford hallucinated details.

Internal profile: `customer-service`

Customer-facing framing: an example of a BZS-built support workflow for a small business.

What it proves:

- The assistant answers from a scoped KB rather than guessing.
- It can use keyword or semantic retrieval, then read the source file for verification.
- It has explicit escalation behavior for off-KB questions, complaints, refunds, and booking requests.
- A small business can adapt the profile by replacing markdown files with its real source-of-truth content.

Suggested script:

1. Set the profile to Customer Service.
2. Ask: `What time does Easy Coffee open on weekdays?`
3. Point out that it should ground the answer in `hours.md`: weekdays open at 6:30 AM and close at 6:00 PM.
4. Ask: `Do you have oat milk and is there an extra charge?`
5. Point out that it should ground the answer in `faq.md`: oat milk is available with no non-dairy upcharge.
6. Ask: `Can I book the back room for a private event tomorrow morning?`
7. Point out that it should use the documented back-room process and avoid inventing unavailable booking commitments.

Talk track:

> The support demo shows the trust boundary. A useful AI workflow is not one that answers everything; it is one that knows what it knows, retrieves it, and escalates the rest cleanly. That is why the workflow owns the KB, prompt, tools, and evals together.

## Optional Demo: Research Analyst For Market Scans

Pain point: teams burn time turning public information into sourced briefs and comparisons.

Internal profile: `research-analyst`

Use when the prospect cares more about internal research, sales enablement, or competitor scans than website support.

Prompt:

```text
Research the market for AI support agents and compare reusable agent framework competitors.
```

What it proves:

- The profile can search the public web, fetch safe page text, cite sources, and calculate comparisons.
- The same engine supports a research workflow without adding KB-only support behavior or sales preview tools.

## Discovery Questions

Ask these before proposing scope:

- Where does work slow down today: leads, support, scheduling, quotes, documents, approvals, follow-ups, or reporting?
- What repetitive task costs the most time each week?
- Where does delay cost money, customer trust, or staff attention?
- What source of truth should the workflow trust: markdown KB, website content, docs, CRM, calendar, email, SMS, or an internal API?
- What should AI draft or prepare, and what should a human approve?
- What would make the first pilot obviously worthwhile: fewer missed leads, faster replies, cleaner handoffs, fewer admin hours, more reviews, or better follow-up consistency?

## Close

> The fastest useful pilot is one painful workflow, one source of truth, and one or two safe AI-assisted actions. BZS maps the workflow first, proves the value with a controlled demo, then builds only what is likely to pay off.

Suggested next step for a prospect: book a workflow review and bring one real workflow with examples of messages, documents, follow-ups, and current tools. BZS can then identify the best first automation target before proposing a build.
