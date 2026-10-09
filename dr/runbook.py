"""BƯỚC 3c — SINH VIÊN VIẾT. Tự động hoá runbook §4 "Runbook: Region Chính Down".

7 bước trên slide, mỗi bước 1 dòng log có ts. Log này CHÍNH LÀ timeline của postmortem.
  1 xac_nhan_outage          — probe cả 2 region, đừng tin 1 lần fail (dùng nhiều lần
                              hoặc gọi health_checker.probe nếu đã viết xong 3a)
  2 thong_bao_incident       — ts của dòng này là mốc "operator biết tin", LUÔN LUÔN
                              SAU t_outage trong chaos-events (không thể trùng — operator
                              không thể biết ngay giây outage xảy ra). Ghi cả 2 ts vào
                              log để postmortem tính được "độ trễ thông báo".
  3 scale_gpu_pool           — gọi HÀM `failover.failover(...)` MỘT LẦN DUY NHẤT. Hàm
                              đó tự làm đủ 5 bước con (verify/restore/scale/wait/cutover)
                              và tự ghi log riêng vào reports/failover-events.jsonl.
  4 verify_state_replica     — KHÔNG gọi lại failover — chỉ ĐỌC kết quả (vector count +
                              weights ở region phụ) từ dict mà bước 3 trả về, để log vào
                              runbook-run.jsonl cho postmortem đọc 1 chỗ duy nhất.
  5 dns_cutover              — cũng chỉ đọc lại: kết quả cutover có ok hay không.
  6 verify_golden_signals    — 10 request thật vào region phụ: p95 latency + error rate
  7 post_incident            — elapsed_s + lệnh đo RTO

BÁN TỰ ĐỘNG, KHÔNG FULL-AUTO (§4: "failover đầu tiên nên là bán tự động — alert +
1-click confirm — tránh flapping gây failover 2 chiều liên tục"). Mặc định phải hỏi
người vận hành confirm; --auto chỉ dùng trong CI/khi chấm điểm.

Chạy:  python dr/runbook.py --primary a --target b --backend fs
"""
import argparse
import json
import pathlib
import sys
import time

import httpx

sys.path.insert(0, ".")
from dr import failover as fo  # noqa: E402

LOG = pathlib.Path("reports/runbook-run.jsonl")
URL = {"a": "http://127.0.0.1:8001", "b": "http://127.0.0.1:8002"}


def step(n, name, **kw):
    """Ghi 1 dòng {ts, iso, step, name, ...} vào LOG."""
    kw["ts"] = time.time()
    kw["iso"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    kw["step"] = n
    kw["name"] = name
    line = json.dumps(kw)
    print(line)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def confirm(auto: bool, msg: str) -> bool:
    """auto=True -> True; ngược lại hỏi y/N."""
    if auto:
        return True
    print(f"\n⚠️  {msg}")
    resp = input("Proceed? [y/N]: ").strip().lower()
    return resp == "y"


def probe_region(region: str, timeout: float = 2.0) -> tuple[bool, str]:
    """Probe 1 region, trả về (ready, reason)."""
    try:
        resp = httpx.get(f"{URL[region]}/readyz", timeout=timeout)
        if resp.status_code == 200:
            return True, "ready"
        return False, f"status={resp.status_code}"
    except httpx.TimeoutException:
        return False, "timeout"
    except httpx.ConnectError:
        return False, "connection_error"
    except Exception as e:
        return False, f"error:{type(e).__name__}"


def run(primary: str, target: str, backend: str, auto: bool) -> dict:
    """7 bước ở trên."""
    start_time = time.time()

    # 1. Xác nhận outage - probe nhiều lần
    step(1, "xac_nhan_outage")
    outage_confirmed = False
    for _ in range(3):
        ready_primary, reason_primary = probe_region(primary)
        if not ready_primary:
            outage_confirmed = True
            step(1, "xac_nhan_outage", primary=primary, reason=reason_primary, confirmed=True)
            break
        time.sleep(1)

    if not outage_confirmed:
        step(1, "xac_nhan_outage", primary=primary, reason="still_healthy", confirmed=False)
        return {"ok": False, "reason": "primary_not_down"}

    # 2. Thông báo incident
    step(2, "thong_bao_incident", primary=primary, target=target)

    # 3. Confirm trước khi failover
    if not confirm(auto, f"Region {primary} is down. Initiate failover to {target}?"):
        step(3, "scale_gpu_pool", status="cancelled_by_user")
        return {"ok": False, "reason": "user_cancelled"}

    # Gọi failover MỘT LẦN DUY NHẤT
    step(3, "scale_gpu_pool")
    failover_result = fo.failover(target, backend, wait=60)

    # 4. Verify state replica
    step(4, "verify_state_replica",
         vector_count=failover_result.get("vector_count", 0),
         weights_loaded=failover_result.get("weights_loaded", False),
         docs_lost=failover_result.get("docs_lost"),
         rpo_seconds=failover_result.get("rpo_seconds"))

    # 5. DNS cutover result
    step(5, "dns_cutover",
         ok=failover_result.get("ok", False),
         target=target)

    # 6. Verify golden signals - 10 requests thật
    latencies = []
    errors = 0
    for i in range(10):
        try:
            t0 = time.time()
            resp = httpx.get(f"{URL[target]}/v1/infer", timeout=10.0)
            lat = (time.time() - t0) * 1000  # ms
            latencies.append(lat)
            if resp.status_code != 200:
                errors += 1
        except Exception:
            errors += 1
            latencies.append(10000)  # timeout = 10000ms

    latencies.sort()
    p95 = latencies[8] if len(latencies) >= 9 else latencies[-1]
    error_rate = errors / 10

    step(6, "verify_golden_signals",
         p95_latency_ms=round(p95, 2),
         error_rate=error_rate,
         requests=10)

    # 7. Post incident
    elapsed = time.time() - start_time
    step(7, "post_incident",
         elapsed_s=round(elapsed, 2),
         failover_ok=failover_result.get("ok", False),
         measure_cmd=f"python3 tools/measure_rto.py --loadgen reports/drill-2-withdr.jsonl --target-rto 300")

    return {
        "ok": failover_result.get("ok", False),
        "elapsed_s": round(elapsed, 2),
        "failover": failover_result,
        "golden_signals": {"p95_ms": round(p95, 2), "error_rate": error_rate},
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--primary", default="a")
    p.add_argument("--target", default="b")
    p.add_argument("--backend", default="fs", choices=["fs", "minio"])
    p.add_argument("--auto", action="store_true")
    a = p.parse_args()
    print(json.dumps(run(a.primary, a.target, a.backend, a.auto), indent=2))
