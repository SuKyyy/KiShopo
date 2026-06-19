import asyncio
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv
import os
from datetime import datetime

load_dotenv()
bot = Bot(token=os.getenv("BOT_TOKEN"))
dp = Dispatcher()

# ================== DADOS (mock - depois vira banco) ==================
user_data = {}          # user_id: {"balance": 0, "orders": [], "name": ""}
products = {
    "1": {"name": "Grok Super 3M (FW)", "price": 12.0, "stock": 39, "desc": "Grok account - Full warranty 3 months\n• Can be used on any account\n• 24h replacement guarantee"},
    "2": {"name": "Gemini Pro 18M", "price": 1.5, "stock": 53, "desc": "Gemini Pro link - 18 months\n• No card needed\n• Can invite 5 members to family"},
    "3": {"name": "ChatGPT Plus 1M", "price": 2.0, "stock": 0, "desc": "ChatGPT Plus shared - 1 month\n• High quality\n• Instant delivery"},
    "4": {"name": "Capcut Pro Team 1M", "price": 2.5, "stock": 30, "desc": "Capcut Pro Team - Full Date\n• Works on all devices\n• 30 days warranty"},
}

# ================== FUNÇÕES AUXILIARES ==================
def get_user(user_id: int, name: str = None):
    if user_id not in user_data:
        user_data[user_id] = {
            "balance": 0.0,
            "orders": [],
            "name": name or "User",
            "referral": f"https://t.me/yourbot?start={user_id}"
        }
    return user_data[user_id]

def main_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Shop", callback_data="shop")],
        [InlineKeyboardButton(text="👤 Profile", callback_data="profile"),
         InlineKeyboardButton(text="📜 Order History", callback_data="history")],
        [InlineKeyboardButton(text="💰 Wallet", callback_data="wallet"),
         InlineKeyboardButton(text="🛟 Support", callback_data="support")],
        [InlineKeyboardButton(text="🌐 Language", callback_data="language")]
    ])

# ================== COMANDOS ==================
@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    user = get_user(message.from_user.id, message.from_user.first_name)
    text = (
        f"🔥 <b>Welcome to SukoUltra Shop - Black Edition</b>\n\n"
        f"User: <b>{user['name']}</b>\n\n"
        "Choose an option below:"
    )
    await message.answer(text, reply_markup=main_menu_kb(), parse_mode="HTML")

# ================== CALLBACKS ==================
@dp.callback_query(F.data == "shop")
async def shop_menu(callback: types.CallbackQuery):
    kb = []
    for pid, p in products.items():
        status = "✅ In Stock" if p["stock"] > 0 else "❌ Out of Stock"
        kb.append([InlineKeyboardButton(text=f"{p['name']} - ${p['price']} ({status})", callback_data=f"product_{pid}")])
    kb.append([InlineKeyboardButton(text="⬅️ Back", callback_data="main_menu")])
    await callback.message.edit_text("🛒 <b>Choose a product:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")

@dp.callback_query(F.data.startswith("product_"))
async def show_product(callback: types.CallbackQuery):
    pid = callback.data.split("_")[1]
    p = products[pid]
    status = "✅ In Stock" if p["stock"] > 0 else "❌ Out of Stock"
    
    text = (
        f"🛍️ <b>{p['name']}</b>\n\n"
        f"💵 Price: <b>${p['price']}</b>\n"
        f"📦 Stock: {p['stock']}\n"
        f"Status: {status}\n\n"
        f"{p['desc']}\n\n"
        "How to buy:\n"
        "• Click Buy below\n"
        "• Pay with USDT or contact support\n"
        "• Instant delivery after payment"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Buy Now", callback_data=f"buy_{pid}")],
        [InlineKeyboardButton(text="⬅️ Back to Shop", callback_data="shop")]
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data.startswith("buy_"))
async def buy_product(callback: types.CallbackQuery):
    pid = callback.data.split("_")[1]
    p = products[pid]
    user = get_user(callback.from_user.id)
    
    if p["stock"] <= 0:
        await callback.answer("❌ Out of stock!", show_alert=True)
        return
    
    # Simulação de compra (depois você liga com pagamento real)
    user["orders"].append({
        "product": p["name"],
        "price": p["price"],
        "date": datetime.now().strftime("%Y-%m-%d %H:%M")
    })
    p["stock"] -= 1
    
    await callback.message.edit_text(
        f"✅ <b>Order placed!</b>\n\n"
        f"Product: {p['name']}\n"
        f"Price: ${p['price']}\n\n"
        f"Please send payment proof to @sukodeuva\n"
        f"After confirmation you will receive the product instantly.",
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "profile")
async def profile_menu(callback: types.CallbackQuery):
    user = get_user(callback.from_user.id)
    text = (
        f"👤 <b>PROFILE</b>\n\n"
        f"🆔 User ID: <code>{callback.from_user.id}</code>\n"
        f"👤 Name: {user['name']}\n"
        f"💰 Balance: <b>${user['balance']}</b>\n"
        f"🔗 Referral Link:\n{user['referral']}\n\n"
        "Invite friends and earn commission!"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Back", callback_data="main_menu")]
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data == "history")
async def order_history(callback: types.CallbackQuery):
    user = get_user(callback.from_user.id)
    if not user["orders"]:
        text = "📜 You have no orders yet."
    else:
        text = "📜 <b>ORDER HISTORY</b>\n\n"
        for order in user["orders"][-10:]:  # últimos 10
            text += f"• {order['date']} - {order['product']} (${order['price']})\n"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Back", callback_data="main_menu")]
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data == "wallet")
async def wallet_menu(callback: types.CallbackQuery):
    user = get_user(callback.from_user.id)
    text = (
        f"💰 <b>WALLET</b>\n\n"
        f"💵 Balance: <b>${user['balance']}</b>\n\n"
        "Deposit / Withdraw:\n"
        "Contact @sukodeuva directly"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Deposit", callback_data="deposit")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="main_menu")]
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data == "deposit")
async def deposit_info(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "💰 <b>DEPOSIT</b>\n\n"
        "Contact @sukodeuva to deposit USDT or other methods.\n"
        "After deposit your balance will be updated automatically.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Back", callback_data="wallet")]])
    )

@dp.callback_query(F.data == "support")
async def support_menu(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "🛟 <b>SUPPORT</b>\n\n"
        "Contact admin directly:\n"
        "@sukodeuva\n\n"
        "Working hours: 24/7",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Back", callback_data="main_menu")]])
    )

@dp.callback_query(F.data == "language")
async def language_menu(callback: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇬🇧 English (Current)", callback_data="lang_en")],
        [InlineKeyboardButton(text="🇧🇷 Português", callback_data="lang_pt")],
        [InlineKeyboardButton(text="🇮🇩 Indonesian", callback_data="lang_id")],
        [InlineKeyboardButton(text="🇮🇳 Hindi", callback_data="lang_hi")],
        [InlineKeyboardButton(text="🇹🇭 Thai", callback_data="lang_th")],
        [InlineKeyboardButton(text="🇨🇳 Chinese", callback_data="lang_zh")],
        [InlineKeyboardButton(text="🇪🇸 Spanish", callback_data="lang_es")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="main_menu")]
    ])
    await callback.message.edit_text("🌐 <b>Choose Language</b>", reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data.startswith("lang_"))
async def change_lang(callback: types.CallbackQuery):
    await callback.answer("✅ Language changed! (Full multi-language coming soon)", show_alert=True)
    await callback.message.edit_text("Main Menu:", reply_markup=main_menu_kb())

@dp.callback_query(F.data == "main_menu")
async def back_to_main(callback: types.CallbackQuery):
    await callback.message.edit_text("Choose an option:", reply_markup=main_menu_kb())

# ================== RUN ==================
if __name__ == "__main__":
    print("🤖 SukoUltra Shop Bot - Black Edition rodando...")
    asyncio.run(dp.start_polling(bot))