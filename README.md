# QAREVIN

Quantitative Adaptive Research, Evidence, Validation & Iteration Network — Hermes agent สำหรับวิจัย พัฒนา และประเมินกลยุทธ์ XAUUSD อย่างทำซ้ำและตรวจสอบหลักฐานได้

- [แผนพัฒนาและเกณฑ์ตรวจรับ](docs/DEVELOPMENT_PLAN.md) — ขอบเขต สถาปัตยกรรม F0–F6, work packages, test plan และ dependencies
- [Implementation specification v1.0](Hermes_Quant_Trading_Agent_Implementation_Spec.md) — เอกสารตั้งต้น

สถานะปัจจุบัน: วางแผนแล้ว ยังไม่มี implementation, market-data validation หรือผล performance

เส้นทางพัฒนา: offline research → deterministic evaluation → Hermes research loop → demo forward evidence → owner-approved live ภายหลัง โดยไม่มีการอนุญาต live อัตโนมัติ

เริ่มตามแผนด้วย foundation และ CSV pipeline ภายใน directory นี้ รายละเอียด native MQL5 EA ยังเป็น decision แยกจาก Python runner ตามสเปก

## Development

Python 3.12+ (local validation: 3.14). The pinned NumPy requires 3.12; this is within the
specification's 3.11+ range. CI checks 3.12 and 3.14.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock
.venv/bin/pip install --no-deps -e .
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/qarevin config-check config/research.example.json
.venv/bin/qarevin preflight --job-memory-mib 768
```

The example contract, session and costs are synthetic and block demo readiness.
Preflight exit 2 means insufficient headroom: defer the job rather than change other agents.
Implementation status: [engineering and evidence](docs/IMPLEMENTATION_STATUS.md).
