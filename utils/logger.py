# ==============================================================
# utils/logger.py
# Cấu hình logging tập trung cho toàn bộ dự án.
# Các module khác chỉ cần:
#   from utils.logger import setup_logger
#   logger = setup_logger(__name__)
# ==============================================================

import os
import sys
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime
from zoneinfo import ZoneInfo

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
LOG_FILE = os.path.join(LOG_DIR, "violations.log")

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

_initialized_loggers = set()


class VNTimeFormatter(logging.Formatter):
    """Formatter hiển thị thời gian theo múi giờ Việt Nam (UTC+7),
    đồng bộ với database.py đang dùng Asia/Ho_Chi_Minh."""

    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created, tz=VN_TZ)
        if datefmt:
            return dt.strftime(datefmt)
        return dt.strftime("%Y-%m-%d %H:%M:%S")


def setup_logger(name: str) -> logging.Logger:
    """
    Tạo và trả về logger đã cấu hình sẵn 2 handler:
      - StreamHandler: in ra terminal (giống database.py hiện tại)
      - TimedRotatingFileHandler: ghi vào logs/violations.log,
        rotation mỗi ngày, giữ tối đa 30 file cũ

    Args:
        name: thường truyền __name__ để biết log từ module nào

    Returns:
        logging.Logger đã cấu hình, sẵn sàng dùng .info(), .warning(), .error()
    """
    if name in _initialized_loggers:
        return logging.getLogger(name)

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    if logger.handlers:
        _initialized_loggers.add(name)
        return logger

    formatter = VNTimeFormatter(
        fmt="[%(asctime)s] [%(levelname)s] %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(formatter)

    os.makedirs(LOG_DIR, exist_ok=True)

    file_handler = RotatingFileHandler(
        filename=LOG_FILE,
        maxBytes=5 * 1024 * 1024,
        backupCount=30,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    _initialized_loggers.add(name)
    return logger
