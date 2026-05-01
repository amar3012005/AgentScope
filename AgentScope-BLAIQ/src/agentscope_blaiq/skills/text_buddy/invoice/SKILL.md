---
name: invoice
description: Rules for composing professional invoices with itemized pricing, payment terms, and entity details.
---
# TextBuddy — Invoice Artifact Skill

## Artifact Type
Invoice — a formal financial document requesting payment for goods or services rendered.
Must contain precise monetary values, line items, payment terms, and entity information.

## Template Structure

Generate the invoice with these sections in order:

### 1. Invoice Header
- **H1 Title**: "INVOICE" (centered, prominent)
- **Invoice Number**: Format `INV-YYYY-NNNN` (e.g., INV-2026-0042). If not provided, generate a plausible one.
- **Invoice Date**: Full date format (e.g., "April 30, 2026").
- **Due Date**: Calculate from payment terms (e.g., Net 30 from invoice date).
- **Status**: "Pending" or "Due on [date]".

Format as a compact block at the top, not as a narrative paragraph.

### 2. Entity Details
Present both parties clearly:

**From (Vendor):**
- Company name
- Address (street, city, postal code, country)
- Tax ID / VAT number if applicable
- Contact email and phone

**Bill To (Client):**
- Client company name or individual name
- Address
- Client reference / PO number if provided

### 3. Line Items Table
Present as a markdown table with these columns:

| # | Description | Quantity | Unit Price | Amount |
|---|-------------|----------|------------|--------|

Rules for line items:
- Each row represents one distinct product, service, or deliverable.
- Description must be specific: "AI Model Licensing — Q2 2026" not "Services."
- Quantity is a number (hours, units, licenses, months).
- Unit Price: currency symbol, thousands separator, two decimals (e.g., € 1,250.00).
- Amount = Quantity × Unit Price.
- If evidence or HITL provides specific items, use them verbatim.
- If no line items are provided, generate plausible items based on the request context.
- Minimum 1 line item, maximum 15.

### 4. Financial Summary
After the line items table, present:

| | |
|---|---|
| **Subtotal** | [sum of all line item amounts] |
| **Tax / VAT** | [rate]% — [amount] |
| **Discount** | [amount or percentage, if applicable] |
| **Total Due** | **[final amount, bold]** |

Rules:
- All figures must be mathematically consistent — subtotal must equal sum of line items.
- Currency must be consistent throughout (€, $, £, etc.).
- Total Due must be the most prominent figure — bold and on its own line.

### 5. Payment Terms
- **Payment Method**: Bank transfer, credit card, PayPal, etc.
- **Bank Details**: IBAN, BIC/SWIFT, account holder name (if provided in evidence/HITL).
- **Terms**: "Net 30", "Due on receipt", "50% upfront, 50% on delivery", etc.
- **Late Payment**: State consequences if applicable (e.g., "2% monthly interest on overdue amounts").

### 6. Notes
- Optional: brief note thanking the client or referencing the project.
- Reference any related documents: "See Proposal #PROP-2026-015 for scope details."
- Keep to 1-2 sentences maximum.

### 7. Footer
- "This is a computer-generated invoice. Questions? Contact [email]."
- Include company registration number if applicable.
- "Confidential" if the invoice contains sensitive pricing.

## Formatting Rules

- Use markdown tables for all financial data — never describe costs in prose only.
- Bold all monetary totals.
- Use consistent currency formatting: symbol + space + amount (e.g., € 1,250.00).
- Align numbers to the right in tables when possible.
- Do not use prose paragraphs where a table or structured field is clearer.

## Tone Rules

- Formal and precise — invoices are legal/financial documents.
- No marketing language, no exclamation marks, no persuasive text.
- Factual and unambiguous — every figure must be verifiable.

## Rules

- Never leave the Total Due blank or ambiguous.
- Never fabricate bank details — use placeholders like "[IBAN to be provided]" if not in evidence.
- If the request is for a "proposal with invoice," generate TWO distinct sections:
  1. The proposal narrative (following the proposal skill structure).
  2. A separate "Invoice" section with the financial table.
- If critical financial data is missing from evidence/HITL, generate plausible figures
  but add a note: "Figures are estimates — confirm with your account manager."
- Every invoice must have: Invoice Number, Date, Due Date, Line Items, Total Due, Payment Terms.
