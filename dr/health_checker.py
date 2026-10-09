"""BƯỚC 3a — SINH VIÊN VIẾT. Health checker cho 2 region.

Yêu cầu (đọc §4 "Kiến Trúc Health-Check-Based Failover" + §2 "DNS Failover"):
  1. Poll /readyz của CẢ HAI region mỗi `interval` giây (mặc định 5s).
     Dùng /readyz, KHÔNG dùng /healthz. /healthz chỉ nói "process còn sống" —
     region có process sống nhưng vector DB rỗng thì vẫn không serve được.
  2. Chỉ đổi trạng thái sau `threshold` lần fail LIÊN TIẾP (mặc định 3).
     Một lần fail không phải outage. Đây là chống flapping (§4 Anti-Patterns).
  3. Ghi 1 dòng JSONL MỖI LẦN ĐỔI TRẠNG THÁI (không ghi mỗi lần poll — log sẽ ngập).
     Dòng bắt buộc có: ts, region, to (HEALTHY|UNHEALTHY), reason,
     interval_s, threshold. Thiếu interval_s/threshold thì tools/measure_rto.py
     không tính được detect floor -> mất điểm.

Chạy:  python dr/health_checker.py --interval 5 --threshold 3 --duration 300 \
              --out reports/health-events.jsonl

CÂU HỎI PHẢI TRẢ LỜI TRƯỚC KHI VIẾT (ghi câu trả lời vào reports/postmortem.md):
  interval=5s, threshold=3 -> sớm nhất bạn có thể phát hiện outage là bao nhiêu giây?
  Con số đó nằm TRONG RTO của bạn. Muốn RTO 5 phút thì được phép chọn interval bao nhiêu?
"""
import argparse
import json
import pathlib
import time

import httpx

URL = {"a": "http://127.0.0.1:8001", "b": "http://127.0.0.1:8002"}


def probe(region: str, timeout: float) -> tuple[bool, str]:
    """Trả về (ready, reason). Timeout PHẢI có — netblock làm request treo mãi."""
    try:
        resp = httpx.get(f"{URL[region]}/readyz", timeout=timeout)
        if resp.status_code == 200:
            return True, "ready"
        else:
            return False, f"status={resp.status_code}"
    except httpx.TimeoutException:
        return False, "timeout"
    except httpx.ConnectError:
        return False, "connection_error"
    except Exception as e:
        return False, f"error:{type(e).__name__}"


def run(interval: float, timeout: float, threshold: int, duration: float, out: pathlib.Path):
    """Vòng lặp poll + phát hiện transition + ghi JSONL."""
    # Track trạng thái hiện tại của mỗi region
    states = {"a": "HEALTHY", "b": "HEALTHY"}
    # Track số lần fail liên tiếp
    consecutive_fails = {"a": 0, "b": 0}

    out.touch()
    start = time.time()

    while time.time() - start < duration:
        for region in ["a", "b"]:
            ready, reason = probe(region, timeout)

            if ready:
                consecutive_fails[region] = 0
                new_state = "HEALTHY"
            else:
                consecutive_fails[region] += 1
                # Chỉ chuyển sang UNHEALTHY khi đủ threshold lần fail liên tiếp
                if consecutive_fails[region] >= threshold:
                    new_state = "UNHEALTHY"
                else:
                    new_state = states[region]

            # Chỉ ghi log khi trạng thái THỰC SỰ thay đổi
            if new_state != states[region]:
                event = {
                    "ts": time.time(),
                    "iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "event": "state_change",
                    "region": region,
                    "from": states[region],
                    "to": new_state,
                    "reason": reason,
                    "consecutive_fails": consecutive_fails[region],
                    "interval_s": interval,
                    "threshold": threshold,
                }
                states[region] = new_state

                with open(out, "a") as f:
                    f.write(json.dumps(event) + "\n")

        time.sleep(interval)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--interval", type=float, default=5.0)
    p.add_argument("--timeout", type=float, default=2.0)
    p.add_argument("--threshold", type=int, default=3)
    p.add_argument("--duration", type=float, default=300)
    p.add_argument("--out", default="reports/health-events.jsonl")
    a = p.parse_args()
    run(a.interval, a.timeout, a.threshold, a.duration, pathlib.Path(a.out))
