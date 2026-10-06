# เปิด login สำหรับเดโม — Login on for a demo

ส่วนเสริมสั้น ๆ ของ [คู่มือการเข้าสู่ระบบและบัญชีทดสอบ](login-tester-guide.docx)
A short companion to the [Login and Test Account Guide](login-tester-guide.docx).

หน้า login ถูกสร้างเสร็จแล้ว แต่จะไม่แสดงจนกว่าจะตั้ง `AUTH_MODE=on` สคริปต์นี้เปิดให้ครบในคำสั่งเดียว:
The login screens are built; they stay invisible until `AUTH_MODE=on`. One script turns everything on:

```bash
scripts/run_prototype_login.sh
```

สคริปต์จะสร้าง `AUTH_SESSION_SECRET` และรหัสผ่านของบัญชีทดสอบขึ้นใหม่ทุกครั้งที่รัน
`AUTH_MODE` ถูก export เข้า environment ของเชลล์เท่านั้น ไม่ถูกเขียนลง `backend/.env` โดยเจตนา
(`app/auth.py` ปฏิเสธ `.env` ที่มี `AUTH_MODE` เพราะชุดเทสต์อ่านไฟล์นั้น)
The script generates `AUTH_SESSION_SECRET` and the shared test password at run time. `AUTH_MODE`
is exported into the shell environment only, never written to `backend/.env` — a `.env` that
names `AUTH_MODE` is refused on purpose (the test suite reads that file).

### ทางเลือกที่ใช้บ่อย · Common options

| ต้องการ · Want | คำสั่ง · Command |
| --- | --- |
| เปิดค้างไว้แล้วออกจากสคริปต์ · start and return | `KEEP_UP=1 scripts/run_prototype_login.sh` |
| เลี่ยงพอร์ตที่ถูกใช้อยู่ · avoid a busy port | `API_PORT=8001 WEB_PORT=5174 scripts/run_prototype_login.sh` |
| ใช้รหัสผ่านที่กำหนดเอง · choose the password | `AUTH_TEST_PASSWORD='...' scripts/run_prototype_login.sh` |

ปิดเซิร์ฟเวอร์ด้วย Ctrl-C หรือ `kill <pid> <pid>` ที่สคริปต์พิมพ์ตอนใช้ `KEEP_UP=1`
Stop the servers with Ctrl-C, or the `kill` line `KEEP_UP=1` prints.

### บัญชีทดสอบ · Test accounts

รหัสผ่านเดียวกันทุกบัญชี: พิมพ์ครั้งเดียวบนหน้าจอตอนรัน หรือมาจาก `AUTH_TEST_PASSWORD`
ห้ามคัดลอกรหัสผ่านลงเอกสารหรือ commit
One shared password: printed once at start, or taken from `AUTH_TEST_PASSWORD`. Never copy it
into a document or a commit.

| ชื่อผู้ใช้ · Username | บทบาท · Role | ทำงานในชื่อ · Acts as |
| --- | --- | --- |
| `tester` | ทุกบทบาท (สลับได้) · any role | เลือกเอง · chooses |
| `officer.test` | OFFICER | `nantapol` |
| `supervisor.test` | SUPERVISOR | `settasak` |
| `manager.test` | MANAGER | `settasak` |
| `owner.test` | OWNER | `owner` |
| `ops.test` | OPS | `ops` |

ชื่อเจ้าหน้าที่อ่านจาก registry ของแอปเอง (`app/officers.py`) ตอนสร้างบัญชี ถ้าชื่อไม่มีใน
`/v1/officers` เซิร์ฟเวอร์จะไม่ยอมเริ่ม
Officers are read from the app's own registry (`app/officers.py`) when the accounts are made;
the server refuses to start if one is missing.

### Google sign-in

ปุ่ม Google จะขึ้นเมื่อมี `GOOGLE_CLIENT_ID` เท่านั้น และ origin ของเดโมต้องถูกเพิ่มใน
Google Cloud Console (OAuth client → Authorized JavaScript origins) เช่น `http://localhost:5173`
ไม่งั้น Google จะตอบ `origin is not allowed` ให้ใช้บัญชีทดสอบแทน
The Google button appears only when `GOOGLE_CLIENT_ID` is set, and the demo origin must be
listed in the Google Cloud Console OAuth client (Authorized JavaScript origins), e.g.
`http://localhost:5173`; otherwise Google answers "origin is not allowed" — use a test account.

### โหมดปกติ (ไม่เปิด login) · Normal mode (login off)

`scripts/run_prototype.sh` ยังทำงานเหมือนเดิม: `AUTH_MODE` ไม่ถูกตั้ง แอปใช้ค่าหัวข้อ
`X-Volt-Role`/`X-Volt-Officer` และไม่มีหน้า login
`scripts/run_prototype.sh` is unchanged: no `AUTH_MODE`, headers are trusted as before, no login page.
