# Staging สำหรับ user testing — สาธารณะด้วย app login

> เอกสารนี้ **ไม่มีความลับ** — รหัสผ่านของบัญชีทดสอบส่งให้ tester คนละช่องทาง (vault/แชตส่วนตัว) เท่านั้น
> No passwords live in this file. Hand them out through the vault or a private channel.

## ลิงก์ · The link

```
https://volt-debt-uat-<hash>-as.a.run.app
```

ได้จากท้ายสคริปต์ `scripts/deploy_gcp.sh` (`URL …`) หรือ
`gcloud run services describe volt-debt-uat --region asia-southeast1 --format='value(status.url)'`

เข้าแล้วเจอหน้า login ของแอป → ใช้บัญชีทดสอบด้านล่าง (ไม่ต้องมี Google account)

## บัญชีกลางตามบทบาท · Shared role accounts

รหัสผ่านเดียวใช้ได้ทุกบัญชี (ส่งให้ tester แล้วแต่ช่องทาง) — **audit log รู้แค่บทบาท ไม่รู้ว่าใคร**
จึงขอให้ tester **พิมพ์ชื่อตัวเองใน feedback ทุกครั้ง**

| Username | บทบาท | ทำอะไรได้ |
| --- | --- | --- |
| `officer` | OFFICER | เคส, บันทึกการติดต่อ, PTP, ย้ายบอร์ด, เปิดเบอร์ |
| `supervisor` | SUPERVISOR | เท่า officer + มอบหมายงาน |
| `manager` | MANAGER | เท่า supervisor + **ยุติสัญญา**, สั่งนำเข้า/ซิงก์, ตั้งเป้า |
| `owner` | OWNER | สูงสุด + **อนุมัติตัดจำหน่าย (write-off)**, ตั้ง NPL type |

## Checklist สำหรับ tester (ใช้เวลาราว 30–45 นาที)

1. **สถานะปิด vs ยุติสัญญา** — เปิดเคสที่มียอดค้าง → ชิปสถานะต้องไม่ขึ้น "ปิด" ถ้ายังไม่จ่ายครบ;
   เคสที่ถูกยุติ (ถ้ามีในข้อมูล) ต้องขึ้น "ยุติสัญญา" และ SOP ต้องบอกเหตุผล (ผิดสัญญา / ลูกค้าขอยุติ)
2. **ยุติสัญญา (บัญชี `manager`)** — กด "ยุติสัญญา" บนเคสที่ยังมียอด → ต้องถูกปฏิเสธพร้อมยอดปิดสัญญา;
   เลือกสาเหตุ + เหตุผลครบก่อนปุ่มยืนยันจะกดได้
3. **เบอร์โทร** — บนหัวเคส: `08x-xxx-xxxx` → กด "เปิดเบอร์" → เห็นเบอร์เต็ม, "คัดลอก" แล้ว paste ได้,
   "โทร" กลายเป็นลิงก์ `tel:` (มือถือกดโทรออกได้) — ทุกครั้งที่เปิดจะถูกบันทึกใน audit
4. **นำเข้าข้อมูล** — หน้า "นำเข้าข้อมูล" ต้องเปิดที่แท็บ **Odoo** และบอกว่า **ซิงก์อัตโนมัติทุก 15 นาที**
   + เวลารอบถัดไป; แท็บ "ไฟล์ชีต" ยังอัปไฟล์ .xlsx/.csv ได้ (≤25 MB)
5. **ปฏิทิน** — สลับหน่วย **วัน / สัปดาห์ / เดือน / ปี**, เลื่อน ◀ ▶, กด "วันนี้", เลือกวันที่ในช่อง
   ปฏิทิน; โหมดปีต้องเห็นสรุป 12 เดือน กดเดือนแล้วเจาะเข้าเดือนนั้นได้
6. **การ์ดก่อนติดตั้ง** — หลักฐานแต่ละเงื่อนไข: แนบ → ถอด → แนบใหม่; ปล่อยเคส (release) ต้องใช้ได้ตามสิทธิ์
7. **Audit** — หน้า "บันทึกการใช้งาน" ต้องเห็น `PHONE_REVEALED`, `CONTRACT_TERMINATED` (ถ้าทดสอบ)
   และ `CASE_VIEWED` ทุกครั้งที่เปิดเคส
8. **มือถือ** — เปิดเว็บบนมือถือ: ตารางอาจต้องเลื่อนแนวนอน แต่ปุ่ม/ฟอร์มต้องกดได้
9. **Feedback** — ทุกครั้งที่เจอปัญหา ส่ง: หน้าไหน + สิ่งที่ทำ + สิ่งที่คาดว่าจะเห็น + สิ่งที่เห็นจริง + ภาพหน้าจอ

## ข้อจำกัดที่ต้องบอก tester ล่วงหน้า

- **ข้อมูลเป็นชุด UAT จริง** (Odoo/PEAK): ห้ามคัดลอกข้อมูลลูกค้าออกนอกทีม (PDPA)
- ตัวเลข **ค่าปรับเป็น indicative** (อัตรา CF1 ยังไม่สรุป)
- ซิงก์ crm.lead ทุก 15 นาที; ไฟล์ที่อัปเองจะเห็นผลทันทีหลังกดตรวจ
- **state อยู่ถาวรใน Cloud SQL** — งานของ tester ไม่หายเมื่อ restart แต่ถ้าต้องเริ่มใหม่ แจ้งทีมให้ล้าง session
- บัญชีกลางใช้ร่วมกัน: ถ้าเห็นข้อมูลที่ไม่ได้สร้างเอง ให้ถือว่าเป็นงานของ tester คนอื่น

## Feedback ที่อยากได้

ใช้แบบฟอร์ม/ชีตของทีม (ใส่ลิงก์ที่นี่) หรือส่งในกลุ่ม พร้อมหัวข้อ:
`หน้า | สิ่งที่ทำ | คาดหวัง | เห็นจริง | ภาพ | ชื่อ tester | ความสำคัญ (บล็อก/ควรมี/อยากได้)`

---

## สำหรับทีม (ops)

```bash
# 0) sign in once per machine (gcloud needs the env file for PATH)
source "$HOME/.volt-gcloud-env" && gcloud auth login

# 1) stand up (ครั้งแรก)
PROJECT=<id> ./scripts/provision_stg.sh [--apply]
PROJECT=<id> ./scripts/push_secrets.sh --apply
PROJECT=<id> ./scripts/staging_accounts.sh --apply
PROJECT=<id> ACCESS=public ./scripts/deploy_gcp.sh
gcloud run jobs execute debt-crm-lead-sync --region asia-southeast1 --wait

# 2) smoke ก่อนส่งลิงก์ — owner สำหรับงานที่ Owners เท่านั้นทำได้ (stub/ราคาล็อต)
#    และผู้รันจะเปิด officer client ให้เองจากรหัสผ่านเดียวกัน เพื่อพิสูจน์การปฏิเสธตามบทบาท
VOLT_PASS='<shared password>' backend/.venv/bin/python scripts/e2e_check.py \
  --base-url https://<svc>.run.app --username owner --timeout 60
UAT_BASE=https://<svc>.run.app UAT_USER=owner UAT_PASS='<shared password>' \
  node scripts/uat_browser.mjs / --max 40

# 3) ระหว่างรอบ
gcloud run services logs read volt-debt-uat --region asia-southeast1 --limit 200
# rollback
gcloud run services update-traffic volt-debt-uat --to-revisions <prev>=100
# ล้าง session ของ tester (ต้องมี session id จาก log/audit) — ระวัง: ลบหมดคือ reset ทุกคน
#   DELETE FROM app.session_state WHERE session_id = 's-…';

# 4) ปิดรอบ (หยุดค่าใช้จ่าย)
gcloud run services update volt-debt-uat --no-traffic
gcloud sql instances patch debt-pg-stg --activation-policy NEVER
```

รอบ sync: `crm-lead-refresh` (Cloud Scheduler, `*/15 * * * *`, Asia/Bangkok) ยิง job
`debt-crm-lead-sync` แม้ service scale to zero · รายชื่อบัญชีคือ secret `AUTH_TEST_ACCOUNTS:latest`
(เพิ่ม version ใหม่แล้ว deploy ซ้ำเพื่อให้ revision อ่าน version ล่าสุด)

### หมายเหตุจากรอบ deploy จริง (2026-09-21)

- **สุขภาพ service:** บน `*.run.app` ใช้ `/readyz` หรือ `/livez` — Google front end
  สงวน `/healthz` ไว้และตอบ 404 เองก่อนถึง container (ในเครื่องยังใช้ `/healthz` ได้)
- **Google sign-in ปิดไว้รอบนี้:** client ของ staging ยังไม่มี origin ของ `*.run.app`
  จึงถอด `GOOGLE_CLIENT_ID` ออก (destroy version) — หน้า login จะเหลือเฉพาะบัญชีทดสอบ
  ถ้าจะเปิด Google: เพิ่ม origin ใน OAuth client ก่อน แล้ว push secret ใหม่ + deploy
- **deploy ครั้งแรกจะ pull crm.lead ให้เอง** (ขั้น "The first crm.lead pull, BEFORE the
  service is pointed at the database") เพราะ `officers.registry()` สร้างจากแถวที่เสิร์ฟ —
  landing ว่าง + allow-list ที่อ้าง officer จริง = service start ไม่ขึ้น
- **`push_secrets.sh` อ่านค่าแบบเดียวกับแอป** (ตัด quote/ช่องว่าง) — ค่าที่มี `"` ครอบใน
  `backend/.env` เคยถูก push ทั้ง quote ทำให้ job ตาย `UnsupportedProtocol`
- **job ทุกตัวรับ integration secrets แล้ว** (`--set-secrets`) — เดิม `debt-odoo-sync`
  และ `debt-crm-lead-sync` ตาย exit 2 เพราะไม่มี ODOO_*/PEAK_*
- **รหัสผ่าน `postgres` ของ Cloud SQL** ถูกสุ่มใหม่ทิ้งหลัง provisioning (ไม่เก็บที่ไหน);
  ต้องใช้เมื่อไหร่ให้ `gcloud sql users set-password postgres --instance debt-pg-stg`

---

## ข้อความเชิญ (พร้อมส่ง) · Ready-to-send invite

**TH**

> สวัสดีครับ/ค่ะ ขอเชิญทดสอบระบบเก็บหนี้ (Volt Debt) รอบ UAT ครับ
> ลิงก์: https://volt-debt-uat-<hash>-as.a.run.app
> เข้าด้วยบัญชีทดสอบที่ส่งให้แยกต่างหาก (มี 4 บทบาท: officer / supervisor / manager / owner)
> ใช้เวลาราว 30–45 นาที ทำตาม checklist ในเอกสารที่แนบ (สถานะปิด/ยุติสัญญา, เบอร์โทร, นำเข้าข้อมูล, ปฏิทิน)
> ข้อมูลเป็นชุด UAT จริง ขอความกรุณาอย่าคัดลอกข้อมูลลูกค้าออกนอกทีม และระบุชื่อใน feedback ทุกครั้ง
> ส่ง feedback ได้ที่ <ลิงก์ฟอร์ม> ภายใน <วันที่> ครับ ขอบคุณครับ

**EN**

> Hello — you are invited to the Volt Debt user-testing round.
> Link: https://volt-debt-uat-<hash>-as.a.run.app
> Sign in with the test account sent to you separately (four roles: officer / supervisor / manager / owner).
> About 30–45 minutes; follow the checklist in the attached guide (closed vs terminated, phone, import data, calendar).
> The data is a real UAT set — please keep customer data inside the team, and name yourself in every feedback item.
> Send feedback to <form link> by <date>. Thank you.
