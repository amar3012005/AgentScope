---
name: invoice
description: Rules for composing invoice artifacts.
---
# TextBuddy — Invoice Artifact Skill

## Artifact Type
Invoice — a formal billing document with itemized charges, totals, and payment terms.

## Template Structure

Generate the invoice with these sections in order:

### 1. Company Header
- Display the issuing company name, address, phone, email, and logo placeholder.
- If brand DNA provides company details, use them exactly. Otherwise use HITL answers.
- Include tax registration number or business ID if provided in evidence.

### 2. Invoice Metadata
- **Invoice Number**: Use the format provided by HITL answers, or default to `INV-YYYYMMDD-001`.
- **Invoice Date**: Use today's date or the date specified in HITL answers.
- **Due Date**: Calculate from payment terms (e.g., Net 30 from invoice date).
- **Reference/PO Number**: Include only if provided via HITL answers or evidence.

### 3. Bill-To Block
- Recipient company name, contact name, address, email.
- Pull all details from HITL answers or evidence — never fabricate recipient info.
- If details are incomplete, include only what is available without placeholder brackets.

### 4. Line Items Table
- Structure as a table with columns: Description, Quantity, Unit Price, Amount.
- Write clear, specific descriptions — "Website redesign: homepage and 4 inner pages"
  not "Design services."
- Each line item must be a distinct deliverable or service.
- Right-align all currency columns.
- Use consistent decimal formatting (two decimal places for all amounts).

### 5. Totals Block
- **Subtotal**: Sum of all line item amounts.
- **Tax**: Apply the tax rate specified in HITL answers or evidence. Label the tax type
  (e.g., "VAT 20%", "Sales Tax 8.25%"). Omit if tax rate is not provided.
- **Discount**: Include only if specified. Show as a negative line with description.
- **Total Due**: Bold and prominent. Include currency symbol.
- Format all currency values with thousands separators and two decimal places
  (e.g., $12,450.00).

### 6. Payment Terms
- State the payment deadline prominently: "Payment due by [date]."
- List accepted payment methods (bank transfer, credit card, etc.) from HITL answers.
- Include bank details or payment link if provided.
- State late payment policy if provided (e.g., "1.5% monthly interest on overdue balances").

### 7. Footer Notes
- Add any special terms, warranty info, or thank-you message.
- Keep to 1-2 sentences maximum.
- Include "Thank you for your business" or similar per brand voice.

## Currency Formatting Rules

- Always prefix amounts with the appropriate currency symbol ($, EUR, GBP, etc.).
- Use the locale-appropriate thousands separator (comma for USD, period for EUR).
- Two decimal places on all monetary values — no exceptions.
- Right-align all numeric columns in the line items table.

## Rules

- Never invent line items, prices, or recipient details — all must come from evidence or HITL.
- If critical details are missing (no line items, no recipient), state what is needed
  rather than fabricating data.
- Keep descriptions professional and unambiguous — avoid abbreviations.
- Do not include confidential payment details (full bank account numbers) in plain text
  unless the user explicitly provides them via HITL.
- The total due amount must be mathematically correct — verify arithmetic.
