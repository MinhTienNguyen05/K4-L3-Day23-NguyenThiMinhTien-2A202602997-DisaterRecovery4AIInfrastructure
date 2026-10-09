# Runbook 1 trang — Region chính down

Runbook phải chạy được lúc 3h sáng bởi người KHÔNG viết nó. Mỗi bước: lệnh copy-paste
được + cách biết bước đó xong.

| # | Bước | Lệnh | Biết là xong khi | Ai làm |
|---|---|---|---|---|
| 1 | Xác nhận outage | `curl localhost:8001/healthz` (timeout hoặc 503) | 3 lần liên tiếp không kết nối được | on-call |
| 2 | Mở incident + bấm giờ RTO | `python3 dr/runbook.py --primary a --target b --backend fs` | ts ghi vào `reports/runbook-run.jsonl` | on-call |
| 3 | Restore state ở region phụ | (tự động trong runbook) | Log có `step:2_restore_snapshot_done` với `rpo_seconds` | SRE |
| 4 | Scale pool warm→full | (tự động trong runbook) | Log có `step:4_wait_ready` với `status:ready` | SRE |
| 5 | DNS/LB cutover | (tự động trong runbook) | Log có `step:5_dns_cutover` + `curl localhost:8080/edge/state` cho `active_region=b` | SRE |
| 6 | Verify golden signals | (tự động trong runbook) | Log có `step:6` với p95 < 100ms, error_rate = 0 | on-call |
| 7 | Đo RTO + postmortem | `python3 tools/measure_rto.py --loadgen reports/drill-2-withdr.jsonl --target-rto 300` | `rto_verdict` = PASS | on-call |

**Rollback (failover ngược):**
- **Điều kiện:** Region A đã restore hoàn toàn và ổn định, p95 < 50ms trong 10 phút
- **Ai quyết định:** Site Reliability Engineer (SRE) Lead hoặc Engineering Manager
- **Lệnh rollback:** `echo "a" > edge/active_region` sau khi xác nhận Region A healthy

**§4 Anti-Patterns:** KHÔNG dùng full-auto failover. Luôn cần human-in-the-loop với confirm `y/N` để tránh flapping gây failover 2 chiều liên tục.
