-- 073_saas_billing_invoice_amount_cents_repair.sql
-- Billing invoice schema drift repair.
--
-- Earlier invoice schema stored subtotal/total/due/paid amounts but later runtime
-- and schema readiness require a compatibility amount_cents column. Existing
-- production databases can have migrations marked applied while this column is
-- absent, causing startup schema_check to fail.

ALTER TABLE saas_billing_invoices
  ADD COLUMN IF NOT EXISTS amount_cents INTEGER NOT NULL DEFAULT 0;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'saas_billing_invoices'
      AND column_name = 'total_cents'
  ) THEN
    EXECUTE '
      UPDATE saas_billing_invoices
      SET amount_cents = GREATEST(amount_cents, COALESCE(total_cents, 0))
      WHERE amount_cents = 0
    ';
  END IF;

  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'saas_billing_invoices'
      AND column_name = 'amount_due_cents'
  ) THEN
    EXECUTE '
      UPDATE saas_billing_invoices
      SET amount_cents = GREATEST(amount_cents, COALESCE(amount_due_cents, 0))
      WHERE amount_cents = 0
    ';
  END IF;

  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'saas_billing_invoices'
      AND column_name = 'amount_paid_cents'
  ) THEN
    EXECUTE '
      UPDATE saas_billing_invoices
      SET amount_cents = GREATEST(amount_cents, COALESCE(amount_paid_cents, 0))
      WHERE amount_cents = 0
    ';
  END IF;
END $$;

ALTER TABLE saas_billing_invoices
  ALTER COLUMN amount_cents SET DEFAULT 0;

