# Import Data — Data Flow Diagrams

> Source of truth for how imported data reaches every feature, after the sync work of
> 2026-09-20 (`app/refresh.py`, `app/import_sync.py`, `app/data_epoch.py`,
> `landing.import_unmapped`). Companion viewer: `docs/import-data-flow.html`.

## 1 — Overview: sources → landing → served book → features

```mermaid
flowchart LR
  subgraph SRC["แหล่งข้อมูล · DataSources screen"]
    P["PEAK invoice report file<br/>PeakIntake.jsx"]
    O["Odoo orders<br/>sync / use-snapshot / use-sheet"]
    C["Odoo crm.lead<br/>pull :start / :run / 15-min schedule"]
    M["manual upload<br/>/v1/imports"]
  end

  P -->|"POST .../peak-report:start (raw file)"| PS["peak_service.run_upload<br/>parse → lock → match → write"]
  C -->|"POST /pipelines/crm-lead:start · :run"| CS["pipelines/service._land<br/>ingress → normalise → writer"]
  O -->|"POST /integrations/odoo:sync"| OS["odoo.sync<br/>sale.order → write_landing"]
  M --> MS["staged ใน session เท่านั้น<br/>ruling 73 — ไม่แตะ landing"]

  PS --> L
  CS --> L
  OS --> L

  L["landing schema<br/>import_run · customer · order<br/>peak_invoice · import_unmapped"]
  L --> R["refresh.after_landing(kind, run_id)<br/>seam เดียวของทุกทางนำเข้า"]
  R --> B["main.CUSTOMERS / IDENTITIES<br/>BY_CUSTOMER / BY_CONTRACT"]
  R -->|"data_epoch.bump()"| E["app.data_epoch<br/>ตัวนับกลาง"]

  B --> F1["Today · Book · Record · workbook"]
  B --> F2["cases · journey · recovery"]
  B --> F3["invoice_pipeline<br/>การ์ดก่อนติดตั้ง"]
  B --> F4["reports · calendar · dashboard"]

  E -.->|"X-Volt-Data-Epoch ทุก response"| H["session heal<br/>import_sync.ensure_current()"]
  H -.->|"reseed เฉพาะของ import"| B

  MS -.->|"ไม่ bump epoch"| M

  classDef store fill:#fff7dc,stroke:#f2b705,color:#111827;
  classDef seam fill:#dbeafe,stroke:#1d4ed8,color:#111827;
  classDef blocked fill:#f3f4f6,stroke:#818995,color:#4b5563,stroke-dasharray:4 3;
  class L,E store;
  class R,H seam;
  class MS blocked;
```

**อ่านภาพ:** ทุกไฟล์/การ pull ลง `landing` ก่อนเสมอ แล้วผ่าน seam เดียว (`refresh.after_landing`)
ที่ rebind สมุดงาน + bump epoch. Manual upload เป็นข้อยกเว้นโดย ruling 73 (staged, ไม่กระทบสมุดงาน)

---

## 2 — PEAK report: upload → apply → serve (sequence)

```mermaid
sequenceDiagram
  autonumber
  participant UI as PeakIntake (FE)
  participant R as routers/peak_pipeline
  participant S as peak_service
  participant DB as landing (Postgres)
  participant RF as refresh / import_sync

  UI->>R: POST .../peak-report:start (ไฟล์ + X-Volt-Filename)
  R-->>UI: 202 + uid (watch)
  R->>S: run_upload (background thread)
  S->>DB: import_run RUNNING (durable ก่อน parse)
  S->>S: parse → fingerprint check → pg advisory lock
  alt ไฟล์ซ้ำ หรือมีรอบทำงานอยู่
    S-->>UI: 409 peak_duplicate_report / peak_run_in_progress
  else ปกติ
    S->>S: match ladder (book + Odoo phone + links)
    S->>DB: peak_invoice (COPY) + rejected → import_unmapped
    S->>DB: finish_run OK
  end
  loop poll ทุก 2 วินาที
    UI->>R: GET .../runs/{uid}
  end
  UI->>R: POST .../{id}:apply
  R->>DB: stamp meta.applied
  Note over R,DB: refuse: already_applied · older · narrower · report_already_applied (force = manager)
  R->>RF: after_landing("peak", id)
  RF->>DB: main.reload_book() + epoch bump (note_book_epoch ด้วย)
  RF->>RF: import_sync.heal_session() + mark_seen — heal ครั้งเดียวต่อ epoch
  R-->>UI: {served, moved_cases, refreshed_cases, note_th}
  opt served = false
    UI->>R: POST .../{id}:refresh-served (ปุ่มซ่อม)
    R->>RF: after_landing ซ้ำ (idempotent)
  end
  UI->>R: POST /links (confirm / retire)
  R->>RF: after_landing("peak-link") — เปลี่ยนเจ้าของ invoice ได้โดยไม่อัปใหม่
```

---

## 3 — Odoo: crm.lead pull + orders sync

```mermaid
sequenceDiagram
  autonumber
  participant UI as DataSources (FE)
  participant R as routers/pipelines · integrations
  participant W as ingress + writer / odoo.sync
  participant DB as landing
  participant OS as orders store (per session)
  participant RF as refresh
  participant MB as main book

  UI->>R: POST /pipelines/crm-lead:start {source: odoo, mode}
  R->>W: search_read crm.lead (paged 500)
  W->>DB: upsert customer / order (NEW_ONLY ข้ามที่ match · OVERWRITE ลง overwrite_ledger)
  R->>RF: after_landing("crm-lead")
  RF->>MB: reload_book + epoch bump → ทุกจอเห็นชุดใหม่ไม่ต้อง restart

  UI->>R: POST /integrations/odoo:sync
  R->>W: sale.order search_read → write_landing (run ODOO)
  R->>OS: set_odoo_rows (เฉพาะ session นี้)
  R->>OS: reconcile_source + reconcile_overrides (key = volt_id ไม่ใช่ no ตำแหน่ง)
  R->>RF: after_landing("odoo")
  R-->>UI: {synced, served, serve_problem, reconciled}

  UI->>R: POST /integrations/odoo:use-snapshot
  R->>DB: landing.last_run(ODOO) + meta.door → บอกว่าชุดไหน
  R->>OS: set_odoo_rows + reconcile
```

---

## 4 — Session auto-heal (คำขอถัดไปเห็นข้อมูลใหม่เสมอ)

```mermaid
sequenceDiagram
  autonumber
  participant A as เบราว์เซอร์ A (ผู้ใช้กด apply)
  participant B as เบราว์เซอร์ B (session อื่น)
  participant MW as tester_session middleware
  participant IS as import_sync
  participant DB as data_epoch + landing
  participant ST as session stores

  A->>DB: apply PEAK / pull crm.lead → refresh.after_landing
  DB-->>DB: epoch = epoch + 1
  B->>MW: GET /v1/today (คำขอถัดไปของ B)
  MW->>IS: ensure_current()
  IS->>DB: current() เทียบ seen_epoch ของ session B
  IS->>ST: heal_session()
  Note over ST: journey.reseed_peak / reseed_migrated_invoices<br/>invoice_pipeline.reseed_from_book<br/>cases.follow_import_for_all / peak_documents.reconcile<br/>ของที่คนทำ (slip/PTP/evidence/gates/release) ไม่ถูกแตะ
  IS->>ST: seen_epoch = epoch
  MW-->>B: 200 + X-Volt-Data-Epoch
  B->>B: DATA_EPOCH_EVENT → useReloadOnEpoch() → refetch จอที่เปิดอยู่
  opt ผู้ใช้ไม่อยากรอ
    B->>MW: POST /v1/session:refresh-imports (ปุ่มบน DataStaleBanner)
  end
```

---

## 5 — State ownership (ใครเป็นเจ้าของค่าอะไรหลัง heal)

| Store | ค่าที่ "import" owns → รีเฟรช | ค่าที่ "คน" owns → คงไว้ |
|---|---|---|
| `journey.state` | PEAK invoices/receipts, ยอด/กำหนด SHEET invoice | slip, PTP, contact, released pipeline invoice |
| `cases.state` | `sheet` snapshot, `payment_status(_system)`, `next_action` เมื่อ set by SEED/MAPLOG | dc_status/NPL/person next action, PTP, contact log, ticket, review |
| `invoice_pipeline.state` | ชื่อ, EPC, planned date, ยอดที่ยังไม่ถูกยืนยัน, การ์ดใหม่ | evidence, gates, history, delivery, released |
| `peak_documents.state` | flag `source_missing` จาก reconcile | สถานะเอกสาร, transport, idempotency key |
| `orders.*` | reconcile กับชุดที่ serve (volt_id) | approvals/added/removed ของ session นั้น |
| `imports.state` (manual) | — (staged อย่างเดียว) | ทั้งหมด — ไม่มี epoch, ไม่แตะ landing |
