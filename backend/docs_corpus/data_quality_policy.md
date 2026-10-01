# Internal Data Quality Policy

## Rejection vs Correction
Bronze data is never modified in place. A row failing validation (FR-02)
is flagged as rejected and excluded from Silver, but remains visible in
Bronze for audit. Automatic correction of invalid values is not
permitted without a documented ADR, to avoid silently biasing
downstream analytics or ML models.

## Retention
Bronze and Silver data is retained indefinitely for audit purposes.
Data quality reports are retained for at least 12 months to support
trend analysis of supplier and pipeline data quality over time.
