# -*- coding: utf-8 -*-
"""
Gửi email đơn hàng qua Flask-Mail (HTML).
Lỗi gửi mail được bắt và in ra console — không làm crash ứng dụng.
"""
from __future__ import annotations

import html
import traceback
from typing import Any, Dict, List, Optional

from flask_mail import Message

from time_utils import format_now_vn, format_utc_iso_to_vn


def _format_dt(created_at: str) -> str:
    """Thời gian đặt hàng: UTC từ DB → hiển thị giờ Việt Nam."""
    return format_utc_iso_to_vn(created_at)


def build_order_html(
    order: Dict[str, Any], items: List[Dict[str, Any]], total_formatted: str
) -> str:
    """Tạo nội dung HTML email (bảng sản phẩm, địa chỉ, tổng tiền)."""
    rows = []
    for it in items:
        name = it.get("product_name") or f"Sản phẩm #{it.get('product_id')}"
        qty = it.get("quantity", 0)
        price = it.get("price", 0)
        line = int(price) * int(qty)
        line_s = f"{line:,}".replace(",", ".")
        price_s = f"{int(price):,}".replace(",", ".")
        rows.append(
            f"<tr><td>{name}</td><td style='text-align:center'>{qty}</td>"
            f"<td style='text-align:right'>{price_s} ₫</td>"
            f"<td style='text-align:right'><strong>{line_s} ₫</strong></td></tr>"
        )

    full_address_parts = [
        order.get("detail_address") or "",
        order.get("ward") or "",
        order.get("district") or "",
        order.get("province") or "",
    ]
    full_address = ", ".join(p for p in full_address_parts if p)

    order_code_html = html.escape(str(order.get("order_code") or ""))

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="font-family: Georgia, 'Times New Roman', serif; color: #2a2520; background: #fdf8ed; padding: 16px;">
  <div style="max-width: 560px; margin: 0 auto; background: #fff; border: 1px solid #e8d4a8; border-radius: 12px; padding: 24px;">
    <p style="font-size: 18px; margin-top: 0; margin-bottom: 12px;"><strong>Mã đơn hàng:</strong> {order_code_html or "—"}</p>
    <h1 style="color: #5c4710; font-size: 22px; margin-top: 0;">Đơn hàng — Yến Sào Nha Trang</h1>
    <p><strong>Khách hàng:</strong> {order.get("full_name", "")}</p>
    <p><strong>Số điện thoại:</strong> {order.get("phone", "")}</p>
    <p><strong>Email:</strong> {order.get("email") or "—"}</p>
    <p><strong>Địa chỉ giao hàng:</strong><br>{full_address or "—"}</p>
    <p><strong>Thời gian đặt (giờ VN):</strong> {_format_dt(order.get("created_at", ""))}</p>
    <h2 style="color: #8b2635; font-size: 18px;">Chi tiết sản phẩm</h2>
    <table style="width:100%; border-collapse: collapse; font-size: 14px;">
      <thead>
        <tr style="background: #f5e6c8;">
          <th style="padding:8px; text-align:left; border:1px solid #e8d4a8;">Tên</th>
          <th style="padding:8px; border:1px solid #e8d4a8;">SL</th>
          <th style="padding:8px; border:1px solid #e8d4a8;">Đơn giá</th>
          <th style="padding:8px; border:1px solid #e8d4a8;">Thành tiền</th>
        </tr>
      </thead>
      <tbody>{"".join(rows)}</tbody>
    </table>
    <p style="font-size: 18px; margin-top: 16px;"><strong>Tổng cộng: {total_formatted}</strong></p>
    <p style="color: #5c5650; font-size: 13px;">Trân trọng,<br>Yến Sào Nha Trang</p>
  </div>
</body></html>"""


def send_order_email(
    mail,
    order: Dict[str, Any],
    items: List[Dict[str, Any]],
    admin_email: Optional[str],
    customer_email: Optional[str],
    subject_admin: str = "Đơn hàng mới - Yến Sào Nha Trang",
    subject_customer: str = "Xác nhận đơn hàng - Yến Sào Nha Trang",
) -> None:
    """
    Gửi email cho admin (bắt buộc nếu cấu hình admin_email) và khách (nếu có email).
    mail: instance Flask-Mail đã gắn app.
    """
    total = int(order.get("total_price") or 0)
    total_formatted = f"{total:,}".replace(",", ".") + " ₫"
    html_body = build_order_html(order, items, total_formatted)
    plain_lines = [
        f"Mã đơn hàng: {order.get('order_code') or '—'}",
        f"Khách: {order.get('full_name')}",
        f"SĐT: {order.get('phone')}",
        f"Email: {order.get('email')}",
        f"Tổng: {total_formatted}",
        f"Thời gian đặt (VN): {_format_dt(order.get('created_at', '') or '')}",
    ]
    body_plain = "\n".join(plain_lines)

    try:
        if admin_email:
            msg_admin = Message(
                subject=subject_admin,
                recipients=[admin_email],
                body=body_plain,
                html=html_body,
            )
            mail.send(msg_admin)
    except Exception as e:
        print("[Email] Gửi cho admin thất bại:", e)
        traceback.print_exc()

    if customer_email and customer_email.strip():
        try:
            msg_cust = Message(
                subject=subject_customer,
                recipients=[customer_email.strip()],
                body=body_plain,
                html=html_body,
            )
            mail.send(msg_cust)
        except Exception as e:
            print("[Email] Gửi xác nhận khách thất bại:", e)
            traceback.print_exc()


def send_contact_email(
    mail,
    name: str,
    email: str,
    phone: str,
    message: str,
    admin_email: Optional[str],
) -> bool:
    """
    Gửi email liên hệ từ form /contact tới ADMIN_EMAIL (HTML + plain text).
    Escape HTML để tránh XSS trong nội dung người dùng.
    Trả về True nếu gửi thành công; False nếu thiếu cấu hình hoặc lỗi SMTP (đã in console).
    """
    if not admin_email:
        print("[Contact email] ADMIN_EMAIL chưa cấu hình — không gửi được.")
        return False

    safe = {
        "name": html.escape(name or ""),
        "email": html.escape(email or ""),
        "phone": html.escape(phone or ""),
        "message": html.escape(message or "").replace("\n", "<br>"),
    }
    html_body = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="font-family: Georgia, 'Times New Roman', serif; color: #2a2520; background: #fdf8ed; padding: 16px;">
  <div style="max-width: 560px; margin: 0 auto; background: #fff; border: 1px solid #e8d4a8; border-radius: 12px; padding: 24px;">
    <h1 style="color: #5c4710; font-size: 20px; margin-top: 0;">Liên hệ mới — Yến Sào Nha Trang</h1>
    <table style="width:100%; border-collapse: collapse; font-size: 14px;">
      <tr><td style="padding:8px; border:1px solid #e8d4a8; background:#f5e6c8; width:32%;"><strong>Họ tên</strong></td>
          <td style="padding:8px; border:1px solid #e8d4a8;">{safe["name"]}</td></tr>
      <tr><td style="padding:8px; border:1px solid #e8d4a8; background:#f5e6c8;"><strong>Email</strong></td>
          <td style="padding:8px; border:1px solid #e8d4a8;">{safe["email"]}</td></tr>
      <tr><td style="padding:8px; border:1px solid #e8d4a8; background:#f5e6c8;"><strong>Số điện thoại</strong></td>
          <td style="padding:8px; border:1px solid #e8d4a8;">{safe["phone"] or "—"}</td></tr>
      <tr><td style="padding:8px; border:1px solid #e8d4a8; background:#f5e6c8; vertical-align:top;"><strong>Nội dung</strong></td>
          <td style="padding:8px; border:1px solid #e8d4a8;">{safe["message"]}</td></tr>
    </table>
    <p style="color: #5c5650; font-size: 12px; margin-top: 16px;"><strong>Thời gian gửi (giờ VN):</strong> {html.escape(format_now_vn())}</p>
    <p style="color: #5c5650; font-size: 12px;">Gửi từ form liên hệ website.</p>
  </div>
</body></html>"""

    plain = (
        f"Họ tên: {name}\n"
        f"Email: {email}\n"
        f"SĐT: {phone or '—'}\n"
        f"Nội dung:\n{message}\n"
        f"Thời gian gửi (VN): {format_now_vn()}"
    )

    try:
        msg = Message(
            subject="Liên hệ mới từ website Yến Sào",
            recipients=[admin_email],
            body=plain,
            html=html_body,
            reply_to=email.strip() if email and "@" in email else None,
        )
        mail.send(msg)
        return True
    except Exception as e:
        print("[Contact email] Gửi thất bại:", e)
        traceback.print_exc()
        return False
