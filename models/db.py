# -*- coding: utf-8 -*-
"""
Kết nối và thao tác PostgreSQL cho ứng dụng Yến Sào Nha Trang:
products, users, cart, orders, order_items.
"""
import logging
import os
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import psycopg2
from psycopg2.extras import RealDictCursor

from time_utils import now_utc_iso_z

logger = logging.getLogger(__name__)

# Trạng thái đơn hàng (admin cập nhật)
ORDER_STATUS_PENDING = "pending"
ORDER_STATUS_CONFIRMED = "confirmed"
ORDER_STATUS_SHIPPED = "shipped"
ORDER_STATUSES = (ORDER_STATUS_PENDING, ORDER_STATUS_CONFIRMED, ORDER_STATUS_SHIPPED)


def get_connection():
    """
    Tạo kết nối PostgreSQL (cursor mặc định trả về dict-like rows).
    """
    url = os.getenv("DATABASE_URL")
    if not url or not str(url).strip():
        err = RuntimeError("DATABASE_URL is not set")
        logger.error("%s", err)
        raise err
    try:
        conn = psycopg2.connect(url.strip(), sslmode="require", cursor_factory=RealDictCursor)
        return conn
    except Exception:
        logger.exception("PostgreSQL connection failed")
        raise


def get_db():
    """Alias theo convention Flask — cùng hành vi với get_connection()."""
    return get_connection()


def _column_exists(conn, table: str, column: str) -> bool:
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s AND column_name = %s
            """,
            (table, column),
        )
        return cur.fetchone() is not None
    finally:
        cur.close()


def _migrate_orders_status(conn) -> None:
    if not _column_exists(conn, "orders", "status"):
        cur = conn.cursor()
        try:
            cur.execute(
                "ALTER TABLE orders ADD COLUMN status TEXT NOT NULL DEFAULT 'pending'"
            )
        finally:
            cur.close()


def generate_order_code() -> str:
    """
    Mã đơn: YS + timestamp UTC (YYYYMMDDHHmmss) + 2 ký tự ngẫu nhiên.
    Ví dụ: YS20260402123045AB
    """
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    suf = "".join(
        secrets.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789") for _ in range(2)
    )
    return f"YS{ts}{suf}"


def _pick_unique_order_code(conn) -> str:
    """Sinh mã không trùng trong bảng orders (thử lại nhiều lần)."""
    cur = conn.cursor()
    try:
        for _ in range(40):
            code = generate_order_code()
            cur.execute("SELECT 1 FROM orders WHERE order_code = %s", (code,))
            if not cur.fetchone():
                return code
        return generate_order_code() + secrets.token_hex(3).upper()
    finally:
        cur.close()


def _migrate_product_images(conn) -> None:
    """
    Chuyển tên file ảnh mẫu từ .svg sang ảnh thật trong static/images.
    Chỉ cập nhật đúng giá trị cũ để không ghi đè ảnh admin đã đổi tay.
    """
    mapping = {
        "yen-1.svg": "intro.jpg",
        "yen-2.svg": "yen-che-bien.jpg",
        "yen-3.svg": "yen-3.webp",
        "yen-4.svg": "yen-1.jpg",
        "yen-5.svg": "landing.png",
        "yen-6.svg": "yen-5.webp",
        "yen-7.svg": "yen-2.jpg",
        "yen-8.svg": "bg.jpg",
    }
    cur = conn.cursor()
    try:
        for old_name, new_name in mapping.items():
            cur.execute(
                "UPDATE products SET image = %s WHERE image = %s",
                (new_name, old_name),
            )
    finally:
        cur.close()


def _migrate_order_code(conn) -> None:
    """Đảm bảo cột order_code, gán mã cho đơn thiếu, UNIQUE index."""
    if not _column_exists(conn, "orders", "order_code"):
        cur = conn.cursor()
        try:
            cur.execute("ALTER TABLE orders ADD COLUMN order_code TEXT")
        finally:
            cur.close()

    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT id FROM orders WHERE order_code IS NULL OR TRIM(order_code) = ''"
        )
        for row in cur.fetchall():
            oid = int(row["id"])
            code = _pick_unique_order_code(conn)
            cur.execute(
                "UPDATE orders SET order_code = %s WHERE id = %s",
                (code, oid),
            )
    finally:
        cur.close()

    cur = conn.cursor()
    try:
        cur.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_orders_order_code ON orders(order_code)"
        )
    finally:
        cur.close()


def init_db() -> None:
    """
    Tạo bảng và dữ liệu mẫu (products) nếu chưa có.
    An toàn gọi nhiều lần khi khởi động app.
    """
    try:
        conn = get_connection()
    except Exception:
        logger.exception("init_db: cannot connect to database")
        raise
    try:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS products (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    price INTEGER NOT NULL,
                    description TEXT,
                    image TEXT NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    password TEXT NOT NULL,
                    full_name TEXT NOT NULL,
                    phone TEXT,
                    address TEXT
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS cart (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
                    quantity INTEGER NOT NULL DEFAULT 1 CHECK (quantity > 0),
                    UNIQUE(user_id, product_id)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS orders (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                    full_name TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    email TEXT,
                    province TEXT,
                    district TEXT,
                    ward TEXT,
                    detail_address TEXT NOT NULL,
                    total_price INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    order_code TEXT
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS order_items (
                    id SERIAL PRIMARY KEY,
                    order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
                    product_id INTEGER NOT NULL REFERENCES products(id),
                    quantity INTEGER NOT NULL,
                    price INTEGER NOT NULL
                )
                """
            )
        finally:
            cur.close()
        conn.commit()

        _migrate_orders_status(conn)
        _migrate_order_code(conn)
        _migrate_product_images(conn)
        conn.commit()

        cur = conn.cursor()
        try:
            cur.execute("SELECT COUNT(*) AS c FROM products")
            count_row = cur.fetchone()
            c = int(count_row["c"]) if count_row else 0
        finally:
            cur.close()

        if c == 0:
            samples = [
                (
                    "Yến tinh chế hộp quà tặng 50g",
                    2850000,
                    "Yến sào tinh chế nguyên chất từ tổ yến thô, sơ chế kỹ, phù hợp biếu tặng cao cấp.",
                    "intro.jpg",
                ),
                (
                    "Yến chưng sẵn hương nhài 6 lọ",
                    420000,
                    "Set 6 lọ yến chưng sẵn, vị thanh mát, tiện dùng hàng ngày.",
                    "yen-che-bien.jpg",
                ),
                (
                    "Yến sào thô nguyên tổ 100g",
                    12500000,
                    "Tổ yến thô nguyên chất Khánh Hòa, giữ trọn dinh dưỡng, cho gia đình.",
                    "yen-3.webp",
                ),
                (
                    "Yến sợi khô cao cấp 100g",
                    3200000,
                    "Sợi yến rút lông tinh khiết, dễ chưng, hương vị truyền thống.",
                    "yen-1.jpg",
                ),
                (
                    "Set quà Tết — Yến & trà 8 món",
                    1890000,
                    "Hộp quà sang trọng: yến chưng, trà, đường phèn — phong vị Tết.",
                    "landing.png",
                ),
                (
                    "Yến hũ chưng đường phèn 70ml x 12",
                    890000,
                    "Thùng 12 hũ nhỏ gọn, đường phèn tự nhiên, an toàn cho mọi lứa tuổi.",
                    "yen-5.webp",
                ),
                (
                    "Yến baby — dành cho trẻ từ 1 tuổi",
                    650000,
                    "Công thức nhẹ, ít đường, bổ sung dinh dưỡng cho trẻ (theo chỉ dẫn bác sĩ).",
                    "yen-2.jpg",
                ),
                (
                    "Combo gia đình: yến tinh chế + chưng sẵn",
                    3290000,
                    "Kết hợp yến khô tinh chế và yến chưng sẵn — tiết kiệm cho cả nhà.",
                    "bg.jpg",
                ),
            ]
            cur = conn.cursor()
            try:
                cur.executemany(
                    "INSERT INTO products (name, price, description, image) VALUES (%s, %s, %s, %s)",
                    samples,
                )
            finally:
                cur.close()
            conn.commit()
    except Exception:
        logger.exception("init_db failed")
        try:
            conn.rollback()
        except Exception:
            logger.exception("init_db rollback failed")
        raise
    finally:
        try:
            conn.close()
        except Exception:
            logger.exception("init_db: error closing connection")


# --- Products (giữ nguyên API cũ) ---


def get_all_products() -> List[Dict[str, Any]]:
    conn = get_connection()
    try:
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT id, name, price, description, image FROM products ORDER BY id ASC"
            )
            return [dict(row) for row in cur.fetchall()]
        finally:
            cur.close()
    except Exception:
        logger.exception("get_all_products failed")
        return []
    finally:
        conn.close()


def get_product_by_id(product_id: int) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    try:
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT id, name, price, description, image FROM products WHERE id = %s",
                (product_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None
        finally:
            cur.close()
    except Exception:
        logger.exception("get_product_by_id failed")
        return None
    finally:
        conn.close()


def search_products(keyword: str) -> List[Dict[str, Any]]:
    if not keyword or not keyword.strip():
        return get_all_products()
    kw = f"%{keyword.strip()}%"
    conn = get_connection()
    try:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT id, name, price, description, image FROM products
                WHERE LOWER(name) LIKE LOWER(%s) OR LOWER(description) LIKE LOWER(%s)
                ORDER BY id ASC
                """,
                (kw, kw),
            )
            return [dict(row) for row in cur.fetchall()]
        finally:
            cur.close()
    except Exception:
        logger.exception("search_products failed")
        return []
    finally:
        conn.close()


def add_product(name: str, price: int, description: str, image: str) -> int:
    conn = get_connection()
    try:
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO products (name, price, description, image) VALUES (%s, %s, %s, %s) RETURNING id",
                (name.strip(), int(price), description.strip(), image.strip()),
            )
            row = cur.fetchone()
            conn.commit()
            return int(row["id"])
        finally:
            cur.close()
    finally:
        conn.close()


# --- Users ---


def create_user(
    username: str, password_hash: str, full_name: str, phone: str, address: str
) -> int:
    """Đăng ký user mới; trả về id."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                INSERT INTO users (username, password, full_name, phone, address)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    username.strip().lower(),
                    password_hash,
                    full_name.strip(),
                    phone.strip(),
                    address.strip(),
                ),
            )
            row = cur.fetchone()
            conn.commit()
            return int(row["id"])
        finally:
            cur.close()
    finally:
        conn.close()


def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    try:
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT id, username, password, full_name, phone, address FROM users WHERE username = %s",
                (username.strip().lower(),),
            )
            row = cur.fetchone()
            return dict(row) if row else None
        finally:
            cur.close()
    except Exception:
        logger.exception("get_user_by_username failed")
        return None
    finally:
        conn.close()


def get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    try:
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT id, username, password, full_name, phone, address FROM users WHERE id = %s",
                (user_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None
        finally:
            cur.close()
    except Exception:
        logger.exception("get_user_by_id failed")
        return None
    finally:
        conn.close()


# --- Cart (chỉ user đã đăng nhập; guest dùng session ở app) ---


def cart_add_item(user_id: int, product_id: int, quantity: int = 1) -> None:
    """Thêm hoặc cộng dồn số lượng trong giỏ DB."""
    if quantity < 1:
        return
    conn = get_connection()
    try:
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT id, quantity FROM cart WHERE user_id = %s AND product_id = %s",
                (user_id, product_id),
            )
            row = cur.fetchone()
            if row:
                new_q = int(row["quantity"]) + quantity
                cur.execute(
                    "UPDATE cart SET quantity = %s WHERE id = %s",
                    (new_q, row["id"]),
                )
            else:
                cur.execute(
                    "INSERT INTO cart (user_id, product_id, quantity) VALUES (%s, %s, %s)",
                    (user_id, product_id, quantity),
                )
            conn.commit()
        finally:
            cur.close()
    except Exception:
        logger.exception("cart_add_item failed")
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        conn.close()


def cart_set_quantity(user_id: int, product_id: int, quantity: int) -> None:
    """Đặt số lượng; quantity <= 0 thì xóa dòng."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        try:
            if quantity <= 0:
                cur.execute(
                    "DELETE FROM cart WHERE user_id = %s AND product_id = %s",
                    (user_id, product_id),
                )
            else:
                cur.execute(
                    "SELECT id FROM cart WHERE user_id = %s AND product_id = %s",
                    (user_id, product_id),
                )
                if cur.fetchone():
                    cur.execute(
                        "UPDATE cart SET quantity = %s WHERE user_id = %s AND product_id = %s",
                        (quantity, user_id, product_id),
                    )
            conn.commit()
        finally:
            cur.close()
    except Exception:
        logger.exception("cart_set_quantity failed")
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        conn.close()


def cart_remove_item(user_id: int, product_id: int) -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        try:
            cur.execute(
                "DELETE FROM cart WHERE user_id = %s AND product_id = %s",
                (user_id, product_id),
            )
            conn.commit()
        finally:
            cur.close()
    except Exception:
        logger.exception("cart_remove_item failed")
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        conn.close()


def cart_clear(user_id: int) -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        try:
            cur.execute("DELETE FROM cart WHERE user_id = %s", (user_id,))
            conn.commit()
        finally:
            cur.close()
    except Exception:
        logger.exception("cart_clear failed")
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        conn.close()


def cart_get_lines_for_user(user_id: int) -> List[Dict[str, Any]]:
    """
    Trả về danh sách dòng giỏ kèm thông tin sản phẩm:
    product_id, quantity, product (dict), line_total.
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT c.product_id, c.quantity,
                       p.name, p.price, p.description, p.image
                FROM cart c
                JOIN products p ON p.id = c.product_id
                WHERE c.user_id = %s
                ORDER BY c.id ASC
                """,
                (user_id,),
            )
            lines = []
            for row in cur.fetchall():
                p = {
                    "id": row["product_id"],
                    "name": row["name"],
                    "price": row["price"],
                    "description": row["description"],
                    "image": row["image"],
                }
                qty = int(row["quantity"])
                lines.append(
                    {
                        "product_id": row["product_id"],
                        "quantity": qty,
                        "product": p,
                        "line_total": int(row["price"]) * qty,
                    }
                )
            return lines
        finally:
            cur.close()
    except Exception:
        logger.exception("cart_get_lines_for_user failed")
        return []
    finally:
        conn.close()


def cart_total_quantity_user(user_id: int) -> int:
    conn = get_connection()
    try:
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT COALESCE(SUM(quantity), 0) AS t FROM cart WHERE user_id = %s",
                (user_id,),
            )
            row = cur.fetchone()
            return int(row["t"]) if row else 0
        finally:
            cur.close()
    except Exception:
        logger.exception("cart_total_quantity_user failed")
        return 0
    finally:
        conn.close()


def merge_session_cart_into_db(user_id: int, session_cart: Dict[str, int]) -> None:
    """
    Sau khi đăng nhập: gộp giỏ session (product_id -> qty) vào giỏ DB.
    """
    for pid_str, qty in session_cart.items():
        try:
            pid = int(pid_str)
            q = int(qty)
            if q > 0:
                cart_add_item(user_id, pid, q)
        except (ValueError, TypeError):
            continue


# --- Orders ---


def create_order(
    user_id: Optional[int],
    full_name: str,
    phone: str,
    email: Optional[str],
    province: str,
    district: str,
    ward: str,
    detail_address: str,
    total_price: int,
    items: List[Dict[str, Any]],
) -> int:
    """
    items: mỗi phần tử có product_id, quantity, price (đơn giá tại thời điểm đặt).
    Trả về order id.
    """
    created_at = now_utc_iso_z()
    conn = get_connection()
    try:
        order_code = _pick_unique_order_code(conn)
        cur = conn.cursor()
        try:
            cur.execute(
                """
                INSERT INTO orders (
                    user_id, full_name, phone, email, province, district, ward,
                    detail_address, total_price, created_at, status, order_code
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    user_id,
                    full_name.strip(),
                    phone.strip(),
                    (email or "").strip() or None,
                    province.strip() or None,
                    district.strip() or None,
                    ward.strip() or None,
                    detail_address.strip(),
                    int(total_price),
                    created_at,
                    ORDER_STATUS_PENDING,
                    order_code,
                ),
            )
            row = cur.fetchone()
            oid = int(row["id"])
            for it in items:
                cur.execute(
                    """
                    INSERT INTO order_items (order_id, product_id, quantity, price)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (oid, int(it["product_id"]), int(it["quantity"]), int(it["price"])),
                )
            conn.commit()
            return oid
        finally:
            cur.close()
    except Exception:
        logger.exception("create_order failed")
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()


def get_order_by_id(order_id: int) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    try:
        cur = conn.cursor()
        try:
            cur.execute("SELECT * FROM orders WHERE id = %s", (order_id,))
            row = cur.fetchone()
            return dict(row) if row else None
        finally:
            cur.close()
    except Exception:
        logger.exception("get_order_by_id failed")
        return None
    finally:
        conn.close()


def get_order_items_for_email(order_id: int) -> List[Dict[str, Any]]:
    """Chi tiết đơn kèm tên sản phẩm (phục vụ gửi mail)."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT oi.product_id, oi.quantity, oi.price, p.name AS product_name
                FROM order_items oi
                JOIN products p ON p.id = oi.product_id
                WHERE oi.order_id = %s
                ORDER BY oi.id ASC
                """,
                (order_id,),
            )
            return [dict(row) for row in cur.fetchall()]
        finally:
            cur.close()
    except Exception:
        logger.exception("get_order_items_for_email failed")
        return []
    finally:
        conn.close()


def lines_total(lines: List[Dict[str, Any]]) -> int:
    """Tổng tiền từ danh sách dòng giỏ (đã có line_total hoặc product + quantity)."""
    s = 0
    for line in lines:
        if "line_total" in line:
            s += int(line["line_total"])
        else:
            s += int(line["product"]["price"]) * int(line["quantity"])
    return s


def list_all_orders(search: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Danh sách đơn hàng (admin), mới nhất trước.
    Nếu search có giá trị: lọc theo order_code (LIKE, không phân biệt hoa thường).
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        try:
            base_sql = """
                SELECT id, user_id, full_name, phone, email, province, district, ward,
                       detail_address, total_price, created_at,
                       COALESCE(status, 'pending') AS status,
                       order_code
                FROM orders
            """
            if search and search.strip():
                q = f"%{search.strip()}%"
                cur.execute(
                    base_sql
                    + " WHERE LOWER(COALESCE(order_code, '')) LIKE LOWER(%s) ORDER BY created_at DESC, id DESC",
                    (q,),
                )
            else:
                cur.execute(base_sql + " ORDER BY created_at DESC, id DESC")
            return [dict(row) for row in cur.fetchall()]
        finally:
            cur.close()
    except Exception:
        logger.exception("list_all_orders failed")
        return []
    finally:
        conn.close()


def get_order_items_admin(order_id: int) -> List[Dict[str, Any]]:
    """Chi tiết dòng đơn cho admin: tên SP, SL, đơn giá, thành tiền."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT oi.product_id, oi.quantity, oi.price, p.name AS product_name
                FROM order_items oi
                JOIN products p ON p.id = oi.product_id
                WHERE oi.order_id = %s
                ORDER BY oi.id ASC
                """,
                (order_id,),
            )
            rows = []
            for row in cur.fetchall():
                q = int(row["quantity"])
                price = int(row["price"])
                rows.append(
                    {
                        "product_id": row["product_id"],
                        "product_name": row["product_name"],
                        "quantity": q,
                        "price": price,
                        "line_total": q * price,
                    }
                )
            return rows
        finally:
            cur.close()
    except Exception:
        logger.exception("get_order_items_admin failed")
        return []
    finally:
        conn.close()


def update_order_status(order_id: int, status: str) -> bool:
    """Cập nhật trạng thái đơn (pending / confirmed / shipped)."""
    if status not in ORDER_STATUSES:
        return False
    conn = get_connection()
    try:
        cur = conn.cursor()
        try:
            cur.execute(
                "UPDATE orders SET status = %s WHERE id = %s",
                (status, order_id),
            )
            conn.commit()
            return True
        finally:
            cur.close()
    except Exception:
        logger.exception("update_order_status failed")
        try:
            conn.rollback()
        except Exception:
            pass
        return False
    finally:
        conn.close()


def count_orders_total() -> int:
    conn = get_connection()
    try:
        cur = conn.cursor()
        try:
            cur.execute("SELECT COUNT(*) AS c FROM orders")
            row = cur.fetchone()
            return int(row["c"]) if row else 0
        finally:
            cur.close()
    except Exception:
        logger.exception("count_orders_total failed")
        return 0
    finally:
        conn.close()


def count_orders_by_status(status: str) -> int:
    conn = get_connection()
    try:
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT COUNT(*) AS c FROM orders WHERE COALESCE(status, 'pending') = %s",
                (status,),
            )
            row = cur.fetchone()
            return int(row["c"]) if row else 0
        finally:
            cur.close()
    except Exception:
        logger.exception("count_orders_by_status failed")
        return 0
    finally:
        conn.close()


def count_products_total() -> int:
    conn = get_connection()
    try:
        cur = conn.cursor()
        try:
            cur.execute("SELECT COUNT(*) AS c FROM products")
            row = cur.fetchone()
            return int(row["c"]) if row else 0
        finally:
            cur.close()
    except Exception:
        logger.exception("count_products_total failed")
        return 0
    finally:
        conn.close()


def update_product(
    product_id: int, name: str, price: int, description: str, image: str
) -> None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                UPDATE products SET name = %s, price = %s, description = %s, image = %s
                WHERE id = %s
                """,
                (name.strip(), int(price), description.strip(), image.strip(), product_id),
            )
            conn.commit()
        finally:
            cur.close()
    except Exception:
        logger.exception("update_product failed")
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()


def delete_product(product_id: int) -> Tuple[bool, str]:
    """
    Xóa sản phẩm nếu chưa xuất hiện trong order_items.
    Xóa trước các dòng cart liên quan.
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT COUNT(*) AS c FROM order_items WHERE product_id = %s",
                (product_id,),
            )
            if int(cur.fetchone()["c"]) > 0:
                return False, "Không thể xóa: sản phẩm đã có trong đơn hàng."
            cur.execute("DELETE FROM cart WHERE product_id = %s", (product_id,))
            cur.execute("DELETE FROM products WHERE id = %s", (product_id,))
            conn.commit()
            return True, ""
        finally:
            cur.close()
    except Exception as e:
        logger.exception("delete_product failed")
        try:
            conn.rollback()
        except Exception:
            pass
        return False, str(e)
    finally:
        conn.close()
