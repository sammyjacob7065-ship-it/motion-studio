"""Progress reporting: one Telegram message that is edited at each stage, plus status.json for /status."""
import datetime
import time
from common import Cancelled

STAGES = [
    ("brief", "📥", "Brief received"),
    ("assets", "🔍", "Checking your files"),
    ("plan", "🧠", "Director is planning"),
    ("stock", "🖼", "Getting pictures"),
    ("voice", "🎙", "Voice and timing"),
    ("timeline", "🎞", "Director is writing the timeline"),
    ("review", "👀", "Checking the layout"),
    ("render", "🎬", "Rendering"),
    ("audio", "🎚", "Mixing audio"),
    ("deliver", "📦", "Delivering"),
]
LABEL = {k: (e, t) for k, e, t in STAGES}


class Monitor:
    def __init__(self, store, tg, job):
        self.store, self.tg, self.job = store, tg, job
        self.msg_id = None
        self.lines = {}
        self.current = None
        self.state = "running"
        self._last_pct_sent = -100

    def _now(self):
        return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

    def _text(self, extra=""):
        out = [f"Motion job {self.job}"]
        for key, _e, _t in STAGES:
            if key in self.lines:
                out.append(self.lines[key])
        if extra:
            out.append(extra)
        return "\n".join(out)

    def _push(self, status, extra=""):
        try:
            if self.msg_id is None or not self.tg.edit(self.msg_id, self._text(extra)):
                self.msg_id = self.tg.send(self._text(extra))
        except Exception:  # noqa: BLE001
            pass
        self.write_status(**status)

    def write_status(self, state=None, stage="", pct=0, message="", output_url=""):
        self.state = state or self.state
        try:
            self.store.put_json(f"motion/jobs/{self.job}/status.json", {"job_id": self.job, "state": self.state, "stage": stage, "pct": pct, "message": message, "updated_at": self._now(), "output_url": output_url})
        except Exception:  # noqa: BLE001
            pass

    def _line(self, key, mark, note=""):
        e, t = LABEL[key]
        self.lines[key] = f"{mark} {e} {t}" + (f" — {note}" if note else "")

    def stage(self, key, note=""):
        self.check_cancel()
        if self.current and self.current in self.lines and self.lines[self.current].startswith("▶"):
            self.lines[self.current] = "✅" + self.lines[self.current][1:]
        self.current = key
        self._line(key, "▶", note)
        self._push({"state": "running", "stage": LABEL[key][1]})

    def done_stage(self, key, note=""):
        self._line(key, "✅", note)

    def note(self, key, note):
        self._line(key, "▶" if key == self.current else "✅", note)
        self._push({"state": "running", "stage": LABEL[key][1]})

    def progress(self, pct, label="Rendering"):
        if pct - self._last_pct_sent < 10 and pct < 100:
            return
        self._last_pct_sent = pct
        self._line("render", "▶", f"{pct}%")
        self._push({"state": "running", "stage": label, "pct": pct})

    def check_cancel(self):
        flag = self.store.get_json(f"motion/jobs/{self.job}/cancel.json")
        if flag and flag.get("cancel", True):
            self.state = "cancelled"
            self.write_status(state="cancelled", stage="Cancelled", message="Stopped by you")
            self.tg.send(f"🛑 Job {self.job} cancelled.")
            raise Cancelled()

    def wait_approval(self, minutes=30):
        """Plan-first mode: wait for /go (approve.json) or /cancel."""
        end = time.time() + minutes * 60
        while time.time() < end:
            self.check_cancel()
            if self.store.get_json(f"motion/jobs/{self.job}/approve.json"):
                return True
            time.sleep(10)
        return False

    def fail(self, stage, err):
        self.write_status(state="failed", stage=f"Failed at: {stage}", message=str(err)[:300])
        self.tg.send(f"❌ Job {self.job} failed at: {stage}\n{str(err)[:500]}\n\nFix the cause if it says what to fix, then send /resume to continue this job from where it stopped (the finished steps are saved). Or send your prompt again to start fresh. If it repeats, check the Actions log in the motion-studio repo.")

    def finish(self, url, note=""):
        self._line("deliver", "✅", "")
        self.write_status(state="done", stage="Done", pct=100, message=note[:300], output_url=url)
