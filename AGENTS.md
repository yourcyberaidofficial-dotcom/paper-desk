# Aureon agent instructions

Before changing code, read:
- docs/AI_ENGINEERING_CHARTER.md
- docs/PRODUCT_SPEC.md
- docs/IMPLEMENTATION_STATUS.md

Rules:
- Production remains WAIT_DEFAULT. Broker execution stays disabled.
- Do not promote a strategy without evidence.
- Do not fabricate market data, candles, signals, or research metrics.
- A feature is complete only when the acceptance criteria in docs/ACCEPTANCE_MATRIX.md pass in the deployed browser.
- Preserve user records and research artifacts.
- Update docs/IMPLEMENTATION_STATUS.md after verified changes.
