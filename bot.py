import asyncio
import sqlite3
import os
import random
import string
import time
import aiohttp
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
BINANCE_ID = os.getenv("BINANCE_ID", "YOUR_BINANCE_ID")
BEP20_ADDRESS = os.getenv("BEP20_ADDRESS", "YOUR_BEP20_WALLET_ADDRESS")
BOT_USERNAME = os.getenv("BOT_USERNAME", "SukoShopBot")
DB_PATH = "sukoshop.db"

# ===== BEP20 / BscScan auto-detection =====
BSCSCAN_API_KEY = os.getenv("BSCSCAN_API_KEY", "")
# Binance-Peg BSC-USD (USDT) BEP20 contract
USDT_CONTRACT = "0x55d398326f99059fF775485246999027B3197955"
SCAN_INTERVAL = 30  # seconds between blockchain scans

# ================== DATABASE ==================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            name TEXT,
            balance REAL DEFAULT 0.0,
            lang TEXT DEFAULT 'en',
            referral TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            order_code TEXT,
            product_name TEXT,
            price REAL,
            quantity INTEGER DEFAULT 1,
            status TEXT DEFAULT 'Pending',
            created_at TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS pending_payments (
            code TEXT PRIMARY KEY,
            user_id INTEGER,
            product_id TEXT,
            quantity INTEGER,
            amount REAL,
            payment_type TEXT,
            expires_at TEXT,
            created_at TEXT,
            expected_bep20 REAL,
            created_epoch INTEGER
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS processed_tx (
            tx_hash TEXT PRIMARY KEY,
            code TEXT,
            user_id INTEGER,
            amount REAL,
            processed_at TEXT
        )
    """)
    # --- migrations for existing databases ---
    for col, decl in [("expected_bep20", "REAL"), ("created_epoch", "INTEGER")]:
        try:
            c.execute(f"ALTER TABLE pending_payments ADD COLUMN {col} {decl}")
        except sqlite3.OperationalError:
            pass  # column already exists
    conn.commit()
    conn.close()

def get_user(user_id: int, name: str = None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    if not row:
        referral = f"https://t.me/{BOT_USERNAME}?start={user_id}"
        c.execute("INSERT INTO users (user_id, name, balance, lang, referral) VALUES (?,?,?,?,?)",
                  (user_id, name or "User", 0.0, "en", referral))
        conn.commit()
        c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
        row = c.fetchone()
    elif name and row[1] != name:
        c.execute("UPDATE users SET name=? WHERE user_id=?", (name, user_id))
        conn.commit()
    conn.close()
    return {"user_id": row[0], "name": row[1], "balance": row[2], "lang": row[3], "referral": row[4]}

def set_user_lang(user_id: int, lang: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET lang=? WHERE user_id=?", (lang, user_id))
    conn.commit()
    conn.close()

def update_balance(user_id: int, delta: float):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (delta, user_id))
    conn.commit()
    conn.close()

def add_order(user_id: int, order_code: str, product_name: str, price: float, quantity: int = 1, status: str = "Pending"):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO orders (user_id, order_code, product_name, price, quantity, status, created_at) VALUES (?,?,?,?,?,?,?)",
              (user_id, order_code, product_name, price, quantity, status,
               datetime.now().strftime("%Y-%m-%d %H:%M")))
    conn.commit()
    conn.close()

def get_orders(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT order_code, product_name, price, quantity, status, created_at FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 10", (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows

def save_pending_payment(code: str, user_id: int, product_id: str, quantity: int, amount: float, payment_type: str, expires_at: str, expected_bep20: float):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""INSERT OR REPLACE INTO pending_payments
                 (code, user_id, product_id, quantity, amount, payment_type, expires_at, created_at, expected_bep20, created_epoch)
                 VALUES (?,?,?,?,?,?,?,?,?,?)""",
              (code, user_id, product_id, quantity, amount, payment_type, expires_at,
               datetime.now().strftime("%Y-%m-%d %H:%M"), expected_bep20, int(time.time())))
    conn.commit()
    conn.close()

def get_pending_payment(code: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT code, user_id, product_id, quantity, amount, payment_type, expires_at, expected_bep20, created_epoch FROM pending_payments WHERE code=?", (code,))
    row = c.fetchone()
    conn.close()
    if row:
        return {"code": row[0], "user_id": row[1], "product_id": row[2],
                "quantity": row[3], "amount": row[4], "payment_type": row[5],
                "expires_at": row[6], "expected_bep20": row[7], "created_epoch": row[8]}
    return None

def generate_unique_bep20(base_amount: float) -> float:
    """Generate a BEP20 amount with a unique cents tail so each payment is identifiable."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT expected_bep20 FROM pending_payments WHERE expected_bep20 IS NOT NULL")
    used = {round(r[0], 4) for r in c.fetchall() if r[0] is not None}
    conn.close()
    for _ in range(300):
        tail = random.randint(11, 999) / 10000  # 0.0011 - 0.0999
        amt = round(base_amount + tail, 4)
        if amt not in used:
            return amt
    return round(base_amount + random.randint(11, 999) / 10000, 4)

def get_all_pending():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT code, user_id, product_id, quantity, amount, payment_type, expires_at, expected_bep20, created_epoch FROM pending_payments")
    rows = c.fetchall()
    conn.close()
    return [{"code": r[0], "user_id": r[1], "product_id": r[2], "quantity": r[3],
             "amount": r[4], "payment_type": r[5], "expires_at": r[6],
             "expected_bep20": r[7], "created_epoch": r[8]} for r in rows]

def is_tx_processed(tx_hash: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT 1 FROM processed_tx WHERE tx_hash=?", (tx_hash,))
    row = c.fetchone()
    conn.close()
    return row is not None

def mark_tx_processed(tx_hash: str, code: str, user_id: int, amount: float):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO processed_tx (tx_hash, code, user_id, amount, processed_at) VALUES (?,?,?,?,?)",
              (tx_hash, code, user_id, amount, datetime.now().strftime("%Y-%m-%d %H:%M")))
    conn.commit()
    conn.close()

def delete_pending_payment(code: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM pending_payments WHERE code=?", (code,))
    conn.commit()
    conn.close()

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
        "no_orders": "📜 Você ainda não tem pedidos.",
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
        "payment_expired": "भुगतान समय समाप्त। फिर कोशिश करें।",
        "deposit_info_title": "💵 <b>USDT डिपॉजिट जानकारी</b>",
        "deposit_info_amount": "राशि",
        "deposit_info_code": "कोड",
        "option1_title": "🔶 विकल्प 1: BINANCE PAY (तत्काल, मुफ्त)",
        "option1_binance_id": "Binance ID",
        "option1_amount": "राशि",
        "option1_note": "नोट",
        "option1_steps": "B. Binance → Pay → Send → ऊपर ID पेस्ट करें\n⚠️ नोट बिल्कुल सही होना चाहिए!",
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
        "deposit_info_amount": "จำนวน",
        "deposit_info_code": "รหัส",
        "option1_title": "🔶 ตัวเลือก 1: BINANCE PAY (ทันที, ฟรี)",
        "option1_binance_id": "Binance ID",
        "option1_amount": "จำนวน",
        "option1_note": "หมายเหตุ",
        "option1_steps": "B. Binance → Pay → Send → วาง ID ด้านบน\n⚠️ หมายเหตุต้องถูกต้องทุกตัวอักษร!",
        "option2_title": "🔷 ตัวเลือก 2: โอนกระเป๋า (BEP20)",
        "option2_address": "ที่อยู่",
        "option2_network": "เครือข่าย: <b>BEP20</b>",
        "option2_amount": "จำนวน",
        "option2_warning": "⚠️ ส่งจำนวนนี้เท่านั้น!\n⚠️ ใช้เครือข่าย <b>BEP20</b> เท่านั้น!",
        "auto_detect": "⏱ ตรวจจับอัตโนมัติภายใน 1-2 นาที\nคุณจะได้รับแจ้งเมื่อเงินเข้า!",
        "auto_detect_buy": "⏱ ตรวจจับอัตโนมัติภายใน 1-2 นาที\nสินค้าจะถูกส่งอัตโนมัติ!\n⏰ การชำระเงินหมดอายุใน 10 นาที",
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
products = {
    "1": {
        "name": "Grok Super 3M (FW)",
        "price": 12.0,
        "stock": 39,
        "emoji": "🤖",
        "desc": (
            "🤖 <b>Grok Super — 3 Month (Family Warranty)</b>\n\n"
            "💵 Price: <b>$12.00 USDT</b>\n"
            "📦 In stock: 39\n\n"
            "✅ Full warranty 3 months\n"
            "✅ Works on any account\n"
            "✅ No credit card needed\n"
            "✅ 24h replacement guarantee\n"
            "✅ Instant delivery after payment"
        ),
    },
    "2": {
        "name": "Grok Super 6M (FW)",
        "price": 19.0,
        "stock": 3,
        "emoji": "🤖",
        "desc": (
            "🤖 <b>Grok Super — 6 Month (Family Warranty)</b>\n\n"
            "💵 Price: <b>$19.00 USDT</b>\n"
            "📦 In stock: 3\n\n"
            "✅ Full warranty 6 months\n"
            "✅ Works on any account\n"
            "✅ No credit card needed\n"
            "✅ 24h replacement guarantee\n"
            "✅ Instant delivery after payment"
        ),
    },
    "3": {
        "name": "Gemini Pro 18M",
        "price": 1.5,
        "stock": 53,
        "emoji": "✨",
        "desc": (
            "✨ <b>Gemini Pro Link — 18 Months</b>\n\n"
            "💵 Price: <b>$1.50 USDT</b>\n"
            "📦 In stock: 53\n\n"
            "✅ 24 hours holding warranty\n"
            "✅ Click on the link and confirm\n"
            "✅ No credit card needed\n"
            "✅ Can be used on any account\n"
            "✅ Can invite 5 more members to family\n"
            "✅ Instant delivery after payment"
        ),
    },
    "4": {
        "name": "Capcut Pro Team 1M (FW)",
        "price": 2.5,
        "stock": 30,
        "emoji": "🎬",
        "desc": (
            "🎬 <b>Capcut Pro Team — 1 Month Full Date (Family Warranty)</b>\n\n"
            "💵 Price: <b>$2.50 USDT</b>\n"
            "📦 In stock: 30\n\n"
            "✅ Full Date warranty\n"
            "✅ Works on all devices\n"
            "✅ No credit card needed\n"
            "✅ 30 days replacement guarantee\n"
            "✅ Instant delivery after payment"
        ),
    },
    "5": {
        "name": "ChatGPT Plus 1M (NW)",
        "price": 2.0,
        "stock": 0,
        "emoji": "💬",
        "desc": (
            "💬 <b>ChatGPT Plus Shared — 1 Month (No Warranty)</b>\n\n"
            "💵 Price: <b>$2.00 USDT</b>\n"
            "📦 Out of stock\n\n"
            "• High quality shared account\n"
            "• Instant delivery after payment\n"
            "• No warranty — sold as is"
        ),
    },
    "6": {
        "name": "Adobe Creative Cloud 1M (NW)",
        "price": 0.5,
        "stock": 0,
        "emoji": "🎨",
        "desc": (
            "🎨 <b>Adobe Creative Cloud — 1 Month (No Warranty)</b>\n\n"
            "💵 Price: <b>$0.50 USDT</b>\n"
            "📦 Out of stock\n\n"
            "• Full Creative Cloud access\n"
            "• All Adobe apps included\n"
            "• No warranty — sold as is"
        ),
    },
    "7": {
        "name": "ElevenLabs 3M (FW)",
        "price": 15.0,
        "stock": 0,
        "emoji": "🎙️",
        "desc": (
            "🎙️ <b>ElevenLabs — 3 Month (Family Warranty)</b>\n\n"
            "💵 Price: <b>$15.00 USDT</b>\n"
            "📦 Out of stock\n\n"
            "✅ Premium voice AI access\n"
            "✅ Full warranty 3 months\n"
            "✅ No credit card needed\n"
            "✅ Instant delivery after payment"
        ),
    },
}

# Tracks users waiting to type qty: {user_id: {"product_id": str, "message_id": int}}
awaiting_qty = {}

# ================== HELPERS ==================
def t(user_id: int, key: str, **kwargs) -> str:
    user = get_user(user_id)
    lang = user.get("lang", "en")
    strings = LANGS.get(lang, LANGS["en"])
    text = strings.get(key, LANGS["en"].get(key, key))
    return text.format(admin=ADMIN, admin_url=ADMIN_URL, **kwargs)

def main_menu_kb(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
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
    ])

def build_payment_message(uid: int, amount: float, code: str, bep20_amount: float, is_deposit: bool = True) -> str:
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
    lines.append(f"<code>{amount}</code>")
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
    kb = []
    for pid, p in products.items():
        if p["stock"] > 0:
            label = f"{p['emoji']} {p['name']} — ${p['price']} ({t(uid, 'in_stock')} {p['stock']})"
        else:
            label = f"🔴 {p['name']} — ${p['price']} ({t(uid, 'out_of_stock')})"
        kb.append([InlineKeyboardButton(text=label, callback_data=f"product_{pid}")])
    kb.append([InlineKeyboardButton(text="🔄 Refresh", callback_data="shop")])
    kb.append([InlineKeyboardButton(text=t(uid, "back"), callback_data="main_menu")])
    await callback.message.edit_text(
        t(uid, "shop_title"),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb),
        parse_mode="HTML"
    )

@dp.callback_query(F.data.startswith("product_"))
async def show_product(callback: types.CallbackQuery):
    uid = callback.from_user.id
    get_user(uid)
    pid = callback.data.split("_")[1]
    p = products.get(pid)
    if not p:
        await callback.answer("Product not found.", show_alert=True)
        return
    kb = []
    if p["stock"] > 0:
        kb.append([InlineKeyboardButton(text=t(uid, "buy_now"), callback_data=f"buy_{pid}")])
    kb.append([InlineKeyboardButton(text=t(uid, "back_to_shop"), callback_data="shop")])
    await callback.message.edit_text(
        p["desc"],
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb),
        parse_mode="HTML"
    )

@dp.callback_query(F.data.startswith("buy_"))
async def buy_product(callback: types.CallbackQuery):
    uid = callback.from_user.id
    pid = callback.data.split("_")[1]
    p = products.get(pid)
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
        expires_at = (datetime.now() + timedelta(hours=24)).strftime("%Y-%m-%d %H:%M")
        save_pending_payment(code, uid, "__deposit__", 1, amount, "deposit", expires_at, bep20_amount)

        text = build_payment_message(uid, amount, code, bep20_amount, is_deposit=True)
        await message.answer(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=t(uid, "back_to_wallet"), callback_data="wallet")]
            ])
        )
        return

    # ----- BUY quantity input -----
    p = products.get(pid)
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
        p["stock"] -= qty
        await message.answer(
            f"✅ <b>Order confirmed!</b>\n\n"
            f"📦 Product: {p['name']}\n"
            f"🔢 Quantity: {qty}\n"
            f"💵 Total: <b>${total:.4f} USDT</b>\n"
            f"🔖 Order code: <code>{order_code}</code>\n\n"
            f"Your product will be delivered shortly. Contact {ADMIN} if needed.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=t(uid, "back"), callback_data="main_menu")]
            ])
        )
    else:
        # Not enough balance — show payment screen
        code = generate_code("BUY")
        bep20_amount = generate_unique_bep20(total)
        expires_at = (datetime.now() + timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M")
        save_pending_payment(code, uid, pid, qty, total, "buy", expires_at, bep20_amount)

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
            f"<code>{total}</code>\n"
            f"📝 {t(uid, 'option1_note')}:\n"
            f"<code>{code}</code>\n\n"
            f"{t(uid, 'option1_steps')}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
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
        p = products.get(pid)
        qty = pending["quantity"]
        name = p["name"] if p else "Product"
        order_code = generate_code("ORD")
        add_order(uid, order_code, name, pending["amount"], qty, "Paid")
        if p and p["stock"] >= qty:
            p["stock"] -= qty
        delete_pending_payment(code)
        try:
            await bot.send_message(
                uid,
                f"✅ <b>Payment received — Order confirmed!</b>\n\n"
                f"📦 Product: <b>{name}</b>\n"
                f"🔢 Quantity: <b>{qty}</b>\n"
                f"💵 Total: <b>${pending['amount']:.2f} USDT</b>\n"
                f"🔖 Order code: <code>{order_code}</code>\n\n"
                f"Your product will be delivered shortly. Contact {ADMIN} if needed.",
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


async def scanner_loop():
    if not BSCSCAN_API_KEY:
        print("[scanner] BSCSCAN_API_KEY not set — BEP20 auto-detection disabled.")
        return
    print("[scanner] BEP20 auto-detection started.")
    while True:
        try:
            await check_bep20_deposits()
        except Exception as e:
            print(f"[scanner] loop error: {e}")
        await asyncio.sleep(SCAN_INTERVAL)


# ================== RUN ==================
async def main():
    init_db()
    print("SukoShop Bot running...")
    asyncio.create_task(scanner_loop())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
