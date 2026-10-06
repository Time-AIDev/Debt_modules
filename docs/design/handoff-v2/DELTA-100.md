# DELTA-100 — master vs Final v2, element by element

Source of truth: `Volt Debt - Final v2.dc.html` (byte-exact import, sha `c628c158…`;
re-import pending the next `/design-login`). Target: rebuild master so the UX/UI
matches the prototype 100%, wire every backend value the prototype shows, then UAT
every screen.

Buckets per row:

- **[FIX]** — unpinned divergence; rebuild to the prototype, no ruling needed.
- **[DATA]** — prototype value the API does not serve yet; backend work under D2.
- **[DECIDE]** — a test-asserted ruling or a safety/compliance shape; needs your call.

Open decisions (D1–D5) are summarised at the end.

## Overview — Dashboard.jsx

| id | prototype | app today | gap | bucket | recommendation | size |
|---|---|---|---|---|---|---|
| O-01 | 839, 870, 2110-2111 | Dashboard.jsx:262, 296 | 1.3fr:1fr row is on officers/next; prototype puts it on aging/target | FIX | swap the two grid classes | S |
| O-02 | 792, 2275 | Dashboard.jsx:163 | arrears cell lacks note "ยังไม่รวมค่าปรับ" | [DATA] static copy | add note | S |
| O-03 | 792, 2277, 2288-2302 | Dashboard.jsx:177, 138, 317 | no queue "202 งาน" / "ทำแล้ว 67" / officer "31 / 96" | DATA | serve done-of-total (D2b) | M |
| O-04 | 785, 1490, 2276 | Dashboard.jsx:161,170-174 | sub omits scope clause; scope note wording | [DECIDE] copy pinned | prototype verbatim (D5) | S |
| O-05 | 797-807, 2639-2647 | Dashboard.jsx:201-218 | KPI labels/notes, weekly edition, prior-week PTP delta, prior-month DSO, contact scope | DATA | serve comparisons; prototype copy | M |
| O-06 | 812-824, 2653-2658 | Dashboard.jsx:223-245 | trend bars are baht vs monthly attainment % | DATA | serve monthly targets/attainment (D2e) | M |
| O-07 | 842-843, 1486 | Dashboard.jsx:264 | aging heading hint "ชุดปฏิบัติงาน · คลิกเพื่อกรองรายการ" | DECIDE | click-to-filter was replaced by the table ruling | S |
| O-08 | 835, 1485 | Dashboard.jsx:258 | roll footnote copy | DECIDE | prototype verbatim (D5) | S |
| O-09 | 867, 1487 | Dashboard.jsx:292 | target footer copy/link | DECIDE | prototype verbatim (D5) | S |
| O-10 | 802, 2639-2647 | Dashboard.jsx:201-218 | bars only on receipts; prototype on all four | DATA | serve targets for all four (D2e) | M |
| O-11 | 846-853, 2281-2282 | Dashboard.jsx:265-270 | aging table vs 5 vertical count bars | DECIDE | match prototype (chart form) | M |
| O-12 | 896-897, 2292-2293 | Dashboard.jsx:150-151 | served vs-team flags vs fixed 60/55, 45/40 thresholds | DECIDE | keep served flags (honest) or prototype thresholds (D5) | S |
| O-13 | 782 | redesign-overview.css:5 | header accent ink-800 vs brand-500 | DECIDE | prototype accent | S |
| O-14 | 918-923, 2311-2315 | Dashboard.jsx:338-339 | next-item label wording | DECIDE | prototype verbatim (D5) | S |
| O-15 | 790-791, 2275-2279 | redesign-overview.css:10-11 | strip typography: 10px/600 uppercase, 19px values | FIX | match prototype | S |

## Today + customer record — Today.jsx / CustomerCase.jsx / SplitView.jsx

| id | prototype | app today | gap | bucket | recommendation | size |
|---|---|---|---|---|---|---|
| T-01 | 234, 1317 | Today.jsx:1090 | pane sub "ทำแล้ว 11 จาก 34 งาน" | DATA | serve done-of-total (D2b) | S |
| T-02 | 231-232, 1317 | Today.jsx:1090 | pane title "วันนี้"; count "63 รายการ" | FIX | title + unit | S |
| T-03 | 236-240 | Today.jsx:1090 | in-pane officer filter | DECIDE | moved to page bar by ruling | S |
| T-04 | 245-252, 1319 | Today.jsx:1083 | 3 status groups vs served tiers | DECIDE | served partition is truth | S |
| T-05 | 2036-2038 | Today.jsx:1132,1137 | null-DPD row loses "ไม่มี DPD" + faded heat | FIX | match prototype | S |
| T-06 | 297, 302-303 | CustomerCase.jsx:554-601 | header eyebrow "ลูกหนี้", composed sub, masking note | FIX | match prototype | M |
| T-07 | 307-309 | CustomerCase.jsx:552-601 | no risk score | DATA | serve risk score (D2a) | M |
| T-08 | 317-325, 2190-2197 | CustomerCase.jsx:668-743 | field-strip note lines; label wording | DECIDE | notes need density caps decision (D1) | M |
| T-09 | 2191 | CustomerCase.jsx:675 | non-zero arrears overdue tone | FIX | match prototype | S |
| T-10 | 2193 | CustomerCase.jsx:695 | "DPD 13" vs "DPD 13 วัน" | DECIDE | prototype verbatim (D5) | S |
| T-11 | 326-332, 2199-2203 | CustomerCase.jsx:750-773 | DPD chevrons + enabled action vs ladder + disabled act | DECIDE | ladder is served truth | M |
| T-12 | 335-337 | CustomerCase.jsx:779+ | 5 tabs replaced by stacked cards | DECIDE | match prototype (tabs) | L |
| T-13 | 339-403, 2212-2251 | CustomerCase.jsx:825-1849 | no 2-col overview: money, recent contacts, open items, PTP, ladder | DECIDE | match prototype (panels) | L |
| T-14 | 429, 1423 | CustomerCase.jsx:1633 | invoices card PEAK note missing | FIX | add | S |
| T-15 | 449, 2230-2232 | CustomerCase.jsx:1563 | contact-allowance footer | DATA | serve weekly cap/used (D2b) | S |
| T-16 | 296-299, 310-314 | CustomerCase.jsx:555,659-666 | extra DC chip + ส่งแจ้งเตือน; LINE conditional | DECIDE | keep extra acts | S |
| T-17 | 319-322 | split-today.css:30-31 | strip typography | FIX | match prototype | S |

## Work book — WorkBook.jsx

| id | prototype | app today | gap | bucket | recommendation | size |
|---|---|---|---|---|---|---|
| B-01 | 1320 | WorkBook.jsx:777-783 | pane sub "212 แถว · New Order Master (SHEET)" | DATA | serve source label (D2f) | S |
| B-02 | 1320 | WorkBook.jsx:777 | pane title "ลูกค้า / สมุดงาน" | FIX | match prototype | S |
| B-03 | 232, 1320 | WorkBook.jsx:777 | count "212 รายการ" | FIX | add unit | S |
| B-04 | 1322 | WorkBook.jsx:643-658 | 4 fixed bands vs served buckets | DECIDE | served band set wins | S |
| B-05 | 1320, 236-240 | WorkBook.jsx:701-752 | in-pane band filter | DECIDE | moved to toolbar | S |
| B-06 | 2036-2038 | Today.jsx:1120-1139 | null-DPD + typography (shared) | FIX | shared fix with T-05/T-17 | S |

## Calendar — Calendar.jsx

| id | prototype | app today | gap | bucket | recommendation | size |
|---|---|---|---|---|---|---|
| C1 | 938-939 | Calendar.jsx:751-755 | title month, drag/reason sub, range sub | FIX | match prototype | S |
| C2 | 948-952 | Calendar.jsx:797-805 | reminder cell: value vs count; conflict note | DECIDE | match prototype cell shape | M |
| C3 | 2323 | Calendar.jsx:780-782 | week range "15/09 – 21/09" | FIX | compact range | S |
| C4 | 986-997 | Calendar.jsx:155-196 | one week card vs per-day sections | DECIDE | match prototype card | L |
| C5 | 991 | Calendar.jsx:174-176 | short kind chips (งาน/PTP/…) | FIX | shorten | S |
| C6 | 994 | Calendar.jsx:738-739 | "เลื่อนวัน" | FIX | rename | S |
| C7 | 2327 | Calendar.jsx:29 | weekday dots | FIX | match prototype | S |
| C8 | 2328-2343 | Calendar.jsx:105-152 | fixed 35-cell month vs served 42-cell grid | DECIDE | render fixed month from served data | L |
| C9 | 950-952 | calendar.css:20-21 | strip typography | FIX | match prototype | S |

## Reviews — ReviewQueue.jsx

| id | prototype | app today | gap | bucket | recommendation | size |
|---|---|---|---|---|---|---|
| R1 | 530-539 | ReviewQueue.jsx:338-366 | side card arrears/DPD + open case | DATA | join case detail (D2g) | M |
| R2 | 518-540 | ReviewQueue.jsx:244,368 | Evidence placement (grid2b) | FIX | match prototype | M |
| R3 | 501-506 | ReviewQueue.jsx:266-321 | quick Reject/Approve vs decision form | DECIDE | keep form (R9) | M |
| R4 | 2035-2036 | ReviewQueue.jsx:426-434 | row money + "รอ n วัน" | DATA | serve (D2g) | S |
| R5 | 235-240 | ReviewQueue.jsx:412-446 | list sort toggle | DATA | sort key from money (D2g) | S |
| R6 | 1323-1325 | ReviewQueue.jsx:401-406 | groups 2-day/open-today vs SLA | DECIDE | served SLA wins | S |
| R7 | 489 | ReviewQueue.jsx:219 | header edge reg-open | FIX | match prototype | S |
| R8 | 491-495 | ReviewQueue.jsx:223-241 | age + result chips | DECIDE | served decision wins | S |
| R9 | 509-517 | ReviewQueue.jsx:323-334 | answer band under header | FIX | relocate | S |
| R10 | 521-528 | ReviewQueue.jsx:98-120 | evidence icon + wording | FIX | match prototype | S |
| R11 | 232, 2170 | ReviewQueue.jsx:414 | count unit | FIX | add | S |
| R12 | 500 | ReviewQueue.jsx:231-235 | per-request need text | DATA | serve need (D2g) | S |
| R13 | 493 | ReviewQueue.jsx:70-80 | age chip days vs hours | DECIDE | prototype days | S |
| R14 | 2038 | ReviewQueue.jsx:426-434 | row heat strip | FIX | age/120 | S |

## Pre-installation — InvoicePipeline.jsx

| id | prototype | app today | gap | bucket | recommendation | size |
|---|---|---|---|---|---|---|
| P1 | 547 | InvoicePipeline.jsx:299 | header edge brand | FIX | match prototype | S |
| P2 | 563-576 | InvoicePipeline.jsx:289-296 | contract-signed condition + chips | DATA | serve contract evidence (D2h) | M |
| P3 | 2516-2526 | InvoicePipeline.jsx:230-281 | generic evidence drawer vs inline forms | DECIDE | keep inline acts | M |
| P4 | 544-581 | InvoicePipeline.jsx:392-543 | after-release card is app-only | DECIDE | keep (required acts) | L |
| P5 | 2532-2533 | InvoicePipeline.jsx:351-364 | disabled release + reason vs clickable | DECIDE | keep R3 (J-20) | S |
| P6 | 544, 1278-1283 | InvoicePipeline.jsx:307,658 | SO-… reference in row/header | DATA | serve order_ref | S |
| P7 | 1282, 2035-2036 | InvoicePipeline.jsx:656-667 | money + "รอ n วัน" | DATA | serve arrears/waiting | S |
| P8 | 2519 | split-pipeline.css:20-24 | passed mark tone | FIX | match prototype | S |
| P9 | 1326-1328 | InvoicePipeline.jsx:608-612 | sub/groups/list-note copy | DECIDE | prototype verbatim (D5) | M |
| P10 | 232, 2170 | InvoicePipeline.jsx:623 | count unit | FIX | add | S |
| P11 | 578, 1431 | InvoicePipeline.jsx:686-687 | peakNote placement/wording | DECIDE | prototype verbatim (D5) | S |

## Receipts & PEAK — Payments.jsx

| id | prototype | app today | gap | bucket | recommendation | size |
|---|---|---|---|---|---|---|
| PAY-1 | 1329 | Payments.jsx:423 | sub names count awaiting AR | FIX | match prototype | S |
| PAY-2 | 2170 | Payments.jsx:423 | count unit | FIX | add | S |
| PAY-3 | 1330 | Payments.jsx:415-418 | lens filter default "ยังไม่อนุมัติ" | FIX | match prototype | S |
| PAY-4 | 1331 | Payments.jsx:361 | group label "รอ AR" | DECIDE | prototype verbatim (D5) | S |
| PAY-5 | 1331 | Payments.jsx:281 | extra group "เสร็จใน PEAK" | DECIDE | keep | S |
| PAY-6 | 596 | Payments.jsx:468-479 | per-state "what is needed" sentence | DATA | serve state_note | S |
| PAY-7 | 586 | split-payments.css:6-8 | header edge brand | FIX | match prototype | S |
| PAY-8 | 2548-2549 | i18n-journey.js:903 | approved chip copy | FIX | match prototype | S |
| PAY-9 | 1377-1381 | i18n-ops.js:665-674 | gate copy | DECIDE | prototype verbatim (D5) | S |
| PAY-10 | 616-617 | Payments.jsx:483-502 | allocation heading gone | DATA | restore with rows (D2d) | S |
| PAY-11 | 618-624 | none | three allocation lines + amounts | DATA | model allocation (D2d) | M |
| PAY-12 | 597 | Payments.jsx:460-465 | Fix and resubmit act | DATA | model resubmit (D2d) | M |
| PAY-13 | 2035 | Payments.jsx:406 | row shows arrears vs doc amount | DATA | serve arrears (D2g) | S |
| PAY-14 | 2036-2037 | Payments.jsx:407 | meta "รอ N วัน" vs created date | DATA | serve waiting_days (done) + show | S |
| PAY-15 | 2039 | Payments.jsx:408 | per-item risk edge | DATA | risk score (D2a) | S |
| PAY-16 | 583-629 | Payments.jsx:429-515 | app-only slip/credit/stub panels | DECIDE | keep | L |
| PAY-17 | 2171 | i18n-journey.js:611 | sort label "ยอดเสี่ยง" | FIX | rename | S |
| PAY-18 | 2549 | i18n-journey.js:905 | UNSENT chip amber | DECIDE | keep tone | S |

## NPL & recovery — Recovery.jsx

| id | prototype | app today | gap | bucket | recommendation | size |
|---|---|---|---|---|---|---|
| REC-1 | 1332 | Recovery.jsx:421 | sub names NPL count + 100% NPV | FIX | match prototype | S |
| REC-2 | 2170 | Recovery.jsx:420 | count unit | FIX | add | S |
| REC-3 | 1334 | Recovery.jsx:170 | extra groups | DECIDE | keep | S |
| REC-4 | 1831 | Recovery.jsx:264,436 | default sort money vs given | FIX | money first | S |
| REC-5 | 2036 | i18n-journey.js:1021 | "ค้าง" vs "รอ" DPD | DECIDE | prototype verbatim (D5) | S |
| REC-6 | 1291-1294 | Recovery.jsx:402-404 | row sub state + NPV | DATA | serve (D2c) | M |
| REC-7 | 637-638 | Recovery.jsx:486 | status/chosen chips | DATA | serve status | M |
| REC-8 | 633 | split-recovery.css:12-14 | risk edge vs group tone | DATA | risk score (D2a) | S |
| REC-9 | 652 | Recovery.jsx:548 | estimate sentence missing | DATA | serve estimate (D2c) | S |
| REC-10 | 670 | Recovery.jsx:218 | pathNote copy | DECIDE | prototype verbatim (D5) | S |
| REC-11 | 2559-2569 | Recovery.jsx:551-553 | cards lack note/฿/rate/caveat/badge | DATA | serve rates/estimates (D2c) | M |
| REC-12 | 1367-1371 | Recovery.jsx:29 | 3 prototype paths vs 4 strategies | DECIDE | add settlement only if business confirms (D2c) | S |
| REC-13 | 2574 | Recovery.jsx:215 | confirm label switches below manager | FIX | match prototype | S |
| REC-14 | 673-684 | Recovery.jsx:529-543 | three steps per path vs one | DATA | extend step templates (D2c) | M |
| REC-15 | 630-687 | Recovery.jsx:224-618 | app-only tabs/NPL type/restructure/lots | DECIDE | keep | L |
| REC-16 | 2039 | Recovery.jsx:404 | per-case risk edge | DATA | risk score (D2a) | S |

## Reports — Reports.jsx

| id | prototype | app today | gap | bucket | recommendation | size |
|---|---|---|---|---|---|---|
| REP-1 | 1336 | Reports.jsx:469-482 | list footer note | FIX | add | S |
| REP-2 | 236-240 | Reports.jsx:469-482 | sort toggle | DATA | serve sortable cash for published (D2i) | M |
| REP-3 | 2170 | Reports.jsx:469 | count unit | FIX | add | S |
| REP-4 | 1335 | Reports.jsx:471-475 | default period "สัปดาห์นี้" | FIX | match prototype | S |
| REP-5 | 1308-1313 | Reports.jsx:446-449 | row naming WK-38/2026 | DECIDE | prototype naming | S |
| REP-6 | 706, 2586 | Reports.jsx:514 | published cash "—" until opened | DATA | serve cash total (D2i) | S |
| REP-7 | 698, 706-708 | Reports.jsx:514-516 | contacts + kept/total "—" | DATA | serve per-edition (D2i) | M |
| REP-8 | 2587 | Reports.jsx:518 | draft badge amber | FIX | match prototype | S |
| REP-9 | 2590 | Reports.jsx:535-573 | download reason form (R16) | DECIDE | keep reason | S |
| REP-10 | 2590 | Reports.jsx:526-530 | non-manager label | DECIDE | keep disabled + sentence | S |
| REP-11 | 688-720 | Reports.jsx:576-836 | app-only tabs/overview/targets/focus/snapshots | DECIDE | keep | L |
| REP-12 | 246 | SplitView.jsx:51 | empty groups hidden | DECIDE | keep | S |
| REP-13 | 2039 | Reports.jsx:451 | no severity stripe | DATA | risk score (D2a) | S |

## Shell — Shell.jsx / top bar / View / tabs / palette

| id | prototype | app today | gap | bucket | recommendation | size |
|---|---|---|---|---|---|---|
| SH1 | 131-138 | Shell.jsx:292-310 | caseload footer never rendered (workload not passed) | DATA | wire workload | M |
| SH2 | 1240-1252 | Shell.jsx:61-64 | book/NPL/settings badges unset | DATA | wire counts | M |
| SH3 | 1410 | i18n-journey.js:876 | KPI eyebrow "ผลงานเทียบเป้า" | DECIDE | prototype verbatim (D5) | S |
| SH4 | 103-106 | Shell.jsx:245-263 | no absolute target line under bar | DATA | serve target; render line | S |
| SH5 | 105 | app.css:144 | KPI fill blue vs brand amber | FIX | match prototype | S |
| SH6 | 2131 | app.css:190-195 | collapsed count pill vs red corner dot | FIX | match prototype | S |
| SH7 | 86-93 | app.css:83-93 | rail head bolt square vs logo/wordmark crop | FIX | use asset as prototype | S |
| SH8 | 1410 | prefs.jsx:537 | descriptor copy | DECIDE | prototype verbatim (D5) | S |
| SH9 | 1412 | prefs.jsx:538 | env chip copy | DECIDE | prototype verbatim (D5) | S |
| SH10 | 1463 | i18n-journey.js:607 | search placeholder word order | DECIDE | prototype verbatim (D5) | S |
| SH11 | 144-149, 1144-1165 | SearchCustomer.jsx:167-248 | centered palette vs inline combobox | DECIDE | match prototype | M |
| SH12 | 1150, 1162 | SearchCustomer.jsx:188 | ESC chip + keyboard footer | DECIDE | match prototype | S |
| SH13 | 163-191 | PrefControls.jsx:63-89 | View options: theme 3 vs 2; labels/values | DECIDE | prototype set/copy | S |
| SH14 | 2154-2164 | i18n-journey.js:619 | context-tab meta copy | DECIDE | prototype verbatim (D5) | S |
| SH15 | 2157 | Shell.jsx:148 | recents cap 4 | DECIDE | keep cap | S |
| SH16 | 197 | RoleSwitcher.jsx:150-155 | identity avatar ring/initials | FIX | match prototype | S |
| SH17 | 143-212 | Shell.jsx:333-404 | top-bar order/extras | DECIDE | reorder env/View; keep feedback | S |
| SH18 | 1242-1252 | i18n/prefs + Shell.test | rail group/row/collapse labels | DECIDE | pinned labels | S |
| SH19 | 76-81 | App (live regions) | bottom-center toast | DECIDE | keep live regions | S |

## Settings — Settings.jsx / UsersPanel.jsx

| id | prototype | app today | gap | bucket | recommendation | size |
|---|---|---|---|---|---|---|
| SE1 | 733-759 | Settings.jsx:235-246 | flat 7-row register vs grouped fieldsets | DECIDE | flat register (prototype) | M |
| SE2 | 749-755 | Settings.jsx:686-695 | edit-on-change vs row Save/Reset | DECIDE | keep Save (audited act) | M |
| SE3 | 1388, 1303 | settings.py:19-21 | "สิทธิ์ติดต่อรายวันต่อลูกหนี้" row absent | DATA | serve key + label + unit | M |
| SE4 | 1306, 762 | UsersPanel.jsx:192 | "ผู้ใช้และสิทธิ์" register row absent | DATA | add row/count | M |
| SE5 | 1442 | i18n-admin.js:1145 | header sub copy | DECIDE | prototype verbatim (D5) | S |
| SE6 | 2613 | i18n-admin.js:1168 | locked hint copy | DECIDE | prototype verbatim (D5) | S |
| SE7 | 2600-2601 | Settings.jsx:715-727 | 2 chips vs 4 + lock icon | DECIDE | prototype chips | S |
| SE8 | 2599, 2112 | redesign-settings.css:11,31 | grid ratio + disabled field style | FIX | match prototype | S |
| SE9 | 1300-1306 | Settings.jsx:591 | per-row design notes vs generic lock note | DATA | serve per-row notes | M |
| SE10 | 1383-1389 | i18n-admin.js:1106-1117 | row labels | DECIDE | prototype verbatim (D5) | S |
| SE11 | 761-775 | UsersPanel.jsx:202-318 | users table + invite vs 4-col rows | DECIDE | keep table | M |

## Data sources — DataSourcesMigration.jsx

| id | prototype | app today | gap | bucket | recommendation | size |
|---|---|---|---|---|---|---|
| DS1 | 1020-1035 | DataSourcesMigration.jsx:421-434 | 4 static chain rows vs 3 served rungs + controls | DATA | serve rungs 2/4 (D2f) | M |
| DS2 | 1021-1022 | i18n-admin.js:1360 | chain note copy | FIX | prototype copy | S |
| DS3 | 2362 | DataSourcesMigration.jsx:385 | strip book value | DECIDE | served name vs prototype source name | S |
| DS4 | 1038-1050 | DataSourcesMigration.jsx:469-522 | numbered steps/source cards | DECIDE | keep single-act ruling | M |
| DS5 | 1047-1050 | DataSourcesMigration.jsx:529-540 | separate land block | DECIDE | keep separate act | M |
| DS6 | 1041 | DropZone.jsx:42 | drop text | FIX | prototype Thai wording | S |
| DS7 | 1067-1074 | DataSourcesMigration.jsx:607-664 | receipt shape (dl vs progress) | DECIDE | keep served receipt | M |
| DS8 | 1075-1078 | DataSourcesMigration.jsx:675 | provenance paragraph | DECIDE | keep | S |
| DS9 | — | DataSourcesMigration.jsx:699-790 | app-only panels | DECIDE | keep | L |
| DS10 | 1051-1061 | DataSourcesMigration.jsx:1310-1460 | preview report shape | DECIDE | keep served report | M |

## Action log — AuditLog.jsx

| id | prototype | app today | gap | bucket | recommendation | size |
|---|---|---|---|---|---|---|
| AL1 | 1459 | i18n-admin.js:1516 | title/sub copy | DECIDE | prototype verbatim (D5) | S |
| AL2 | 2388 | i18n-admin.js:1553 | source cell "91% จากการเข้าสู่ระบบ" | DATA | serve stat | S |
| AL3 | 1109-1113 | AuditLog.jsx:223-294 | 5-col table vs 8-col grid | DECIDE | 5-col prototype (loses role/reason) | L |
| AL4 | 1103-1112 | AuditLog.jsx:187-200 | filter labels | DECIDE | pinned visible labels | S |
| AL5 | 2392 | i18n-admin.js:1548 | claimed badge "อ้างเอง" | DECIDE | prototype verbatim | S |
| AL6 | 2391 | i18n-admin.js:1541 | result chip wording | DECIDE | prototype verbatim (D5) | S |
| AL7 | 1357 | AuditLog.jsx:40-44 | time format th-TH long vs "15/09 14:32" | FIX | fixed dd/MM HH:mm | S |
| AL8 | 2386 | AuditLog.jsx:136-180 | chain cell wording | DECIDE | prototype verbatim (D5) | S |

## Drawers — contact / review / evidence / move

| id | prototype | app today | gap | bucket | recommendation | size |
|---|---|---|---|---|---|---|
| DR1 | 1167-1177, 1223-1226 | CaseContactDrawer.jsx:886-927 | right slide-over vs centered draggable dialog | DECIDE | restyle slide-over, keep fields | L |
| DR2 | 1179-1188 | CaseContactDrawer.jsx:1021-1290 | simpler body | DECIDE | keep richer form | L |
| DR3 | 1184 | CaseContactDrawer.jsx:1092 | callout vs split labels | DECIDE | keep split | S |
| DR4 | 1190-1197 | ReviewQueue.jsx:266-321 | drawer vs inline form | DECIDE | keep inline (R9) | M |
| DR5 | 1199-1209 | none | Attach-evidence drawer missing | DECIDE | add attachment contract + drawer | L |
| DR6 | 1211-1220 | Calendar.jsx:848-887 | move panel order/labels/placeholder/note | FIX | match prototype | S |
| DR7 | 1173-1174, 1225 | various | shared drawer header/footer verbs | DECIDE | keep per-surface | M |

## Decisions

- **D1 — density census.** `density.test.jsx` caps visible elements in the record
  (and carries "authorised test edit" governance notes). 100% needs those caps
  rewritten. Approve?
- **D2 — model and serve (already agreed in principle).** Define the semantics:
  a) risk score formula; b) done-of-total for queue and contacts allowance;
  c) Recovery rates/estimates, three steps, and whether Settlement exists;
  d) allocation lines and Fix-and-resubmit (OD-02 is unset today);
  e) monthly/weekly targets for KPI bars; f) workbook/chain source labels;
  g) review-row money/DPD and per-request need; h) contract-signed evidence and
  the attachment contract; i) per-edition contacts/kept totals and published cash.
- **D3 — audit completeness vs prototype.** Action log 5 columns (prototype) or
  8 columns (role/change/reason today); Settings users card (table + invite) or
  the prototype's 4-column rows; Settings register flat (prototype) or grouped.
- **D4 — drawer shapes.** Contact drawer: prototype slide-over with fewer fields,
  or slide-over look with today's richer fields; review inline form or prototype
  drawer.
- **D5 — copy verbatim.** Already agreed: prototype Thai/English wins. EN twins
  stay per the i18n mechanism. Applies to ~30 copy rows above.

---

## Completion record — 2026-09-18

Decisions applied: D1 (density census rewritten), D2 (model and serve: risk score,
done-of-total, comparisons, targets, review money/need, contract evidence,
allocation states, recovery estimates, edition figures, source chain), D3 (match
prototype: flat register, four-column users rows, five-column audit table), D4
(contact drawer is the prototype slide-over with the richer body kept), D5
(prototype copy verbatim with EN twins).

Built in this pass — backend: risk.py + weights; team/shell completion counts,
comparisons, targets and `GET /v1/shell/summary`; review rows with money/DPD/need/
risk; pipeline conditions re-cut with the evidence model and endpoints; payments
allocation states, need sentences and resubmit; recovery rate/estimate/steps;
audit signing-source stat; four-rung source chain; edition figures; and the
record's `risk_score` / `contact_allowance` / workbook `source_label`. Frontend:
all twelve screens rebuilt to the prototype (Shell chrome, Overview, Today/Book/
Record five tabs, Calendar fixed month + week card, Reviews, Pipeline evidence
drawer, Payments allocation + resubmit, Recovery cards, Reports, Settings flat
register, Data sources rungs, Action log table, drawer slide-over).

UAT: scripted at `scripts/uat_final_v2.mjs` → `.v2-outcome/uat/uat-report.md`
(screen walk TH/EN, acceptance list, product failures with reproduction). The one
real product bug it found — pipeline gate responses returning pre-write conditions
— is fixed with regression tests (`fix(ui+api): UAT findings…`).

Known residuals, deliberately documented rather than faked:
- Payments row arrears (PAY-13) and per-edition risk stripe (REP-13): no served
  signal exists; the rows keep the document amount / neutral edge.
- Recovery cash rows keep the group tone (risk score is served for NPL/recovery
  rows only).
- Recovery confirm below Manager shows the approval label; no approval queue is
  modelled for opening a recovery (the restructure path has its own panel).
- `reason-required` acts, lock model and role refusals keep their ruled
  safeguards (D3/D4 did not ask to remove those).
