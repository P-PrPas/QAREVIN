# QAREVIN — แผนพัฒนาและเกณฑ์ตรวจรับ

วันที่: 6 พฤศจิกายน 2026  
สถานะ: แผนเสนอสำหรับเริ่มพัฒนา ยังไม่มี implementation หรือผลทดสอบกลยุทธ์  
พื้นที่ทำงานหลัก: `/home/peerapas68/projects/hermes/qarevin`  
เอกสารตั้งต้น: [Hermes Quant Trading Agent — Implementation Specification v1.0](../Hermes_Quant_Trading_Agent_Implementation_Spec.md)

## 1. เป้าหมายและหลักการตัดสินใจ

QAREVIN ย่อจาก Quantitative Adaptive Research, Evidence, Validation & Iteration Network เป็น Hermes agent สำหรับเสนอสมมติฐาน พัฒนากลยุทธ์ XAUUSD ทดลอง ตรวจหลักฐาน และจดจำผล เพื่อค้นหากลยุทธ์ที่อาจมีผลตอบแทนสุทธิหลังต้นทุนภายใต้ความเสี่ยงที่กำหนด

ความสำเร็จมีสามระดับที่ต้องรายงานแยกกัน:

1. **Engineering:** ข้อมูลถูกต้อง การจำลองทำซ้ำได้ สิทธิ์แยกกัน และระบบหยุดเมื่อไม่แน่ใจ
2. **Research:** challenger มีหลักฐานที่ดีกว่า baseline ที่ตรึงไว้ บนข้อมูลนอกช่วงปรับแต่งและ demo ในอนาคต
3. **Economic:** ผลตอบแทนเงินจริงหลังต้นทุนอยู่ภายใต้ drawdown ที่เจ้าของยอมรับ ต้องพิสูจน์ภายหลัง และไม่รับประกันว่าจะเกิดขึ้น

หลักพัฒนา: data correctness → deterministic simulation → independent evaluation → bounded agent → demo execution → หลักฐาน forward → owner-approved live เท่านั้น หากไม่พบ edge ให้สรุปว่าไม่พบและหยุดตาม budget ห้ามลดเกณฑ์เพื่อให้ได้ผู้ชนะ

การเรียนรู้ใน v1 คือ feedback-guided research และ structured memory ไม่ใช่การฝึก RL weights ไม่เริ่ม GPU training, HFT, dashboard เต็มรูปแบบ หรือ distributed services

## 2. สิ่งที่อ่านและสภาพแวดล้อมที่ตรวจพบ

อ่านสเปก Qarevin ครบทั้ง 19 หัวข้อ รวมถึง README, Docker Compose และตัวอย่าง MCP/configuration ของ TREVAN กับ NALVORIN เพื่อให้ agent ตัวใหม่อยู่ร่วมกับระบบเดิมได้

- `qarevin/` เริ่มต้นมีเพียง specification ยังไม่มี source code, market data หรือ broker integration
- agent เดิมแยก Hermes home, container, token และ MCP tools; ใช้ API เป็นขอบเขตแทนการ mount ระบบที่ agent ควบคุม
- configuration ตัวอย่างของ NALVORIN ปิด shell/file/browser/code execution ที่เสี่ยง และเปิดเฉพาะ MCP ที่กำหนด แนวทางนี้นำมาปรับใช้ แต่ต้องตรวจ schema กับ Hermes รุ่นที่ติดตั้งจริงก่อน
- checkout ที่ทำงานอยู่ยังไม่เป็น Git repository (`git status` รายงาน not a git repository) ต้องกำหนด version control ใน F0 เพื่อให้มี commit identity จริง
- snapshot เครื่องวันที่จัดทำแผน: RAM รวมประมาณ 6.7 GiB, available ประมาณ 1.8 GiB, swap 4 GiB เกือบเต็ม, disk available ประมาณ 151 GiB เป็นค่าชั่วขณะ ไม่ใช่ budget ที่จองไว้

ผลต่อแผน: เริ่มด้วย CLI และ worker แบบเรียกตามงาน ห้ามเปิด stack เพิ่มทั้งหมดตามตัวเลข 8 GB ในสเปกโดยไม่ benchmark ร่วมกับ workloads เดิม การอ่านเอกสารครั้งนี้ไม่ได้ restart container, เปลี่ยน Hermes config หรือสร้างคำสั่งซื้อขาย

## 3. ขอบเขต EA และข้อเสนอที่ต้องตรึงก่อน implementation

### 3.1 เส้นทางหลักตามสเปก

เริ่มด้วยกลยุทธ์ Python และ deterministic runner บน Ubuntu ส่วน MT5 อยู่หลัง broker adapter การเรียกสิ่งนี้ว่า EA ในระดับผลิตภัณฑ์ไม่ควรทำให้เข้าใจว่ามีไฟล์ `.mq5/.ex5` แล้ว

หากเป้าหมายต้องเป็น native MQL5 EA ให้เพิ่ม work package แยก: port/generate เฉพาะกลยุทธ์ที่เลือก, compile ในสภาพแวดล้อม MT5, เปรียบเทียบ indicators/signals/position sizing กับ Python ด้วย golden fixtures และทดสอบใน Strategy Tester + demo ใหม่ ความเท่ากันของผล backtest ข้าม engine ห้ามสมมติเอาเอง งานนี้ยังไม่รวมใน estimate เส้นทางหลัก

### 3.2 สิ่งที่ยึดตาม baseline specification

- XAUUSD intraday, เริ่มสาม families: EMA trend H1, BB/RSI mean reversion M15, Donchian breakout M30
- สัญญาณจากแท่งปิดแล้วเท่านั้น และ execute ได้เร็วที่สุดที่ quote ถัดไปที่เกิดหลังการตัดสินใจ
- CSV M1 เป็นแหล่งข้อมูลตั้งต้น; เป้าหมายประวัติ 2016–ตุลาคม 2026 เท่าที่มีจริง
- research, demo และ live แยกสิทธิ์และ runtime; agent ไม่มี live credentials
- การขอ live และการอนุมัติเป็นคนละ identity; ห้าม agent ยกระดับสิทธิ์หรือแก้ risk/evaluator

### 3.3 ข้อเสนอเพิ่มในแผนนี้ ยังไม่ใช่ผลอนุมัติใหม่จากเจ้าของ

- เริ่ม 3–5 experiments/day, worker หนึ่งงาน, family เดียวต่อ batch; เพดาน 20/day ในสเปกเป็นขีดบนที่ยังไม่เปิดใช้
- เริ่ม demo ด้วยหนึ่งกลยุทธ์และหนึ่ง position รวม เพื่อให้ exposure และ reconciliation ตรวจสอบง่าย การเพิ่ม concurrency ต้องมี policy version ใหม่
- เปิด final holdout หนึ่งรอบต่อ campaign ที่ preregister แล้ว; strategy/evaluator/thresholds ต้องตรึงก่อนเปิด
- demo activation ครั้งแรกผ่าน owner action หลัง gates ผ่าน; ภายหลังจะเพิ่ม guarded automation ได้โดยไม่เกี่ยวกับสิทธิ์ live
- ตั้ง default session เป็น **ยังไม่พร้อม deploy** จนมี timezone, calendar และ cutoff ของ broker จริง; synthetic tests ใช้ calendar ที่ระบุชัด

ข้อเสนอเหล่านี้ช่วยให้เริ่มงาน foundation/data ได้ก่อน โดยไม่ตีความช่องว่างว่าอนุญาต deploy หรือเพิ่มความเสี่ยงแล้ว

## 4. สถาปัตยกรรมและขอบเขตความเชื่อถือ

สร้าง Python modular monolith หนึ่ง codebase แต่แยก process ตามสิทธิ์ ไม่สร้าง microservice สำหรับทุก module

### 4.1 Control และ research

1. **Hermes Qarevin:** คุยกับเจ้าของ อ่านผล เสนอการทดลอง ส่ง candidate source/parameters ผ่าน tools และเขียน interpretation
2. **MCP client + Control API:** validate schema, authenticate, ตรวจ scopes/budgets, register hypothesis, queue jobs และ audit; HTTP `/api/v1` ใช้เมื่อถึง integration ส่วน CLI เรียก application layer เดียวกัน
3. **Trusted job controller:** lease งาน เตรียม dataset slice และ launch sandbox ตาม profile ตายตัว ไม่รับคำสั่ง shell, Docker options หรือ mount paths จาก agent
4. **Research sandbox:** รัน candidate ที่ไม่น่าเชื่อถือ ไม่มี network, secrets, DB, holdout หรือ host Docker socket; input read-only และ scratch จำกัดขนาด
5. **Trusted evaluator:** อ่านผลที่ validate แล้ว คำนวณ metrics/gates เองและ seal scorecard; ไม่รับ PnL หรือ gate verdict ที่ candidate อ้างมาเป็นความจริง
6. **Registry + reports:** immutable manifests, lineage, artifacts และ audit; agent memory อ้าง experiment ID แทนการเป็นแหล่งตัวเลขหลัก

สำหรับสาม seed families เริ่มจาก parameterized trusted strategies ก่อน งาน arbitrary Python code generation เปิดหลัง sandbox negative tests ผ่าน โดย source ที่ส่งเข้ามาแก้ได้เฉพาะ strategy interface ห้าม import candidate เข้าสู่ API/evaluator process

### 4.2 Execution

ลำดับจริงต้องเป็น `pinned strategy → order intent → trusted risk check/reservation → broker adapter → broker` ทุกคำสั่ง รวมการแก้ protection และ order recovery ต้องผ่านนโยบายที่กำหนด ห้ามมีเส้นทางจาก agent หรือ strategy ไป `order_send` โดยตรง

- demo/live runner ไม่มี Hermes model อยู่ใน decision path
- arbitrary strategy code หากอนุญาต ต้องอยู่ใน process ที่ไม่มี broker credentials และส่งได้เฉพาะ signal ที่ validate แล้ว
- adapter รับ intent ได้เฉพาะจาก execution service ที่ยืนยันตัวตน; risk state ถูกควบคุมโดย service ไม่ใช่ไฟล์ที่ strategy เขียนทับได้
- live ใช้ deployment profile, credentials, account identity และ DB แยกจาก demo; ไม่มี live service ใน default Compose
- halt ห้ามเปิด position ใหม่ แต่ protective actions ที่ลดความเสี่ยงยังต้องทำได้ตาม runbook

### 4.3 การป้องกัน holdout

การติดป้าย `sealed=true` ใน DB ไม่เพียงพอ controller ต้องแยกไฟล์/credentials สำหรับ holdout ออกจาก research mounts และ dataset tools ต้องบังคับช่วงวันที่ ห้ามดึงข้อมูล tail ผ่าน import, report, compare หรือ memory

sealed evaluation เป็น owner-triggered job ของ trusted evaluator ที่รัน frozen artifact และคืนรายงานให้ owner; iterative agent ไม่ได้รับ holdout metrics เป็น reward บันทึกทุกการเปิด รวม run ที่ fail/cancel และ candidate ที่ส่งเข้าไป

ถ้านำผลที่เปิดแล้วไปแก้กลยุทธ์หรือเลือกผู้ชนะ ช่วงนั้นเปลี่ยนสถานะเป็น `consumed/contaminated` ใช้ประกอบประวัติได้ แต่ห้ามเรียก unseen อีก campaign ถัดไปต้องอาศัย tail ใหม่หรือ future forward evidence

## 5. โครงสร้างที่ตั้งใจสร้าง

ทุกอย่างอยู่ใต้ `qarevin/` ใช้ package ชื่อ `qarevin` และ CLI ชื่อเดียวกันเพื่อสื่อกับ agent อื่นชัดเจน:

```text
qarevin/
  Hermes_Quant_Trading_Agent_Implementation_Spec.md
  README.md
  pyproject.toml
  docs/DEVELOPMENT_PLAN.md
  docs/architecture.md
  docs/validation_protocol.md
  docs/runbooks.md
  config/research.yaml
  config/risk_policy.demo.yaml
  config/sessions.example.yaml
  src/qarevin/
    domain/          # typed contracts และ state transitions
    data/            # CSV, timezone, QA, causal resampling
    strategies/      # frozen seeds และ strategy interface
    backtest/        # events, fills, ledger, costs
    evaluation/      # independent metrics, splits, gates
    registry/        # datasets, experiments, lineage, jobs
    research/        # preregistration, budgets, sandbox control
    memory/          # structured observations อ้างอิงหลักฐาน
    api/             # scoped control endpoints
    reports/         # QA, experiment, candidate evidence
    risk/            # shared deterministic risk rules
    broker/          # contract, fake adapter, selected demo adapter
    execution/       # intents, reconciliation, watchdog
    cli.py
  qarevin_tools/     # thin MCP wrappers
  strategies/       # candidate source bundles ที่ sandbox อ่าน
  skills/           # สร้างเมื่อถึง F3
  jobs/             # research/report triggers
  scripts/          # setup, import, replay, backup/restore
  tests/            # unit, golden, integration, fault tests
  eval/             # actual-agent scenarios และ injection corpus
  docker-compose.yml
```

นี่เป็น target layout ไม่สร้าง empty modules ทั้งหมดตั้งแต่วันแรก ใช้ Python รุ่นที่รองรับและ pin เวอร์ชัน/lockfile ใน F0; เลือก dependencies เท่าที่ milestone ใช้จริง ตาม stack ในสเปก เริ่ม SQLite + Parquet; DuckDB, Redis, PostgreSQL และ vector database ยังไม่จำเป็น

runtime data อยู่นอก source tree: `~/.hermes-qarevin` สำหรับ persona/memory/chat configuration และ `~/.local/share/qarevin` สำหรับ registry/artifacts โดยแยก owner และ read/write permissions แต่ละ process ชัดเจน demo execution state แยกอีก directory; live จัดสรรภายหลัง

ห้าม copy `.env` หรือ config ของ agent อื่นทั้งไฟล์ หาก reuse helper ให้แยกเฉพาะ non-secret settings และ generate configuration ของ Qarevin เอง

## 6. Data contract และการแบ่งเวลา

### 6.1 Import pipeline

รับไฟล์ผ่าน owner staging directory ที่ allowlist ไว้ ไม่รับ arbitrary host path, URL หรือ symlink escape จาก agent

1. hash raw file และเก็บ provenance แบบอ่านอย่างเดียว
2. ตรวจ delimiter/encoding/columns; แยก MT5 export format กับ normalized format; reject format ที่ตีความไม่ได้
3. ระบุ source timezone/offset schedule และความหมาย timestamp ว่าเป็น bar open; ไม่เดา timezone จากชื่อ broker
4. แปลง UTC เก็บทั้ง `bar_open_utc`, `bar_close_utc`, `available_at_utc` และ metadata ต้นทาง
5. ตรวจ OHLC, nonpositive price, duplicate/conflict, ordering, missingness, sessions/DST และ spikes; invalid/conflicting rows quarantine พร้อมเหตุผล
6. resample M15/M30/H1 ตาม anchor ที่ประกาศไว้ ใช้เฉพาะ M1 ที่ปิดครบแล้ว; incomplete bars ถูก flag/ตัดจาก signal ตาม policy
7. สร้าง manifest ของ raw/normalized data, QA, coverage, contract version และ partitions

Python MT5 API ระบุข้อมูลเวลา UTC และจำกัด history ตามที่ terminal มี แต่ CSV จากการ export ต้องพิสูจน์ timezone ของไฟล์แยกต่างหาก ห้ามนำข้อกำหนด API ไปสรุปว่า CSV ทุกไฟล์เป็น UTC [MetaQuotes: copy_rates_range](https://www.mql5.com/en/docs/python_metatrader5/mt5copyratesrange_py)

tick volume เป็นกิจกรรม quote ไม่ถือเป็นจำนวนทองที่ซื้อขายจริง; `spread_points` ต้องใช้ `point` ของ contract แปลงหน่วย และต้องระบุว่าเป็น snapshot/estimate ไม่ใช่ intrabar bid/ask path

### 6.2 Split protocol

ข้อเสนอตั้งต้นจากสเปก: development 2016–2022, secondary OOS 2023–2024, sealed tail 2025–ตุลาคม 2026 ทั้งหมดเลื่อนตาม coverage จริงได้ **ก่อน** ดูผลเท่านั้น

- ใช้ rolling train 24 เดือน → validation 6 เดือน → outer test 6 เดือน เลื่อนครั้งละ 6 เดือนเป็น starting protocol; จัด folds ให้พอดีกับ development coverage และตรึง exact boundaries ใน manifest
- parameter selection ดูได้เฉพาะ train/validation; outer test ใช้ประเมินกระบวนการเลือก ส่วนการใช้ outer results เพื่อพัฒนาซ้ำต้องบันทึกว่าเป็น adaptive research evidence
- 2023–2024 หากเปิดใช้เลือกหลายครั้งให้รายงานเป็น selection history ไม่อ้างเป็น independent final test
- warmup อ่านราคาก่อนขอบได้เพื่อสร้าง indicator state แต่ไม่คิด trade/PnL ก่อนขอบ; ไม่มี fitting บนอนาคต
- boundary positions ต้องปิดตาม simulation policy หรือ carry อย่างมีบัญชีชัดเจน ไม่ซ้ำ PnL ข้าม folds; purge/embargo ตาม holding horizon จริง
- รายงาน stitched OOS equity จาก windows ที่ไม่ซ้อนกัน ห้ามรวมผล overlapping folds ให้ดูเหมือนเงินถูกใช้งานเพียงก้อนเดียว
- หากข้อมูลไม่พอสำหรับ protocol ให้รายงาน insufficient evidence และออก protocol version ใหม่ ห้ามย้ายวันเพื่อเลือกผลสวย

## 7. Strategy contract และ baseline ที่เสนอ

interface รับ closed bars + readonly state และคืน `SignalIntent` เช่น long/short/exit พร้อมเหตุผลและ stop reference; position size เป็นหน้าที่ trusted sizing/risk module ไม่ให้ strategy กำหนด leverage เอง

ทุก baseline มี strategy version, code hash, parameter hash, indicator convention, session policy และ exact warmup rule ข้อเสนอต่อไปนี้ต้องตรึงก่อนทดลองจริง:

- **S1 H1:** EMA50 ตัด EMA200 ขึ้น/ลงบนแท่งปิด เข้า next eligible quote, initial stop 2×ATR14, ออกเมื่อ stop/opposite crossover/session cutoff; ไม่ re-enter เพียงเพราะ EMA ยังเรียงตัวเหมือนเดิม
- **S2 M15:** close แท่งก่อนอยู่นอก BB20/2 และ RSI14 <30 หรือ >70; แท่งปัจจุบันปิดกลับเข้าขอบ band จึงเกิด reversal confirmation; stop 2×ATR14, exit เมื่อ closed price ถึง middle band แล้วส่งคำสั่งที่ quote ถัดไป หรือ stop/cutoff; regime filter เสนอ ADX14 ≤25 ที่แท่งสัญญาณ
- **S3 M30:** close ทะลุ high/low ของ 20 แท่งก่อนหน้า ไม่รวมแท่งสัญญาณ; ATR14 ต้องไม่ต่ำกว่าค่ามัธยฐาน ATR ของ 100 แท่งก่อนหน้า; stop 2×ATR14, ออกเมื่อ opposite-channel signal/stop/cutoff

S2 regime filter, S3 volatility filter และ exit details เป็น engineering baseline proposals ไม่ใช่สิ่งที่สเปกอนุมัติไว้อย่างละเอียดแล้ว ไม่เลือกตัวเลขจากการแอบดู holdout

กำหนด EMA initialization, Wilder ATR/RSI/ADX, BB standard deviation (`ddof`) และ equality/crossing rules ชัดเจน พร้อม hand-computed fixtures; warmup จนทุก feature มีค่า valid และผ่าน minimum stabilization ที่ protocol กำหนด

มี no-trade, untouched seeds และ cost-aware permuted/random controls ตาม seed ที่ตรึงไว้; buy/hold ใช้เป็นบริบทเท่านั้นเพราะ exposure ต่างจาก intraday strategy ทุก challenger ระบุ parent และเปลี่ยนสมมติฐานหลักครั้งละหนึ่งเรื่อง

## 8. Backtest, accounting และ risk semantics

ใช้ signal timeframe M15/M30/H1 แต่จำลอง execution/risk บน M1 หรือ ticks ที่มีจริง ห้ามตรวจ stop เฉพาะตอน H1 ปิด ทั้งนี้ M1 ยังไม่บอกลำดับราคาในแท่งครบถ้วน

- buy เข้าที่ ask ออก bid; sell เข้าที่ bid ออก ask ไม่คิด spread ซ้ำอีกครั้งเมื่อ bid/ask รวมอยู่แล้ว
- commission ระบุ per-side/round-trip และ currency; swap/financing รวมเมื่อเกิด overnight โดยไม่ได้ตั้งใจ
- stop gap-through fill ที่ executable price ถัดไปพร้อม adverse cost; ห้าม fill ที่ stop เดิมทั้งที่ไม่มีราคาให้ซื้อขาย
- OHLC ชน stop และ target แท่งเดียวใช้ adverse ordering; ไม่ให้ pending signal ใช้ high/low ที่เกิดก่อน entry อย่างแน่นอนเมื่อไม่มี sequencing proof
- ledger มี balance, realized/unrealized PnL, liquidation-side equity, fees, margin, open risk และ order/fill events
- round lots ลงตาม step; หากต่ำกว่า minimum หรือ risk/margin เกินให้ skip ไม่ round ขึ้นเพื่อให้เปิดได้
- ใช้ contract-specific profit/margin calculation และ currency conversion; production เทียบกับ broker calculation ใน demo
- จำลอง reject/partial fill/latency อย่าง deterministic ตาม scenario; อย่าอ้างว่า OHLC ระบุ fill probability จริงได้

baseline cost ต้องมาจากข้อมูลที่ระบุได้; ถ้ายังไม่มีใช้ synthetic scenarios เพื่อทดสอบ engine เท่านั้น รายงานผลตลาดจะติด `cost_unverified` และห้าม promotion ค่า stress เช่น spread/slippage 1.5×/2× เป็นข้อเสนอให้ตรึงก่อน batch ไม่ใช่ข้อสรุปว่าครอบคลุม worst case

### Risk policy ของ demo

ยึดสเปก: 0.25% equity/trade, daily loss stop 1% day-start equity, drawdown halt 5%, provisional equity USD1,000 โดยต้องพิสูจน์ minimum-lot feasibility ก่อน

- risk/trade เป็น estimated loss ที่ stop รวม costs/buffer; gap/slippage อาจทำให้ realized loss เกินได้ ต้องรายงานตามจริง
- daily loss วัด equity รวม unrealized และปรับ deposits/withdrawals; กำหนด risk-day timezone ชัด ไม่ reset จากการ restart service
- drawdown ใช้ persistent high-water mark ที่ปรับ cash flows และห้าม agent reset เพื่อกลับมาเทรด
- หนึ่ง position รวมใน demo ระยะแรก; open/pending risk ต้องถูก reserve แบบ atomic ก่อนส่ง intent ป้องกันหลายคำสั่งผ่าน budget เดียวกัน
- cutoff หยุด entry, cancel pending และพยายาม close ตาม runbook; ถ้าตลาดปิด/หลุดเชื่อมต่อให้คง protection, halt, alert และ reconcile เมื่อกลับมา ไม่บันทึกว่าปิดแล้วหากไม่มี fill
- stop ที่ broker ต้องยืนยันติดจริง; หากติดไม่ได้ให้เข้าสู่ protection-failure policy และห้ามเปิดเพิ่ม

policy owner-managed, versioned และ read-only ต่อ agent ทั้ง backtest กับ runner ใช้ risk function เดียวกัน; evaluator ยังตรวจ breach อิสระ

## 9. Evaluation และการเรียนรู้จากหลักฐาน

### 9.1 Scorecard

แยก in-sample, walk-forward, holdout, demo, live ทุกครั้ง รายงาน net PnL/return, equity drawdown, trade count/exposure, profit factor, daily-return Sharpe, Calmar เมื่อ horizon เหมาะสม, worst day, tail loss, cost sensitivity และผลแต่ละ fold/regime

กรณี no trade, no loss, zero drawdown, invalid annualization ให้ `null + reason` แทน Infinity หรือคะแนนสมบูรณ์แบบ uncertainty ใช้ block resampling เมื่อข้อมูลพอและระบุ assumptions; DSR เป็น optional diagnostic ไม่เพิ่มตัวเลขที่ตรวจ assumptions ไม่ได้

### 9.2 Gates

- safety/data gate: leakage, unknown contract, missing costs, reproducibility fail, audit gap หรือ risk breach → rejected/quarantined ไม่จัดอันดับ
- research defaults จากสเปก: net >0, max DD ≤15%, PF >1.2, ≥100 trades และ stitched walk-forward net >0/DD ≤15%; Calmar >0.5 เมื่อระยะเวลารองรับการตีความ
- จำนวน 100 trades เป็นขั้นต่ำเชิงปฏิบัติ ไม่ถือว่า independent observations ครบโดยอัตโนมัติ
- robustness gate ตรวจ fold concentration, parameter neighborhood, equal-exposure comparison และ cost stresses โดย preregister quantitative thresholds ก่อน run; v1 กำหนดเป็น gate `not_configured` ที่ block promotion จน protocol ตรึงครบ
- ถ้า Calmar ตีความไม่ได้ให้ evidence status `insufficient` ไม่ข้ามเกณฑ์อัตโนมัติ

ผ่าน hard gates แล้วจึง rank ด้วย Calmar ของ non-overlapping stitched OOS เมื่อใช้ได้ และแสดง supporting metrics/uncertainty ไม่เลือกเพราะ aggregate ratio อย่างเดียว

### 9.3 Research reward

v1 ใช้ evidence vector ที่อ่านได้: gate status, baseline-relative net return/DD, fold consistency, complexity และ stressed costs ไม่เริ่มจาก weighted scalar ที่ตั้งน้ำหนักเพื่อเลือกผู้ชนะ หากเพิ่ม scalar ภายหลังต้องมี formula/caps/weights ใน versioned batch protocol เดียวกัน ห้ามปน holdout/demo/live เข้า iterative OOS reward

memory บันทึก hypothesis, experiment IDs, observation, uncertainty, alternative explanations, next falsifiable test; retrieval อ่าน scorecard ล่าสุดประกอบเสมอ ใช้ SQLite filters/text search และ fingerprints ก่อน embedding

เก็บทุก attempt รวม crash/abort/rejected source; count parameters, variants และ duplicate attempts ทั้งหมดใน multiple-testing ledger ใช้ budget 70/20/10 ตามสเปกเป็นสัดส่วนเวลา/จำนวนงาน และเปิด exploration เพิ่มเมื่อ seed pipeline นิ่งแล้ว

## 10. Registry, jobs และ reproducibility

entities หลัก: DatasetVersion, ContractSpecVersion, SplitManifest, CostModelVersion, EvaluationProtocol, RiskPolicyVersion, StrategyArtifact, Hypothesis, Experiment, Job, Scorecard, HoldoutAccess, Promotion, Deployment, OrderIntent, OrderEvent, DailyEquity, AgentMemory และ AuditEvent

manifest ของ experiment ต้องผูก source bundle/hash, parent, parameters, dataset/partitions, splits, costs, sessions, risk/evaluator hash, RNG seed, environment/lockfile/container digest และ Git commit เมื่อมีแล้ว

hash ผลลัพธ์เชิงตัวเลขและ canonical payload แยกจาก operational metadata เช่นเวลา run และ job ID เพื่อให้ replay ทำซ้ำได้จริง numeric tolerance ข้าม platform ต้องกำหนดไว้ ไม่กล่าวอ้าง byte-identical Parquet หาก writer metadata ต่าง

- strategy: draft → validated → registered → research-eligible; archived/rejected เก็บ lineage
- job: queued → leased/running → succeeded/failed/cancelled/timed_out; heartbeat/lease expiry ทำให้กู้ queue ได้
- promotion: requested → gates_passed → owner_authorized → deployed; denied/expired/revoked ทุก transition ถูก audit
- deployment: preparing → reconciling → active → paused/stopped/failed; restart ห้ามกลับ active ก่อน reconcile

SQLite ใช้ WAL + single writer ผ่าน control service; worker ไม่มีสิทธิ์แก้ DB ส่ง outputs ให้ controller validate ใช้ temp artifact → verify/hash → atomic finalize และ transaction อ้าง artifact ที่ครบแล้ว orphan outputs ถูกกัก ไม่รายงาน succeeded เมื่อผลไม่ครบ

dedup key ผูก strategy/data/config/evaluator identities; intentional repeat เป็น replay ที่เชื่อม original run ไม่ลบทิ้ง ใช้ DB uniqueness และ idempotency key ป้องกัน tool retries สร้าง experiment ซ้ำ

backup ใช้ SQLite online backup/checkpoint ที่ถูกต้อง ไม่ copy main DB โดยละเลย WAL; artifact backup มี manifest และ restore drill ตรวจ hash/replay ไม่มี credentials ใน report/log

## 11. แผนพัฒนา F0–F6

แต่ละระยะผ่าน engineering gate ก่อนขั้นถัดไป งาน broker feasibility ทำล่วงหน้าขนานกับ data ได้โดยยังไม่เปิดคำสั่งซื้อขาย

### F0 — Foundation, contracts และ risk charter

**งาน:** ยืนยัน Git boundary (แนะนำ repository ภายใน `qarevin/` หากไม่มี parent repo ที่เจ้าของตั้งใจใช้), Python/lockfile, CLI skeleton, typed contracts, environment profiles, explicit session/cost completeness flags, registry migration แรก, logging/redaction และ architecture/validation protocol

กำหนด threat model: untrusted candidate/data/peer text ไม่สามารถเปลี่ยน evaluator, policy, holdout หรือ secrets; เตรียม test profiles โดยไม่ต้องใช้เงินจริง ตั้ง resource preflight และ baseline measurement ของ host

**ส่งมอบ:** package ติดตั้งใน clean venv ได้, config examples ไม่มี secrets, synthetic fixtures, developer commands และ decision log

**Gate:** invalid/incomplete config fail ชัดเจน; research profile ไม่มี credential/order capability; no live service; permission/serialization tests ผ่าน ตั้ง version identities ได้จริง

### F1 — CSV, indicators, seeds และ deterministic backtest

**งาน:** import/QA/chunked Parquet, resampling, exact indicator conventions, frozen seed definitions, session logic, cost-aware event ledger, sizing และ synthetic broker constraints

**ส่งมอบ:** CLI ที่ตั้งใจใช้ `qarevin import`, `data qa`, `backtest`, `report`, `replay`; QA report + equity/trade ledger ของ seeds และ controls

**Gate:** hand-computed fills/PnL ถูกต้อง; การเปลี่ยน future bars ไม่เปลี่ยน signal/ผลอดีต; next-event execution, intrabar ambiguity, DST, gaps, lots และ costs ผ่าน; replay canonical results ตรงกัน

synthetic data ใช้ทำงานระยะนี้ได้ แต่จะผ่าน real-data readiness ได้ต่อเมื่อ owner CSV และ contract/cost metadata ตรวจแล้ว

### F2 — Independent evaluation, registry และ sealed holdout

**งาน:** frozen split manifests, rolling/nested selection, stitched OOS, metrics edge cases, gates, stresses, immutable lineage, attempt ledger และ candidate evidence report; แยก holdout storage/identity

**ส่งมอบ:** `walk-forward`, `evaluate`, `compare`, candidate report, restore/reproduction script และ promotion readiness status ที่แสดง missing evidence

**Gate:** reconstruct experiment บน clean environment ได้; metric fixtures ถูกต้อง; fail cases ไม่ผ่าน gate; research identity อ่าน holdout ทุกเส้นทางไม่ได้; owner เปิด holdout แล้วมี access record แม้ job ล้ม

ยังไม่ต้องเปิด holdout จริงเพื่อทดสอบ isolation ใช้ synthetic sealed dataset ได้ ไม่มีข้อบังคับว่าต้องมีกลยุทธ์ผ่าน research gate เพื่อถือว่า engine เสร็จ

### F3 — Hermes research loop ที่จำกัดขอบเขต

**งาน:** FastAPI control, scoped MCP, async job tools, sandbox, structured memory, fingerprint dedup, budget reservations, research/report triggers, separate Hermes home/container และ draft persona/skills

tools เริ่ม `market.list_datasets`, `research.propose`, `research.submit_candidate`, `research.run_backtest`, `research.run_walk_forward`, `research.get_job`, `research.cancel_job`, `research.get_result`, `research.compare`, `registry.get_lineage`, `registry.register_candidate`, `memory.record/get` และ `promotion.request_demo`

การ submit source ต้องเป็น bounded text/bundle ผ่าน schema ไม่เปิด shell ทั่วไป tools คืน job ID ทันที ไม่ block model รอ backtest ยาว การ import owner data ทำผ่าน owner CLI ก่อน

**ส่งมอบ:** ตัว agent อ่านผลจริง เสนอ hypothesis ลงทะเบียนก่อนทดลอง เปรียบเทียบ frozen baseline และเขียน memory ที่มี evidence links; default 3–5 runs/day จน benchmark ผ่าน

**Gate:** ≥20 autonomous research runs ครบวงจรและ audit ทุกครั้ง; budget/dedup/crash recovery ผ่าน; actual-agent injection evaluation ยืนยันว่าไม่ทำตาม external instructions และ server ปฏิเสธ policy/holdout/owner actions; sandbox blocked network/path escape/forged metrics/resource exhaustion

20 runs เป็น smoke coverage ของกระบวนการ ไม่เป็นหลักฐานว่ากลยุทธ์ดีขึ้น การสร้าง persona/skill ในระยะนี้ต้องอ้างอิง conventions ของ agents เดิมแต่ไม่คัดลอก permission model ที่ไม่ตรงงาน

### F4A — Broker feasibility และ demo execution engineering

**Dependency:** broker/terminal/bridge และ account contract ที่พิสูจน์แล้ว; research core ยังพัฒนาต่อได้หากส่วนนี้ติดภายนอก

**งาน:** fake adapter ก่อน selected adapter; verify account demo identity, symbol mapping, account netting/hedging, contract/margin/profit calculation, sessions, supported fill/protection modes, stop/freeze levels และ secured bridge

ลำดับ order: persist intent + risk reservation → send → inspect acceptance/fill → reconcile broker history; network timeout หลัง send เป็น `unknown` ไม่ retry blindly การมี `client_order_id` ในระบบเราไม่ได้แปลว่า broker รองรับ exactly-once ต้องมี single execution writer และ broker correlation/reconciliation

**ส่งมอบ:** demo runner, independent risk engine, watchdog, monitoring, order/fill ledger, kill/pause/flatten runbooks และ broker contract test report

**Gate:** reject/partial fill, restart ทุกจุดสำคัญ, stale quote, disconnect, duplicate delivery, wrong account, missing stop, disk/DB failure, daily-loss/DD halt และ late cutoff ผ่าน; open positions ถูก reconcile ก่อน new entry ไม่มี unprotected gap ที่ไม่มี policy รองรับ

ทดสอบ fault simulation ก่อน broker demo แล้วทำ controlled demo smoke ด้วย owner action สถาปัตยกรรม Windows terminal bridge เป็นทางเลือกหลักที่ควรสำรวจ ไม่สมมติว่ามี Windows host อยู่แล้ว Wine ต้องมี compatibility evidence และ maintenance plan ก่อนเลือก

### F4B — Demo forward evidence

**Dependency:** candidate ผ่าน F2 gates/controlled holdout protocol, F4A ผ่าน และ owner เปิด demo deployment

**งาน:** pin strategy/policy/dataset definitions; เก็บ quotes/fills/costs/equity; เทียบ matched shadow replay กับ actual demo; วิเคราะห์ drift และ execution gap; ส่งรายงานรายวัน/สัปดาห์

**Gate:** อย่างน้อย 3 เดือนปฏิทินจริงพร้อมจำนวน trades และ market states ที่ protocol ระบุว่าพอ; ไม่มี unresolved material reconciliation/risk issue; cost/latency differences อธิบายได้ และ evidence report ครบ

ถ้า strategy เปลี่ยนสาระสำคัญให้ version ใหม่และแยก forward cohort ห้ามต่อ equity หลายเวอร์ชันแล้วอ้างว่าเป็นผลของ artifact เดียว ถ้าไม่มี candidate ผ่านให้คง research ต่อภายใต้ budget หรือพัก ไม่เปิด demo เพื่อให้ตรง timeline

### F5 — Live approval workflow ซึ่งปิดโดยค่าเริ่มต้น

**Dependency:** demo evidence ผ่าน, actual broker live feasibility, owner-set capital/live-specific risk policy และ authenticated owner approval

**งาน:** signed, short-lived, revocable, one-time deployment authorization ผูก strategy hash, evaluator/evidence report, risk policy hash, account/server, environment, capital/notional cap; controller ตรวจเอง; แยก credentials/process/state และ versioned rollback

**ส่งมอบ:** owner-only approval action/หน้าเล็กตามความจำเป็น, evidence packet, limited rollout plan, rollback/kill rehearsal และ selected-broker validation

**Gate:** ไม่มี/ปลอม/หมดอายุ/ถูกใช้ซ้ำ/ถูก revoke/ผิด hash/account/capital/environment อนุมัติไม่ได้; agent token ไม่มี approve/deploy scope; halt/reconcile/persistent risk state ตรวจแล้ว owner จึงตัดสินใจเรื่อง live แยกอีกครั้ง

การพัฒนา workflow ไม่ถือเป็นอนุญาตให้เปิด live งานนี้ยังไม่เริ่มใน initial implementation batch

### F6 — Bounded continuous improvement

รักษา frozen champion และ challenger, เปรียบเทียบบน future windows เดียวกันโดยคำนึง overlapping exposure; เพิ่มข้อมูล forward แบบ versioned, review drift/costs/near-duplicate research และรายงาน lessons

ไม่มี autonomous champion replacement ใน live ทุก strategy/policy เปลี่ยนต้องผ่าน cycle เดิม; portfolio-level risk ต้องเพิ่มก่อนรันหลาย strategies พร้อมกัน

## 12. ลำดับ work packages และช่วงเวลาประมาณการ

หน่วยต่อไปนี้เป็น focused engineering days ของผู้พัฒนาที่คุ้นระบบ ไม่ใช่กำหนดส่งหรือเวลาที่ agent run ได้เองทั้งหมด และยังต้องปรับหลัง benchmark/data intake

1. **WP01 — Foundation/config/contracts:** 2–3 วัน; F0
2. **WP02 — Import/QA/time/resampling:** 3–5 วัน; พึ่ง WP01
3. **WP03 — Indicators + exact seed rules:** 2–4 วัน; พึ่ง WP01/02
4. **WP04 — Event engine/costs/risk accounting:** 5–8 วัน; พึ่ง WP02/03
5. **WP05 — Registry/replay/backup:** 3–5 วัน; schema เริ่ม WP01, integration หลัง WP04
6. **WP06 — Walk-forward/metrics/gates/reports/holdout:** 5–8 วัน; พึ่ง WP04/05
7. **WP07 — API/MCP/sandbox/Hermes loop:** 5–8 วัน; พึ่ง WP06
8. **WP08 — Broker feasibility/adapter/reconciliation:** 5–10 วันเมื่อเข้าถึง broker/terminal แล้ว; discovery เริ่มล่วงหน้าได้
9. **WP09 — Risk faults/monitoring/demo readiness:** 4–7 วัน; พึ่ง WP08 และ core risk
10. **WP10 — Forward validation:** อย่างน้อย 3 เดือนปฏิทินหลัง readiness; engineering effort เพิ่มตาม incident และ trade sample
11. **WP11 — Live approval + rehearsal:** ประเมินใหม่หลัง WP10 และเลือก capital/policy แล้ว

รวม research agent เส้นทาง WP01–07 ประมาณ 25–41 focused days; demo engineering เพิ่มประมาณ 9–17 วันก่อนเริ่มเก็บ forward evidence หาก CSV/contract/bridge พร้อม ช่วงที่กลยุทธ์ไม่ผ่าน gates อาจยืดไม่มีกำหนด งาน native MQL5 EA แยก estimate หลังยืนยันขอบเขต

ไม่สร้าง task จริงบน scheduler หรือเริ่ม agent เพิ่มจากเอกสารนี้ การทำงานอัตโนมัติจะติดตั้งเมื่อ F3 พร้อมและมี budget configuration

## 13. First implementation batch ที่แนะนำ

แบ่ง first PR ที่สเปกเสนอออกเป็นชิ้นเล็กเพื่อให้ reviewer ตรวจ math/time semantics ได้ แต่ยังคงเนื้องานครบตามเป้าหมายเดิม:

1. **Batch A:** package/CLI/config/schema, Git/version identities, sample dataset manifest, permission/resource profiles และ synthetic fixtures
2. **Batch B:** CSV importer/QA/resampler + timezone/DST/completeness tests + owner-facing import report
3. **Batch C:** S1 + no-trade + minimal M1 execution ledger/cost/sizing + golden accounting/replay/no-look-ahead tests
4. **Batch D:** S2/S3 และ controls, edge/fault scenarios, immutable baseline reports
5. **Batch E:** walk-forward, registry completion, `evaluate/report`, split/holdout isolation และ reproducibility package

สิ่งที่ owner จะตรวจได้หลัง Batch C คือ import → QA → H1 signals → next-quote fills → equity/fees/risk report → replay ด้วย input เดิม นี่เป็นจุดตรวจ engine ก่อนให้ LLM เริ่มเปลี่ยนกลยุทธ์

## 14. Test strategy และหลักฐานที่ต้องเก็บ

เลือกตรวจกลไกที่เสี่ยง ไม่เขียน test ที่เพียงยืนยันชื่อไฟล์หรือสะท้อน implementation

- **Data:** corrupted CSV, duplicate conflict, mixed timezone/DST, missing session, incomplete resampling, preserved hashes และไม่ fabricate bars
- **Causality:** append/change future data แล้ว historical features/signals ไม่เปลี่ยน, Donchian exclude current bar, no execution ก่อน signal availability
- **Accounting:** golden trades long/short, bid/ask/cost units, gap stop, stop/target collision, min lot, margin, negative equity และ cash-flow-adjusted DD
- **Evaluation:** no-trade/zero-loss/null metrics, split boundary/warmup, stitched OOS, failed gate, tampered artifacts และ frozen evaluator version
- **Agent/control:** invalid schema, unauthorized action, budget racing/retries, duplicate trial, malicious source, forged output, holdout escape และ actual model prompt injection scenarios
- **Execution:** unknown send result, partial fills, restart/reconcile, manual external position, wrong account/server, stale quote, missing protection และ outstanding order risks
- **Approval:** owner identity, signature, expiry, replay/revoke และ scope binding ทุก field
- **Operations:** OOM/timeout/disk-full, SQLite migration/restore, failed alerts with durable event queue และ clean-host replay

offline suite ต้องไม่ใช้ model, network หรือ broker; opt-in integration suite แสดง dependency และสถานะ skipped ชัดเจน actual-agent eval กับ demo-broker tests รายงานแยกจาก unit pass

ทุก milestone มี command ที่รันได้จริงใน README เมื่อ code เกิดขึ้น, artifact/evidence path, config hashes, results และ unresolved limitations ปัจจุบันยังไม่มี pytest suite ให้รัน จึงไม่ถือว่า plan นี้ผ่าน implementation tests แล้ว

## 15. Resource และ operations budget

เริ่ม benchmark CLI process บน synthetic/real partitions ก่อนเปิด Hermes container เพิ่ม บันทึก peak RSS, wall time, disk writes, host available memory และ swap pressure ร่วมกับงานเดิม

- concurrency หนึ่ง CPU-heavy job, จำกัด BLAS threads และ CPU quota; initial job cap เสนอ 15 นาที ปรับด้วย benchmark ก่อน full-history walk-forward
- trial sandbox เสนอ memory cap 512–768 MiB เฉพาะ workload ที่พิสูจน์ว่าอยู่ได้; trusted engine budget แยกและต้องไม่ทำให้ host memory reserve ต่ำกว่าเกณฑ์เริ่มงาน
- preflight เสนอ available-memory reserve อย่างน้อย 1 GiB **หลัง** เผื่องานที่จะเริ่ม หากไม่ผ่านให้ job queued/deferred ไม่เริ่มจน OOM
- ใช้ chunked CSV import และ Parquet column/partition reads; โหลดเฉพาะช่วง/fold ที่จำเป็น ไม่ copy M1 สิบปีหลายชุดเข้าหน่วยความจำ
- หนึ่ง daily experiment budget + compute wall-time + source/output size + LLM token/cost cap; warning 70%, stop 100% เป็น initial operational proposal และต้องมี config ที่ตั้งจริง
- ถ้า quota ใช้หมดระหว่าง job ให้ cancel ที่ safe boundary และเก็บ partial evidence/status; execution safety/watchdog ไม่หยุดตาม research token budget
- หาก resources ยังไม่พอ ให้ batch บน research window ที่กำหนดหรือย้าย worker ไปเครื่องอื่นก่อนเพิ่ม parallelism; ห้ามลด fidelity/ตัด costs เงียบ ๆ

Hermes image ต้อง pin digest เมื่อ smoke test ผ่าน ไม่ใช้ `latest` เป็น reproducibility identity ระยะยาว; networks ให้ Qarevin เข้าถึงเฉพาะ API ที่จำเป็น ไม่ join peer/search network โดยอัตโนมัติ

ใช้ Telegram สำหรับสนทนาตาม pattern เดิมได้ Discord reports/alerts เป็น option เมื่อเลือกช่องทางแล้ว แยก delivery จาก durable audit; critical alert มี retry/escalation/ack state จึงยังตรวจพบได้แม้ chat ส่งไม่สำเร็จ ไม่สร้าง bot หรือส่งข้อความจากขั้นวางแผน

## 16. Decision register และ external dependencies

### ต้องชัดก่อนใช้ market data ประเมินจริง

- CSV ตัวอย่าง, coverage, source timezone/offset history, bid/ask basis และสิทธิ์ใช้ข้อมูล — owner/data provider; ตอนนี้พัฒนา synthetic pipeline ต่อได้
- tick size/value, lot/step, commission/swap, account currency, contract history — broker/owner; unknown ให้ block economic claims
- exact seeds, session/cutoff และ split/evaluation/robustness thresholds — implementer เสนอและตรึง protocol ก่อน tuning
- ช่วง holdout เคยถูก owner หรือระบบอื่นใช้เลือกกลยุทธ์หรือยัง — owner ยืนยัน provenance; ถ้าใช้แล้วต้องบันทึก contamination ตามจริง
- version-control boundary และ runtime backup destinations — ตัดสินใน F0

### ต้องชัดก่อน F4 demo

- Python runner เพียงพอหรือจำเป็นต้องส่ง native MQL5 EA — default ตามสเปกเป็น Python; ถ้า native จำเป็นให้แก้ work packages ก่อนผูก execution architecture
- broker demo, supported jurisdiction/account, symbol mapping และ Windows terminal/secured bridge หรือ API ที่ใช้ได้จริง — ไม่แนะนำ broker โดยไม่มี requirements
- session calendar, close/cancel cutoff, timezone ของ daily risk reset, Friday/holiday behavior และ protection-failure/flatten policy
- demo capital/minimum lot feasibility, portfolio/open-risk cap และ alert recipient/channel

### เลื่อนไปหลังมี demo evidence

- live capital, leverage/margin constraints, live risk limits, owner authentication/approval mechanism และ rollout cap
- multi-strategy portfolio deployment, automatic data acquisition, native MQL5 export หากยังไม่ใช่ core requirement, และ advanced statistical diagnostics

ไม่มี decision ข้างต้นจำเป็นต้องขอ credentials เพื่อวางแผนหรือพัฒนา offline หากภายหลังต้องรับ secrets ให้ใช้ช่องทาง private secret entry ไม่ใส่ใน chat/docs/repository

## 17. ข้อจำกัดสำคัญและการตอบสนอง

- **M1 ambiguity / insufficient costs:** ใช้ conservative scenarios และติด limitation; ถ้าผลขึ้นกับ assumption มากให้ reject promotion หรือหาข้อมูล ticks เพิ่ม
- **Minimum lot ใหญ่กว่า risk budget:** skip order หรือ owner เลือก demo setup ที่เหมาะสม ห้ามเพิ่ม risk เงียบ ๆ
- **Historical winner จากการลองซ้ำ:** preregister/count ทุก attempt, frozen controls, holdout access control และ future demo; ไม่อ้างว่า statistical correction ล้าง selection bias ได้ทั้งหมด
- **MT5 unavailable บน host:** offline research ยังเดินได้ broker milestone รอ proof-of-connection แยกจาก strategy score
- **Malformed/generated strategy:** isolation และ trusted evaluation/risk; การตรวจ AST เป็นเพียง defense เพิ่ม ไม่ใช่ sandbox boundary
- **Broker ไม่รองรับ idempotency:** persistent intent + single writer + reconciliation; unknown state block entry ไม่รับประกัน exactly-once จาก client ID อย่างเดียว
- **No profitable candidate:** ถือเป็น research result ที่ยอมรับได้ เก็บ negative evidence และหยุด/ทบทวนตาม budget
- **Resource contention:** defer jobs และแจ้งเหตุ ไม่ restart agent อื่นหรือเพิ่ม swap/limits จากการคาดเดา

## 18. Traceability กลับไปยัง specification

- Spec §1–4 → เป้าหมาย/ขอบเขต/architecture/layout ในแผน §1–5; F0
- Spec §5 → data/time/splits/holdout ใน §4.3 และ §6; F1–F2
- Spec §6–7 → exact seed proposals และ execution semantics ใน §7–8; F1
- Spec §8–9 → metrics/gates/reward/anti-overfit ใน §9; F2–F3
- Spec §10–11 → registry/memory/tools/budgets/sandbox ใน §4, §9–11, §15; F2–F3
- Spec §12 → adapter/risk/reconciliation ใน §8 และ F4A
- Spec §13 → live evidence/owner authorization ใน F4B–F5
- Spec §14 → alerts/backups/kill/restore ใน §10, F4A, §14–15
- Spec §15–18 → phase gates/work packages/first batches ใน §11–14
- Spec §19 → การแยก memory, evidence และ profitability ตลอดแผน

candidate live report ใน F5 ต้องมีครบ: human-readable strategy/diff/hash, dataset/QC/splits, trial count/holdout openings, all metrics/stresses, demo fills/duration/trades, uncertainty/alternative explanations, exact account/capital/policy, correlated exposure, rollback และ authenticated owner authorization

## 19. เอกสารอ้างอิงที่ตรวจเพิ่ม

ตรวจเมื่อ 6 พฤศจิกายน 2026 เฉพาะประเด็น implementation ที่เกี่ยวกับ MT5; ไม่มีการตรวจ broker/account ของเจ้าของในขั้นนี้

- [MetaQuotes — Python Integration](https://www.mql5.com/en/docs/python_metatrader5): package ติดต่อ MT5 terminal ผ่าน interprocess communication; จึงต้องมี terminal integration ที่ตรวจจริง ไม่ถือว่า pip install บน Ubuntu แล้ว execution พร้อม
- [MetaQuotes — copy_rates_range](https://www.mql5.com/en/docs/python_metatrader5/mt5copyratesrange_py): history availability และ UTC semantics ของ API ต่างจากการอนุมาน timezone ของ export CSV
- [MetaQuotes — Symbol Properties](https://www.mql5.com/en/docs/constants/environment_state/marketinfoconstants): contract/volume/fill mode ต้องอ่านจาก symbol จริง ไม่ hardcode gold ทุก broker เหมือนกัน
- [MetaQuotes — order_send](https://www.mql5.com/en/docs/python_metatrader5/mt5ordersend_py): request/result ของ terminal เป็นส่วนหนึ่งของ order lifecycle; เก็บผลและ reconcile แยกจากการสร้าง intent
- [MetaQuotes — Testing Trading Strategies](https://www.mql5.com/en/docs/runtime/testing): modes ที่ใช้ generated ticks/Minute OHLC เป็นการจำลองที่มีข้อจำกัด ต้องบันทึก mode และ data provenance ในงาน native EA parity

ขั้นถัดไปที่แผนรองรับคือ Batch A ของ F0 จากนั้น Batch B ด้วย synthetic CSV โดยยังไม่ต้องมี broker, Telegram token หรือบัญชีเงินจริง
