# Yến Sào Nha Trang

Website giới thiệu và bán yến sào cao cấp — **Flask**, **Jinja2**, **SQLite**, HTML/CSS thuần.

## Yêu cầu

- Python 3.9+ (khuyến nghị 3.10+)

## Cài đặt và chạy

1. Sao chép `.env.example` thành `.env` và điền `SECRET_KEY`, thông tin SMTP Gmail (mật khẩu ứng dụng), `ADMIN_EMAIL`.

Trong thư mục dự án:

```bash
cd Web-Yen
python -m venv venv
```

**Windows (PowerShell):**

```powershell
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

**Windows (cmd):**

```cmd
venv\Scripts\activate.bat
pip install -r requirements.txt
python app.py
```

Mở trình duyệt: [http://127.0.0.1:5000](http://127.0.0.1:5000)

- Lần chạy đầu tiên, file `database.db` được tạo tự động kèm **8 sản phẩm mẫu** và các bảng `users`, `cart`, `orders`, `order_items`.
- **Tài khoản**: `/register`, `/login`, `/logout` — mật khẩu hash bằng Werkzeug.
- **Giỏ hàng**: đã đăng nhập lưu DB; khách lưu session. Sau đăng nhập, giỏ khách được gộp vào tài khoản.
- **Thanh toán**: `/checkout`, đặt hàng `POST /place_order` — email xác nhận gửi qua Flask-Mail (thread; lỗi SMTP chỉ in console).
- Tìm kiếm: trang **Sản phẩm** — ô tìm kiếm, hoặc `/search?q=...`.
- **Quản trị**: đăng nhập bằng tài khoản trùng `ADMIN_USERNAME` trong `.env` (mặc định `admin`) — [Dashboard](http://127.0.0.1:5000/admin), đơn hàng, sản phẩm. Không đăng ký trùng username admin.

## Cấu trúc chính

- `app.py` — route Flask
- `models/db.py` — kết nối SQLite, khởi tạo DB, truy vấn
- `templates/` — Jinja2, kế thừa `base.html`
- `static/css/style.css`, `static/js/main.js`, `static/images/`
