# Postmortem — DR Drill Lab 23

Theo đúng template §4 "Sau Failover: Blameless Postmortem". Blameless: câu hỏi là
"hệ thống/process nào cho phép chuyện này", không phải "ai làm sai".

## 1. Timeline (mọi dòng phải có evidence path:line)

| ISO time | Sự kiện | Evidence |
|---|---|---|
| 2026-10-09T02:54:53 | outage bắt đầu | `chaos/chaos-events.jsonl:5` |
| 2026-10-09T02:54:53 | user đầu tiên bị ảnh hưởng | `reports/drill-2-withdr.jsonl:25` |
| 2026-10-09T02:55:13 | health check alert | `reports/health-events.jsonl:3` |
| 2026-10-09T02:55:15 | operator confirm cutover | `reports/runbook-run.jsonl` |
| 2026-10-09T02:55:15 | resolved (request đầu tiên OK từ region phụ) | `reports/drill-2-withdr.jsonl:36` |

## 2. RTO/RPO đo được vs mục tiêu — gap ở bước nào?

- RTO mục tiêu: 300s · đo được: `22.3s` · gap: `-277.7s` ✅ (tốt hơn mục tiêu)
- RPO mục tiêu: 300s · đo được: `28.06s` (`14` doc bị mất) · gap: `-271.94s` ✅
- **Bước tốn nhiều giây nhất:** `Health-check detect floor` — vì sao? Đây là khoảng thời gian chờ để xác nhận region thật sự down (3 lần fail × 5s = 15s). Đây là trade-off giữa phát hiện nhanh và tránh false positive.

## 3. Root cause (5 whys)

Không phải "vì tôi chạy chaos script". Câu hỏi: *nếu đây là outage thật, bước nào
trong runbook của tôi sẽ thất bại?*

1. Tại sao Region A không tự phục hồi? → Vì không có auto-failover khi không có DR
2. Tại sao health check cần 15s để phát hiện? → Đây là threshold chống flapping (false positive)
3. Tại sao cần threshold chống flapping? → Nếu không có threshold, network blip nhỏ sẽ trigger failover không cần thiết
4. Tại sao failover ngược lại không tự động? → Full-auto failover có thể gây flapping giữa 2 region
5. Tại sao flapping nguy hiểm? → Mỗi failover = downtime + data loss tiềm năng

## 4. Action items (có owner + deadline)

| # | Action | Owner | Deadline | Giảm RTO/RPO bao nhiêu giây |
|---|---|---|---|---|
| 1 | Giảm health check interval từ 5s xuống 2s | DevOps | 1 tuần | -9s |
| 2 | Thêm alerting khi detect floor > 10s | SRE | 2 tuần | 0s (giám sát) |

## 5. Ba câu hỏi bắt buộc trả lời

1. `interval × threshold` của bạn là bao nhiêu giây? Nó chiếm bao nhiêu % RTO?
   - 5s × 3 = 15s, chiếm ~67% RTO (15s / 22.3s)

2. Nếu hạ interval xuống 1s, RTO giảm mấy giây — và bạn trả giá gì (§4 flapping)?
   - Giảm được ~12s (15s → 3s), nhưng tăng nguy cơ false positive khi network không ổn định

3. Nếu outage kéo dài 6 giờ và region chính mất dữ liệu vĩnh viễn, `docs_lost` của
   bạn có nghĩa gì với khách hàng?
   - 14 documents bị mất = 14 queries không được trả lời = potential data inconsistency
   - Khách hàng có thể nhận thấy: thiếu thông tin, không tìm thấy document gần đây
