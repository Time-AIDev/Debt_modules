"""Who can see and do what, per role — the source for the guide's checklists.

Every row cites the code that decides it (file, line, and a literal `needle` that
must appear within 3 lines of it). test_guides.py opens each citation, so when the
code moves, the guide's build fails instead of quietly going stale.

Corrected 2026-09-13 against a fresh read of every cited line (task 8): the seed
table this file replaced was written from a code sweep and had never been opened.
Six of its citations pointed at the wrong line or the wrong code entirely — see
task-8-report.md for the full diff. Where a frontend gate and its backend
counterpart agreed, the backend citation is kept (it is what actually refuses).
Where they disagree, the backend is still cited and the gap is called out in the
row's own wording, so the checklist surfaces the bug instead of hiding it. (The one
such gap, restore-power for OPS, was closed 2026-09-14.)
"""
ROLES = ("OFFICER", "SUPERVISOR", "MANAGER", "OWNER", "OPS")
ALL = ROLES

# (screen_th, screen_en, what_th, what_en, allowed_roles, file, line, needle)
ROWS = (
    ("วันนี้", "Today", "เห็นรายการงานของตัวเอง (ตามเจ้าหน้าที่ที่เลือกไว้)",
     "See your own work list (as the officer chosen in the identity menu)",
     ALL, "frontend/src/screens/Today.jsx", 163, "role === 'OFFICER' ? acting : ''"),
    ("วันนี้", "Today", "เห็นภาระงานของทีม (มุมมองหัวหน้า)", "See the team workload panel (lead view)",
     ("SUPERVISOR", "MANAGER", "OWNER"), "frontend/src/screens/Today.jsx", 488,
     "role === 'SUPERVISOR' || role === 'MANAGER' || role === 'OWNER'"),
    ("วันนี้", "Today", "มอบหมายเคสให้เจ้าหน้าที่คนอื่น", "Reassign a case to another officer",
     ("SUPERVISOR", "MANAGER", "OWNER"), "frontend/src/screens/Today.jsx", 488,
     "canAssign = role === 'SUPERVISOR' || role === 'MANAGER' || role === 'OWNER'"),

    ("รอตรวจ", "Review queue", "ตอบรายการรอตรวจ", "Answer a review",
     ("SUPERVISOR", "MANAGER", "OWNER"), "backend/app/cases.py", 1458,
     'role not in ("SUPERVISOR", "MANAGER", "OWNER")'),

    ("เงินเข้าและ PEAK", "Payments", "ออกใบลดหนี้", "Issue a credit note",
     ("MANAGER", "OWNER"), "frontend/src/screens/Payments.jsx", 26, "CREDIT_NOTE_ROLES = ['MANAGER', 'OWNER']"),
    ("เงินเข้าและ PEAK", "Payments", "แผงจำลอง PEAK (เฉพาะเจ้าของ)", "The PEAK simulator panel (owner only)",
     ("OWNER",), "frontend/src/screens/Payments.jsx", 411, "showStub = role === 'OWNER'"),

    ("ติดตามหนี้เสีย", "Recovery", "อนุมัติคำขอปรับโครงสร้างหนี้", "Approve a debt-restructure request",
     ("MANAGER", "OWNER"), "backend/app/routers/journey.py", 939, 'role not in ("OWNER", "MANAGER")'),
    ("ติดตามหนี้เสีย", "Recovery", "กำหนดประเภท NPL", "Set the NPL type",
     ("MANAGER", "OWNER"), "backend/app/cases.py", 1089, 'role not in ("MANAGER", "OWNER")'),
    # Was the literal name "Dan"; a role since 2026-09-14 (Arina).
    ("ติดตามหนี้เสีย", "Recovery", "บันทึกราคาขายต่อของล็อตยึดคืน", "Record a repossession lot's resale price",
     ("OPS", "OWNER"), "backend/app/routers/journey.py", 1514, 'PRICE_LOT_ROLES = ("OPS", "OWNER")'),

    ("รายงาน", "Reports", "ตั้งเป้าหมาย", "Set targets",
     ("MANAGER", "OWNER"), "frontend/src/components/role.jsx", 22, "canSetTargets"),

    ("ตั้งค่า", "Settings", "แก้ไขค่าตั้งระดับผู้จัดการ", "Edit a manager-level setting",
     ("MANAGER", "OWNER"), "frontend/src/screens/Settings.jsx", 24, "canEdit = role === 'MANAGER' || role === 'OWNER'"),
    ("ตั้งค่า", "Settings", "แก้ไขค่าตั้งเฉพาะเจ้าของ (OPEN/DECIDED)", "Edit an owner-only setting (OPEN/DECIDED)",
     ("OWNER",), "frontend/src/screens/Settings.jsx", 568, "if (lock === 'owner_only') return role === 'OWNER' ? null : 'ownerOnly'"),
    ("ตั้งค่า", "Settings", "มอบหมายเจ้าหน้าที่", "Assign officers",
     ("SUPERVISOR", "MANAGER", "OWNER"), "frontend/src/screens/Settings.jsx", 25, "canAssign = role === 'SUPERVISOR' || canEdit"),

    ("ลูกค้า", "Customer case", "สั่งตัดไฟ", "Execute a power cut",
     ("SUPERVISOR", "MANAGER", "OWNER", "OPS"), "backend/app/cases.py", 1692, "POWER_EXECUTE_ROLES"),
    # The screen hid this button from OPS until 2026-09-14 (Arina ruled OPS may restore).
    ("ลูกค้า", "Customer case", "สั่งคืนไฟ", "Restore power",
     ("SUPERVISOR", "MANAGER", "OWNER", "OPS"), "backend/app/cases.py", 1693, "POWER_RESTORE_ROLES"),
    ("ลูกค้า", "Customer case", "อนุมัติหรือปฏิเสธคำขอตัดไฟ", "Approve or reject a power-cutoff request",
     ("OWNER",), "backend/app/cases.py", 1531, 'role != settings.power_restriction_approver and role != "OWNER"'),
    ("ลูกค้า", "Customer case", "บันทึกการติดต่อเกินโควตาวันนี้", "Log a contact past today's slot",
     ("MANAGER", "OWNER"), "backend/app/collections/contact.py", 66, "OVERRIDE_ROLES"),

    ("แหล่งข้อมูล", "Data sources", "ส่วนของผู้จัดการขึ้นไป", "Manager-and-above section",
     ("MANAGER", "OWNER"), "frontend/src/screens/DataSourcesMigration.jsx", 39, "isManagerUp = role === 'MANAGER' || role === 'OWNER'"),
    ("แหล่งข้อมูล", "Data sources", "ส่วนของเจ้าของเท่านั้น", "Owner-only section",
     ("OWNER",), "frontend/src/screens/DataSourcesMigration.jsx", 37, "isOwner = role === 'OWNER'"),

    ("บันทึกการกระทำ", "Action log", "เปิดดูบันทึกทั้งหมด", "Read the whole log",
     ALL, "backend/app/routers/audit.py", 65, "everyone sees everything"),
)
