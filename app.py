# -*- coding: utf-8 -*-
"""
Ứng dụng Flask: Yến Sào Nha Trang — sản phẩm, tài khoản, giỏ hàng, thanh toán, email.
Chạy: python app.py  (cấu hình SMTP trong file .env)
"""
from __future__ import annotations

import logging
import os
import re
import threading
import traceback
import uuid
from functools import wraps
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_mail import Mail
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from email_service import send_contact_email, send_order_email
from models import db
from time_utils import format_utc_iso_to_vn

# Nạp biến môi trường từ .env (không commit mật khẩu thật)
load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get(
    "SECRET_KEY", "yen-sao-nha-trang-dev-key-doi-khi-production"
)

# --- Flask-Mail (Gmail SMTP — mật khẩu lấy từ biến môi trường) ---
app.config["MAIL_SERVER"] = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
app.config["MAIL_PORT"] = int(os.environ.get("MAIL_PORT", "587"))
app.config["MAIL_USE_TLS"] = os.environ.get("MAIL_USE_TLS", "true").lower() in (
    "1",
    "true",
    "yes",
)
app.config["MAIL_USERNAME"] = os.environ.get("MAIL_USERNAME", "")
app.config["MAIL_PASSWORD"] = os.environ.get("MAIL_PASSWORD", "")
app.config["MAIL_DEFAULT_SENDER"] = os.environ.get("MAIL_DEFAULT_SENDER", "")

mail = Mail(app)

# Email admin nhận thông báo đơn mới
ADMIN_NOTIFY_EMAIL = os.environ.get("ADMIN_EMAIL", "").strip()

# Tài khoản admin duy nhất (so khớp session["username"], không phân role phức tạp)
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin").strip().lower()

# Session key cho giỏ khách (dict: product_id str -> số lượng)
GUEST_CART_KEY = "guest_cart"

# Ảnh upload sản phẩm (admin)
ALLOWED_IMAGE_EXT = frozenset({"png", "jpg", "jpeg", "gif", "webp"})


def save_uploaded_product_image(file_storage):
    """
    Lưu file upload vào static/images/, trả về tên file mới hoặc None.
    """
    if not file_storage or not file_storage.filename:
        return None
    raw = secure_filename(file_storage.filename)
    if not raw or "." not in raw:
        return None
    ext = raw.rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_IMAGE_EXT:
        return None
    fname = f"{uuid.uuid4().hex[:16]}.{ext}"
    dest_dir = os.path.join(app.root_path, "static", "images")
    os.makedirs(dest_dir, exist_ok=True)
    file_storage.save(os.path.join(dest_dir, fname))
    return fname


# -----------------------------------------------------------------------------
# Helpers giỏ hàng (guest = session)
# -----------------------------------------------------------------------------


def _guest_cart_get() -> Dict[str, int]:
    raw = session.get(GUEST_CART_KEY) or {}
    out: Dict[str, int] = {}
    for k, v in raw.items():
        try:
            out[str(k)] = int(v)
        except (TypeError, ValueError):
            continue
    return out


def _guest_cart_set(cart: Dict[str, int]) -> None:
    session[GUEST_CART_KEY] = cart
    session.modified = True


def guest_cart_add(product_id: int, quantity: int = 1) -> None:
    if quantity < 1:
        return
    cart = _guest_cart_get()
    key = str(product_id)
    cart[key] = cart.get(key, 0) + quantity
    _guest_cart_set(cart)


def guest_cart_remove(product_id: int) -> None:
    cart = _guest_cart_get()
    cart.pop(str(product_id), None)
    _guest_cart_set(cart)


def guest_cart_clear() -> None:
    session.pop(GUEST_CART_KEY, None)
    session.modified = True


def guest_cart_lines() -> List[Dict[str, Any]]:
    """Build danh sách dòng giỏ khách (cùng cấu trúc với cart_get_lines_for_user)."""
    lines: List[Dict[str, Any]] = []
    for pid_str, qty in _guest_cart_get().items():
        try:
            pid = int(pid_str)
            q = int(qty)
        except (ValueError, TypeError):
            continue
        if q <= 0:
            continue
        p = db.get_product_by_id(pid)
        if not p:
            continue
        lines.append(
            {
                "product_id": pid,
                "quantity": q,
                "product": p,
                "line_total": int(p["price"]) * q,
            }
        )
    return lines


def get_cart_lines() -> List[Dict[str, Any]]:
    """Giỏ hiện tại: DB nếu đã đăng nhập, không thì session."""
    uid = session.get("user_id")
    if uid:
        return db.cart_get_lines_for_user(int(uid))
    return guest_cart_lines()


def cart_total_quantity() -> int:
    uid = session.get("user_id")
    if uid:
        return db.cart_total_quantity_user(int(uid))
    return sum(_guest_cart_get().values())


# -----------------------------------------------------------------------------
# Decorator & context
# -----------------------------------------------------------------------------


def login_required(view_func):
    """Bảo vệ route cần đăng nhập (ví dụ trang admin)."""

    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            flash("Vui lòng đăng nhập để tiếp tục.", "error")
            # Chỉ truyền path (tránh open redirect)
            return redirect(url_for("login", next=request.path))
        return view_func(*args, **kwargs)

    return wrapped


def is_admin_user() -> bool:
    """True nếu user đăng nhập là admin (username trùng ADMIN_USERNAME)."""
    if not session.get("user_id"):
        return False
    return session.get("username", "").strip().lower() == ADMIN_USERNAME


def admin_required(view_func):
    """Chỉ đăng nhập + đúng tài khoản admin; không phải admin → flash + về trang chủ."""

    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            flash("Vui lòng đăng nhập để tiếp tục.", "error")
            return redirect(url_for("login", next=request.path))
        if not is_admin_user():
            flash("Bạn không có quyền truy cập", "error")
            return redirect(url_for("home"))
        return view_func(*args, **kwargs)

    return wrapped


@app.context_processor
def inject_globals():
    """Navbar: giỏ hàng, user, cờ admin (menu quản trị)."""
    uid = session.get("user_id")
    user = None
    if uid:
        user = db.get_user_by_id(int(uid))
    return dict(
        cart_count=cart_total_quantity(),
        current_user=user,
        is_admin=is_admin_user(),
    )


@app.template_filter("vnd")
def format_vnd(value):
    """Định dạng số tiền kiểu Việt Nam."""
    if value is None:
        return "0 ₫"
    try:
        n = int(value)
    except (TypeError, ValueError):
        return str(value)
    s = f"{n:,}".replace(",", ".")
    return f"{s} ₫"


@app.template_filter("datetime_vn")
def datetime_vn_filter(value):
    """Chuỗi ISO UTC từ DB → hiển thị giờ Việt Nam (UTC+7)."""
    return format_utc_iso_to_vn(value)


# -----------------------------------------------------------------------------
# Trang tĩnh & sản phẩm
# -----------------------------------------------------------------------------


@app.route("/")
def home():
    featured_products = db.get_all_products()[:4]
    return render_template("home.html", featured_products=featured_products)


@app.route("/products")
def products():
    q = request.args.get("q", "").strip()
    if q:
        items = db.search_products(q)
    else:
        items = db.get_all_products()
    return render_template("products.html", products=items, query=q)


@app.route("/product/<int:product_id>")
def product_detail(product_id):
    product = db.get_product_by_id(product_id)
    if not product:
        flash("Không tìm thấy sản phẩm.", "error")
        return redirect(url_for("products"))
    return render_template("product_detail.html", product=product)


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/contact", methods=["GET", "POST"])
def contact():
    """
    GET: hiển thị thông tin liên hệ + form.
    POST: validate name, email, message — gửi email tới ADMIN_EMAIL (Flask-Mail).
    """
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email_addr = request.form.get("email", "").strip()
        phone = request.form.get("phone", "").strip()
        message = request.form.get("message", "").strip()

        errors: List[str] = []
        if not name:
            errors.append("Vui lòng nhập họ tên.")
        if not email_addr or "@" not in email_addr:
            errors.append("Vui lòng nhập email hợp lệ.")
        if not message:
            errors.append("Vui lòng nhập nội dung tin nhắn.")

        if errors:
            for msg in errors:
                flash(msg, "error")
            return render_template("contact.html", form=request.form)

        # Gửi email tới admin; lỗi SMTP không làm crash — xử lý trong send_contact_email
        ok = send_contact_email(
            mail,
            name,
            email_addr,
            phone,
            message,
            os.getenv("ADMIN_EMAIL"),
        )
        if ok:
            flash("Gửi liên hệ thành công!", "success")
        else:
            flash(
                "Không thể gửi email lúc này (kiểm tra cấu hình SMTP hoặc thử lại sau). "
                "Bạn vẫn có thể gọi hotline để được hỗ trợ.",
                "error",
            )
        return redirect(url_for("contact"))

    return render_template("contact.html", form=None)


@app.route("/search")
def search():
    q = request.args.get("q", "")
    return redirect(url_for("products", q=q))


# -----------------------------------------------------------------------------
# Tài khoản: đăng ký / đăng nhập / đăng xuất
# -----------------------------------------------------------------------------


def _validate_register(username: str, password: str, full_name: str) -> List[str]:
    err: List[str] = []
    if not full_name or len(full_name) < 2:
        err.append("Họ tên phải có ít nhất 2 ký tự.")
    if not username or len(username) < 3:
        err.append("Tên đăng nhập tối thiểu 3 ký tự.")
    elif not re.match(r"^[a-zA-Z0-9_]+$", username):
        err.append("Tên đăng nhập chỉ gồm chữ, số và gạch dưới.")
    if not password or len(password) < 6:
        err.append("Mật khẩu tối thiểu 6 ký tự.")
    return err


@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("user_id"):
        return redirect(url_for("home"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        full_name = request.form.get("full_name", "").strip()
        phone = request.form.get("phone", "").strip()
        address = request.form.get("address", "").strip()

        errors = _validate_register(username, password, full_name)
        # Chặn đăng ký trùng tài khoản admin (username độc quyền)
        if username.strip().lower() == ADMIN_USERNAME:
            errors.append("Không được đăng ký tên đăng nhập này.")
        if db.get_user_by_username(username):
            errors.append("Tên đăng nhập đã được sử dụng.")

        if errors:
            for e in errors:
                flash(e, "error")
            return render_template(
                "register.html",
                form=request.form,
            )

        pwd_hash = generate_password_hash(password)
        db.create_user(username, pwd_hash, full_name, phone, address)
        flash("Đăng ký thành công. Vui lòng đăng nhập.", "success")
        return redirect(url_for("login"))

    return render_template("register.html", form=None)


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("home"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        nxt = request.form.get("next") or request.args.get("next") or ""

        user = db.get_user_by_username(username)
        if not user or not check_password_hash(user["password"], password):
            flash("Sai tên đăng nhập hoặc mật khẩu.", "error")
            return render_template("login.html", next_url=nxt)

        session["user_id"] = user["id"]
        session["username"] = user["username"]

        # Gộp giỏ khách vào DB (nếu có)
        gc = _guest_cart_get()
        if gc:
            db.merge_session_cart_into_db(int(user["id"]), gc)
            guest_cart_clear()

        flash("Đăng nhập thành công.", "success")
        # Chỉ chấp nhận redirect nội bộ (bắt đầu bằng /, không //)
        if nxt and nxt.startswith("/") and not nxt.startswith("//"):
            return redirect(nxt)
        return redirect(url_for("home"))

    nxt = request.args.get("next") or ""
    return render_template("login.html", next_url=nxt)


@app.route("/logout")
def logout():
    session.pop("user_id", None)
    session.pop("username", None)
    flash("Bạn đã đăng xuất.", "info")
    return redirect(url_for("home"))


# -----------------------------------------------------------------------------
# Giỏ hàng
# -----------------------------------------------------------------------------


@app.route("/add_to_cart/<int:product_id>", methods=["GET", "POST"])
def add_to_cart(product_id):
    product = db.get_product_by_id(product_id)
    if not product:
        flash("Sản phẩm không tồn tại.", "error")
        return redirect(url_for("products"))

    qty_raw = request.args.get("qty") if request.method == "GET" else request.form.get("qty")
    try:
        qty = int(qty_raw) if qty_raw is not None else 1
    except (ValueError, TypeError):
        qty = 1
    qty = max(1, min(qty, 99))

    uid = session.get("user_id")
    if uid:
        db.cart_add_item(int(uid), product_id, qty)
    else:
        guest_cart_add(product_id, qty)

    flash("Đã thêm vào giỏ hàng.", "success")
    ref = request.referrer
    if ref and request.host and request.host in ref:
        return redirect(ref)
    return redirect(url_for("cart"))


@app.route("/remove_from_cart/<int:product_id>")
def remove_from_cart(product_id):
    uid = session.get("user_id")
    if uid:
        db.cart_remove_item(int(uid), product_id)
    else:
        guest_cart_remove(product_id)
    flash("Đã xóa sản phẩm khỏi giỏ.", "info")
    return redirect(url_for("cart"))


@app.route("/update_cart", methods=["POST"])
def update_cart():
    """Cập nhật số lượng theo field qty_<product_id> (0 = xóa dòng)."""
    uid = session.get("user_id")
    for key, val in request.form.items():
        if not key.startswith("qty_"):
            continue
        try:
            pid = int(key.replace("qty_", "", 1))
            q = int(val)
        except (ValueError, TypeError):
            continue
        if uid:
            db.cart_set_quantity(int(uid), pid, q)
        else:
            cart = _guest_cart_get()
            sk = str(pid)
            if q <= 0:
                cart.pop(sk, None)
            else:
                cart[sk] = min(q, 999)
            _guest_cart_set(cart)
    flash("Đã cập nhật giỏ hàng.", "success")
    return redirect(url_for("cart"))


@app.route("/cart")
def cart():
    lines = get_cart_lines()
    total = db.lines_total(lines)
    return render_template("cart.html", cart_lines=lines, total=total)


# -----------------------------------------------------------------------------
# Thanh toán & đặt hàng
# -----------------------------------------------------------------------------


def _validate_place_order(
    is_guest: bool,
    full_name: str,
    phone: str,
    email: str,
    province: str,
    district: str,
    ward: str,
    detail: str,
) -> List[str]:
    """Khách (guest): bắt buộc email + đủ cấp địa chỉ. User đăng nhập: chỉ cần họ tên, SĐT, địa chỉ chi tiết."""
    errors: List[str] = []
    if not full_name or len(full_name.strip()) < 2:
        errors.append("Vui lòng nhập họ tên hợp lệ.")
    if not phone or len(re.sub(r"\D", "", phone)) < 9:
        errors.append("Số điện thoại không hợp lệ.")
    if not detail or len(detail.strip()) < 3:
        errors.append("Địa chỉ giao hàng (chi tiết) là bắt buộc.")
    if is_guest:
        if not email.strip() or "@" not in email:
            errors.append("Email là bắt buộc với khách chưa đăng nhập.")
        if not province.strip():
            errors.append("Vui lòng nhập Tỉnh/Thành phố.")
        if not district.strip():
            errors.append("Vui lòng nhập Quận/Huyện.")
        if not ward.strip():
            errors.append("Vui lòng nhập Phường/Xã.")
    return errors


def _send_order_emails_thread(app_obj: Flask, order_id: int) -> None:
    """Bonus: gửi email trong thread — không chặn response HTTP."""

    def _run():
        with app_obj.app_context():
            try:
                order = db.get_order_by_id(order_id)
                if not order:
                    return
                items = db.get_order_items_for_email(order_id)
                # Bổ sung key cho template HTML
                send_order_email(
                    mail,
                    order,
                    items,
                    ADMIN_NOTIFY_EMAIL or None,
                    order.get("email") or None,
                )
            except Exception as e:
                print("[Email] Lỗi gửi đơn hàng #%s:" % order_id, e)
                traceback.print_exc()

    t = threading.Thread(target=_run, daemon=True)
    t.start()


@app.route("/checkout", methods=["GET"])
def checkout():
    lines = get_cart_lines()
    if not lines:
        flash("Giỏ hàng trống.", "error")
        return redirect(url_for("cart"))

    total = db.lines_total(lines)
    uid = session.get("user_id")
    user = db.get_user_by_id(int(uid)) if uid else None
    # User đã đăng nhập: điền sẵn từ profile
    prefilled = None
    if user:
        prefilled = {
            "full_name": user.get("full_name") or "",
            "phone": user.get("phone") or "",
            "detail_address": user.get("address") or "",
            "email": "",
            "province": "",
            "district": "",
            "ward": "",
        }
    return render_template(
        "checkout.html",
        cart_lines=lines,
        total=total,
        prefilled=prefilled,
        is_guest=not bool(uid),
    )


@app.route("/place_order", methods=["POST"])
def place_order():
    lines = get_cart_lines()
    if not lines:
        flash("Giỏ hàng trống.", "error")
        return redirect(url_for("cart"))

    uid = session.get("user_id")
    is_guest = not bool(uid)

    full_name = request.form.get("full_name", "").strip()
    phone = request.form.get("phone", "").strip()
    email = request.form.get("email", "").strip()
    province = request.form.get("province", "").strip()
    district = request.form.get("district", "").strip()
    ward = request.form.get("ward", "").strip()
    detail_address = request.form.get("detail_address", "").strip()

    # Tính lại tổng tiền từ DB (không tin tưởng client)
    recalc_lines: List[Dict[str, Any]] = []
    total_price = 0
    for line in lines:
        p = db.get_product_by_id(int(line["product_id"]))
        if not p:
            continue
        q = int(line["quantity"])
        price = int(p["price"])
        total_price += price * q
        recalc_lines.append(
            {"product_id": int(line["product_id"]), "quantity": q, "price": price}
        )

    if not recalc_lines:
        flash("Không có sản phẩm hợp lệ trong giỏ.", "error")
        return redirect(url_for("cart"))

    errors = _validate_place_order(
        is_guest, full_name, phone, email, province, district, ward, detail_address
    )
    if errors:
        for e in errors:
            flash(e, "error")
        total = total_price
        prefilled = {
            "full_name": full_name,
            "phone": phone,
            "email": email,
            "province": province,
            "district": district,
            "ward": ward,
            "detail_address": detail_address,
        }
        return render_template(
            "checkout.html",
            cart_lines=lines,
            total=total,
            prefilled=prefilled,
            is_guest=is_guest,
        )

    user_id_opt = int(uid) if uid else None

    try:
        order_id = db.create_order(
            user_id_opt,
            full_name,
            phone,
            email if email else None,
            province,
            district,
            ward,
            detail_address,
            total_price,
            recalc_lines,
        )
    except Exception as e:
        print("[Order] Lỗi lưu đơn:", e)
        traceback.print_exc()
        flash("Không thể tạo đơn hàng. Vui lòng thử lại.", "error")
        return redirect(url_for("checkout"))

    # Xóa giỏ
    if uid:
        db.cart_clear(int(uid))
    else:
        guest_cart_clear()

    row = db.get_order_by_id(order_id)
    code = (row.get("order_code") if row else None) or str(order_id)
    flash(
        "Đặt hàng thành công! Mã đơn: %s. Chúng tôi sẽ liên hệ xác nhận." % code,
        "success",
    )

    _send_order_emails_thread(app, order_id)

    return redirect(url_for("home"))


# -----------------------------------------------------------------------------
# Khu vực quản trị — tất cả @admin_required (username == ADMIN_USERNAME)
# -----------------------------------------------------------------------------


@app.route("/admin")
@admin_required
def admin_dashboard():
    """Tổng quan: số đơn, đơn chờ xử lý, số sản phẩm."""
    return render_template(
        "admin/dashboard.html",
        total_orders=db.count_orders_total(),
        pending_orders=db.count_orders_by_status(db.ORDER_STATUS_PENDING),
        total_products=db.count_products_total(),
    )


@app.route("/admin/orders")
@admin_required
def admin_orders():
    q = request.args.get("q", "").strip()
    orders = db.list_all_orders(q if q else None)
    return render_template("admin/orders.html", orders=orders, search_q=q)


@app.route("/admin/order/<int:order_id>", methods=["GET", "POST"])
@admin_required
def admin_order_detail(order_id):
    order = db.get_order_by_id(order_id)
    if not order:
        flash("Không tìm thấy đơn hàng.", "error")
        return redirect(url_for("admin_orders"))

    if request.method == "POST":
        new_status = request.form.get("status", "").strip()
        if new_status in db.ORDER_STATUSES:
            db.update_order_status(order_id, new_status)
            flash("Đã cập nhật trạng thái đơn hàng.", "success")
        else:
            flash("Trạng thái không hợp lệ.", "error")
        return redirect(url_for("admin_order_detail", order_id=order_id))

    items = db.get_order_items_admin(order_id)
    order_dict = dict(order)
    if "status" not in order_dict or order_dict.get("status") is None:
        order_dict["status"] = db.ORDER_STATUS_PENDING

    parts = [
        order_dict.get("detail_address") or "",
        order_dict.get("ward") or "",
        order_dict.get("district") or "",
        order_dict.get("province") or "",
    ]
    full_address = ", ".join(p for p in parts if p)

    return render_template(
        "admin/order_detail.html",
        order=order_dict,
        items=items,
        full_address=full_address,
        order_statuses=db.ORDER_STATUSES,
    )


@app.route("/admin/products")
@admin_required
def admin_products():
    products = db.get_all_products()
    return render_template("admin/products.html", products=products)


@app.route("/admin/add-product", methods=["GET", "POST"])
@admin_required
def admin_add_product():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        price_raw = request.form.get("price", "0").strip()
        description = request.form.get("description", "").strip()
        uploaded = save_uploaded_product_image(request.files.get("image_file"))
        if uploaded:
            image = uploaded
        else:
            image = request.form.get("image", "intro.jpg").strip() or "intro.jpg"
        try:
            price = int(price_raw.replace(".", "").replace(",", ""))
        except ValueError:
            flash("Giá không hợp lệ.", "error")
            return redirect(url_for("admin_add_product"))
        if not name:
            flash("Tên sản phẩm không được để trống.", "error")
            return redirect(url_for("admin_add_product"))
        new_id = db.add_product(name, price, description, image)
        flash(f"Đã thêm sản phẩm mã #{new_id}.", "success")
        return redirect(url_for("admin_products"))
    return render_template("admin/add_product.html")


@app.route("/admin/edit-product/<int:product_id>", methods=["GET", "POST"])
@admin_required
def admin_edit_product(product_id):
    product = db.get_product_by_id(product_id)
    if not product:
        flash("Không tìm thấy sản phẩm.", "error")
        return redirect(url_for("admin_products"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        price_raw = request.form.get("price", "0").strip()
        description = request.form.get("description", "").strip()
        image = (request.form.get("image") or product["image"] or "intro.jpg").strip()
        uploaded = save_uploaded_product_image(request.files.get("image_file"))
        if uploaded:
            image = uploaded
        try:
            price = int(price_raw.replace(".", "").replace(",", ""))
        except ValueError:
            flash("Giá không hợp lệ.", "error")
            return redirect(url_for("admin_edit_product", product_id=product_id))
        if not name:
            flash("Tên sản phẩm không được để trống.", "error")
            return redirect(url_for("admin_edit_product", product_id=product_id))
        db.update_product(product_id, name, price, description, image)
        flash("Đã cập nhật sản phẩm.", "success")
        return redirect(url_for("admin_products"))

    return render_template("admin/edit_product.html", product=product)


@app.route("/admin/delete-product/<int:product_id>", methods=["POST"])
@admin_required
def admin_delete_product(product_id):
    ok, msg = db.delete_product(product_id)
    if ok:
        flash("Đã xóa sản phẩm.", "success")
    else:
        flash(msg, "error")
    return redirect(url_for("admin_products"))
# -----------------------------------------------------------------------------


try:
    db.init_db()
except Exception:
    logging.exception(
        "db.init_db() thất bại — kiểm tra DATABASE_URL và PostgreSQL (sslmode=require)."
    )

if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)
