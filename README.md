# QAREVIN

Quantitative Adaptive Research, Evidence, Validation & Iteration Network — Hermes agent สำหรับวิจัย พัฒนา และประเมินกลยุทธ์ XAUUSD อย่างทำซ้ำและตรวจสอบหลักฐานได้

- [แผนพัฒนาและเกณฑ์ตรวจรับ](docs/DEVELOPMENT_PLAN.md) — ขอบเขต สถาปัตยกรรม F0–F6, work packages, test plan และ dependencies
- [Implementation specification v1.0](Hermes_Quant_Trading_Agent_Implementation_Spec.md) — เอกสารตั้งต้น

สถานะปัจจุบัน: วางแผนแล้ว ยังไม่มี implementation, market-data validation หรือผล performance

เส้นทางพัฒนา: offline research → deterministic evaluation → Hermes research loop → demo forward evidence → owner-approved live ภายหลัง โดยไม่มีการอนุญาต live อัตโนมัติ

เริ่มตามแผนด้วย foundation และ CSV pipeline ภายใน directory นี้ รายละเอียด native MQL5 EA ยังเป็น decision แยกจาก Python runner ตามสเปก
