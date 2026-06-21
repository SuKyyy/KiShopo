import asyncio
import os
import random
import string
import time
import hmac
import hashlib
import html
import urllib.parse
import aiohttp
import psycopg2
from psycopg2.pool import ThreadedConnectionPool
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

load_dotenv()
bot = Bot(token=os.getenv("BOT_TOKEN"))
dp = Dispatcher()

ADMIN = "@sukodeuva"
ADMIN_URL = "https://t.me/sukodeuva"
# Telegram user IDs allowed to access the admin panel.
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "7658392821").replace(" ", "").split(",") if x}

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

BINANCE_ID = os.getenv("BINANCE_ID", "YOUR_BINANCE_ID")
BEP20_ADDRESS = os.getenv("BEP20_ADDRESS", "YOUR_BEP20_WALLET_ADDRESS")
BOT_USERNAME = os.getenv("BOT_USERNAME", "SukoShopBot")
DATABASE_URL = os.getenv("DATABASE_URL", "")

# ===== BEP20 / BscScan auto-detection =====
BSCSCAN_API_KEY = os.getenv("BSCSCAN_API_KEY", "")
# Binance-Peg BSC-USD (USDT) BEP20 contract
USDT_CONTRACT = "0x55d398326f99059fF775485246999027B3197955"
SCAN_INTERVAL = 30  # seconds between blockchain scans

# ===== Binance Pay auto-detection (personal account API) =====
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")
BINANCE_BASE_URL = "https://api.binance.com"

# ================== DATABASE (Neon / PostgreSQL) ==================
_pool = None

def get_pool():
    global _pool
    if _pool is None:
        if not DATABASE_URL:
            raise RuntimeError("DATABASE_URL is not set")
        _pool = ThreadedConnectionPool(1, 10, dsn=DATABASE_URL)
    return _pool

@contextmanager
def db_cursor(commit: bool = False):
    pool = get_pool()
    conn = pool.getconn()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            yield cur
            if commit:
                conn.commit()
        finally:
            cur.close()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)

def init_db():
    with db_cursor(commit=True) as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                name TEXT,
                balance DOUBLE PRECISION DEFAULT 0.0,
                lang TEXT DEFAULT 'en',
                referral TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                order_code TEXT,
                product_name TEXT,
                price DOUBLE PRECISION,
                quantity INTEGER DEFAULT 1,
                status TEXT DEFAULT 'Pending',
                created_at TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS pending_payments (
                code TEXT PRIMARY KEY,
                user_id BIGINT,
                product_id TEXT,
                quantity INTEGER,
                amount DOUBLE PRECISION,
                payment_type TEXT,
                expires_at TEXT,
                created_at TEXT,
                expected_bep20 DOUBLE PRECISION,
                expected_binance DOUBLE PRECISION,
                created_epoch BIGINT
            )
        """)
        c.execute("ALTER TABLE pending_payments ADD COLUMN IF NOT EXISTS expected_binance DOUBLE PRECISION")
        c.execute("""
            CREATE TABLE IF NOT EXISTS processed_tx (
                tx_hash TEXT PRIMARY KEY,
                code TEXT,
                user_id BIGINT,
                amount DOUBLE PRECISION,
                processed_at TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                price DOUBLE PRECISION NOT NULL DEFAULT 0,
                stock INTEGER NOT NULL DEFAULT 0,
                emoji TEXT DEFAULT '📦',
                description TEXT DEFAULT '',
                category TEXT DEFAULT '',
                sort_order INTEGER DEFAULT 0,
                active BOOLEAN DEFAULT TRUE,
                delivery_type TEXT DEFAULT 'manual',
                manual_msg TEXT DEFAULT ''
            )
        """)
        # Migrations for pre-existing products tables
        c.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS delivery_type TEXT DEFAULT 'manual'")
        c.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS manual_msg TEXT DEFAULT ''")
        c.execute("""
            CREATE TABLE IF NOT EXISTS stock_items (
                id SERIAL PRIMARY KEY,
                product_id TEXT,
                content TEXT,
                used BOOLEAN DEFAULT FALSE,
                used_by BIGINT,
                used_at TEXT
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_stock_items_pid ON stock_items (product_id, used)")
        c.execute("""
            CREATE TABLE IF NOT EXISTS translations (
                src_hash TEXT,
                target_lang TEXT,
                translated TEXT,
                PRIMARY KEY (src_hash, target_lang)
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
    seed_products_if_empty()

def get_user(user_id: int, name: str = None):
    with db_cursor(commit=True) as c:
        c.execute("SELECT * FROM users WHERE user_id=%s", (user_id,))
        row = c.fetchone()
        if not row:
            referral = f"https://t.me/{BOT_USERNAME}?start={user_id}"
            c.execute("INSERT INTO users (user_id, name, balance, lang, referral) VALUES (%s,%s,%s,%s,%s)",
                      (user_id, name or "User", 0.0, "en", referral))
            c.execute("SELECT * FROM users WHERE user_id=%s", (user_id,))
            row = c.fetchone()
        elif name and row["name"] != name:
            c.execute("UPDATE users SET name=%s WHERE user_id=%s", (name, user_id))
            row["name"] = name
    return {"user_id": row["user_id"], "name": row["name"], "balance": row["balance"],
            "lang": row["lang"], "referral": row["referral"]}

def set_user_lang(user_id: int, lang: str):
    with db_cursor(commit=True) as c:
        c.execute("UPDATE users SET lang=%s WHERE user_id=%s", (lang, user_id))

def update_balance(user_id: int, delta: float):
    with db_cursor(commit=True) as c:
        c.execute("UPDATE users SET balance=balance+%s WHERE user_id=%s", (delta, user_id))

def add_order(user_id: int, order_code: str, product_name: str, price: float, quantity: int = 1, status: str = "Pending"):
    with db_cursor(commit=True) as c:
        c.execute("INSERT INTO orders (user_id, order_code, product_name, price, quantity, status, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                  (user_id, order_code, product_name, price, quantity, status,
                   datetime.now().strftime("%Y-%m-%d %H:%M")))

def get_orders(user_id: int):
    with db_cursor() as c:
        c.execute("SELECT order_code, product_name, price, quantity, status, created_at FROM orders WHERE user_id=%s ORDER BY id DESC LIMIT 10", (user_id,))
        rows = c.fetchall()
    return [(r["order_code"], r["product_name"], r["price"], r["quantity"], r["status"], r["created_at"]) for r in rows]

def save_pending_payment(code: str, user_id: int, product_id: str, quantity: int, amount: float, payment_type: str, expires_at: str, expected_bep20: float, expected_binance: float):
    with db_cursor(commit=True) as c:
        c.execute("""INSERT INTO pending_payments
                     (code, user_id, product_id, quantity, amount, payment_type, expires_at, created_at, expected_bep20, expected_binance, created_epoch)
                     VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                     ON CONFLICT (code) DO UPDATE SET
                       user_id=EXCLUDED.user_id, product_id=EXCLUDED.product_id,
                       quantity=EXCLUDED.quantity, amount=EXCLUDED.amount,
                       payment_type=EXCLUDED.payment_type, expires_at=EXCLUDED.expires_at,
                       created_at=EXCLUDED.created_at, expected_bep20=EXCLUDED.expected_bep20,
                       expected_binance=EXCLUDED.expected_binance, created_epoch=EXCLUDED.created_epoch""",
                  (code, user_id, product_id, quantity, amount, payment_type, expires_at,
                   datetime.now().strftime("%Y-%m-%d %H:%M"), expected_bep20, expected_binance, int(time.time())))

def get_pending_payment(code: str):
    with db_cursor() as c:
        c.execute("SELECT code, user_id, product_id, quantity, amount, payment_type, expires_at, expected_bep20, expected_binance, created_epoch FROM pending_payments WHERE code=%s", (code,))
        row = c.fetchone()
    if row:
        return {"code": row["code"], "user_id": row["user_id"], "product_id": row["product_id"],
                "quantity": row["quantity"], "amount": row["amount"], "payment_type": row["payment_type"],
                "expires_at": row["expires_at"], "expected_bep20": row["expected_bep20"],
                "expected_binance": row["expected_binance"], "created_epoch": row["created_epoch"]}
    return None

def generate_unique_amount(base_amount: float, field: str) -> float:
    """Generate an amount with a unique cents tail so each payment is identifiable by value."""
    with db_cursor() as c:
        c.execute(f"SELECT {field} FROM pending_payments WHERE {field} IS NOT NULL")
        used = {round(r[field], 4) for r in c.fetchall() if r[field] is not None}
    for _ in range(500):
        tail = random.randint(11, 999) / 10000  # 0.0011 - 0.0999
        amt = round(base_amount + tail, 4)
        if amt not in used:
            return amt
    return round(base_amount + random.randint(11, 999) / 10000, 4)

def generate_unique_bep20(base_amount: float) -> float:
    return generate_unique_amount(base_amount, "expected_bep20")

def generate_unique_binance(base_amount: float) -> float:
    return generate_unique_amount(base_amount, "expected_binance")

def get_all_pending():
    with db_cursor() as c:
        c.execute("SELECT code, user_id, product_id, quantity, amount, payment_type, expires_at, expected_bep20, expected_binance, created_epoch FROM pending_payments")
        rows = c.fetchall()
    return [{"code": r["code"], "user_id": r["user_id"], "product_id": r["product_id"], "quantity": r["quantity"],
             "amount": r["amount"], "payment_type": r["payment_type"], "expires_at": r["expires_at"],
             "expected_bep20": r["expected_bep20"], "expected_binance": r["expected_binance"],
             "created_epoch": r["created_epoch"]} for r in rows]

def is_tx_processed(tx_hash: str) -> bool:
    with db_cursor() as c:
        c.execute("SELECT 1 FROM processed_tx WHERE tx_hash=%s", (tx_hash,))
        row = c.fetchone()
    return row is not None

def mark_tx_processed(tx_hash: str, code: str, user_id: int, amount: float):
    with db_cursor(commit=True) as c:
        c.execute("INSERT INTO processed_tx (tx_hash, code, user_id, amount, processed_at) VALUES (%s,%s,%s,%s,%s) ON CONFLICT (tx_hash) DO NOTHING",
                  (tx_hash, code, user_id, amount, datetime.now().strftime("%Y-%m-%d %H:%M")))

def delete_pending_payment(code: str):
    with db_cursor(commit=True) as c:
        c.execute("DELETE FROM pending_payments WHERE code=%s", (code,))

# ----- Products (Neon-backed) -----
def seed_products_if_empty():
    """Populate the products table from SEED_PRODUCTS the first time only."""
    with db_cursor(commit=True) as c:
        c.execute("SELECT COUNT(*) AS n FROM products")
        if c.fetchone()["n"] > 0:
            return
        for i, p in enumerate(SEED_PRODUCTS):
            c.execute("""INSERT INTO products (id, name, price, stock, emoji, description, category, sort_order, active)
                         VALUES (%s,%s,%s,%s,%s,%s,%s,%s,TRUE)
                         ON CONFLICT (id) DO NOTHING""",
                      (p["id"], p["name"], p["price"], p["stock"], p["emoji"],
                       p["description"], p["category"], i))
    print("[db] seeded products table")

PRODUCT_COLS = "id, name, price, stock, emoji, description, category, sort_order, active, delivery_type, manual_msg"

def get_all_products(active_only: bool = False):
    q = f"SELECT {PRODUCT_COLS} FROM products"
    if active_only:
        q += " WHERE active=TRUE"
    q += " ORDER BY sort_order ASC, id ASC"
    with db_cursor() as c:
        c.execute(q)
        rows = c.fetchall()
    return [dict(r) for r in rows]

def get_product(pid: str):
    with db_cursor() as c:
        c.execute(f"SELECT {PRODUCT_COLS} FROM products WHERE id=%s", (pid,))
        row = c.fetchone()
    return dict(row) if row else None

def next_product_id() -> str:
    with db_cursor() as c:
        c.execute("SELECT id FROM products")
        ids = [r["id"] for r in c.fetchall()]
    n = 1
    nums = [int(i) for i in ids if i.isdigit()]
    if nums:
        n = max(nums) + 1
    return str(n)

def create_product(name: str, price: float, stock: int, emoji: str, description: str, category: str,
                   delivery_type: str = "manual") -> str:
    pid = next_product_id()
    with db_cursor(commit=True) as c:
        c.execute("SELECT COALESCE(MAX(sort_order), 0) + 1 AS so FROM products")
        so = c.fetchone()["so"]
        c.execute("""INSERT INTO products (id, name, price, stock, emoji, description, category, sort_order, active, delivery_type, manual_msg)
                     VALUES (%s,%s,%s,%s,%s,%s,%s,%s,TRUE,%s,'')""",
                  (pid, name, price, stock, emoji, description, category, so, delivery_type))
    return pid

def update_product_field(pid: str, field: str, value):
    allowed = {"name", "price", "stock", "emoji", "description", "category", "active", "delivery_type", "manual_msg"}
    if field not in allowed:
        raise ValueError(f"invalid field {field}")
    with db_cursor(commit=True) as c:
        c.execute(f"UPDATE products SET {field}=%s WHERE id=%s", (value, pid))

def delete_product(pid: str):
    with db_cursor(commit=True) as c:
        c.execute("DELETE FROM stock_items WHERE product_id=%s", (pid,))
        c.execute("DELETE FROM products WHERE id=%s", (pid,))

def decrement_stock(pid: str, qty: int):
    with db_cursor(commit=True) as c:
        c.execute("UPDATE products SET stock = GREATEST(stock - %s, 0) WHERE id=%s", (qty, pid))

# ----- Auto-delivery stock items -----
def count_available_items(pid: str) -> int:
    with db_cursor() as c:
        c.execute("SELECT COUNT(*) AS n FROM stock_items WHERE product_id=%s AND used=FALSE", (pid,))
        return c.fetchone()["n"]

def sync_auto_stock(pid: str):
    """For auto products, the stock column mirrors the number of unused items."""
    n = count_available_items(pid)
    with db_cursor(commit=True) as c:
        c.execute("UPDATE products SET stock=%s WHERE id=%s", (n, pid))
    return n

def add_stock_items(pid: str, items: list):
    with db_cursor(commit=True) as c:
        for content in items:
            c.execute("INSERT INTO stock_items (product_id, content, used) VALUES (%s,%s,FALSE)",
                      (pid, content))
    return sync_auto_stock(pid)

def pop_stock_items(pid: str, qty: int):
    """Atomically claim up to `qty` unused items. Returns list of contents delivered."""
    delivered = []
    with db_cursor(commit=True) as c:
        c.execute("""SELECT id, content FROM stock_items
                     WHERE product_id=%s AND used=FALSE
                     ORDER BY id ASC LIMIT %s FOR UPDATE""", (pid, qty))
        rows = c.fetchall()
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        for r in rows:
            c.execute("UPDATE stock_items SET used=TRUE, used_at=%s WHERE id=%s", (now, r["id"]))
            delivered.append(r["content"])
    sync_auto_stock(pid)
    return delivered

def get_categories():
    """Return ordered list of distinct non-empty categories."""
    with db_cursor() as c:
        c.execute("""SELECT category, MIN(sort_order) AS so FROM products
                     WHERE active=TRUE AND COALESCE(category,'') <> ''
                     GROUP BY category ORDER BY so ASC""")
        rows = c.fetchall()
    return [r["category"] for r in rows]

# ----- App settings (key/value) -----
def get_setting(key: str, default: str = "") -> str:
    with db_cursor() as c:
        c.execute("SELECT value FROM app_settings WHERE key=%s", (key,))
        row = c.fetchone()
    return row["value"] if row and row["value"] is not None else default

def set_setting(key: str, value: str):
    with db_cursor(commit=True) as c:
        c.execute("""INSERT INTO app_settings (key, value) VALUES (%s,%s)
                     ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value""", (key, value))

# ----- Auto translation (Google translate free endpoint, with DB cache) -----
def _cache_get_translation(src_hash: str, target_lang: str):
    with db_cursor() as c:
        c.execute("SELECT translated FROM translations WHERE src_hash=%s AND target_lang=%s",
                  (src_hash, target_lang))
        row = c.fetchone()
    return row["translated"] if row else None

def _cache_put_translation(src_hash: str, target_lang: str, translated: str):
    with db_cursor(commit=True) as c:
        c.execute("""INSERT INTO translations (src_hash, target_lang, translated) VALUES (%s,%s,%s)
                     ON CONFLICT (src_hash, target_lang) DO UPDATE SET translated=EXCLUDED.translated""",
                  (src_hash, target_lang, translated))

async def translate_text(text: str, target_lang: str) -> str:
    """Translate `text` to target_lang. Caches results in the DB.
    Falls back to the original text if translation fails."""
    if not text or not text.strip():
        return text
    target_lang = (target_lang or "en").split("-")[0]
    src_hash = hashlib.sha256(f"{target_lang}:{text}".encode("utf-8")).hexdigest()
    cached = _cache_get_translation(src_hash, target_lang)
    if cached is not None:
        return cached
    url = (
        "https://translate.googleapis.com/translate_a/single"
        f"?client=gtx&sl=auto&tl={target_lang}&dt=t&q={urllib.parse.quote(text)}"
    )
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return text
                data = await resp.json(content_type=None)
        # data[0] is a list of [translated_segment, original_segment, ...]
        translated = "".join(seg[0] for seg in data[0] if seg and seg[0])
        if not translated.strip():
            return text
        _cache_put_translation(src_hash, target_lang, translated)
        return translated
    except Exception as e:
        print(f"[translate] failed ({target_lang}): {e}")
        return text

# ----- Admin helpers -----
def get_all_user_ids():
    with db_cursor() as c:
        c.execute("SELECT user_id FROM users")
        rows = c.fetchall()
    return [r["user_id"] for r in rows]

def get_stats():
    with db_cursor() as c:
        c.execute("SELECT COUNT(*) AS n, COALESCE(SUM(balance),0) AS bal FROM users")
        u = c.fetchone()
        c.execute("SELECT COUNT(*) AS n, COALESCE(SUM(price*quantity),0) AS rev FROM orders WHERE status='Paid'")
        o = c.fetchone()
        c.execute("SELECT COUNT(*) AS n FROM products WHERE active=TRUE")
        p = c.fetchone()
        c.execute("SELECT COUNT(*) AS n FROM pending_payments")
        pend = c.fetchone()
    return {
        "users": u["n"], "balance_total": float(u["bal"]),
        "paid_orders": o["n"], "revenue": float(o["rev"]),
        "active_products": p["n"], "pending": pend["n"],
    }

def generate_code(prefix: str = "BN") -> str:
    ts = datetime.now().strftime("%y%m%d%H%M%S")
    rand = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"{prefix}{ts}{rand}"

# ================== TRANSLATIONS ==================
LANGS = {
    "en": {
        "welcome": (
            "🔥 <b>Welcome to SukoShop — Auto Order Bot</b>\n\n"
            "👋 Hello, <b>{name}</b>!\n\n"
            "📌 Quick guide:\n"
            "1. Click <b>Shop</b> to browse products.\n"
            "2. Choose the product you want.\n"
            "3. Pay via Binance Pay or BEP20 wallet.\n"
            "4. After payment the bot delivers automatically.\n\n"
            "Please choose an option:"
        ),
        "choose_option": "Please choose an option:",
        "shop_title": "🛒 <b>SHOP</b>\n\nChoose a product to buy:",
        "in_stock": "In Stock",
        "out_of_stock": "Out of Stock",
        "back": "⬅️ Back",
        "back_to_shop": "⬅️ Back to Shop",
        "back_to_wallet": "⬅️ Back to Wallet",
        "buy_now": "💳 Buy Now",
        "profile_title": "👤 <b>PROFILE</b>",
        "user_id": "User ID",
        "name_label": "Name",
        "balance_label": "Balance",
        "referral_label": "Referral Link",
        "referral_desc": "Share your link and earn commission!",
        "history_title": "📜 <b>ORDER HISTORY</b>",
        "no_orders": "📜 You have no orders yet.",
        "wallet_title": "💰 <b>WALLET</b>",
        "usdt_balance": "USDT Balance",
        "deposit_btn": "➕ Deposit",
        "withdraw_btn": "💸 Withdraw",
        "withdraw_title": "💸 <b>WITHDRAW</b>",
        "withdraw_text": (
            "To withdraw your balance:\n\n"
            "1. Contact <a href='{admin_url}'>{admin}</a>\n"
            "2. Send your BEP20 wallet address and amount\n"
            "3. Withdrawal processed within 24h"
        ),
        "support_title": "🛟 <b>SUPPORT</b>",
        "support_text": "👤 Admin: <a href='{admin_url}'>{admin}</a>\n\n⏰ Working hours: 8h - 22h daily",
        "language_title": "🌐 <b>Choose Language</b>",
        "lang_changed": "Language changed to English!",
        "out_of_stock_alert": "Out of stock!",
        "enter_qty": "Enter quantity (1-{max}):\n\n💵 Your balance: <b>${balance:.2f} USDT</b>",
        "invalid_qty": "Invalid quantity. Please enter a number between 1 and {max}.",
        "insufficient_balance": "Insufficient balance! You need ${needed:.2f} USDT but have ${balance:.2f} USDT.\nPlease deposit first.",
        "waiting_payment": "⏳ <b>WAITING FOR PAYMENT...</b>",
        "payment_expired": "Payment expired. Please try again.",
        "deposit_info_title": "💵 <b>USDT DEPOSIT INFO</b>",
        "deposit_info_amount": "Amount",
        "deposit_info_code": "Code",
        "option1_title": "🔶 OPTION 1: BINANCE PAY (Instant, Free)",
        "option1_binance_id": "Binance ID",
        "option1_amount": "Amount",
        "option1_note": "Note",
        "option1_steps": "B. Binance → Pay → Send → paste ID above\n⚠️ Note MUST be exact!",
        "option2_title": "🔷 OPTION 2: WALLET TRANSFER (BEP20)",
        "option2_address": "Address",
        "option2_network": "Network: <b>BEP20</b>",
        "option2_amount": "Amount",
        "option2_warning": "⚠️ Send EXACTLY this amount!\n⚠️ Use <b>BEP20</b> network ONLY!",
        "auto_detect": "⏱ Auto-detection within 1-2 minutes.\nYou'll be notified when funds are added!",
        "auto_detect_buy": "⏱ Auto-detection within 1-2 minutes.\nProduct will be delivered automatically!\n⏰ Payment expires in 10 minutes.",
        "cancel_payment": "❌ Cancel",
        "btn_shop": "🛒 Shop",
        "btn_profile": "👤 Profile",
        "btn_history": "📜 Order History",
        "btn_wallet": "💰 Wallet",
        "btn_support": "🛟 Support",
        "btn_language": "🌐 Language",
        "order_confirmed_title": "Order confirmed!",
        "product_label": "Product",
        "qty_label": "Quantity",
        "total_label": "Total",
        "order_code_label": "Order code",
        "your_items": "Your items:",
        "partial_delivery": "Only part of your order was in stock. The remaining {missing} will be delivered manually by {admin}.",
        "await_manual": "Your items are being prepared. Please contact {admin} to receive them.",
        "contact_seller": "💬 Contact seller",
        "manual_instructions": "To receive your product, contact the seller {admin} and send the message below:",
        "copy_message": "Copy and send this message:",
    },
    "pt": {
        "welcome": (
            "🔥 <b>Bem-vindo ao SukoShop — Bot de Pedido Automático</b>\n\n"
            "👋 Olá, <b>{name}</b>!\n\n"
            "📌 Guia rápido:\n"
            "1. Clique em <b>Loja</b> para ver os produtos.\n"
            "2. Escolha o produto desejado.\n"
            "3. Pague via Binance Pay ou carteira BEP20.\n"
            "4. Após o pagamento o bot entrega automaticamente.\n\n"
            "Escolha uma opção:"
        ),
        "choose_option": "Escolha uma opção:",
        "shop_title": "🛒 <b>LOJA</b>\n\nEscolha um produto:",
        "in_stock": "Disponível",
        "out_of_stock": "Esgotado",
        "back": "⬅️ Voltar",
        "back_to_shop": "⬅️ Voltar à Loja",
        "back_to_wallet": "⬅️ Voltar à Carteira",
        "buy_now": "💳 Comprar Agora",
        "profile_title": "👤 <b>PERFIL</b>",
        "user_id": "ID do Usuário",
        "name_label": "Nome",
        "balance_label": "Saldo",
        "referral_label": "Link de Indicação",
        "referral_desc": "Compartilhe seu link e ganhe comissão!",
        "history_title": "📜 <b>HISTÓRICO DE PEDIDOS</b>",
        "no_orders": "���� Você ainda não tem pedidos.",
        "wallet_title": "💰 <b>CARTEIRA</b>",
        "usdt_balance": "Saldo USDT",
        "deposit_btn": "➕ Depositar",
        "withdraw_btn": "💸 Sacar",
        "withdraw_title": "💸 <b>SAQUE</b>",
        "withdraw_text": (
            "Para sacar seu saldo:\n\n"
            "1. Contate <a href='{admin_url}'>{admin}</a>\n"
            "2. Informe seu endereço BEP20 e o valor\n"
            "3. Saque processado em até 24h"
        ),
        "support_title": "🛟 <b>SUPORTE</b>",
        "support_text": "👤 Admin: <a href='{admin_url}'>{admin}</a>\n\n⏰ Horário: 8h - 22h",
        "language_title": "🌐 <b>Escolha o Idioma</b>",
        "lang_changed": "Idioma alterado para Português!",
        "out_of_stock_alert": "Produto esgotado!",
        "enter_qty": "Digite a quantidade (1-{max}):\n\n💵 Seu saldo: <b>${balance:.2f} USDT</b>",
        "invalid_qty": "Quantidade inválida. Digite um número entre 1 e {max}.",
        "insufficient_balance": "Saldo insuficiente! Você precisa de ${needed:.2f} USDT mas tem ${balance:.2f} USDT.\nFaça um depósito primeiro.",
        "waiting_payment": "⏳ <b>AGUARDANDO PAGAMENTO...</b>",
        "payment_expired": "Pagamento expirado. Tente novamente.",
        "deposit_info_title": "💵 <b>INFO DE DEPÓSITO USDT</b>",
        "deposit_info_amount": "Valor",
        "deposit_info_code": "Código",
        "option1_title": "🔶 OPÇÃO 1: BINANCE PAY (Instantâneo, Grátis)",
        "option1_binance_id": "ID Binance",
        "option1_amount": "Valor",
        "option1_note": "Nota",
        "option1_steps": "B. Binance → Pay → Send → cole o ID acima\n⚠️ A nota DEVE ser exata!",
        "option2_title": "🔷 OPÇÃO 2: TRANSFERÊNCIA CARTEIRA (BEP20)",
        "option2_address": "Endereço",
        "option2_network": "Rede: <b>BEP20</b>",
        "option2_amount": "Valor",
        "option2_warning": "⚠️ Envie EXATAMENTE este valor!\n⚠️ Use a rede <b>BEP20</b> APENAS!",
        "auto_detect": "⏱ Detecção automática em 1-2 minutos.\nVocê será notificado quando o saldo for adicionado!",
        "auto_detect_buy": "⏱ Detecção automática em 1-2 minutos.\nO produto será entregue automaticamente!\n⏰ Pagamento expira em 10 minutos.",
        "cancel_payment": "❌ Cancelar",
        "btn_shop": "🛒 Loja",
        "btn_profile": "👤 Perfil",
        "btn_history": "📜 Histórico",
        "btn_wallet": "💰 Carteira",
        "btn_support": "🛟 Suporte",
        "btn_language": "🌐 Idioma",
        "order_confirmed_title": "Pedido confirmado!",
        "product_label": "Produto",
        "qty_label": "Quantidade",
        "total_label": "Total",
        "order_code_label": "Código do pedido",
        "your_items": "Seus itens:",
        "partial_delivery": "Apenas parte do seu pedido tinha estoque. Os {missing} restantes serão entregues manualmente por {admin}.",
        "await_manual": "Seus itens estão sendo preparados. Entre em contato com {admin} para recebê-los.",
        "contact_seller": "💬 Falar com o vendedor",
        "manual_instructions": "Para receber seu produto, fale com o vendedor {admin} e envie a mensagem abaixo:",
        "copy_message": "Copie e envie esta mensagem:",
    },
    "id": {
        "welcome": (
            "🔥 <b>Selamat datang di SukoShop — Bot Pesanan Otomatis</b>\n\n"
            "👋 Halo, <b>{name}</b>!\n\n"
            "📌 Panduan cepat:\n"
            "1. Klik <b>Toko</b> untuk melihat produk.\n"
            "2. Pilih produk yang Anda inginkan.\n"
            "3. Bayar via Binance Pay atau dompet BEP20.\n"
            "4. Setelah pembayaran bot otomatis kirim.\n\n"
            "Pilih opsi:"
        ),
        "choose_option": "Pilih opsi:",
        "shop_title": "🛒 <b>TOKO</b>\n\nPilih produk:",
        "in_stock": "Tersedia",
        "out_of_stock": "Habis",
        "back": "⬅️ Kembali",
        "back_to_shop": "⬅️ Kembali ke Toko",
        "back_to_wallet": "⬅️ Kembali ke Dompet",
        "buy_now": "💳 Beli Sekarang",
        "profile_title": "👤 <b>PROFIL</b>",
        "user_id": "ID Pengguna",
        "name_label": "Nama",
        "balance_label": "Saldo",
        "referral_label": "Link Referral",
        "referral_desc": "Bagikan link Anda dan dapatkan komisi!",
        "history_title": "📜 <b>RIWAYAT PESANAN</b>",
        "no_orders": "📜 Anda belum memiliki pesanan.",
        "wallet_title": "💰 <b>DOMPET</b>",
        "usdt_balance": "Saldo USDT",
        "deposit_btn": "➕ Deposit",
        "withdraw_btn": "💸 Tarik Dana",
        "withdraw_title": "💸 <b>TARIK DANA</b>",
        "withdraw_text": (
            "Untuk menarik saldo:\n\n"
            "1. Hubungi <a href='{admin_url}'>{admin}</a>\n"
            "2. Kirim alamat BEP20 dan jumlah Anda\n"
            "3. Penarikan diproses dalam 24 jam"
        ),
        "support_title": "🛟 <b>DUKUNGAN</b>",
        "support_text": "👤 Admin: <a href='{admin_url}'>{admin}</a>\n\n⏰ Jam kerja: 8 - 22 setiap hari",
        "language_title": "🌐 <b>Pilih Bahasa</b>",
        "lang_changed": "Bahasa diubah ke Indonesia!",
        "out_of_stock_alert": "Stok habis!",
        "enter_qty": "Masukkan jumlah (1-{max}):\n\n💵 Saldo Anda: <b>${balance:.2f} USDT</b>",
        "invalid_qty": "Jumlah tidak valid. Masukkan angka antara 1 dan {max}.",
        "insufficient_balance": "Saldo tidak cukup! Anda butuh ${needed:.2f} USDT tapi punya ${balance:.2f} USDT.\nSilakan deposit dulu.",
        "waiting_payment": "⏳ <b>MENUNGGU PEMBAYARAN...</b>",
        "payment_expired": "Pembayaran kadaluarsa. Coba lagi.",
        "deposit_info_title": "💵 <b>INFO DEPOSIT USDT</b>",
        "deposit_info_amount": "Jumlah",
        "deposit_info_code": "Kode",
        "option1_title": "🔶 OPSI 1: BINANCE PAY (Instan, Gratis)",
        "option1_binance_id": "ID Binance",
        "option1_amount": "Jumlah",
        "option1_note": "Catatan",
        "option1_steps": "B. Binance → Pay → Send → tempel ID di atas\n⚠️ Catatan HARUS tepat!",
        "option2_title": "🔷 OPSI 2: TRANSFER DOMPET (BEP20)",
        "option2_address": "Alamat",
        "option2_network": "Jaringan: <b>BEP20</b>",
        "option2_amount": "Jumlah",
        "option2_warning": "⚠️ Kirim TEPAT jumlah ini!\n⚠️ Gunakan jaringan <b>BEP20</b> SAJA!",
        "auto_detect": "⏱ Deteksi otomatis dalam 1-2 menit.\nAnda akan diberi tahu saat dana ditambahkan!",
        "auto_detect_buy": "⏱ Deteksi otomatis dalam 1-2 menit.\nProduk akan dikirim otomatis!\n⏰ Pembayaran kadaluarsa dalam 10 menit.",
        "cancel_payment": "❌ Batal",
        "btn_shop": "🛒 Toko",
        "btn_profile": "👤 Profil",
        "btn_history": "📜 Riwayat",
        "btn_wallet": "💰 Dompet",
        "btn_support": "🛟 Dukungan",
        "btn_language": "🌐 Bahasa",
    },
    "hi": {
        "welcome": (
            "🔥 <b>SukoShop में आपका स्वागत है — ऑटो ऑर्डर बॉट</b>\n\n"
            "👋 नमस्ते, <b>{name}</b>!\n\n"
            "📌 त्वरित गाइड:\n"
            "1. <b>शॉप</b> पर क्लिक करें।\n"
            "2. उत्पाद चुनें।\n"
            "3. Binance Pay या BEP20 से भुगतान करें।\n"
            "4. भुगतान के बाद बॉट स्वतः डिलीवर करेगा।\n\n"
            "एक विकल्प चुनें:"
        ),
        "choose_option": "एक विकल्प चुनें:",
        "shop_title": "🛒 <b>शॉप</b>\n\nउत्पाद चुनें:",
        "in_stock": "उपलब्ध",
        "out_of_stock": "स्टॉक खत्म",
        "back": "⬅️ वापस",
        "back_to_shop": "⬅️ शॉप पर वापस",
        "back_to_wallet": "⬅️ वॉलेट पर वापस",
        "buy_now": "💳 अभी खरीदें",
        "profile_title": "👤 <b>प्रोफ़ाइल</b>",
        "user_id": "यूजर आईडी",
        "name_label": "नाम",
        "balance_label": "बैलेंस",
        "referral_label": "रेफरल लिंक",
        "referral_desc": "अपना लिंक शेयर करें और कमीशन कमाएं!",
        "history_title": "📜 <b>ऑर्डर हिस्ट्री</b>",
        "no_orders": "📜 अभी तक कोई ऑर्डर नहीं।",
        "wallet_title": "💰 <b>वॉलेट</b>",
        "usdt_balance": "USDT बैलेंस",
        "deposit_btn": "➕ डिपॉजिट",
        "withdraw_btn": "💸 निकासी",
        "withdraw_title": "💸 <b>निकासी</b>",
        "withdraw_text": (
            "बैलेंस निकालने के लिए:\n\n"
            "1. <a href='{admin_url}'>{admin}</a> से संपर्क करें\n"
            "2. BEP20 पता और राशि भेजें\n"
            "3. 24 घंटे में प्रोसेस होगा"
        ),
        "support_title": "🛟 <b>सहायता</b>",
        "support_text": "👤 एडमिन: <a href='{admin_url}'>{admin}</a>\n\n⏰ समय: सुबह 8 - रात 10",
        "language_title": "🌐 <b>भाषा चुनें</b>",
        "lang_changed": "भाषा हिंदी में बदली!",
        "out_of_stock_alert": "स्टॉक खत्म!",
        "enter_qty": "मात्रा दर्ज करें (1-{max}):\n\n💵 आपका बैलेंस: <b>${balance:.2f} USDT</b>",
        "invalid_qty": "अमान्य मात्रा। 1 और {max} के बीच संख्या दर्ज करें।",
        "insufficient_balance": "बैलेंस कम है! आपको ${needed:.2f} USDT चाहिए लेकिन है ${balance:.2f} USDT।\nपहले डिपॉजिट करें।",
        "waiting_payment": "⏳ <b>भुगतान का इंतजार...</b>",
        "payment_expired": "भुगतान समय समाप्त। फिर कोशिश ��रे���।",
        "deposit_info_title": "💵 <b>USDT डिपॉजिट जानकारी</b>",
        "deposit_info_amount": "राशि",
        "deposit_info_code": "कोड",
        "option1_title": "🔶 विकल्प 1: BINANCE PAY (तत्काल, मुफ्त)",
        "option1_binance_id": "Binance ID",
        "option1_amount": "राशि",
        "option1_note": "नोट",
        "option1_steps": "B. Binance → Pay → Send → ऊ���र ID पेस्ट करें\n⚠️ नोट बिल्कुल सही होना चाहिए!",
        "option2_title": "🔷 विकल्प 2: वॉलेट ट्रांसफर (BEP20)",
        "option2_address": "पता",
        "option2_network": "नेटवर्क: <b>BEP20</b>",
        "option2_amount": "राशि",
        "option2_warning": "⚠️ बिल्कुल यही राशि भेजें!\n⚠️ केवल <b>BEP20</b> नेटवर्क उपयोग करें!",
        "auto_detect": "⏱ 1-2 मिनट में स्वतः पहचान।\nराशि जुड़ने पर सूचना मिलेगी!",
        "auto_detect_buy": "⏱ 1-2 मिनट में स्वतः पहचान।\nउत्पाद स्वतः डिलीवर होगा!\n⏰ भुगतान 10 मिनट में समाप्त।",
        "cancel_payment": "❌ रद्द करें",
        "btn_shop": "🛒 शॉप",
        "btn_profile": "👤 प्रोफ़ाइल",
        "btn_history": "📜 हिस्ट्री",
        "btn_wallet": "💰 वॉलेट",
        "btn_support": "🛟 सहायता",
        "btn_language": "🌐 भाषा",
    },
    "th": {
        "welcome": (
            "🔥 <b>ยินดีต้อนรับสู่ SukoShop — บอทสั่งซื้ออัตโนมัติ</b>\n\n"
            "👋 สวัสดี, <b>{name}</b>!\n\n"
            "📌 คู่มือด่วน:\n"
            "1. คลิก <b>ร้านค้า</b> เพื่อดูสินค้า\n"
            "2. เลือกสินค้าที่ต้องการ\n"
            "3. ชำระผ่าน Binance Pay หรือ BEP20\n"
            "4. หลังชำระบอทส่งสินค้าอัตโนมัติ\n\n"
            "กรุณาเลือกตัวเลือก:"
        ),
        "choose_option": "กรุณาเลือกตัวเลือก:",
        "shop_title": "🛒 <b>ร้านค้า</b>\n\nเลือกสินค้า:",
        "in_stock": "มีสินค้า",
        "out_of_stock": "สินค้าหมด",
        "back": "⬅️ กลับ",
        "back_to_shop": "⬅️ กลับไปร้านค้า",
        "back_to_wallet": "⬅️ กลับไปกระเป๋า",
        "buy_now": "💳 ซื้อเลย",
        "profile_title": "👤 <b>โปรไฟล์</b>",
        "user_id": "รหัสผู้ใช้",
        "name_label": "ชื่อ",
        "balance_label": "ยอดคงเหลือ",
        "referral_label": "ลิงก์แนะนำ",
        "referral_desc": "แชร์ลิงก์ของคุณเพื่อรับค่าคอมมิชชั่น!",
        "history_title": "📜 <b>ประวัติการสั่งซื้อ</b>",
        "no_orders": "📜 คุณยังไม่มีคำสั่งซื้อ",
        "wallet_title": "💰 <b>กระเป๋าเงิน</b>",
        "usdt_balance": "ยอด USDT",
        "deposit_btn": "➕ ฝากเงิน",
        "withdraw_btn": "💸 ถอนเงิน",
        "withdraw_title": "💸 <b>ถอนเงิน</b>",
        "withdraw_text": (
            "วิธีถอนยอดคงเหลือ:\n\n"
            "1. ติดต่อ <a href='{admin_url}'>{admin}</a>\n"
            "2. แจ้งที่อยู่ BEP20 และจำนวน\n"
            "3. ดำเนินการภายใน 24 ชั่วโมง"
        ),
        "support_title": "🛟 <b>ฝ่ายสนับสนุน</b>",
        "support_text": "👤 แอดมิน: <a href='{admin_url}'>{admin}</a>\n\n⏰ เวลาทำการ: 8 - 22 น. ทุกวัน",
        "language_title": "🌐 <b>เลือกภาษา</b>",
        "lang_changed": "เปลี่ยนภาษาเป็นภาษาไทย!",
        "out_of_stock_alert": "สินค้าหมด!",
        "enter_qty": "ป้อนจำนวน (1-{max}):\n\n💵 ยอดของคุณ: <b>${balance:.2f} USDT</b>",
        "invalid_qty": "จำนวนไม่ถูกต้อง กรุณาป้อนตัวเลขระหว่าง 1 ถึง {max}",
        "insufficient_balance": "ยอดไม่เพียงพอ! คุณต้องการ ${needed:.2f} USDT แต่มี ${balance:.2f} USDT\nกรุณาฝากเงินก่อน",
        "waiting_payment": "⏳ <b>รอการชำระเงิน...</b>",
        "payment_expired": "การชำระเงินหมดเวลา กรุณาลองใหม่",
        "deposit_info_title": "💵 <b>ข้อมูลฝาก USDT</b>",
        "deposit_info_amount": "จ��นวน",
        "deposit_info_code": "รหัส",
        "option1_title": "🔶 ตัวเลือก 1: BINANCE PAY (ทันที, ฟรี)",
        "option1_binance_id": "Binance ID",
        "option1_amount": "จำนวน",
        "option1_note": "หมายเหตุ",
        "option1_steps": "B. Binance → Pay → Send → วาง ID ด้านบน\n⚠️ หมายเหตุต้องถูกต้องทุกต��วอักษร!",
        "option2_title": "🔷 ตัวเลือก 2: โอนกระเป๋า (BEP20)",
        "option2_address": "ที่อยู่",
        "option2_network": "เครือข่าย: <b>BEP20</b>",
        "option2_amount": "จำนวน",
        "option2_warning": "⚠️ ส่งจำนวนนี้เท่านั้น!\n⚠️ ใช้เครือข่าย <b>BEP20</b> เท่านั้น!",
        "auto_detect": "⏱ ตรวจจับอัตโนมัติภายใน 1-2 นาที\nคุณจะได้รับแจ้งเมื่อเงินเข้า!",
        "auto_detect_buy": "⏱ ตรวจจับอัตโนมัติภายใน 1-2 นาที\nสินค้าจะถูกส่งอัตโนมัติ!\n⏰ การชำระเงินหมดอายุ���น 10 นาที",
        "cancel_payment": "❌ ยกเลิก",
        "btn_shop": "🛒 ร้านค้า",
        "btn_profile": "👤 โปรไฟล์",
        "btn_history": "📜 ประวัติ",
        "btn_wallet": "💰 กระเป๋า",
        "btn_support": "🛟 สนับสนุน",
        "btn_language": "🌐 ภาษา",
    },
    "zh": {
        "welcome": (
            "🔥 <b>欢迎来到 SukoShop — 自动订购机器人</b>\n\n"
            "👋 你好, <b>{name}</b>!\n\n"
            "📌 快速指南:\n"
            "1. 点击<b>商店</b>浏览商品。\n"
            "2. 选择您想要的商品。\n"
            "3. 通过 Binance Pay 或 BEP20 付款。\n"
            "4. 付款后机器人自动发货。\n\n"
            "请选择一个选项:"
        ),
        "choose_option": "请选择一个选项:",
        "shop_title": "🛒 <b>商店</b>\n\n选择商品:",
        "in_stock": "有库存",
        "out_of_stock": "缺货",
        "back": "⬅️ 返回",
        "back_to_shop": "⬅️ 返回商店",
        "back_to_wallet": "⬅️ 返回钱包",
        "buy_now": "💳 立即购买",
        "profile_title": "👤 <b>个人资料</b>",
        "user_id": "用户ID",
        "name_label": "姓名",
        "balance_label": "余额",
        "referral_label": "推荐链接",
        "referral_desc": "分享您的链接并赚取佣金！",
        "history_title": "📜 <b>订单历史</b>",
        "no_orders": "📜 您还没有订单。",
        "wallet_title": "💰 <b>钱包</b>",
        "usdt_balance": "USDT余额",
        "deposit_btn": "➕ 充值",
        "withdraw_btn": "💸 提现",
        "withdraw_title": "💸 <b>提现</b>",
        "withdraw_text": (
            "提取余额:\n\n"
            "1. 联系 <a href='{admin_url}'>{admin}</a>\n"
            "2. 发送您的 BEP20 地址和金额\n"
            "3. 24小时内处理"
        ),
        "support_title": "🛟 <b>客服支持</b>",
        "support_text": "👤 管理员: <a href='{admin_url}'>{admin}</a>\n\n⏰ 工作时间: 每天 8 - 22 点",
        "language_title": "🌐 <b>选择语言</b>",
        "lang_changed": "语言已更改为中文！",
        "out_of_stock_alert": "缺货！",
        "enter_qty": "输入数量 (1-{max}):\n\n💵 您的余额: <b>${balance:.2f} USDT</b>",
        "invalid_qty": "数量无效，请输入 1 到 {max} 之间的数字。",
        "insufficient_balance": "余额不足！您需要 ${needed:.2f} USDT，但只有 ${balance:.2f} USDT。\n请先充值。",
        "waiting_payment": "⏳ <b>等待付款...</b>",
        "payment_expired": "付款已过期，请重试。",
        "deposit_info_title": "💵 <b>USDT 充值信息</b>",
        "deposit_info_amount": "金额",
        "deposit_info_code": "代码",
        "option1_title": "🔶 选项 1: BINANCE PAY (即时, 免费)",
        "option1_binance_id": "Binance ID",
        "option1_amount": "金额",
        "option1_note": "备注",
        "option1_steps": "B. Binance → Pay → Send → 粘贴上方ID\n⚠️ 备注必须完全一致!",
        "option2_title": "🔷 选项 2: 钱包转账 (BEP20)",
        "option2_address": "地址",
        "option2_network": "网络: <b>BEP20</b>",
        "option2_amount": "金额",
        "option2_warning": "⚠️ 必须发送准确金额!\n⚠️ 只使用 <b>BEP20</b> 网络!",
        "auto_detect": "⏱ 1-2分钟内自动检测。\n资金到账后将通知您！",
        "auto_detect_buy": "⏱ 1-2分钟内自动检测。\n产品将自动发送！\n⏰ 付款将在10分钟后过期。",
        "cancel_payment": "❌ 取消",
        "btn_shop": "🛒 商店",
        "btn_profile": "👤 个人资料",
        "btn_history": "📜 订单历史",
        "btn_wallet": "💰 钱包",
        "btn_support": "🛟 客服",
        "btn_language": "🌐 语言",
    },
    "es": {
        "welcome": (
            "🔥 <b>Bienvenido a SukoShop — Bot de Pedido Automático</b>\n\n"
            "👋 Hola, <b>{name}</b>!\n\n"
            "📌 Guía rápida:\n"
            "1. Haz clic en <b>Tienda</b> para ver productos.\n"
            "2. Elige el producto que deseas.\n"
            "3. Paga via Binance Pay o billetera BEP20.\n"
            "4. Tras el pago el bot entrega automáticamente.\n\n"
            "Elige una opción:"
        ),
        "choose_option": "Elige una opción:",
        "shop_title": "🛒 <b>TIENDA</b>\n\nElige un producto:",
        "in_stock": "En Stock",
        "out_of_stock": "Sin Stock",
        "back": "⬅️ Volver",
        "back_to_shop": "⬅️ Volver a la Tienda",
        "back_to_wallet": "⬅️ Volver a la Billetera",
        "buy_now": "💳 Comprar Ahora",
        "profile_title": "👤 <b>PERFIL</b>",
        "user_id": "ID de Usuario",
        "name_label": "Nombre",
        "balance_label": "Saldo",
        "referral_label": "Link de Referido",
        "referral_desc": "Comparte tu link y gana comisión!",
        "history_title": "📜 <b>HISTORIAL DE PEDIDOS</b>",
        "no_orders": "📜 Aún no tienes pedidos.",
        "wallet_title": "💰 <b>BILLETERA</b>",
        "usdt_balance": "Saldo USDT",
        "deposit_btn": "➕ Depositar",
        "withdraw_btn": "💸 Retirar",
        "withdraw_title": "💸 <b>RETIRO</b>",
        "withdraw_text": (
            "Para retirar tu saldo:\n\n"
            "1. Contacta <a href='{admin_url}'>{admin}</a>\n"
            "2. Envía tu dirección BEP20 y monto\n"
            "3. El retiro se procesa en 24h"
        ),
        "support_title": "🛟 <b>SOPORTE</b>",
        "support_text": "👤 Admin: <a href='{admin_url}'>{admin}</a>\n\n⏰ Horario: 8h - 22h todos los días",
        "language_title": "🌐 <b>Elegir Idioma</b>",
        "lang_changed": "Idioma cambiado a Español!",
        "out_of_stock_alert": "Sin stock!",
        "enter_qty": "Ingresa cantidad (1-{max}):\n\n💵 Tu saldo: <b>${balance:.2f} USDT</b>",
        "invalid_qty": "Cantidad inválida. Ingresa un número entre 1 y {max}.",
        "insufficient_balance": "Saldo insuficiente! Necesitas ${needed:.2f} USDT pero tienes ${balance:.2f} USDT.\nDeposita primero.",
        "waiting_payment": "⏳ <b>ESPERANDO PAGO...</b>",
        "payment_expired": "Pago expirado. Intenta de nuevo.",
        "deposit_info_title": "💵 <b>INFO DE DEPÓSITO USDT</b>",
        "deposit_info_amount": "Monto",
        "deposit_info_code": "Código",
        "option1_title": "🔶 OPCIÓN 1: BINANCE PAY (Instantáneo, Gratis)",
        "option1_binance_id": "Binance ID",
        "option1_amount": "Monto",
        "option1_note": "Nota",
        "option1_steps": "B. Binance → Pay → Send → pega el ID arriba\n⚠️ La nota DEBE ser exacta!",
        "option2_title": "🔷 OPCIÓN 2: TRANSFERENCIA BILLETERA (BEP20)",
        "option2_address": "Dirección",
        "option2_network": "Red: <b>BEP20</b>",
        "option2_amount": "Monto",
        "option2_warning": "⚠️ Envía EXACTAMENTE este monto!\n⚠️ Usa red <b>BEP20</b> SOLO!",
        "auto_detect": "⏱ Detección automática en 1-2 minutos.\nSe te notificará cuando los fondos se añadan!",
        "auto_detect_buy": "⏱ Detección automática en 1-2 minutos.\nEl producto se entregará automáticamente!\n⏰ El pago expira en 10 minutos.",
        "cancel_payment": "❌ Cancelar",
        "btn_shop": "🛒 Tienda",
        "btn_profile": "👤 Perfil",
        "btn_history": "📜 Historial",
        "btn_wallet": "💰 Billetera",
        "btn_support": "🛟 Soporte",
        "btn_language": "🌐 Idioma",
    },
}

# ================== PRODUCTS ==================
# Seed data — only used to populate the Neon `products` table on first run.
# After that, products live in the database and are managed via the admin panel.
SEED_PRODUCTS = [
    {
        "id": "1", "name": "Grok Super 3M (FW)", "price": 12.0, "stock": 39,
        "emoji": "🤖", "category": "AI Assistants",
        "description": (
            "✅ Full warranty 3 months\n"
            "✅ Works on any account\n"
            "✅ No credit card needed\n"
            "✅ 24h replacement guarantee\n"
            "✅ Instant delivery after payment"
        ),
    },
    {
        "id": "2", "name": "Grok Super 6M (FW)", "price": 19.0, "stock": 3,
        "emoji": "🤖", "category": "AI Assistants",
        "description": (
            "✅ Full warranty 6 months\n"
            "✅ Works on any account\n"
            "✅ No credit card needed\n"
            "✅ 24h replacement guarantee\n"
            "✅ Instant delivery after payment"
        ),
    },
    {
        "id": "3", "name": "Gemini Pro 18M", "price": 1.5, "stock": 53,
        "emoji": "✨", "category": "AI Assistants",
        "description": (
            "✅ 24 hours holding warranty\n"
            "✅ Click on the link and confirm\n"
            "✅ No credit card needed\n"
            "✅ Can be used on any account\n"
            "✅ Can invite 5 more members to family\n"
            "✅ Instant delivery after payment"
        ),
    },
    {
        "id": "4", "name": "Capcut Pro Team 1M (FW)", "price": 2.5, "stock": 30,
        "emoji": "🎬", "category": "Creative",
        "description": (
            "✅ Full Date warranty\n"
            "✅ Works on all devices\n"
            "✅ No credit card needed\n"
            "✅ 30 days replacement guarantee\n"
            "✅ Instant delivery after payment"
        ),
    },
    {
        "id": "5", "name": "ChatGPT Plus 1M (NW)", "price": 2.0, "stock": 0,
        "emoji": "💬", "category": "AI Assistants",
        "description": (
            "• High quality shared account\n"
            "• Instant delivery after payment\n"
            "• No warranty — sold as is"
        ),
    },
    {
        "id": "6", "name": "Adobe Creative Cloud 1M (NW)", "price": 0.5, "stock": 0,
        "emoji": "🎨", "category": "Creative",
        "description": (
            "• Full Creative Cloud access\n"
            "• All Adobe apps included\n"
            "• No warranty — sold as is"
        ),
    },
    {
        "id": "7", "name": "ElevenLabs 3M (FW)", "price": 15.0, "stock": 0,
        "emoji": "🎙️", "category": "AI Tools",
        "description": (
            "✅ Premium voice AI access\n"
            "✅ Full warranty 3 months\n"
            "✅ No credit card needed\n"
            "✅ Instant delivery after payment"
        ),
    },
]

# Tracks users waiting to type qty: {user_id: {"product_id": str, "message_id": int}}
awaiting_qty = {}
# Tracks admin multi-step flows: {user_id: {"action": str, "step": str, "data": {...}}}
admin_state = {}

# ================== HELPERS ==================
def t(user_id: int, key: str, **kwargs) -> str:
    user = get_user(user_id)
    lang = user.get("lang", "en")
    strings = LANGS.get(lang, LANGS["en"])
    text = strings.get(key, LANGS["en"].get(key, key))
    return text.format(admin=ADMIN, admin_url=ADMIN_URL, **kwargs)

def main_menu_kb(user_id: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=t(user_id, "btn_shop"), callback_data="shop")],
        [
            InlineKeyboardButton(text=t(user_id, "btn_profile"), callback_data="profile"),
            InlineKeyboardButton(text=t(user_id, "btn_history"), callback_data="history"),
        ],
        [InlineKeyboardButton(text=t(user_id, "btn_wallet"), callback_data="wallet")],
        [
            InlineKeyboardButton(text=t(user_id, "btn_support"), callback_data="support"),
            InlineKeyboardButton(text=t(user_id, "btn_language"), callback_data="language"),
        ],
    ]
    if is_admin(user_id):
        rows.append([InlineKeyboardButton(text="🛠 Admin Panel", callback_data="admin")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

async def product_detail_text(uid: int, p: dict) -> str:
    """Build the product detail message dynamically from DB fields.
    The description is auto-translated to the user's language."""
    if p["stock"] > 0:
        stock_line = f"📦 {t(uid, 'in_stock')}: {p['stock']}"
    else:
        stock_line = f"📦 {t(uid, 'out_of_stock')}"
    body = (p.get("description") or "").strip()
    if body:
        lang = get_user(uid).get("lang", "en")
        body = await translate_text(body, lang)
    lines = [
        f"{p['emoji']} <b>{p['name']}</b>",
        "",
        f"💵 {t(uid, 'deposit_info_amount')}: <b>${p['price']:.2f} USDT</b>",
        stock_line,
    ]
    if body:
        lines.append("")
        lines.append(html.escape(body))
    return "\n".join(lines)

def build_manual_message(p: dict, qty: int, order_code: str) -> str:
    """Pre-filled message the buyer copies and sends to the seller's DM."""
    template = (p.get("manual_msg") or "").strip()
    if template:
        try:
            return template.format(product=p["name"], qty=qty, code=order_code, price=p["price"])
        except Exception:
            return template
    return (
        f"Olá! Acabei de comprar: {p['name']} (x{qty}).\n"
        f"Pedido: {order_code}.\n"
        f"Aguardo a entrega, obrigado!"
    )

async def deliver_product(uid: int, p: dict, qty: int, order_code: str, total: float):
    """Deliver a purchased product to the buyer based on its delivery type."""
    pid = p["id"]
    header = (
        f"✅ <b>{t(uid, 'order_confirmed_title')}</b>\n\n"
        f"📦 {t(uid, 'product_label')}: <b>{html.escape(p['name'])}</b>\n"
        f"🔢 {t(uid, 'qty_label')}: <b>{qty}</b>\n"
        f"💵 {t(uid, 'total_label')}: <b>${total:.2f} USDT</b>\n"
        f"🔖 {t(uid, 'order_code_label')}: <code>{order_code}</code>"
    )

    if p.get("delivery_type") == "auto":
        items = pop_stock_items(pid, qty)
        if items:
            body = "\n".join(f"<code>{html.escape(it)}</code>" for it in items)
            text = f"{header}\n\n🎁 <b>{t(uid, 'your_items')}</b>\n{body}"
            if len(items) < qty:
                # Not enough stock — deliver what we have, escalate the rest
                missing = qty - len(items)
                text += f"\n\n⚠️ {t(uid, 'partial_delivery', missing=missing, admin=ADMIN)}"
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=t(uid, "back"), callback_data="main_menu")]
            ])
            await bot.send_message(uid, text, parse_mode="HTML", reply_markup=kb)
            return
        # No items available at all -> fall through to manual escalation
        text = f"{header}\n\n⏳ {t(uid, 'await_manual', admin=ADMIN)}"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t(uid, "contact_seller"), url=ADMIN_URL)],
            [InlineKeyboardButton(text=t(uid, "back"), callback_data="main_menu")],
        ])
        await bot.send_message(uid, text, parse_mode="HTML", reply_markup=kb)
        return

    # Manual delivery
    prefilled = build_manual_message(p, qty, order_code)
    text = (
        f"{header}\n\n"
        f"🤝 {t(uid, 'manual_instructions', admin=ADMIN)}\n\n"
        f"📋 {t(uid, 'copy_message')}\n"
        f"<code>{html.escape(prefilled)}</code>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(uid, "contact_seller"), url=ADMIN_URL)],
        [InlineKeyboardButton(text=t(uid, "back"), callback_data="main_menu")],
    ])
    await bot.send_message(uid, text, parse_mode="HTML", reply_markup=kb)

def build_payment_message(uid: int, amount: float, code: str, bep20_amount: float, binance_amount: float, is_deposit: bool = True) -> str:
    lines = []

    if is_deposit:
        lines.append(t(uid, "deposit_info_title"))
        lines.append("")
        lines.append(f"💵 {t(uid, 'deposit_info_amount')}: <b>{amount} USDT</b>")
        lines.append(f"🔖 {t(uid, 'deposit_info_code')}: <code>{code}</code>")
    else:
        lines.append(t(uid, "waiting_payment"))

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"🔶 <b>{t(uid, 'option1_title')}</b>")
    lines.append("")
    lines.append(f"🆔 {t(uid, 'option1_binance_id')}:")
    lines.append(f"<code>{BINANCE_ID}</code>")
    lines.append(f"💵 {t(uid, 'option1_amount')}:")
    lines.append(f"<code>{binance_amount}</code>")
    lines.append(f"📝 {t(uid, 'option1_note')}:")
    lines.append(f"<code>{code}</code>")
    lines.append("")
    lines.append(t(uid, "option1_steps"))
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"🔷 <b>{t(uid, 'option2_title')}</b>")
    lines.append("")
    lines.append(f"📍 {t(uid, 'option2_address')}:")
    lines.append(f"<code>{BEP20_ADDRESS}</code>")
    lines.append(f"🔗 {t(uid, 'option2_network')}")
    lines.append(f"💵 {t(uid, 'option2_amount')}:")
    lines.append(f"<code>{bep20_amount}</code>")
    lines.append("")
    lines.append(t(uid, "option2_warning"))
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    if is_deposit:
        lines.append(t(uid, "auto_detect"))
    else:
        lines.append(t(uid, "auto_detect_buy"))

    return "\n".join(lines)

# ================== HANDLERS ==================

@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    user = get_user(message.from_user.id, message.from_user.first_name)
    await message.answer(
        t(message.from_user.id, "welcome", name=user["name"]),
        reply_markup=main_menu_kb(message.from_user.id),
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "main_menu")
async def back_to_main(callback: types.CallbackQuery):
    uid = callback.from_user.id
    get_user(uid)
    awaiting_qty.pop(uid, None)
    await callback.message.edit_text(
        t(uid, "choose_option"),
        reply_markup=main_menu_kb(uid),
        parse_mode="HTML"
    )

# ---------- SHOP ----------
@dp.callback_query(F.data == "shop")
async def shop_menu(callback: types.CallbackQuery):
    uid = callback.from_user.id
    get_user(uid)
    all_products = get_all_products(active_only=True)
    kb = []
    # Group by category (uncategorized products go under "Other" at the end)
    categories = get_categories()
    grouped = {cat: [] for cat in categories}
    other = []
    for p in all_products:
        cat = (p.get("category") or "").strip()
        if cat in grouped:
            grouped[cat].append(p)
        else:
            other.append(p)

    def add_product_button(p):
        if p["stock"] > 0:
            label = f"{p['emoji']} {p['name']} — ${p['price']:.2f} ({t(uid, 'in_stock')} {p['stock']})"
        else:
            label = f"🔴 {p['name']} — ${p['price']:.2f} ({t(uid, 'out_of_stock')})"
        kb.append([InlineKeyboardButton(text=label, callback_data=f"product_{p['id']}")])

    for cat in categories:
        if grouped[cat]:
            kb.append([InlineKeyboardButton(text=f"📂 {cat}", callback_data="noop")])
            for p in grouped[cat]:
                add_product_button(p)
    if other:
        if categories:
            kb.append([InlineKeyboardButton(text="📂 Other", callback_data="noop")])
        for p in other:
            add_product_button(p)

    if not all_products:
        kb.append([InlineKeyboardButton(text="— empty —", callback_data="noop")])
    kb.append([InlineKeyboardButton(text="🔄 Refresh", callback_data="shop")])
    kb.append([InlineKeyboardButton(text=t(uid, "back"), callback_data="main_menu")])
    await callback.message.edit_text(
        t(uid, "shop_title"),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb),
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "noop")
async def noop_handler(callback: types.CallbackQuery):
    await callback.answer()

@dp.callback_query(F.data.startswith("product_"))
async def show_product(callback: types.CallbackQuery):
    uid = callback.from_user.id
    get_user(uid)
    pid = callback.data.split("_", 1)[1]
    p = get_product(pid)
    if not p:
        await callback.answer("Product not found.", show_alert=True)
        return
    kb = []
    if p["stock"] > 0:
        kb.append([InlineKeyboardButton(text=t(uid, "buy_now"), callback_data=f"buy_{pid}")])
    kb.append([InlineKeyboardButton(text=t(uid, "back_to_shop"), callback_data="shop")])
    detail = await product_detail_text(uid, p)
    await callback.message.edit_text(
        detail,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb),
        parse_mode="HTML"
    )

@dp.callback_query(F.data.startswith("buy_"))
async def buy_product(callback: types.CallbackQuery):
    uid = callback.from_user.id
    pid = callback.data.split("_", 1)[1]
    p = get_product(pid)
    user = get_user(uid)

    if not p or p["stock"] <= 0:
        await callback.answer(t(uid, "out_of_stock_alert"), show_alert=True)
        return

    awaiting_qty[uid] = {"product_id": pid, "message_id": callback.message.message_id}

    await callback.message.edit_text(
        t(uid, "enter_qty", max=p["stock"], balance=user["balance"]),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t(uid, "back_to_shop"), callback_data="shop")]
        ])
    )

@dp.message(F.text)
async def handle_text(message: types.Message):
    uid = message.from_user.id

    # Admin multi-step flows take priority
    if await handle_admin_text(message):
        return

    if uid not in awaiting_qty:
        return

    info = awaiting_qty[uid]
    pid = info["product_id"]

    # ----- DEPOSIT amount input -----
    if pid == "__deposit__":
        try:
            amount = float(message.text.strip().replace(",", "."))
            if amount <= 0:
                raise ValueError
        except ValueError:
            await message.reply(
                "Invalid amount. Please enter a positive number, e.g. <code>5</code> or <code>10.5</code>",
                parse_mode="HTML"
            )
            return

        awaiting_qty.pop(uid, None)
        amount = round(amount, 4)
        code = generate_code("BN")
        bep20_amount = generate_unique_bep20(amount)
        binance_amount = generate_unique_binance(amount)
        expires_at = (datetime.now() + timedelta(hours=24)).strftime("%Y-%m-%d %H:%M")
        save_pending_payment(code, uid, "__deposit__", 1, amount, "deposit", expires_at, bep20_amount, binance_amount)

        text = build_payment_message(uid, amount, code, bep20_amount, binance_amount, is_deposit=True)
        await message.answer(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=t(uid, "back_to_wallet"), callback_data="wallet")]
            ])
        )
        return

    # ----- BUY quantity input -----
    p = get_product(pid)
    if not p:
        awaiting_qty.pop(uid, None)
        return

    try:
        qty = int(message.text.strip())
        if qty < 1 or qty > p["stock"]:
            raise ValueError
    except ValueError:
        await message.reply(
            t(uid, "invalid_qty", max=p["stock"]),
            parse_mode="HTML"
        )
        return

    awaiting_qty.pop(uid, None)

    user = get_user(uid)
    total = round(p["price"] * qty, 4)

    if user["balance"] >= total:
        # Pay from balance directly
        update_balance(uid, -total)
        order_code = generate_code("ORD")
        add_order(uid, order_code, p["name"], total, qty, "Paid")
        # Auto products manage stock via the item pool; manual decrements the counter.
        if p.get("delivery_type") != "auto":
            decrement_stock(pid, qty)
        await deliver_product(uid, p, qty, order_code, total)
    else:
        # Not enough balance — show payment screen
        code = generate_code("BUY")
        bep20_amount = generate_unique_bep20(total)
        binance_amount = generate_unique_binance(total)
        expires_at = (datetime.now() + timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M")
        save_pending_payment(code, uid, pid, qty, total, "buy", expires_at, bep20_amount, binance_amount)

        text = (
            f"{t(uid, 'waiting_payment')}\n\n"
            f"📦 Product: <b>{p['name']}</b>\n"
            f"🔢 Quantity: <b>{qty}</b>\n"
            f"💵 Total: <b>${total:.4f} USDT</b>\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🔶 <b>{t(uid, 'option1_title')}</b>\n\n"
            f"🆔 {t(uid, 'option1_binance_id')}:\n"
            f"<code>{BINANCE_ID}</code>\n"
            f"💵 {t(uid, 'option1_amount')}:\n"
            f"<code>{binance_amount}</code>\n"
            f"📝 {t(uid, 'option1_note')}:\n"
            f"<code>{code}</code>\n\n"
            f"{t(uid, 'option1_steps')}\n\n"
            f"━━━━━━━━━━━━━━━��━━━━\n"
            f"🔷 <b>{t(uid, 'option2_title')}</b>\n\n"
            f"📍 {t(uid, 'option2_address')}:\n"
            f"<code>{BEP20_ADDRESS}</code>\n"
            f"🔗 {t(uid, 'option2_network')}\n"
            f"💵 {t(uid, 'option2_amount')}:\n"
            f"<code>{bep20_amount}</code>\n\n"
            f"{t(uid, 'option2_warning')}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"{t(uid, 'auto_detect_buy')}"
        )
        await message.answer(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=t(uid, "cancel_payment"), callback_data="main_menu")]
            ])
        )

# ---------- PROFILE ----------
@dp.callback_query(F.data == "profile")
async def profile_menu(callback: types.CallbackQuery):
    uid = callback.from_user.id
    user = get_user(uid)
    text = (
        f"{t(uid, 'profile_title')}\n\n"
        f"🆔 {t(uid, 'user_id')}: <code>{uid}</code>\n"
        f"👤 {t(uid, 'name_label')}: <b>{user['name']}</b>\n"
        f"💰 {t(uid, 'balance_label')}: <b>${user['balance']:.2f} USDT</b>\n\n"
        f"🔗 {t(uid, 'referral_label')}:\n"
        f"<code>{user['referral']}</code>\n\n"
        f"{t(uid, 'referral_desc')}"
    )
    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t(uid, "back"), callback_data="main_menu")]
        ])
    )

# ---------- ORDER HISTORY ----------
@dp.callback_query(F.data == "history")
async def order_history(callback: types.CallbackQuery):
    uid = callback.from_user.id
    orders = get_orders(uid)
    if not orders:
        text = t(uid, "no_orders")
    else:
        text = f"{t(uid, 'history_title')}\n\n"
        for row in orders:
            code, name, price, qty, status, created_at = row
            text += f"• <code>{code}</code> | {name} x{qty} | ${price:.2f} | {status} | {created_at}\n"
    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t(uid, "back"), callback_data="main_menu")]
        ])
    )

# ---------- WALLET ----------
@dp.callback_query(F.data == "wallet")
async def wallet_menu(callback: types.CallbackQuery):
    uid = callback.from_user.id
    user = get_user(uid)
    text = (
        f"{t(uid, 'wallet_title')}\n\n"
        f"💵 {t(uid, 'usdt_balance')}: <b>${user['balance']:.2f}</b>"
    )
    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text=t(uid, "deposit_btn"), callback_data="deposit"),
                InlineKeyboardButton(text=t(uid, "withdraw_btn"), callback_data="withdraw"),
            ],
            [InlineKeyboardButton(text=t(uid, "back"), callback_data="main_menu")]
        ])
    )

@dp.callback_query(F.data == "deposit")
async def deposit_menu(callback: types.CallbackQuery):
    uid = callback.from_user.id
    get_user(uid)

    # Ask for amount
    awaiting_qty[uid] = {"product_id": "__deposit__", "message_id": callback.message.message_id}
    await callback.message.edit_text(
        "💵 <b>DEPOSIT USDT</b>\n\nEnter the amount you want to deposit (e.g. <code>5</code> or <code>10.5</code>):",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t(uid, "back_to_wallet"), callback_data="wallet")]
        ])
    )

@dp.callback_query(F.data == "withdraw")
async def withdraw_info(callback: types.CallbackQuery):
    uid = callback.from_user.id
    get_user(uid)
    await callback.message.edit_text(
        t(uid, "withdraw_title") + "\n\n" + t(uid, "withdraw_text"),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t(uid, "back_to_wallet"), callback_data="wallet")]
        ])
    )

# ---------- SUPPORT ----------
@dp.callback_query(F.data == "support")
async def support_menu(callback: types.CallbackQuery):
    uid = callback.from_user.id
    get_user(uid)
    await callback.message.edit_text(
        t(uid, "support_title") + "\n\n" + t(uid, "support_text"),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t(uid, "back"), callback_data="main_menu")]
        ])
    )

# ---------- LANGUAGE ----------
@dp.callback_query(F.data == "language")
async def language_menu(callback: types.CallbackQuery):
    uid = callback.from_user.id
    get_user(uid)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇬🇧 English", callback_data="lang_en")],
        [InlineKeyboardButton(text="🇧🇷 Português (Brasil)", callback_data="lang_pt")],
        [InlineKeyboardButton(text="🇮🇩 Bahasa Indonesia", callback_data="lang_id")],
        [InlineKeyboardButton(text="🇮🇳 हिंदी (Hindi)", callback_data="lang_hi")],
        [InlineKeyboardButton(text="🇹🇭 ภาษาไทย (Thai)", callback_data="lang_th")],
        [InlineKeyboardButton(text="🇨🇳 中文 (Chinese)", callback_data="lang_zh")],
        [InlineKeyboardButton(text="🇪🇸 Español", callback_data="lang_es")],
        [InlineKeyboardButton(text=t(uid, "back"), callback_data="main_menu")]
    ])
    await callback.message.edit_text(t(uid, "language_title"), reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data.startswith("lang_"))
async def change_lang(callback: types.CallbackQuery):
    uid = callback.from_user.id
    get_user(uid)
    lang = callback.data.split("_")[1]
    if lang in LANGS:
        set_user_lang(uid, lang)
    await callback.answer(t(uid, "lang_changed"), show_alert=True)
    await callback.message.edit_text(
        t(uid, "choose_option"),
        reply_markup=main_menu_kb(uid),
        parse_mode="HTML"
    )

# ================== ADMIN PANEL ==================
def admin_main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 Produtos", callback_data="admin_products")],
        [InlineKeyboardButton(text="📢 Aviso para todos", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="💰 Ajustar saldo", callback_data="admin_balance")],
        [InlineKeyboardButton(text="📊 Estatísticas", callback_data="admin_stats")],
        [InlineKeyboardButton(text="⬅️ Voltar ao menu", callback_data="main_menu")],
    ])

ADMIN_HOME_TEXT = (
    "🛠 <b>PAINEL ADMIN</b>\n\n"
    "Gerencie sua loja por aqui:\n"
    "• 📦 Produtos — adicionar, editar (nome, preço, estoque, descrição, categoria) e remover\n"
    "• 📢 Aviso — enviar mensagem para todos os usuários\n"
    "• 💰 Saldo — creditar/debitar saldo de um usuário\n"
    "• 📊 Estatísticas — visão geral da loja\n\n"
    "Escolha uma opção:"
)

async def show_admin_home(message_or_cb, edit: bool):
    if edit:
        await message_or_cb.message.edit_text(ADMIN_HOME_TEXT, reply_markup=admin_main_kb(), parse_mode="HTML")
    else:
        await message_or_cb.answer(ADMIN_HOME_TEXT, reply_markup=admin_main_kb(), parse_mode="HTML")

@dp.message(Command("admin"))
async def admin_cmd(message: types.Message):
    uid = message.from_user.id
    if not is_admin(uid):
        return
    admin_state.pop(uid, None)
    await show_admin_home(message, edit=False)

@dp.callback_query(F.data == "admin")
async def admin_home(callback: types.CallbackQuery):
    uid = callback.from_user.id
    if not is_admin(uid):
        await callback.answer("Acesso negado.", show_alert=True)
        return
    admin_state.pop(uid, None)
    await show_admin_home(callback, edit=True)

# ---------- ADMIN: PRODUCTS ----------
@dp.callback_query(F.data == "admin_products")
async def admin_products(callback: types.CallbackQuery):
    uid = callback.from_user.id
    if not is_admin(uid):
        await callback.answer("Acesso negado.", show_alert=True)
        return
    admin_state.pop(uid, None)
    prods = get_all_products()
    kb = [[InlineKeyboardButton(text="➕ Adicionar produto", callback_data="admin_addprod")]]
    for p in prods:
        status = "🟢" if p["active"] and p["stock"] > 0 else ("🟡" if p["active"] else "⚪️")
        kb.append([InlineKeyboardButton(
            text=f"{status} {p['emoji']} {p['name']} — ${p['price']:.2f} (x{p['stock']})",
            callback_data=f"admin_prod_{p['id']}"
        )])
    kb.append([InlineKeyboardButton(text="⬅️ Voltar", callback_data="admin")])
    await callback.message.edit_text(
        "📦 <b>PRODUTOS</b>\n\n🟢 ativo c/ estoque · 🟡 ativo s/ estoque · ⚪️ inativo\n\nSelecione um produto para editar:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML"
    )

def admin_product_kb(p: dict) -> InlineKeyboardMarkup:
    pid = p["id"]
    is_auto = p.get("delivery_type") == "auto"
    rows = [
        [
            InlineKeyboardButton(text="✏️ Nome", callback_data=f"admin_edit_name_{pid}"),
            InlineKeyboardButton(text="💵 Preço", callback_data=f"admin_edit_price_{pid}"),
        ],
    ]
    # Stock row: auto products manage stock via the item pool
    if is_auto:
        rows.append([
            InlineKeyboardButton(text="📥 Itens (estoque)", callback_data=f"admin_items_{pid}"),
            InlineKeyboardButton(text="😀 Emoji", callback_data=f"admin_edit_emoji_{pid}"),
        ])
    else:
        rows.append([
            InlineKeyboardButton(text="📦 Estoque", callback_data=f"admin_edit_stock_{pid}"),
            InlineKeyboardButton(text="😀 Emoji", callback_data=f"admin_edit_emoji_{pid}"),
        ])
    rows.append([
        InlineKeyboardButton(text="🗂 Categoria", callback_data=f"admin_edit_category_{pid}"),
        InlineKeyboardButton(text="📝 Descrição", callback_data=f"admin_edit_description_{pid}"),
    ])
    # Delivery type toggle
    rows.append([InlineKeyboardButton(
        text=("🚚 Entrega: AUTOMÁTICA ▸ trocar p/ manual" if is_auto
              else "🚚 Entrega: MANUAL ▸ trocar p/ automática"),
        callback_data=f"admin_delivery_{pid}"
    )])
    if not is_auto:
        rows.append([InlineKeyboardButton(text="✉️ Mensagem de entrega (manual)",
                                          callback_data=f"admin_edit_manualmsg_{pid}")])
    rows.append([InlineKeyboardButton(
        text="🚫 Desativar" if p["active"] else "✅ Ativar",
        callback_data=f"admin_toggle_{pid}"
    )])
    rows.append([InlineKeyboardButton(text="🗑 Remover", callback_data=f"admin_del_{pid}")])
    rows.append([InlineKeyboardButton(text="⬅️ Voltar", callback_data="admin_products")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

async def render_admin_product(target, pid: str, edit: bool):
    p = get_product(pid)
    if not p:
        if edit:
            await target.message.edit_text("Produto não encontrado.", reply_markup=admin_main_kb())
        else:
            await target.answer("Produto não encontrado.", reply_markup=admin_main_kb())
        return
    body = html.escape(p.get("description") or "")
    is_auto = p.get("delivery_type") == "auto"
    if is_auto:
        avail = count_available_items(pid)
        stock_line = f"📦 Itens disponíveis: <b>{avail}</b>"
        delivery_line = "🚚 Entrega: <b>AUTOMÁTICA</b> (entrega itens do estoque)"
    else:
        stock_line = f"📦 Estoque: <b>{p['stock']}</b>"
        delivery_line = "🚚 Entrega: <b>MANUAL</b> (cliente fala no seu privado)"
    text = (
        f"📦 <b>{html.escape(p['name'])}</b>\n\n"
        f"🆔 ID: <code>{p['id']}</code>\n"
        f"{p['emoji']} Emoji\n"
        f"💵 Preço: <b>${p['price']:.2f}</b>\n"
        f"{stock_line}\n"
        f"🗂 Categoria: <b>{html.escape(p.get('category') or '—')}</b>\n"
        f"{delivery_line}\n"
        f"{'🟢 Ativo' if p['active'] else '⚪️ Inativo'}\n\n"
        f"📝 Descrição:\n{body or '—'}"
    )
    kb = admin_product_kb(p)
    if edit:
        await target.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    else:
        await target.answer(text, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data.startswith("admin_prod_"))
async def admin_product_view(callback: types.CallbackQuery):
    uid = callback.from_user.id
    if not is_admin(uid):
        await callback.answer("Acesso negado.", show_alert=True)
        return
    admin_state.pop(uid, None)
    pid = callback.data[len("admin_prod_"):]
    await render_admin_product(callback, pid, edit=True)

@dp.callback_query(F.data.startswith("admin_toggle_"))
async def admin_toggle_product(callback: types.CallbackQuery):
    uid = callback.from_user.id
    if not is_admin(uid):
        await callback.answer("Acesso negado.", show_alert=True)
        return
    pid = callback.data[len("admin_toggle_"):]
    p = get_product(pid)
    if p:
        update_product_field(pid, "active", not p["active"])
    await render_admin_product(callback, pid, edit=True)

@dp.callback_query(F.data.startswith("admin_del_"))
async def admin_delete_confirm(callback: types.CallbackQuery):
    uid = callback.from_user.id
    if not is_admin(uid):
        await callback.answer("Acesso negado.", show_alert=True)
        return
    pid = callback.data[len("admin_del_"):]
    p = get_product(pid)
    name = html.escape(p["name"]) if p else pid
    await callback.message.edit_text(
        f"🗑 Remover <b>{name}</b>?\n\nIsto não pode ser desfeito.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Sim, remover", callback_data=f"admin_delyes_{pid}")],
            [InlineKeyboardButton(text="❌ Cancelar", callback_data=f"admin_prod_{pid}")],
        ])
    )

@dp.callback_query(F.data.startswith("admin_delyes_"))
async def admin_delete_yes(callback: types.CallbackQuery):
    uid = callback.from_user.id
    if not is_admin(uid):
        await callback.answer("Acesso negado.", show_alert=True)
        return
    pid = callback.data[len("admin_delyes_"):]
    delete_product(pid)
    await callback.answer("Produto removido.", show_alert=True)
    await admin_products(callback)

@dp.callback_query(F.data.startswith("admin_delivery_"))
async def admin_toggle_delivery(callback: types.CallbackQuery):
    uid = callback.from_user.id
    if not is_admin(uid):
        await callback.answer("Acesso negado.", show_alert=True)
        return
    pid = callback.data[len("admin_delivery_"):]
    p = get_product(pid)
    if not p:
        await callback.answer("Produto não encontrado.", show_alert=True)
        return
    new_type = "manual" if p.get("delivery_type") == "auto" else "auto"
    update_product_field(pid, "delivery_type", new_type)
    if new_type == "auto":
        # When switching to auto, stock mirrors the item pool
        sync_auto_stock(pid)
        await callback.answer("Entrega automática ativada. Adicione itens ao estoque.", show_alert=True)
    else:
        await callback.answer("Entrega manual ativada.", show_alert=True)
    await render_admin_product(callback, pid, edit=True)

@dp.callback_query(F.data.startswith("admin_items_"))
async def admin_items(callback: types.CallbackQuery):
    uid = callback.from_user.id
    if not is_admin(uid):
        await callback.answer("Acesso negado.", show_alert=True)
        return
    pid = callback.data[len("admin_items_"):]
    p = get_product(pid)
    if not p:
        await callback.answer("Produto não encontrado.", show_alert=True)
        return
    avail = count_available_items(pid)
    await callback.message.edit_text(
        f"📥 <b>ESTOQUE DE ITENS</b>\n\n"
        f"Produto: <b>{html.escape(p['name'])}</b>\n"
        f"Itens disponíveis: <b>{avail}</b>\n\n"
        f"Cada linha que você enviar vira 1 item entregue automaticamente "
        f"(ex: um login:senha, um código, um link). Toque em adicionar para enviar vários de uma vez.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Adicionar itens", callback_data=f"admin_additems_{pid}")],
            [InlineKeyboardButton(text="⬅️ Voltar", callback_data=f"admin_prod_{pid}")],
        ])
    )

@dp.callback_query(F.data.startswith("admin_additems_"))
async def admin_add_items(callback: types.CallbackQuery):
    uid = callback.from_user.id
    if not is_admin(uid):
        await callback.answer("Acesso negado.", show_alert=True)
        return
    pid = callback.data[len("admin_additems_"):]
    admin_state[uid] = {"action": "add_items", "pid": pid}
    await callback.message.edit_text(
        "📥 Envie os itens — <b>um por linha</b>.\n\n"
        "Cada linha será 1 unidade entregue automaticamente após o pagamento.\n"
        "Ex:\n<code>email1@x.com:senha123\nemail2@x.com:senha456</code>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Cancelar", callback_data=f"admin_items_{pid}")]
        ])
    )

EDIT_FIELD_PROMPTS = {
    "name": "✏️ Envie o novo <b>nome</b> do produto:",
    "price": "💵 Envie o novo <b>preço</b> (ex: <code>9.99</code>):",
    "stock": "📦 Envie o novo <b>estoque</b> (número inteiro):",
    "emoji": "😀 Envie o novo <b>emoji</b> do produto:",
    "category": "🗂 Envie a nova <b>categoria</b> (ou <code>-</code> para nenhuma):",
    "description": "📝 Envie a nova <b>descrição</b> (pode ter várias linhas):",
    "manualmsg": (
        "✉️ Envie a <b>mensagem de entrega manual</b> que o cliente vai copiar e te mandar.\n\n"
        "Você pode usar estas variáveis:\n"
        "<code>{product}</code> nome · <code>{qty}</code> quantidade · <code>{code}</code> pedido · <code>{price}</code> preço\n\n"
        "Envie <code>-</code> para usar a mensagem padrão."
    ),
}

# Maps callback field tokens to actual DB columns
FIELD_DB_MAP = {"manualmsg": "manual_msg"}

@dp.callback_query(F.data.startswith("admin_edit_"))
async def admin_edit_field(callback: types.CallbackQuery):
    uid = callback.from_user.id
    if not is_admin(uid):
        await callback.answer("Acesso negado.", show_alert=True)
        return
    rest = callback.data[len("admin_edit_"):]
    field, pid = rest.split("_", 1)
    if field not in EDIT_FIELD_PROMPTS:
        await callback.answer("Campo inválido.", show_alert=True)
        return
    admin_state[uid] = {"action": "edit_field", "field": field, "pid": pid}
    await callback.message.edit_text(
        EDIT_FIELD_PROMPTS[field],
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Cancelar", callback_data=f"admin_prod_{pid}")]
        ])
    )

# ---------- ADMIN: ADD PRODUCT ----------
ADD_STEPS = ["name", "price", "stock", "emoji", "category", "description"]
ADD_PROMPTS = {
    "name": "➕ <b>Novo produto</b>\n\nEnvie o <b>nome</b>:",
    "price": "💵 Envie o <b>preço</b> (ex: <code>9.99</code>):",
    "stock": "📦 Envie o <b>estoque</b> inicial (número inteiro):",
    "emoji": "😀 Envie um <b>emoji</b> (ou <code>-</code> para 📦):",
    "category": "🗂 Envie a <b>categoria</b> (ou <code>-</code> para nenhuma):",
    "description": "📝 Envie a <b>descrição</b> (ou <code>-</code> para vazia):",
}

@dp.callback_query(F.data == "admin_addprod")
async def admin_add_product(callback: types.CallbackQuery):
    uid = callback.from_user.id
    if not is_admin(uid):
        await callback.answer("Acesso negado.", show_alert=True)
        return
    admin_state[uid] = {"action": "add", "step": "name", "data": {}}
    await callback.message.edit_text(
        ADD_PROMPTS["name"], parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Cancelar", callback_data="admin_products")]
        ])
    )

# ---------- ADMIN: BROADCAST ----------
@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_start(callback: types.CallbackQuery):
    uid = callback.from_user.id
    if not is_admin(uid):
        await callback.answer("Acesso negado.", show_alert=True)
        return
    admin_state[uid] = {"action": "broadcast"}
    await callback.message.edit_text(
        "📢 <b>AVISO PARA TODOS</b>\n\nEnvie a mensagem que será enviada a todos os usuários.\n"
        "Você poderá confirmar antes do envio.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Cancelar", callback_data="admin")]
        ])
    )

@dp.callback_query(F.data == "admin_bcast_send")
async def admin_broadcast_send(callback: types.CallbackQuery):
    uid = callback.from_user.id
    if not is_admin(uid):
        await callback.answer("Acesso negado.", show_alert=True)
        return
    st = admin_state.get(uid)
    if not st or st.get("action") != "broadcast" or not st.get("text"):
        await callback.answer("Nada para enviar.", show_alert=True)
        await show_admin_home(callback, edit=True)
        return
    text = st["text"]
    admin_state.pop(uid, None)
    await callback.message.edit_text("📡 Enviando aviso...", parse_mode="HTML")
    user_ids = get_all_user_ids()
    sent, failed = 0, 0
    for target_id in user_ids:
        try:
            await bot.send_message(target_id, text, parse_mode="HTML")
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)  # stay under Telegram rate limits
    await callback.message.answer(
        f"✅ <b>Aviso enviado!</b>\n\n📨 Entregue: {sent}\n⚠️ Falhou: {failed}",
        parse_mode="HTML", reply_markup=admin_main_kb()
    )

# ---------- ADMIN: ADJUST BALANCE ----------
@dp.callback_query(F.data == "admin_balance")
async def admin_balance_start(callback: types.CallbackQuery):
    uid = callback.from_user.id
    if not is_admin(uid):
        await callback.answer("Acesso negado.", show_alert=True)
        return
    admin_state[uid] = {"action": "balance", "step": "uid", "data": {}}
    await callback.message.edit_text(
        "💰 <b>AJUSTAR SALDO</b>\n\nEnvie o <b>ID do usuário</b> (número do Telegram):",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Cancelar", callback_data="admin")]
        ])
    )

# ---------- ADMIN: STATS ----------
@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: types.CallbackQuery):
    uid = callback.from_user.id
    if not is_admin(uid):
        await callback.answer("Acesso negado.", show_alert=True)
        return
    s = get_stats()
    text = (
        "📊 <b>ESTATÍSTICAS</b>\n\n"
        f"👥 Usuários: <b>{s['users']}</b>\n"
        f"💰 Saldo total em circulação: <b>${s['balance_total']:.2f} USDT</b>\n"
        f"✅ Pedidos pagos: <b>{s['paid_orders']}</b>\n"
        f"💵 Receita (pagos): <b>${s['revenue']:.2f} USDT</b>\n"
        f"📦 Produtos ativos: <b>{s['active_products']}</b>\n"
        f"⏳ Pagamentos pendentes: <b>{s['pending']}</b>"
    )
    await callback.message.edit_text(
        text, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Atualizar", callback_data="admin_stats")],
            [InlineKeyboardButton(text="⬅️ Voltar", callback_data="admin")],
        ])
    )

async def handle_admin_text(message: types.Message) -> bool:
    """Process admin multi-step text input. Returns True if it consumed the message."""
    uid = message.from_user.id
    if not is_admin(uid) or uid not in admin_state:
        return False

    st = admin_state[uid]
    action = st.get("action")
    txt = message.text.strip()

    # ----- Edit single product field -----
    if action == "edit_field":
        field, pid = st["field"], st["pid"]
        if not get_product(pid):
            admin_state.pop(uid, None)
            await message.answer("Produto não encontrado.", reply_markup=admin_main_kb())
            return True
        try:
            if field == "price":
                value = round(float(txt.replace(",", ".")), 2)
                if value < 0:
                    raise ValueError
            elif field == "stock":
                value = int(txt)
                if value < 0:
                    raise ValueError
            elif field == "category":
                value = "" if txt == "-" else txt
            elif field == "manualmsg":
                value = "" if txt == "-" else message.text
            elif field == "description":
                value = message.text
            else:
                value = txt
        except ValueError:
            await message.reply("Valor inválido. Tente novamente.")
            return True
        db_field = FIELD_DB_MAP.get(field, field)
        update_product_field(pid, db_field, value)
        admin_state.pop(uid, None)
        await message.answer("✅ Atualizado!")
        await render_admin_product(message, pid, edit=False)
        return True

    # ----- Add auto-delivery stock items (one per line) -----
    if action == "add_items":
        pid = st["pid"]
        if not get_product(pid):
            admin_state.pop(uid, None)
            await message.answer("Produto não encontrado.", reply_markup=admin_main_kb())
            return True
        items = [line.strip() for line in message.text.splitlines() if line.strip()]
        if not items:
            await message.reply("Nenhum item válido. Envie pelo menos uma linha.")
            return True
        total = add_stock_items(pid, items)
        admin_state.pop(uid, None)
        await message.answer(f"✅ {len(items)} item(ns) adicionado(s)!\n📦 Total disponível agora: {total}")
        await render_admin_product(message, pid, edit=False)
        return True

    # ----- Add product flow -----
    if action == "add":
        step = st["step"]
        data = st["data"]
        try:
            if step == "price":
                data["price"] = round(float(txt.replace(",", ".")), 2)
                if data["price"] < 0:
                    raise ValueError
            elif step == "stock":
                data["stock"] = int(txt)
                if data["stock"] < 0:
                    raise ValueError
            elif step == "emoji":
                data["emoji"] = "📦" if txt == "-" else txt
            elif step == "category":
                data["category"] = "" if txt == "-" else txt
            elif step == "description":
                data["description"] = "" if txt == "-" else message.text
            else:  # name
                data["name"] = txt
        except ValueError:
            await message.reply("Valor inválido. Tente novamente.")
            return True

        idx = ADD_STEPS.index(step)
        if idx + 1 < len(ADD_STEPS):
            next_step = ADD_STEPS[idx + 1]
            st["step"] = next_step
            await message.answer(ADD_PROMPTS[next_step], parse_mode="HTML")
        else:
            pid = create_product(
                data["name"], data["price"], data["stock"],
                data.get("emoji", "📦"), data.get("description", ""), data.get("category", "")
            )
            admin_state.pop(uid, None)
            await message.answer(f"✅ Produto criado! (ID {pid})")
            await render_admin_product(message, pid, edit=False)
        return True

    # ----- Broadcast: capture text, then confirm -----
    if action == "broadcast":
        st["text"] = message.html_text if message.html_text else message.text
        preview = st["text"]
        await message.answer(
            f"📢 <b>Pré-visualização do aviso:</b>\n\n{preview}\n\n"
            f"Enviar para <b>{len(get_all_user_ids())}</b> usuários?",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Enviar agora", callback_data="admin_bcast_send")],
                [InlineKeyboardButton(text="❌ Cancelar", callback_data="admin")],
            ])
        )
        return True

    # ----- Adjust balance flow -----
    if action == "balance":
        step = st["step"]
        if step == "uid":
            try:
                target = int(txt)
            except ValueError:
                await message.reply("ID inválido. Envie apenas números.")
                return True
            st["data"]["target"] = target
            st["step"] = "amount"
            await message.answer(
                "💵 Envie o valor a ajustar. Use positivo para creditar ou negativo para debitar.\n"
                "Ex: <code>10</code> ou <code>-5.5</code>",
                parse_mode="HTML"
            )
            return True
        elif step == "amount":
            try:
                delta = round(float(txt.replace(",", ".")), 4)
            except ValueError:
                await message.reply("Valor inválido. Tente novamente.")
                return True
            target = st["data"]["target"]
            get_user(target)  # ensure the user row exists
            update_balance(target, delta)
            new_bal = get_user(target)["balance"]
            admin_state.pop(uid, None)
            await message.answer(
                f"✅ Saldo ajustado!\n\n👤 Usuário: <code>{target}</code>\n"
                f"➕ Ajuste: <b>{delta:+.2f} USDT</b>\n💰 Novo saldo: <b>${new_bal:.2f} USDT</b>",
                parse_mode="HTML", reply_markup=admin_main_kb()
            )
            # Notify the user about the balance change
            try:
                if delta != 0:
                    await bot.send_message(
                        target,
                        f"💰 Seu saldo foi {'creditado' if delta > 0 else 'ajustado'}: "
                        f"<b>{delta:+.2f} USDT</b>\nNovo saldo: <b>${new_bal:.2f} USDT</b>",
                        parse_mode="HTML"
                    )
            except Exception:
                pass
            return True

    return False

# ================== BEP20 AUTO-DETECTION ==================
async def fulfill_payment(pending: dict, tx_hash: str):
    """Credit balance (deposit) or deliver product (buy) once a matching tx is found."""
    uid = pending["user_id"]
    code = pending["code"]
    ptype = pending["payment_type"]

    if ptype == "deposit":
        update_balance(uid, pending["amount"])
        delete_pending_payment(code)
        user = get_user(uid)
        try:
            await bot.send_message(
                uid,
                f"✅ <b>Deposit received!</b>\n\n"
                f"💵 Amount: <b>${pending['amount']:.2f} USDT</b>\n"
                f"🔖 Code: <code>{code}</code>\n"
                f"💰 New balance: <b>${user['balance']:.2f} USDT</b>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text=t(uid, "back"), callback_data="main_menu")]
                ])
            )
        except Exception as e:
            print(f"[scanner] notify deposit failed: {e}")

    elif ptype == "buy":
        pid = pending["product_id"]
        p = get_product(pid)
        qty = pending["quantity"]
        name = p["name"] if p else "Product"
        order_code = generate_code("ORD")
        add_order(uid, order_code, name, pending["amount"], qty, "Paid")
        if p and p.get("delivery_type") != "auto":
            decrement_stock(pid, qty)
        delete_pending_payment(code)
        try:
            if p:
                await deliver_product(uid, p, qty, order_code, pending["amount"])
            else:
                await bot.send_message(
                    uid,
                    f"✅ <b>Payment received — Order confirmed!</b>\n\n"
                    f"🔖 Order code: <code>{order_code}</code>\n\n"
                    f"Contact {ADMIN} to receive your product.",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text=t(uid, "back"), callback_data="main_menu")]
                    ])
                )
        except Exception as e:
            print(f"[scanner] notify buy failed: {e}")


async def check_bep20_deposits():
    """Poll BscScan for incoming USDT (BEP20) transfers and match them to pending payments."""
    pendings = get_all_pending()
    if not pendings:
        return

    # Build lookup of expected amount -> pending (only those with a bep20 amount)
    expected = {}
    for pn in pendings:
        if pn.get("expected_bep20") is not None:
            expected[round(pn["expected_bep20"], 4)] = pn

    if not expected:
        return

    url = (
        "https://api.bscscan.com/api"
        f"?module=account&action=tokentx"
        f"&contractaddress={USDT_CONTRACT}"
        f"&address={BEP20_ADDRESS}"
        f"&page=1&offset=50&sort=desc"
        f"&apikey={BSCSCAN_API_KEY}"
    )

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                data = await resp.json()
    except Exception as e:
        print(f"[scanner] request failed: {e}")
        return

    if str(data.get("status")) != "1" or not isinstance(data.get("result"), list):
        return

    for tx in data["result"]:
        try:
            if tx.get("to", "").lower() != BEP20_ADDRESS.lower():
                continue
            tx_hash = tx.get("hash")
            if not tx_hash or is_tx_processed(tx_hash):
                continue

            decimals = int(tx.get("tokenDecimal", 18))
            value = round(int(tx["value"]) / (10 ** decimals), 4)
            tx_epoch = int(tx.get("timeStamp", 0))

            match = expected.get(value)
            if not match:
                continue
            # Only accept transfers that happened after the payment was created
            if tx_epoch and match.get("created_epoch") and tx_epoch < match["created_epoch"] - 120:
                continue

            mark_tx_processed(tx_hash, match["code"], match["user_id"], value)
            print(f"[scanner] matched tx {tx_hash} -> {match['code']} ({value} USDT)")
            await fulfill_payment(match, tx_hash)
        except Exception as e:
            print(f"[scanner] tx parse error: {e}")
            continue


async def check_binance_pay():
    """Poll Binance personal-account Pay history and match incoming transfers by unique amount."""
    pendings = get_all_pending()
    if not pendings:
        return

    # Build lookup of expected Binance Pay amount -> pending
    expected = {}
    for pn in pendings:
        if pn.get("expected_binance") is not None:
            expected[round(pn["expected_binance"], 4)] = pn
    if not expected:
        return

    # Signed request to /sapi/v1/pay/transactions (last ~24h)
    timestamp = int(time.time() * 1000)
    start_time = timestamp - 24 * 60 * 60 * 1000
    params = {
        "startTime": start_time,
        "endTime": timestamp,
        "limit": 100,
        "timestamp": timestamp,
        "recvWindow": 60000,
    }
    query = urllib.parse.urlencode(params)
    signature = hmac.new(BINANCE_API_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()
    url = f"{BINANCE_BASE_URL}/sapi/v1/pay/transactions?{query}&signature={signature}"
    headers = {"X-MBX-APIKEY": BINANCE_API_KEY}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                data = await resp.json()
    except Exception as e:
        print(f"[binance] request failed: {e}")
        return

    if not isinstance(data, dict) or str(data.get("code")) not in ("000000", "0", "None"):
        # Binance returns code "000000" on success
        if data.get("code") and str(data.get("code")) != "000000":
            print(f"[binance] API error: {data}")
            return

    txs = data.get("data") or []
    if not isinstance(txs, list):
        return

    for tx in txs:
        try:
            # amount is a string; positive = income
            amount = round(float(tx.get("amount", 0)), 4)
            if amount <= 0:
                continue
            currency = (tx.get("currency") or "").upper()
            if currency and currency != "USDT":
                continue

            tx_id = str(tx.get("transactionId") or tx.get("orderId") or "")
            if not tx_id:
                continue
            uniq = f"BNPAY-{tx_id}"
            if is_tx_processed(uniq):
                continue

            match = expected.get(amount)
            if not match:
                continue

            tx_time = tx.get("transactionTime") or tx.get("orderTime") or 0
            tx_epoch = int(int(tx_time) / 1000) if tx_time else 0
            if tx_epoch and match.get("created_epoch") and tx_epoch < match["created_epoch"] - 120:
                continue

            mark_tx_processed(uniq, match["code"], match["user_id"], amount)
            print(f"[binance] matched pay tx {tx_id} -> {match['code']} ({amount} USDT)")
            await fulfill_payment(match, tx_id)
        except Exception as e:
            print(f"[binance] tx parse error: {e}")
            continue


async def scanner_loop():
    if not BSCSCAN_API_KEY and not (BINANCE_API_KEY and BINANCE_API_SECRET):
        print("[scanner] No payment APIs configured — auto-detection disabled.")
        return
    if BSCSCAN_API_KEY:
        print("[scanner] BEP20 auto-detection started.")
    if BINANCE_API_KEY and BINANCE_API_SECRET:
        print("[scanner] Binance Pay auto-detection started.")
    while True:
        if BSCSCAN_API_KEY:
            try:
                await check_bep20_deposits()
            except Exception as e:
                print(f"[scanner] bep20 loop error: {e}")
        if BINANCE_API_KEY and BINANCE_API_SECRET:
            try:
                await check_binance_pay()
            except Exception as e:
                print(f"[scanner] binance loop error: {e}")
        await asyncio.sleep(SCAN_INTERVAL)


# ================== RUN ==================
async def main():
    init_db()
    print("SukoShop Bot running...")
    # Drop any webhook + queued updates so this instance starts clean.
    try:
        await bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        print(f"[startup] delete_webhook warning: {e}")
    asyncio.create_task(scanner_loop())
    # NOTE: If you ever see a permanent "TelegramConflictError ... terminated by
    # other getUpdates request" loop, it means ANOTHER instance is polling this
    # same token somewhere. The only guaranteed fix is to /revoke the token in
    # BotFather, then update BOT_TOKEN on the host. aiogram retries this error
    # internally, so it cannot be resolved purely in code.
    await dp.start_polling(bot, drop_pending_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
