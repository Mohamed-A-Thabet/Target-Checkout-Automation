import re
import time
import threading
from datetime import datetime, timezone, timedelta
from typing import Optional
from imap_tools import MailBox, A

class TargetOTPListener:
    def __init__(self, gmail_email: str, app_password: str):
        self.email = gmail_email
        self.password = app_password
        self._code: Optional[str] = None
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._armed_at: Optional[datetime] = None

    def start(self):
        print("📧 Starting background listener for Target OTP...")
        self._code = None
        self._armed_at = None
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._monitor_inbox, daemon=True)
        self._thread.start()

    def arm(self):
        self._code = None
        self._armed_at = datetime.now(timezone.utc)
        print(f"🎯 OTP listener armed at {self._armed_at.isoformat()}")

    def stop(self):
        if self._thread and self._thread.is_alive():
            print("🛑 Stopping background listener...")
            self._stop_event.set()
            self._thread.join(timeout=5)

    def get_code(self) -> Optional[str]:
        return self._code

    def wait_for_code(self, timeout: float = 30.0, poll_interval: float = 0.1) -> Optional[str]:
        """
        Waits up to `timeout` seconds for the OTP to appear.
        """
        end = time.monotonic() + timeout
        while time.monotonic() < end and not self._stop_event.is_set():
            if self._code:
                return self._code
            time.sleep(poll_interval)
        return None

    def _extract_code(self, msg) -> Optional[str]:
        sender = (msg.from_ or "").lower()
        subject = (msg.subject or "").lower()

        if "target" not in sender and "target" not in subject:
            return None

        content = "\n".join([
            msg.subject or "",
            msg.text or "",
            msg.html or "",
        ])

        # First try an OTP-ish pattern
        m = re.search(
            r"(?:verification|security|one[- ]time|login|sign[- ]in)?[\s\S]{0,80}\b(\d{6})\b",
            content,
            re.IGNORECASE
        )
        if m:
            return m.group(1)

        # Fallback: any 6-digit number
        m = re.search(r"\b(\d{6})\b", content)
        return m.group(1) if m else None

    def _scan_recent_messages(self, mailbox) -> bool:
        """
        Scan only the most recent few messages.
        """
        cutoff = self._armed_at or datetime.now(timezone.utc)

        for msg in mailbox.fetch(A(all=True), mark_seen=False, reverse=True, limit=10):
            msg_date = msg.date
            if msg_date.tzinfo is None:
                msg_date = msg_date.replace(tzinfo=timezone.utc)

            if msg_date < cutoff:
                break

            code = self._extract_code(msg)
            if code:
                self._code = code
                print(f"✅ [BACKGROUND] OTP FOUND: {self._code}")
                return True

        return False

    def _monitor_inbox(self):
        while not self._stop_event.is_set():
            try:
                with MailBox("imap.gmail.com").login(self.email, self.password, "INBOX") as mailbox:
                    print("✅ Background listener connected.")

                    while not self._stop_event.is_set():
                        # First do a quick scan in case the email already arrived
                        if self._armed_at and self._scan_recent_messages(mailbox):
                            return

                        # Sleep 2 seconds to avoid aggressive Gmail IMAP rate-limiting
                        time.sleep(2.0)

            except Exception as e:
                print(f"⚠️ [BACKGROUND] Listener warning: {e}")
                time.sleep(2)
