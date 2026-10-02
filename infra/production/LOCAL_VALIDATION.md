# Local validation — 2026-10-02

สถานะ: **เตรียม code/infrastructure สำหรับ review; ยังไม่ได้ provision หรือ Go live**. ผลนี้ทดสอบ working tree ที่มีงานอื่นร่วมอยู่ด้วย ไม่ใช่ immutable release digest และไม่ใช้แทน production evidence gates.

| ตรวจ | ผล |
|---|---|
| Backend suite, PostgreSQL 16 DB แยก `volt_prd_validation`, Python 3.12 | 2,239 passed / 14 skipped / 1 warning, 325.55s |
| Production regressions หลังขยาย child assignment guard ครั้งสุดท้าย | 44 passed / 1 warning, 5.19s |
| Frontend | 59 files / 356 tests passed |
| Frontend production build | Passed; มี warning bundle เกิน 500 kB |
| Terraform validate | Passed |
| Terraform mock plan | 2 passed; ไม่มีการสร้าง GCP resources |
| npm / Python dependency audits | ไม่พบ known vulnerabilities ใน dependency versions ที่ตรวจ; ไม่ครอบคลุม scanner OS image |
| git diff --check | Passed |

Backend full suite รันก่อนขยาย child-identifier assignment guard ครั้งสุดท้าย; หลังแก้ได้ตรวจชุด production regressions ซึ่งรวม HTTP auth/assignment, commit/rollback, two-process writes, sessions, durable jobs/uploads/schedule, scanner boundary และ release gates แล้ว. Full suite มี skip จึงไม่กล่าวว่าทุก test scenario ผ่าน. ต้อง rerun pipeline จาก clean reviewed release commit และ images จริงก่อน promote.

Logs และ SHA-256 อยู่ใน [validation artifacts](../../output/production-validation-2026-10-02/checksums.json). ไม่มี credentials/token จริงใน artifacts เหล่านี้.

ต้องพิสูจน์เพิ่มก่อน Go live: frontend form version/idempotency integration, browser role/session E2E, scanner/signature refresh จริง, GCP IAM/OIDC/DNS/OAuth, 10-user 2-hour load/soak พร้อม background import, Cloud SQL failover/PITR restore/RPO/RTO, migration rollback, alert delivery และ reconciliation ข้อมูลจริง. Global mutation lock ยังครอบ import ทั้งงาน; ต้องแก้ critical section หากทำให้ load gate ไม่ผ่าน.

รอ external inputs ตามแผนช่วง B: billing authorization/approved budget, DNS access, incident recipients/owner, data approver และ production OAuth configuration. ราคาประมาณและ spec อยู่ใน [COST.md](COST.md); ขั้นตอน candidate/cutover/rollback อยู่ใน [README.md](README.md).
