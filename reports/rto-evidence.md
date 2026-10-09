# RTO/RPO Evidence — Lab 23

Quy tắc duy nhất: mỗi con số ở đây phải trỏ được về **một dòng log thật**
(`đường/dẫn.jsonl:số_dòng`). `pytest tests/test_rto_evidence.py` sẽ mở từng file ra kiểm tra.
Con số không có evidence = trượt, bất kể các phần khác.

## 1. Drill 1 — không có DR (baseline)

| Chỉ số | Giá trị | Cách đo | Evidence |
|---|---|---|---|
| t_outage | `2026-10-09T02:35:22` | chaos kill | `chaos/chaos-events.jsonl:1` |
| Request fail đầu tiên | `+0.2s` | dòng `ok:false` đầu tiên sau t_outage | `reports/drill-1-nodr.jsonl:17` |
| Request thành công sau đó | không có | không có dòng `ok:true` nào sau t_outage | `reports/drill-1-nodr.jsonl` (không có recovery) |
| RTO | `NO_RECOVERY` | `tools/measure_rto.py` | `reports/drill-1-nodr.jsonl` |

## 2. Drill 2 — có DR

| Mốc | +giây từ t_outage | Cách đo | Evidence |
|---|---|---|---|
| t_outage (mốc 0) | 0 | `action:kill` | `chaos/chaos-events.jsonl:5` |
| User thấy lỗi đầu tiên | +0.1s | dòng `ok:false` đầu | `reports/drill-2-withdr.jsonl:25` |
| Health check phát hiện | +19.2s | `to:UNHEALTHY, region:a` | `reports/health-events.jsonl:1` |
| Snapshot restore xong | +22.2s | `step:2_restore_snapshot` | `reports/failover-events.jsonl:3` |
| Region phụ ready | +22.2s | `step:4_wait_ready` | `reports/failover-events.jsonl:5` |
| DNS cutover | +22.2s | `step:5_dns_cutover` | `reports/failover-events.jsonl:7` |
| **RTO đo được** | **+22.3s** | dòng `ok:true` đầu sau lỗi | `reports/drill-2-withdr.jsonl:36` |

| Chỉ số | Đo được | Mục tiêu (slide §1) | Verdict |
|---|---|---|---|
| RTO — Inference API | `22.3s` | 300s (5 phút) | ✅ PASS |
| RPO — Vector DB | `28.06s` / `14` doc | 300s (5 phút) | ✅ PASS |

## 3. RTO của tôi gồm những gì (bắt buộc — đây là phần chấm điểm hiểu bài)

| Thành phần | Giây | Nó đến từ đâu | Giảm được bằng cách nào |
|---|---|---|---|
| Health-check detect floor | 15.0s | `interval_s × threshold` = 5 × 3 | Giảm interval hoặc threshold |
| Snapshot restore | ~0.03s | 2_restore → 3_scale | Đã nhanh (fs backend) |
| GPU pool warm-up | 0.02s | `waited_s` ở `4_wait_ready` | Đã nhanh |
| DNS/LB TTL cache | 0.1s | t_recovered − t_cutover | Giảm EDGE_TTL_SECONDS |
| **Tổng RTO** | **~22.3s** | | |
