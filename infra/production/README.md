# Volt Debt production — small team, Regional HA

## สถานะ

ชุดนี้แยกจาก `infra/terraform` เดิมและปฏิเสธ project staging `dept-collection-508109`. เป้าหมาย ≤10 concurrent users; SQL PostgreSQL16 Enterprise Regional HA 2 vCPU / 8 GiB, SSD20 GiB auto-grow. รายละเอียดราคาอยู่ใน [COST.md](COST.md). **ยังไม่ได้ provision, deploy หรือเปิด `debt.volt.co.th`.** Terraform validate ไม่ใช่หลักฐานว่ามี resource หรือว่า application ผ่าน SLA.

ต้องยืนยัน billing account/วงเงิน, DNS provider และสิทธิ์, incident owner/email, Google OAuth production origin และผู้รับรองข้อมูลจริงก่อน provision/cutover. พบ billing account เปิดใช้งานหนึ่งบัญชี แต่ยังไม่ถือว่าได้รับอนุมัติให้ใช้. ชุดข้อมูล production เริ่มว่าง; ไม่ copy staging DB.

## Resource และ application

| Workload | ขนาด | Min / Max | Concurrency |
|---|---|---|---|
| API | 1 CPU / 2 GiB | 1 / 3 | 4 |
| Web | 1 CPU / 256 MiB | 0 / 2 | 80 |
| Worker | 1 CPU / 2 GiB | 0 / 1 | 1 |
| Scanner | 1 CPU / 3 GiB | 0 / 1 | 1 |

HTTPS LB → serverless NEGs → web/API; Cloud Armor Standard; private SQL + Direct VPC egress + fixed NAT IP for Odoo. Runtime IAM database usersแยก API/worker; migration มี admin secret แยก. Buckets private uploads/clean/documents/exports, build-source และ state แยก. Secret versions และ image digestsต้อง pin ตัวเลข/sha256.

Business Stores ใช้ shared versioned JSON records ใน `app.business_record`; ค่า `criteria.default` และ private report snapshots แยกตาม subject. ตาราง `records`/`landing` ที่มีอยู่ยังใช้ตามเดิม. Adapter นี้ยังไม่ใช่การ normalize ทุก workflow เป็น domain-specific relational tables. ไม่มีการ deserialize staging pickle ใน production.

Mutation ใช้ PostgreSQL advisory transaction lock และ transaction ครอบ business/audit/version; response ถูก buffer จน commit. `If-Match: <x-volt-state-version>` ตรวจข้อมูลเก่า; `Idempotency-Key` ที่เดิมและ request เดิม replay ผลที่ commit แล้ว. Key เดิมกับ request ต่างกันตอบ409. Client integration ของ optimistic concurrency ต้องพิสูจน์ใน role E2E; header support อย่างเดียวไม่พิสูจน์ว่าแบบฟอร์มทุกหน้าเก็บ version ที่ถูกต้อง.

GET ใช้ snapshot transactionและไม่ flush business Stores; progress/cancellationอ่านจาก DB. Workers publish progress แยกจาก business commit และใช้ run/outbox UID เดิมสำหรับ retry. ปัจจุบัน lock ของ mutation ยังครอบ import ทั้งงาน: ต้องวัดความขัดแย้งกับ interactive writes และลดช่วง critical section หาก load gate ไม่ผ่าน. ห้ามลดเกณฑ์ทดสอบเพื่อให้ผ่าน.

Tab token อยู่ใน sessionStorage เท่านั้น; DB เก็บ hash, revoke และ account status. ไม่มี idle/absolute expiry. Logout เพิกถอนแท็บเดียว; disableบัญชีมีผลกับ request ถัดไป. Reload/sleep/offlineไม่ล้าง token. sessionStorageอาจถูก copy เมื่อ duplicate tab และกู้คืนโดย browser restore; ต้องบันทึก behavior ใน browser E2E. ปิดแท็บไม่ได้ลบ recordฝั่งserverทันที. CSP และ noopenerลดความเสี่ยงที่เกี่ยวข้อง.

Production assignment guard ตรวจ OFFICER จาก session ฝั่ง server เทียบกับผู้รับมอบหมายใน case สำหรับ mutation ที่อ้าง `customer_uid`, `customer_uids`, `contract_uid` หรือ `case_uid`; contact/PTP/review/issue/power/today identifiers ตรวจผ่าน customer ของ record แม่ และ legacy contact retraction ตรวจจาก customer identity. Path identifier มีลำดับเหนือ body; ปลอม role/header หรือเปลี่ยน customer ใน body ไม่ข้าม guard. การทดสอบ HTTP กับ PostgreSQL ผ่านสำหรับการปฏิเสธ direct customer และ unit tests ผ่านสำหรับ child identifiers ที่ตรวจพบ. ยังต้องตรวจ matrix ทุก endpoint/role ด้วย browser E2E ก่อนเปิดจริง; guard นี้ไม่ได้เป็นหลักฐานว่า authorization ทุก workflow ผ่านแล้ว.

PEAK outbound/API report doorปิด; ใช้ไฟล์. Penalty invoicingปิดใน production. ไม่มี in-process Odoo timers. Scheduler relayทุกนาที; Odoo cadenceอยู่ใน `app.schedule_config`, เริ่ม disabled, Manager/Ownerเปิดผ่าน routeเดิมหลังตรวจ credentials/NAT/source-of-truth. เวลา Scheduler Asia/Bangkok.

## เตรียมและ provision

1. แยก release commitที่ผ่าน reviewออกจาก working treeงานอื่น. Buildใช้ full40-character Git SHA. เก็บ previous production digest/schemaไว้. ห้ามใช้ staging revisionเป็น rollback targetของ tab-session production.
2. ตรวจ availability ของ project ID และ organization policies. เมื่อได้รับ billing authorizationแล้วสร้าง dedicated projectและผูก billingด้วย explicit project flags; ห้ามเปลี่ยน gcloud default project.
3. Bootstrap state bucket `${PROJECT}-tfstate` ใน Singapore: uniform bucket-level access, public access prevention, versioning; จำกัด state accessให้ deployment operators. เก็บ backend configนอกgit. Stateมีข้อมูล infrastructureที่ต้องจำกัดสิทธิ์.
4. Copy `production.example.tfvars` เป็น local ignored `production.tfvars`. ใส่ project/billing/incident emailsที่ยืนยันแล้ว; คง `enable_workloads=false`, `enable_migration=false`, `go_live=false`. `monthly_budget=15000` เป็นค่าเสนอ ไม่ใช่ spending approval.
5. `terraform -chdir=infra/production init -backend-config=bucket=${PROJECT}-tfstate`; จากนั้น `python infra/production/release.py plan --vars /ABS/production.tfvars --out /ABS/foundation.tfplan`. Reviewทั้งรายการและราคา; ไม่มี delete/replacement/staging addresses. ใช้ `release.py apply --plan ... --reviewed-sha256 ...` กับไฟล์ที่ตรวจแล้วเท่านั้น.
6. เติม Secret Manager versions ผ่าน stdin/APIที่ไม่ใส่ valuesลง command/log: AUTH_SESSION_SECRETแบบสุ่ม, AUTH_ALLOWLISTผู้ใช้จริง/role/officer, GOOGLE_CLIENT_ID, ODOO_URL/DB/LOGIN/API_KEY และ MIGRATION_DATABASE_URLของ dedicated SQL admin. ไม่เติม AUTH_TEST_ACCOUNTSหรือ PEAK_UAT secrets. ห้ามเก็บ secret valuesใน tfvars/state. Runtimeมีเฉพาะสิทธิ์ secretที่ต้องใช้; migration URLมีให้ migrationเท่านั้น.
7. เพิ่ม `https://debt.volt.co.th` เป็น Google authorized JavaScript origin; อนุญาต NAT IPใน Odoo. DNS A recordไป output `load_balancer_ip`; รอ managed certificate ACTIVE. ตรวจว่า ingress direct Cloud Run bypassไม่ได้และ worker/scannerปฏิเสธ unauthorized requests.

## Build → migrate → candidate

1. Cloud Build custom SA `debt-build` มี registry writer, source bucket viewer, exports creatorและlog writer. Operatorต้องมี actAsต่อSAนี้และสิทธิ์submit build. ใช้ `gcloud builds submit --project "$PROJECT" --config infra/production/cloudbuild.yaml --gcs-source-staging-dir "gs://$PROJECT-build-source/source" --substitutions "_RELEASE=$FULL_SHA" .` จาก clean reviewed checkout.
2. Pipelineเริ่ม PostgreSQL16สำหรับ integration tests, รัน backend/frontend testsและproduction build แล้ว build/push API, webและscanner. ส่ง `release.json`ที่มี immutable digestsพร้อม backend junitไป exports. ไม่มี auto-deploy/migration/trafficใน build pipeline.
3. ใส่ digestsและnumeric `secret_versions`ในlocal tfvars. เปิด migrationก่อน: `enable_migration=true`, workloadsยังfalse. Review/apply plan แล้ว `release.py migrate --project "$PROJECT"`; jobใช้API digestเดียวกันและgrantทั้ง API/worker rolesผ่านDB_RUNTIME_ROLES. Migrationล้มเหลวต้องหยุด.
4. เปิด `enable_workloads=true` โดย `go_live=false`. Owner/OPSเตรียมข้อมูลได้; cohortบัญชีGoogleจริงที่ระบุ `candidate_test_subjects` ทดสอบworkflowตามroleได้; คนอื่นยังmaintenance. ไม่ seedบัญชีtest. Outbox relayทำงานใน candidateเพื่อทดสอบ imports; auto Odoo tickยังไม่ทำงานจน go_live=true.
5. Smoke `/readyz`, `/api/v1/auth/config`, Google login, `/api/v1/auth/me`, workbookและprivate job/scanner. Tokenไม่ลงURL/log/localStorage. Uploadไฟล์EICARต้องถูกปฏิเสธและscanner downต้อง503; clean objectอยู่GCS ไม่อยู่SQL bytes. วัด scanner startup/signature refreshจริง; Docker sourceที่เตรียมไว้ยังไม่เป็นหลักฐานว่าผ่าน ClamAV end-to-end.

## เกณฑ์ก่อนเปิดจริง

- Backend/frontend tests, dependency audits, clean production build, role E2E และ assignment enforcementทุก business mutation. ทดสอบ2บัญชีแก้ recordเดียวกัน, old version409, no duplicate/lost write และ audit/versionตรงcommit.
- Session: idle>30m, elapsed>8h, reload, offline/sleep, tab close/open, restore, duplicate, logoutแท็บเดียว, disableบัญชีและrollbackระหว่างมีsession. Unit testเลื่อนนาฬิกาไม่ทดแทน browserจริง.
- Load/soak10 concurrent users ≥7200s ด้วยข้อมูลเท่าของจริง, representative reads/writesและbackground import. workbook p95≤2s, unexpected5xx<0.5%, zero lost/duplicate writes/OOM. `scripts/load_test_workbook.py`อ่านอย่างเดียวและใช้Bearerเดียว ไม่ถือว่าเป็นหลักฐานโหลดทั้งระบบ. ห้ามส่ง tokenผ่านcommand lineในการทดสอบ production; ใช้secret environment/fileที่permission0600กับrunnerที่ออกแบบสำหรับหลายบัญชี.
- ตัดDB connection, restartAPI/worker, duplicate Tasks, kill workerระหว่างparse/apply/หลังcommit; ดูoutboxและoperation_runว่ากลับมาถูกต้อง. ทดสอบmigration compatibilityและapplication rollbackด้วยsessionจริง.
- Restore/failover drillใน candidateและisolated restore instance: บันทึกUTC write/backup/PITR/recovery timestamps, RPO≤300s, RTO≤3600s, counts/ยอด/relationsหลังrestore. เลือก PITR pointด้วยหลักฐาน; ห้ามrestoreทับ primaryที่มีข้อมูลใหม่. Restore instanceชั่วคราวเพิ่มค่าใช้จ่ายและต้องลบเมื่อพิสูจน์เสร็จ. Regional outageอยู่นอกHAรอบนี้.
- Fresh importsตามdependencies Odoo/PEAKเวลาcutoffเดียวกัน; ไม่มีtest data, unexplained money/record difference=0. แยกยอดรายบริษัท, unmatched/conflictsมีresolutionและผู้รับรองข้อมูล. Backupก่อนเปิดรับงาน.
- Alert deliveryจริง: readiness, SQLcapacity, queue/outbox,5xx/latency, imports/reconciliationและbudget. ต้องมีincident ownerรับผิดชอบและหลักฐานส่งถึงปลายทาง.

Copy `evidence.example.json`และเติมจากผลจริงเท่านั้น. แต่ละgateต้องpassedและartifact hashตรง; imagesต้องตรงrelease. `release.py verify-gates --release ... --evidence ...`ปฏิเสธหลักฐานที่ขาดหรือไม่ผ่าน. อย่าเปลี่ยนnull/falseเป็นค่าผ่านเพียงเพื่อข้ามgate.

## Cutover / rollback

1. ปิด staging writesและscheduled importsตามrunbookของstaging; ตรวจว่าไม่มีสองระบบทำงานพร้อมกัน. ห้ามแก้ staging Terraformจากmoduleนี้.
2. Backup production, รับรองreconciliation, review final plan `go_live=true`. `release.py apply`สำหรับplanนี้ต้องแนบreleaseและevidenceที่ผ่าน. ให้กลุ่มผู้ใช้จริงก่อนและติดตามworkflow/ยอด; ownerขยายallowlistเมื่อพร้อม.
3. Releaseถัดไป pin `active_revisions={api=previous,web=previous}`ก่อนcandidate deployเพื่อคงtrafficเดิม; ใช้ canary_percent10 ≥15min →50 ≥15min →100 หลังแต่ละช่วงผ่าน. ต้องพิสูจน์old/newAPI+web/schema compatibilityก่อน. Workerเป็นconsumerที่ต้องcompatibleกับjobsที่ค้างด้วย.
4. หยุดrolloutทันทีเมื่อlost/duplicate write, permission leakหรือยอดผิด; ปัญหาทั่วไปใช้5xx>1%หรือworkbookp95>2sต่อเนื่อง5min. Rollbackapplicationไปpreviousproduction revisions/digestsที่compatibleโดยใช้DBเดิม; Terraformreview trafficplanและคืนค่าตรงdesiredstate.
5. ข้อมูลเสีย: stop writes, restoreไปDBใหม่, reconcileรายการหลังrecovery pointก่อนswitch. ไม่สลับกลับstagingและไม่restoreทับข้อมูลใหม่เพื่อrollbackcode. Expand–migrate–contractเก็บschemaเดิมอย่างน้อย1release.
6. ดูแลเข้ม48h, daily reconciliation,เก็บactualURL/digests/configที่ไม่ลับ/test evidence/dashboard/runbookและผู้รับincident. URLที่เสนอคือ`https://debt.volt.co.th/`และ`/api/v1`; ยังไม่ถือว่าliveจนตรวจปลายทางจริง.

## งานที่ยังต้องพิสูจน์

No public production endpoint/resources exist yet. GCP plansยังไม่ได้refresh/planกับproductionprojectจริง, buildimagesยังไม่ผ่านCloudBuild, actualGoogleOAuth/DNS/secret/IAM/OIDC/ClamAVยังไม่ทดสอบ. Full role/assignmentmatrixและfrontendversion/idempotencyintegrationต้องreviewให้ครบก่อนGoLive. Snapshot adapter/globalmutationlockต้องผ่านloadwithimports; ถ้าไม่ผ่านให้refactor critical section. ไม่มีหลักฐานload2h, failover/restore, rollbackหรือdatareconciliationจริงในชุดโค้ดนี้.
