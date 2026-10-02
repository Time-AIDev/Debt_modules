# Production สำหรับผู้ใช้ไม่เกิน 10 คน โดยคง Regional HA

ราคาอ้างอิง Cloud Billing Catalogue วันที่ 2 ตุลาคม 2026 สำหรับ `asia-southeast1` และสกุล THB; rates มีผล 1 ตุลาคม 2026. เก็บ SKU และ unit rates ที่ใช้ใน `pricing-snapshot.json`. Billing account ที่อ่านพบมี currency THB แต่ยังไม่ได้รับคำยืนยันให้ผูก production project กับบัญชีนั้น.

สมมติฐาน 730 ชั่วโมง/เดือน, on-demand, ไม่หัก free tier/credits/CUD, ไม่รวมภาษีและ staging เดิม. จำนวนผู้ใช้ไม่ใช่ตัวกำหนดค่าใช้จ่ายทั้งหมด: ขนาดข้อมูล, จำนวน import, cold starts และ logs มีผลด้วย.

| รายการ | วิธีคำนวณโดยประมาณ | บาท/เดือน |
|---|---|---:|
| SQL HA CPU 2 vCPU | `2 × 730 × 3.883293` | 5,670 |
| SQL HA RAM 8 GiB | `8 × 730 × 0.658413` | 3,845 |
| SQL HA SSD 20 GiB | `20 × 15.99003` | 320 |
| Backup/PITR | สมมติ billed backup storage 60 GiB × 3.76236; ต้องตรวจปริมาณจริง | 226 |
| Cloud Run ทุก service | API idle + สมมติ API active 40h, worker 10h, scanner 3h, web 20h | 1,220 |
| HTTPS LB | forwarding-rule minimum 730 × 0.8398125 + processed data 100 GiB สองทิศทาง | 674 |
| NAT | IP 1 ตัว + เผื่อ instance-equivalent 8 ตัวตลอดเดือน + data 20 GiB | 428 |
| Cloud Armor Standard | 1 policy + 3 rules + 1 ล้าน requests | 294 |
| GCS, registry, secrets, tasks, scheduler, logs, internet egress | เผื่อการใช้งานต่ำ; เปลี่ยนตามปริมาณจริง | 300–1,000 |
| **รวมก่อน contingency** | | **ประมาณ 13,000–13,700** |

**วงเงินที่เสนอ 15,000 บาท/เดือน ยังไม่ถือว่าได้รับอนุมัติ.** ตั้ง budget alerts 50/80/100%; budget ไม่หยุดค่าใช้จ่าย. เดือนที่ restore drill หรือ load test อาจมี temporary SQL instance, backup copies และ compute เพิ่ม ต้องแยกประมาณการก่อนรัน.

Cloud Run API 1 CPU / 2 GiB min 1 max 3 concurrency 4; web min 0 max 2; worker min 0 max 1; scanner min 0 max 1. ใช้ Direct VPC egress แทน paid VPC connector. SQL storage auto-grow เพิ่มค่าใช้จ่ายตามพื้นที่จริง. เก็บ HA, daily backups 30 ชุด และ PITR 7 วันไว้. ยังไม่มี load proof ว่าขนาดนี้ผ่าน SLA ของ application.

ไม่จอง CUD จนกว่าจะเห็น usage จริงอย่างน้อยหนึ่งรอบ billing. ไม่เพิ่ม Redis, replica หรือ GKE ในรอบแรก.

แหล่งอ้างอิง: [Cloud Billing Catalogue](https://docs.cloud.google.com/billing/v1/how-tos/catalog-api), [Cloud SQL pricing](https://cloud.google.com/sql/pricing), [Cloud Run pricing](https://cloud.google.com/run/pricing), [Network pricing](https://cloud.google.com/vpc/network-pricing), [Cloud Armor pricing](https://cloud.google.com/armor/pricing).
