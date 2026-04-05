# -*- coding: utf-8 -*-
"""
Chuẩn hóa thời gian hiển thị: DB/email lưu UTC, hiển thị theo giờ Việt Nam (UTC+7).

Ưu tiên zoneinfo (Python 3.9+). Trên Python cũ hơn dùng timezone cố định +7
(Việt Nam không DST — tương đương Asia/Ho_Chi_Minh).
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional

try:
    from zoneinfo import ZoneInfo

    VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
except ModuleNotFoundError:  # pragma: no cover
    VN_TZ = timezone(timedelta(hours=7))

UTC_TZ = timezone.utc


def format_utc_iso_to_vn(iso_str: Optional[str]) -> str:
    """
    Parse chuỗi ISO từ DB (thường kết thúc Z = UTC) và format dd/mm/YYYY HH:MM tại VN.
    Nếu parse lỗi, trả về chuỗi gốc.
    """
    if not iso_str:
        return ""
    s = str(iso_str).strip()
    try:
        if s.endswith("Z"):
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        else:
            dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC_TZ)
        return dt.astimezone(VN_TZ).strftime("%d/%m/%Y %H:%M")
    except (ValueError, TypeError, OSError):
        return s


def now_utc_iso_z() -> str:
    """Thời điểm hiện tại UTC dạng ISO kết thúc Z (lưu DB)."""
    dt = datetime.now(timezone.utc).replace(microsecond=0)
    return dt.isoformat().replace("+00:00", "Z")


def format_now_vn() -> str:
    """Thời gian hiện tại (UTC) hiển thị theo giờ Việt Nam — dùng email liên hệ."""
    return datetime.now(timezone.utc).astimezone(VN_TZ).strftime("%d/%m/%Y %H:%M")
