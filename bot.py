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

ADMIN = "@sukodeuva"

# ================== TRANSLATIONS ==================
LANGS = {
    "en": {
        "welcome": (
            "🔥 <b>Welcome to SukoShop - Auto Order Bot</b>\n\n"
            "👋 Hello, <b>{name}</b>!\n\n"
            "📌 Quick guide:\n"
            "1. Click <b>Shop</b> to browse products.\n"
            "2. Choose the product you want.\n"
            "3. Pay with your wallet balance.\n"
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
        "name": "Name",
        "balance": "Balance",
        "referral": "Referral Link",
        "referral_desc": "Share your link and earn commission!",
        "history_title": "📜 <b>ORDER HISTORY</b>",
        "no_orders": "📜 You have no orders yet.",
        "wallet_title": "💰 <b>WALLET</b>",
        "usdt_balance": "USDT Balance",
        "deposit_info": "➕ Deposit: Contact <a href='https://t.me/sukodeuva'>{admin}</a>",
        "withdraw_info": "💸 Withdraw: Contact <a href='https://t.me/sukodeuva'>{admin}</a>",
        "deposit_btn": "➕ Deposit",
        "withdraw_btn": "💸 Withdraw",
        "deposit_title": "➕ <b>DEPOSIT</b>",
        "deposit_text": "To deposit USDT into your account:\n\n1. Contact <a href='https://t.me/sukodeuva'>{admin}</a>\n2. Send the amount you want to deposit\n3. Your balance will be updated after confirmation",
        "withdraw_title": "💸 <b>WITHDRAW</b>",
        "withdraw_text": "To withdraw your balance:\n\n1. Contact <a href='https://t.me/sukodeuva'>{admin}</a>\n2. Send your wallet address and amount\n3. Withdrawal will be processed within 24h",
        "support_title": "🛟 <b>SUPPORT</b>",
        "support_text": "👤 Admin: <a href='https://t.me/sukodeuva'>{admin}</a>\n\n⏰ Working hours: 8h - 22h daily",
        "language_title": "🌐 <b>Choose Language</b>",
        "lang_changed": "Language changed to English!",
        "order_placed": (
            "✅ <b>Order placed!</b>\n\n"
            "Product: {product}\n"
            "Price: ${price}\n\n"
            "Please send payment to {admin}\n"
            "Your product will be delivered after confirmation."
        ),
        "out_of_stock_alert": "Out of stock!",
        "low_balance_alert": "Insufficient balance! Please deposit first.",
        "btn_shop": "🛒 Shop",
        "btn_profile": "👤 Profile",
        "btn_history": "📜 Order History",
        "btn_wallet": "💰 Wallet",
        "btn_support": "🛟 Support",
        "btn_language": "🌐 Language",
    },
    "pt": {
        "welcome": (
            "🔥 <b>Bem-vindo ao SukoShop - Bot de Pedido Automático</b>\n\n"
            "👋 Olá, <b>{name}</b>!\n\n"
            "📌 Guia rápido:\n"
            "1. Clique em <b>Loja</b> para ver os produtos.\n"
            "2. Escolha o produto desejado.\n"
            "3. Pague com o saldo da sua carteira.\n"
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
        "name": "Nome",
        "balance": "Saldo",
        "referral": "Link de Indicação",
        "referral_desc": "Compartilhe seu link e ganhe comissão!",
        "history_title": "📜 <b>HISTÓRICO DE PEDIDOS</b>",
        "no_orders": "📜 Você ainda não tem pedidos.",
        "wallet_title": "💰 <b>CARTEIRA</b>",
        "usdt_balance": "Saldo USDT",
        "deposit_info": "➕ Depositar: Contate <a href='https://t.me/sukodeuva'>{admin}</a>",
        "withdraw_info": "💸 Sacar: Contate <a href='https://t.me/sukodeuva'>{admin}</a>",
        "deposit_btn": "➕ Depositar",
        "withdraw_btn": "💸 Sacar",
        "deposit_title": "➕ <b>DEPÓSITO</b>",
        "deposit_text": "Para depositar USDT:\n\n1. Contate <a href='https://t.me/sukodeuva'>{admin}</a>\n2. Informe o valor que deseja depositar\n3. Seu saldo será atualizado após confirmação",
        "withdraw_title": "💸 <b>SAQUE</b>",
        "withdraw_text": "Para sacar seu saldo:\n\n1. Contate <a href='https://t.me/sukodeuva'>{admin}</a>\n2. Informe seu endereço de carteira e valor\n3. O saque será processado em até 24h",
        "support_title": "🛟 <b>SUPORTE</b>",
        "support_text": "👤 Admin: <a href='https://t.me/sukodeuva'>{admin}</a>\n\n⏰ Horário de atendimento: 8h - 22h",
        "language_title": "🌐 <b>Escolha o Idioma</b>",
        "lang_changed": "Idioma alterado para Português!",
        "order_placed": (
            "✅ <b>Pedido realizado!</b>\n\n"
            "Produto: {product}\n"
            "Preço: ${price}\n\n"
            "Envie o comprovante para {admin}\n"
            "Seu produto será entregue após confirmação."
        ),
        "out_of_stock_alert": "Produto esgotado!",
        "low_balance_alert": "Saldo insuficiente! Faça um depósito primeiro.",
        "btn_shop": "🛒 Loja",
        "btn_profile": "👤 Perfil",
        "btn_history": "📜 Histórico",
        "btn_wallet": "💰 Carteira",
        "btn_support": "🛟 Suporte",
        "btn_language": "🌐 Idioma",
    },
    "id": {
        "welcome": (
            "🔥 <b>Selamat datang di SukoShop - Bot Pesanan Otomatis</b>\n\n"
            "👋 Halo, <b>{name}</b>!\n\n"
            "📌 Panduan cepat:\n"
            "1. Klik <b>Toko</b> untuk melihat produk.\n"
            "2. Pilih produk yang Anda inginkan.\n"
            "3. Bayar dengan saldo dompet Anda.\n"
            "4. Setelah pembayaran bot akan otomatis mengirim.\n\n"
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
        "name": "Nama",
        "balance": "Saldo",
        "referral": "Link Referral",
        "referral_desc": "Bagikan link Anda dan dapatkan komisi!",
        "history_title": "📜 <b>RIWAYAT PESANAN</b>",
        "no_orders": "📜 Anda belum memiliki pesanan.",
        "wallet_title": "💰 <b>DOMPET</b>",
        "usdt_balance": "Saldo USDT",
        "deposit_info": "➕ Deposit: Hubungi <a href='https://t.me/sukodeuva'>{admin}</a>",
        "withdraw_info": "💸 Tarik: Hubungi <a href='https://t.me/sukodeuva'>{admin}</a>",
        "deposit_btn": "➕ Deposit",
        "withdraw_btn": "💸 Tarik Dana",
        "deposit_title": "➕ <b>DEPOSIT</b>",
        "deposit_text": "Untuk deposit USDT:\n\n1. Hubungi <a href='https://t.me/sukodeuva'>{admin}</a>\n2. Kirim jumlah yang ingin Anda deposit\n3. Saldo akan diperbarui setelah konfirmasi",
        "withdraw_title": "💸 <b>TARIK DANA</b>",
        "withdraw_text": "Untuk menarik saldo:\n\n1. Hubungi <a href='https://t.me/sukodeuva'>{admin}</a>\n2. Kirim alamat dompet dan jumlah Anda\n3. Penarikan diproses dalam 24 jam",
        "support_title": "🛟 <b>DUKUNGAN</b>",
        "support_text": "👤 Admin: <a href='https://t.me/sukodeuva'>{admin}</a>\n\n⏰ Jam kerja: 8 - 22 setiap hari",
        "language_title": "🌐 <b>Pilih Bahasa</b>",
        "lang_changed": "Bahasa diubah ke Indonesia!",
        "order_placed": (
            "✅ <b>Pesanan berhasil!</b>\n\n"
            "Produk: {product}\n"
            "Harga: ${price}\n\n"
            "Kirim bukti pembayaran ke {admin}\n"
            "Produk akan dikirim setelah konfirmasi."
        ),
        "out_of_stock_alert": "Stok habis!",
        "low_balance_alert": "Saldo tidak cukup! Silakan deposit terlebih dahulu.",
        "btn_shop": "🛒 Toko",
        "btn_profile": "👤 Profil",
        "btn_history": "📜 Riwayat",
        "btn_wallet": "💰 Dompet",
        "btn_support": "🛟 Dukungan",
        "btn_language": "🌐 Bahasa",
    },
    "hi": {
        "welcome": (
            "🔥 <b>SukoShop में आपका स्वागत है - ऑटो ऑर्डर बॉट</b>\n\n"
            "👋 नमस्ते, <b>{name}</b>!\n\n"
            "📌 त्वरित गाइड:\n"
            "1. उत्पाद देखने के लिए <b>शॉप</b> पर क्लिक करें।\n"
            "2. अपना उत्पाद चुनें।\n"
            "3. वॉलेट बैलेंस से भुगतान करें।\n"
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
        "name": "नाम",
        "balance": "बैलेंस",
        "referral": "रेफरल लिंक",
        "referral_desc": "अपना लिंक शेयर करें और कमीशन कमाएं!",
        "history_title": "📜 <b>ऑर्डर हिस्ट्री</b>",
        "no_orders": "📜 आपके कोई ऑर्डर नहीं हैं।",
        "wallet_title": "💰 <b>वॉलेट</b>",
        "usdt_balance": "USDT बैलेंस",
        "deposit_info": "➕ डिपॉजिट: <a href='https://t.me/sukodeuva'>{admin}</a> से संपर्क करें",
        "withdraw_info": "💸 निकासी: <a href='https://t.me/sukodeuva'>{admin}</a> से संपर्क करें",
        "deposit_btn": "➕ डिपॉजिट",
        "withdraw_btn": "💸 निकासी",
        "deposit_title": "➕ <b>डिपॉजिट</b>",
        "deposit_text": "USDT डिपॉजिट करने के लिए:\n\n1. <a href='https://t.me/sukodeuva'>{admin}</a> से संपर्क करें\n2. राशि भेजें\n3. पुष्टि के बाद बैलेंस अपडेट होगा",
        "withdraw_title": "💸 <b>निकासी</b>",
        "withdraw_text": "बैलेंस निकालने के लिए:\n\n1. <a href='https://t.me/sukodeuva'>{admin}</a> से संपर्क करें\n2. अपना वॉलेट पता और राशि भेजें\n3. 24 घंटे में प्रोसेस होगा",
        "support_title": "🛟 <b>सहायता</b>",
        "support_text": "👤 एडमिन: <a href='https://t.me/sukodeuva'>{admin}</a>\n\n⏰ काम के घंटे: सुबह 8 - रात 10",
        "language_title": "🌐 <b>भाषा चुनें</b>",
        "lang_changed": "भाषा हिंदी में बदली!",
        "order_placed": (
            "✅ <b>ऑर्डर हो गया!</b>\n\n"
            "उत्पाद: {product}\n"
            "कीमत: ${price}\n\n"
            "भुगतान प्रमाण {admin} को भेजें\n"
            "पुष्टि के बाद उत्पाद मिलेगा।"
        ),
        "out_of_stock_alert": "स्टॉक खत्म!",
        "low_balance_alert": "अपर्याप्त बैलेंस! पहले डिपॉजिट करें।",
        "btn_shop": "🛒 शॉप",
        "btn_profile": "👤 प्रोफ़ाइल",
        "btn_history": "📜 हिस्ट्री",
        "btn_wallet": "💰 वॉलेट",
        "btn_support": "🛟 सहायता",
        "btn_language": "🌐 भाषा",
    },
    "th": {
        "welcome": (
            "🔥 <b>ยินดีต้อนรับสู่ SukoShop - บอทสั่งซื้ออัตโนมัติ</b>\n\n"
            "👋 สวัสดี, <b>{name}</b>!\n\n"
            "📌 คู่มือด่วน:\n"
            "1. คลิก <b>ร้านค้า</b> เพื่อดูสินค้า\n"
            "2. เลือกสินค้าที่ต้องการ\n"
            "3. ชำระด้วยยอดคงเหลือในกระเป๋า\n"
            "4. หลังชำระบอทจะส่งสินค้าอัตโนมัติ\n\n"
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
        "name": "ชื่อ",
        "balance": "ยอดคงเหลือ",
        "referral": "ลิงก์แนะนำ",
        "referral_desc": "แชร์ลิงก์ของคุณเพื่อรับค่าคอมมิชชั่น!",
        "history_title": "📜 <b>ประวัติการสั่งซื้อ</b>",
        "no_orders": "📜 คุณยังไม่มีคำสั่งซื้อ",
        "wallet_title": "💰 <b>กระเป๋าเงิน</b>",
        "usdt_balance": "ยอด USDT",
        "deposit_info": "➕ ฝากเงิน: ติดต่อ <a href='https://t.me/sukodeuva'>{admin}</a>",
        "withdraw_info": "💸 ถอนเงิน: ติดต่อ <a href='https://t.me/sukodeuva'>{admin}</a>",
        "deposit_btn": "➕ ฝากเงิน",
        "withdraw_btn": "💸 ถอนเงิน",
        "deposit_title": "➕ <b>ฝากเงิน</b>",
        "deposit_text": "วิธีฝาก USDT:\n\n1. ติดต่อ <a href='https://t.me/sukodeuva'>{admin}</a>\n2. แจ้งจำนวนที่ต้องการฝาก\n3. ยอดจะอัปเดตหลังยืนยัน",
        "withdraw_title": "💸 <b>ถอนเงิน</b>",
        "withdraw_text": "วิธีถอนยอดคงเหลือ:\n\n1. ติดต่อ <a href='https://t.me/sukodeuva'>{admin}</a>\n2. แจ้งที่อยู่กระเป๋าและจำนวน\n3. ดำเนินการภายใน 24 ชั่วโมง",
        "support_title": "🛟 <b>ฝ่ายสนับสนุน</b>",
        "support_text": "👤 แอดมิน: <a href='https://t.me/sukodeuva'>{admin}</a>\n\n⏰ เวลาทำการ: 8 - 22 น. ทุกวัน",
        "language_title": "🌐 <b>เลือกภาษา</b>",
        "lang_changed": "เปลี่ยนภาษาเป็นภาษาไทย!",
        "order_placed": (
            "✅ <b>สั่งซื้อสำเร็จ!</b>\n\n"
            "สินค้า: {product}\n"
            "ราคา: ${price}\n\n"
            "ส่งหลักฐานการชำระให้ {admin}\n"
            "สินค้าจะถูกส่งหลังยืนยัน"
        ),
        "out_of_stock_alert": "สินค้าหมด!",
        "low_balance_alert": "ยอดคงเหลือไม่เพียงพอ! กรุณาฝากเงินก่อน",
        "btn_shop": "🛒 ร้านค้า",
        "btn_profile": "👤 โปรไฟล์",
        "btn_history": "📜 ประวัติ",
        "btn_wallet": "💰 กระเป๋า",
        "btn_support": "🛟 สนับสนุน",
        "btn_language": "🌐 ภาษา",
    },
    "zh": {
        "welcome": (
            "🔥 <b>欢迎来到 SukoShop - 自动订购机器人</b>\n\n"
            "👋 你好, <b>{name}</b>!\n\n"
            "📌 快速指南:\n"
            "1. 点击<b>商店</b>浏览商品。\n"
            "2. 选择您想要的商品。\n"
            "3. 用钱包余额支付。\n"
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
        "name": "姓名",
        "balance": "余额",
        "referral": "推荐链接",
        "referral_desc": "分享您的链接并赚取佣金！",
        "history_title": "📜 <b>订单历史</b>",
        "no_orders": "📜 您还没有订单。",
        "wallet_title": "💰 <b>钱包</b>",
        "usdt_balance": "USDT余额",
        "deposit_info": "➕ 充值: 联系 <a href='https://t.me/sukodeuva'>{admin}</a>",
        "withdraw_info": "💸 提现: 联系 <a href='https://t.me/sukodeuva'>{admin}</a>",
        "deposit_btn": "➕ 充值",
        "withdraw_btn": "💸 提现",
        "deposit_title": "➕ <b>充值</b>",
        "deposit_text": "充值USDT:\n\n1. 联系 <a href='https://t.me/sukodeuva'>{admin}</a>\n2. 发送充值金额\n3. 确认后余额更新",
        "withdraw_title": "💸 <b>提现</b>",
        "withdraw_text": "提取余额:\n\n1. 联系 <a href='https://t.me/sukodeuva'>{admin}</a>\n2. 发送您的钱包地址和金额\n3. 24小时内处理",
        "support_title": "🛟 <b>客服支持</b>",
        "support_text": "👤 管理员: <a href='https://t.me/sukodeuva'>{admin}</a>\n\n⏰ 工作时间: 每天 8 - 22 点",
        "language_title": "🌐 <b>选择语言</b>",
        "lang_changed": "语言已更改为中文！",
        "order_placed": (
            "✅ <b>下单成功！</b>\n\n"
            "商品: {product}\n"
            "价格: ${price}\n\n"
            "请将付款凭证发送给 {admin}\n"
            "确认后商品将自动发送。"
        ),
        "out_of_stock_alert": "缺货！",
        "low_balance_alert": "余额不足！请先充值。",
        "btn_shop": "🛒 商店",
        "btn_profile": "👤 个人资料",
        "btn_history": "📜 订单历史",
        "btn_wallet": "💰 钱包",
        "btn_support": "🛟 客服",
        "btn_language": "🌐 语言",
    },
    "es": {
        "welcome": (
            "🔥 <b>Bienvenido a SukoShop - Bot de Pedido Automático</b>\n\n"
            "👋 Hola, <b>{name}</b>!\n\n"
            "📌 Guía rápida:\n"
            "1. Haz clic en <b>Tienda</b> para ver los productos.\n"
            "2. Elige el producto que deseas.\n"
            "3. Paga con el saldo de tu billetera.\n"
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
        "name": "Nombre",
        "balance": "Saldo",
        "referral": "Link de Referido",
        "referral_desc": "Comparte tu link y gana comisión!",
        "history_title": "📜 <b>HISTORIAL DE PEDIDOS</b>",
        "no_orders": "📜 Aún no tienes pedidos.",
        "wallet_title": "💰 <b>BILLETERA</b>",
        "usdt_balance": "Saldo USDT",
        "deposit_info": "➕ Depositar: Contacta <a href='https://t.me/sukodeuva'>{admin}</a>",
        "withdraw_info": "💸 Retirar: Contacta <a href='https://t.me/sukodeuva'>{admin}</a>",
        "deposit_btn": "➕ Depositar",
        "withdraw_btn": "💸 Retirar",
        "deposit_title": "➕ <b>DEPÓSITO</b>",
        "deposit_text": "Para depositar USDT:\n\n1. Contacta <a href='https://t.me/sukodeuva'>{admin}</a>\n2. Envía el monto que deseas depositar\n3. Tu saldo se actualizará tras confirmación",
        "withdraw_title": "💸 <b>RETIRO</b>",
        "withdraw_text": "Para retirar tu saldo:\n\n1. Contacta <a href='https://t.me/sukodeuva'>{admin}</a>\n2. Envía tu dirección de billetera y monto\n3. El retiro se procesa en 24h",
        "support_title": "🛟 <b>SOPORTE</b>",
        "support_text": "👤 Admin: <a href='https://t.me/sukodeuva'>{admin}</a>\n\n⏰ Horario: 8h - 22h todos los días",
        "language_title": "🌐 <b>Elegir Idioma</b>",
        "lang_changed": "Idioma cambiado a Español!",
        "order_placed": (
            "✅ <b>Pedido realizado!</b>\n\n"
            "Producto: {product}\n"
            "Precio: ${price}\n\n"
            "Envía el comprobante de pago a {admin}\n"
            "Tu producto será entregado tras confirmación."
        ),
        "out_of_stock_alert": "Sin stock!",
        "low_balance_alert": "Saldo insuficiente! Por favor deposita primero.",
        "btn_shop": "🛒 Tienda",
        "btn_profile": "👤 Perfil",
        "btn_history": "📜 Historial",
        "btn_wallet": "💰 Billetera",
        "btn_support": "🛟 Soporte",
        "btn_language": "🌐 Idioma",
    },
}

# ================== PRODUTOS ==================
products = {
    "1": {
        "name": "Grok Super 3M (FW)",
        "price": 12.0,
        "stock": 39,
        "emoji": "🤖",
        "desc": (
            "🤖 <b>Grok Super - 3 Month (Family Warranty)</b>\n\n"
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
            "🤖 <b>Grok Super - 6 Month (Family Warranty)</b>\n\n"
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
            "✨ <b>Gemini Pro Link - 18 Months</b>\n\n"
            "💵 Price: <b>$1.50 USDT</b>\n"
            "📦 In stock: 53\n\n"
            "✅ 24 hours holding warranty\n"
            "✅ Click on the link and confirm\n"
            "✅ Do not need Card\n"
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
            "🎬 <b>Capcut Pro Team - 1 Month Full Date (Family Warranty)</b>\n\n"
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
            "💬 <b>ChatGPT Plus Shared - 1 Month (No Warranty)</b>\n\n"
            "💵 Price: <b>$2.00 USDT</b>\n"
            "📦 Out of stock\n\n"
            "• High quality shared account\n"
            "• Instant delivery after payment\n"
            "• No warranty - sold as is"
        ),
    },
    "6": {
        "name": "Adobe Creative Cloud 1M (NW)",
        "price": 0.5,
        "stock": 0,
        "emoji": "🎨",
        "desc": (
            "🎨 <b>Adobe Creative Cloud - 1 Month (No Warranty)</b>\n\n"
            "💵 Price: <b>$0.50 USDT</b>\n"
            "📦 Out of stock\n\n"
            "• Full Creative Cloud access\n"
            "• All Adobe apps included\n"
            "• No warranty - sold as is"
        ),
    },
    "7": {
        "name": "ElevenLabs 3M (FW)",
        "price": 15.0,
        "stock": 0,
        "emoji": "🎙️",
        "desc": (
            "🎙️ <b>ElevenLabs - 3 Month (Family Warranty)</b>\n\n"
            "💵 Price: <b>$15.00 USDT</b>\n"
            "📦 Out of stock\n\n"
            "✅ Premium voice AI access\n"
            "✅ Full warranty 3 months\n"
            "✅ No credit card needed\n"
            "✅ Instant delivery after payment"
        ),
    },
}

# ================== USER DATA (mock) ==================
user_data = {}

def get_user(user_id: int, name: str = None):
    if user_id not in user_data:
        user_data[user_id] = {
            "balance": 0.0,
            "orders": [],
            "name": name or "User",
            "lang": "en",
            "referral": f"https://t.me/SukoShopBot?start={user_id}"
        }
    return user_data[user_id]

def t(user_id: int, key: str, **kwargs):
    user = user_data.get(user_id, {})
    lang = user.get("lang", "en")
    strings = LANGS.get(lang, LANGS["en"])
    text = strings.get(key, LANGS["en"].get(key, key))
    return text.format(admin=ADMIN, **kwargs)

def main_menu_kb(user_id: int):
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
    get_user(callback.from_user.id)
    await callback.message.edit_text(
        t(callback.from_user.id, "choose_option"),
        reply_markup=main_menu_kb(callback.from_user.id)
    )

# ---------- SHOP ----------
@dp.callback_query(F.data == "shop")
async def shop_menu(callback: types.CallbackQuery):
    uid = callback.from_user.id
    get_user(uid)
    kb = []
    for pid, p in products.items():
        if p["stock"] > 0:
            label = f"{p['emoji']} {p['name']} - ${p['price']} ({t(uid, 'in_stock')} {p['stock']})"
        else:
            label = f"🔴 {p['name']} - ${p['price']} ({t(uid, 'out_of_stock')})"
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

    user["orders"].append({
        "id": f"#{len(user['orders']) + 1:05d}",
        "product": p["name"],
        "price": p["price"],
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "status": "Pending"
    })
    p["stock"] -= 1

    await callback.message.edit_text(
        t(uid, "order_placed", product=p["name"], price=p["price"]),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t(uid, "back"), callback_data="main_menu")]
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
        f"👤 {t(uid, 'name')}: <b>{user['name']}</b>\n"
        f"💰 {t(uid, 'balance')}: <b>${user['balance']:.2f} USDT</b>\n\n"
        f"🔗 {t(uid, 'referral')}:\n"
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
    user = get_user(uid)
    if not user["orders"]:
        text = t(uid, "no_orders")
    else:
        text = f"{t(uid, 'history_title')}\n\n"
        for order in reversed(user["orders"][-10:]):
            text += f"• {order['id']} | {order['product']} | ${order['price']} | {order['date']}\n"
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
        f"💵 {t(uid, 'usdt_balance')}: <b>${user['balance']:.2f}</b>\n\n"
        f"{t(uid, 'deposit_info')}\n"
        f"{t(uid, 'withdraw_info')}"
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
async def deposit_info(callback: types.CallbackQuery):
    uid = callback.from_user.id
    get_user(uid)
    await callback.message.edit_text(
        t(uid, "deposit_title") + "\n\n" + t(uid, "deposit_text"),
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
    user = get_user(uid)
    lang = callback.data.split("_")[1]
    if lang in LANGS:
        user["lang"] = lang
    await callback.answer(t(uid, "lang_changed"), show_alert=True)
    await callback.message.edit_text(
        t(uid, "choose_option"),
        reply_markup=main_menu_kb(uid)
    )

# ================== RUN ==================
if __name__ == "__main__":
    print("SukoShop Bot running...")
    asyncio.run(dp.start_polling(bot))
