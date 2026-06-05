"""
Bộ quyết định buồn ngủ tập trung - Phương án A (luật >=2/3 chỉ số).

Đây là nơi DUY NHẤT chứa "luật" phán xét buồn ngủ. Mỗi chỉ số (mắt/miệng/đầu)
được coi là "vi phạm" khi vượt ngưỡng liên tục đủ thời gian xác nhận của nó.

  - >=2/3 chỉ số vi phạm  -> DROWSY (high), cảnh báo.
  - đúng 1/3 và là mắt     -> EYES_CLOSED (low), cảnh báo nhẹ.
  - 1/3 là miệng/đầu, 0    -> không cảnh báo.

Lớp này thuần Python: không phụ thuộc Flask/MediaPipe/camera, thời gian được
truyền vào qua tham số `now` để dễ kiểm thử.
"""


class DrowsinessDetector:
    def __init__(self, ear_threshold=0.22, mar_threshold=0.3,
                 eyes_seconds=3.0, mouth_seconds=2.0, head_seconds=2.0):
        self.ear_threshold = ear_threshold
        self.mar_threshold = mar_threshold
        self.eyes_seconds = eyes_seconds
        self.mouth_seconds = mouth_seconds
        self.head_seconds = head_seconds
        self.reset()

    def reset(self):
        """Xóa state đếm thời gian. Gọi khi đổi tài xế hoặc mất khuôn mặt."""
        self._eyes_since = None
        self._mouth_since = None
        self._head_since = None

    @staticmethod
    def _sustained(over, since, now, seconds):
        """
        Trả (đang_vi_phạm, since_mới).
        over: chỉ số có đang vượt ngưỡng ở frame này không.
        since: mốc thời gian bắt đầu vượt ngưỡng (None nếu chưa).
        """
        if not over:
            return False, None
        if since is None:
            since = now
        return (now - since) >= seconds, since

    def update(self, ear, mar, head_down, now):
        eyes_breaching, self._eyes_since = self._sustained(
            ear < self.ear_threshold, self._eyes_since, now, self.eyes_seconds)
        mouth_breaching, self._mouth_since = self._sustained(
            mar > self.mar_threshold, self._mouth_since, now, self.mouth_seconds)
        head_breaching, self._head_since = self._sustained(
            bool(head_down), self._head_since, now, self.head_seconds)

        count = int(eyes_breaching) + int(mouth_breaching) + int(head_breaching)

        if count >= 2:
            alert_type, alert_level = "DROWSY", "high"
        elif count == 1 and eyes_breaching:
            alert_type, alert_level = "EYES_CLOSED", "low"
        else:
            alert_type, alert_level = None, None

        return {
            "eyes_breaching": eyes_breaching,
            "mouth_breaching": mouth_breaching,
            "head_breaching": head_breaching,
            "count": count,
            "alert_type": alert_type,
            "alert_level": alert_level,
        }
