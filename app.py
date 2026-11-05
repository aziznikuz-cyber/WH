# language: Python, file: bot.py
# target: Python 3.10+, aiogram 3.x, SQLite
# deps: aiogram
import asyncio, sqlite3, secrets, datetime
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ===== ВПИШИ =====
BOT_TOKEN = "ТВОЙ_ТОКЕН_ЗДЕСЬ"
ADMIN_ID = 123456789  # Твой Telegram ID (@userinfobot)
ADMIN_PASS = "HEDV-SKSB-SKHS"
# ================

DB = "oxide.db"

def db_init():
    c = sqlite3.connect(DB)
    c.executescript("""
    CREATE TABLE IF NOT EXISTS plans(
      id TEXT PRIMARY KEY, name TEXT, price INTEGER, days INTEGER);
    CREATE TABLE IF NOT EXISTS orders(
      id TEXT PRIMARY KEY, uid INTEGER, contact TEXT, plan_id TEXT,
      status TEXT, ts TEXT);
    CREATE TABLE IF NOT EXISTS keys(
      key TEXT PRIMARY KEY, order_id TEXT, uid INTEGER, plan_id TEXT,
      created TEXT);
    """)
    for pid, nm, pr, dy in [
        ("d1",  "1 день",   90,   1),
        ("d7",  "7 дней",   370,  7),
        ("d30", "30 дней",  1400, 30),
        ("life","Навсегда", 2800, 0),
    ]:
        c.execute("INSERT OR REPLACE INTO plans VALUES(?,?,?,?)", (pid, nm, pr, dy))
    c.commit(); c.close()
db_init()

def q(sql, args=()):
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    r = c.execute(sql, args).fetchall(); c.close(); return r

def x(sql, args=()):
    c = sqlite3.connect(DB); c.execute(sql, args); c.commit(); c.close()

bot = Bot(BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
rt = Router()
dp.include_router(rt)

class Buy(StatesGroup):
    contact = State()

class AdminAuth(StatesGroup):
    password = State()

def kb_main():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Тарифы", callback_data="plans")],
        [InlineKeyboardButton(text="🔑 Мои ключи", callback_data="mykeys")],
    ])

def kb_plans():
    rows = []
    for p in q("SELECT * FROM plans ORDER BY price"):
        rows.append([InlineKeyboardButton(
            text=f"{p['name']} — {p['price']}₽",
            callback_data=f"buy:{p['id']}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def kb_admin():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏳ Ожидают оплаты", callback_data="adm_pending")],
        [InlineKeyboardButton(text="📦 Все заказы", callback_data="adm_all")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="adm_stats")],
    ])

# ---------- ЮЗЕРСКАЯ ЧАСТЬ ----------
@rt.message(CommandStart())
async def start(m: Message):
    await m.answer(
        "👋 <b>OxideWH</b>\n"
        "Магазин ключей для <b>Phantom Internal</b> (Oxide Survival Island).\n\n"
        "Выбери действие:", reply_markup=kb_main(), parse_mode="HTML")

@rt.callback_query(F.data == "plans")
async def plans(cb: CallbackQuery):
    txt = "<b>Доступные тарифы:</b>\n\n"
    for p in q("SELECT * FROM plans ORDER BY price"):
        txt += f"▪️ <b>{p['name']}</b> — {p['price']}₽\n"
    await cb.message.edit_text(txt, reply_markup=kb_plans(), parse_mode="HTML")
    await cb.answer()

@rt.callback_query(F.data.startswith("buy:"))
async def buy(cb: CallbackQuery, state: FSMContext):
    pid = cb.data.split(":")[1]
    p = q("SELECT * FROM plans WHERE id=?", (pid,))[0]
    await state.update_data(plan_id=pid, price=p["price"], plan_name=p["name"])
    await cb.message.answer(
        f"Выбран тариф <b>{p['name']}</b> за {p['price']}₽.\n\n"
        f"Введите ваш контакт (Telegram @username или email) для связи и выдачи ключа:",
        parse_mode="HTML")
    await state.set_state(Buy.contact)
    await cb.answer()

@rt.message(Buy.contact)
async def get_contact(m: Message, state: FSMContext):
    contact = m.text.strip()
    if len(contact) < 3:
        await m.answer("Слишком короткий контакт. Введите еще раз:")
        return
    
    d = await state.get_data()
    oid = f"ORD-{secrets.token_hex(3).upper()}"
    
    x("INSERT INTO orders VALUES(?,?,?,?,?,?)",
      (oid, m.from_user.id, contact, d["plan_id"], "pending", datetime.datetime.now().isoformat()))
    await state.clear()
    
    await m.answer(
        f"✅ Заказ <b>{oid}</b> создан.\n"
        f"Тариф: {d['plan_name']} ({d['price']}₽)\n"
        f"Контакт: {contact}\n\n"
        f"Ожидайте подтверждения оплаты. После проверки ключ придет сюда.",
        parse_mode="HTML")
    
    # Уведомление админу
    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Выдать ключ", callback_data=f"issue:{oid}")]
    ])
    try:
        await bot.send_message(
            ADMIN_ID,
            f"🔔 <b>Новый заказ!</b>\n"
            f"ID: <code>{oid}</code>\n"
            f"Юзер: <a href='tg://user?id={m.from_user.id}'>{m.from_user.first_name}</a> (ID: {m.from_user.id})\n"
            f"Тариф: {d['plan_name']} — {d['price']}₽\n"
            f"Контакт: {contact}\n\n"
            f"Проверь оплату и нажми кнопку.",
            reply_markup=admin_kb, parse_mode="HTML")
    except Exception as e:
        print("Не удалось отправить админу:", e)

@rt.callback_query(F.data == "mykeys")
async def mykeys(cb: CallbackQuery):
    ks = q("SELECT k.key, p.name FROM keys k JOIN plans p ON k.plan_id = p.id WHERE k.uid = ?", (cb.from_user.id,))
    if not ks:
        await cb.message.answer("У вас пока нет купленных ключей.")
    else:
        txt = "<b>Ваши ключи:</b>\n\n"
        for k in ks:
            txt += f"<code>{k['key']}</code> — {k['name']}\n"
        await cb.message.answer(txt, parse_mode="HTML")
    await cb.answer()

# ---------- АДМИН-ПАНЕЛЬ ----------
@rt.message(Command("admin"))
async def admin_cmd(m: Message, state: FSMContext):
    if m.from_user.id != ADMIN_ID:
        await m.answer("У вас нет доступа к этой команде.")
        return
    await m.answer("Введите пароль администратора:")
    await state.set_state(AdminAuth.password)

@rt.message(AdminAuth.password)
async def admin_auth(m: Message, state: FSMContext):
    if m.text.strip() == ADMIN_PASS:
        await state.clear()
        await m.answer("✅ Доступ разрешен. Админ-панель:", reply_markup=kb_admin())
    else:
        await m.answer("❌ Неверный пароль. Попробуйте еще раз или отмените командой /start.")
        # Оставляем в состоянии, чтобы можно было попробовать снова

@rt.callback_query(F.data == "adm_pending")
async def adm_pending(cb: CallbackQuery):
    if cb.from_user.id != ADMIN_ID: return
    orders = q("SELECT * FROM orders WHERE status='pending' ORDER BY ts DESC")
    if not orders:
        await cb.message.edit_text("Нет заказов, ожидающих оплаты.", reply_markup=kb_admin())
        await cb.answer(); return
    
    await cb.message.edit_text(f"<b>Ожидают оплаты ({len(orders)}):</b>", reply_markup=kb_admin())
    for o in orders:
        p = q("SELECT name, price FROM plans WHERE id=?", (o["plan_id"],))[0]
        txt = (f"ID: <code>{o['id']}</code>\n"
               f"Юзер: <a href='tg://user?id={o['uid']}'>профиль</a> (ID: {o['uid']})\n"
               f"Контакт: {o['contact']}\n"
               f"Тариф: {p['name']} — {p['price']}₽")
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Выдать ключ", callback_data=f"issue:{o['id']}")]
        ])
        await cb.message.answer(txt, reply_markup=kb, parse_mode="HTML")
    await cb.answer()

@rt.callback_query(F.data == "adm_all")
async def adm_all(cb: CallbackQuery):
    if cb.from_user.id != ADMIN_ID: return
    orders = q("SELECT * FROM orders ORDER BY ts DESC LIMIT 20")
    if not orders:
        await cb.message.edit_text("Заказов нет.", reply_markup=kb_admin())
        await cb.answer(); return
        
    txt = "<b>Последние 20 заказов:</b>\n\n"
    for o in orders:
        icon = "✅" if o["status"] == "paid" else "⏳"
        txt += f"{icon} <code>{o['id']}</code> | {o['contact']} | {o['plan_id']}\n"
    await cb.message.edit_text(txt, reply_markup=kb_admin(), parse_mode="HTML")
    await cb.answer()

@rt.callback_query(F.data == "adm_stats")
async def adm_stats(cb: CallbackQuery):
    if cb.from_user.id != ADMIN_ID: return
    total = q("SELECT COUNT(*) c FROM orders WHERE status='paid'")[0]["c"]
    revenue = q("SELECT SUM(p.price) s FROM orders o JOIN plans p ON o.plan_id = p.id WHERE o.status='paid'")[0]["s"] or 0
    pending = q("SELECT COUNT(*) c FROM orders WHERE status='pending'")[0]["c"]
    
    txt = (f"<b>📊 Статистика</b>\n\n"
           f"Выдано ключей: {total}\n"
           f"Выручка: {revenue}₽\n"
           f"Ожидают оплаты: {pending}")
    await cb.message.edit_text(txt, reply_markup=kb_admin(), parse_mode="HTML")
    await cb.answer()

@rt.callback_query(F.data.startswith("issue:"))
async def issue_key(cb: CallbackQuery):
    if cb.from_user.id != ADMIN_ID: return
    
    oid = cb.data.split(":")[1]
    o = q("SELECT * FROM orders WHERE id=?", (oid,))
    if not o:
        await cb.answer("Заказ не найден.", show_alert=True); return
    o = o[0]
    
    if o["status"] == "paid":
        await cb.answer("Ключ по этому заказу уже выдан.", show_alert=True); return

    # Генерация ключа
    key = f"PHANTOM-{secrets.token_hex(4).upper()}"
    x("INSERT INTO keys VALUES(?,?,?,?,?)",
      (key, oid, o["uid"], o["plan_id"], datetime.datetime.now().isoformat()))
    x("UPDATE orders SET status='paid' WHERE id=?", (oid,))
    
    # Выдача юзеру
    try:
        await bot.send_message(
            o["uid"],
            f"✅ <b>Оплата подтверждена!</b>\n\n"
            f"Ваш ключ для <b>Phantom Internal</b>:\n"
            f"<code>{key}</code>\n\n"
            f"Введите его в меню программы при первом запуске.",
            parse_mode="HTML")
    except:
        pass
        
    await cb.message.edit_text(f"Заказ <code>{oid}</code> выполнен.\nВыдан ключ: <code>{key}</code>", parse_mode="HTML")
    await cb.answer("Готово")

@rt.message(Command("panel"))
async def panel_shortcut(m: Message):
    # Удобный шорткат для админа
    if m.from_user.id == ADMIN_ID:
        await m.answer("Админ-панель:", reply_markup=kb_admin())

async def main():
    print("Магазин OxideWH запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())