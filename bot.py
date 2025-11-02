from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters, CallbackQueryHandler
import math
import sqlite3
import os
import logging
import asyncio
import sys
import re
from datetime import datetime, timedelta
import random
import string
import time
import traceback
from dotenv import load_dotenv
import requests
import psutil  # optional: for robust PID check (install psutil) or use os

load_dotenv()  # سيحمّل القيم من .env في مجلد المشروع

# إسكات تحذيرات Deprecation العامة المتعلقة بـ asyncio.WindowsSelectorEventLoopPolicy
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise SystemExit("BOT_TOKEN missing")
DATA_ENC_KEY = os.getenv("DATA_ENC_KEY")
if not DATA_ENC_KEY:
    raise SystemExit("DATA_ENC_KEY missing")
try:
    ADMIN_ID = int(os.getenv("ADMIN_USER_ID", "0")) or 0
except Exception:
    ADMIN_ID = 0

WORK_TYPES = [
    "سباكة", "تركيب الكاميرات", "طلاء منازل", "كهربائي منازل", "شاحنات مياه صالحة للشرب",
    "عاملات نظافة وأشغال عامة", "تنظيف السجاد و المفروشات في المنزل", "فني انترنت", "توصيل رجالي", "توصيل نسائي", "سيارات الاسعاف",
    "تصوير مناسبات",
    "الخدمات التعليمية", "أخرى"
]

SERVICE_KEYS = {"الخدمات", "🛠️ الخدمات", "الخدمة", "خدمات", "عرض الخدمات", "سيرفز", "سرفز"}
CONTACT_KEYS = {"تواصل معنا", "اتصل بنا", "تواصل", "اتصل", "📞 تواصل معنا"}
ABOUT_KEYS = {"نبذة عنا", "📜 نبذة عنا", "📜نبذة عنا", "نبذة", "عن التطبيق", "من نحن"}

# Main persistent keyboard used across client interactions. Use this single instance
# so all entry points present the same buttons and avoid disappearing rows.
MAIN_MENU_LAYOUT = [["📝 التسجيل للحرفيين"], ["🛠️ الخدمات", "📜 نبذة عنا"], ["📞 تواصل معنا"]]
MAIN_KB = ReplyKeyboardMarkup(MAIN_MENU_LAYOUT, resize_keyboard=True)

user_states = {}
workers = {}

DB_PATH = os.path.join(os.path.dirname(__file__), "data.db")
LOCKFILE = os.path.join(os.path.dirname(__file__), "bot.lock")

# Windows event loop policy (suppress DeprecationWarning when calling)
import sys, asyncio
import warnings
# فقط اضبط سياسة الحلقة على ويندوز إذا كانت نسخة بايثون أقل من 3.16
if sys.platform.startswith("win"):
    try:
        if sys.version_info < (3, 16) and hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", category=DeprecationWarning, message=".*WindowsSelectorEventLoopPolicy.*")
                warnings.filterwarnings("ignore", category=DeprecationWarning, message=".*set_event_loop_policy.*")
                asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:
        pass

# ---------- DB init ----------
def add_column_if_not_exists(conn, table, column_def):
    """column_def example: 'appearance_count INTEGER DEFAULT 0'"""
    colname = column_def.split()[0]
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    cols = [r[1] for r in cur.fetchall()]
    if colname not in cols:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column_def}")
        conn.commit()

def init_db():
    try:
        logging.info("Init DB -> %s", DB_PATH)
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()

        cur.execute("""
        CREATE TABLE IF NOT EXISTS workers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE,
            name TEXT,
            phone TEXT,
            work_type TEXT,
            lat REAL,
            lon REAL,
            worker_code INTEGER,
            coupon_code TEXT,
            subscription_level INTEGER DEFAULT 0,
            subscription_expiry TIMESTAMP
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS clients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            name TEXT,
            phone TEXT,
            service TEXT,
            lat REAL,
            lon REAL,
            assigned_worker_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS coupons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE,
            amount INTEGER,
            used INTEGER DEFAULT 0,
            used_by_worker_user_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            used_at TIMESTAMP
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS ratings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            worker_user_id INTEGER,
            client_user_id INTEGER,
            rating INTEGER,
            comment TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # usage_stats table to track total users/requests
        cur.execute("""
        CREATE TABLE IF NOT EXISTS usage_stats (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            total_users INTEGER DEFAULT 0,
            total_requests INTEGER DEFAULT 0
        )
        """)
        cur.execute("INSERT OR IGNORE INTO usage_stats (id, total_users, total_requests) VALUES (1,0,0)")

        # table to track if we've greeted a user before (so first-time users get the full menu)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS seen_users (
            user_id INTEGER PRIMARY KEY,
            first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        conn.commit()

        # Ensure counter columns exist on workers (safe migration)
        try:
            add_column_if_not_exists(conn, "workers", "appearance_count INTEGER DEFAULT 0")
            add_column_if_not_exists(conn, "workers", "ratings_received INTEGER DEFAULT 0")
            add_column_if_not_exists(conn, "workers", "selected_count INTEGER DEFAULT 0")
            # new column to record education service subtype for workers who register under educational services
            add_column_if_not_exists(conn, "workers", "education_type TEXT")
        except Exception:
            logging.exception("Failed adding counter columns")

        conn.commit()
        conn.close()
        logging.info("Database initialized / migrated successfully.")
    except Exception:
        logging.exception("init_db error")

# ---------- Counters / stats helpers ----------
def increment_worker_appearance(worker_user_id, by=1):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    try:
        cur.execute("UPDATE workers SET appearance_count = COALESCE(appearance_count,0) + ? WHERE user_id = ?", (by, worker_user_id))
        conn.commit()
    finally:
        conn.close()

def increment_worker_selected(worker_user_id, by=1):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    try:
        cur.execute("UPDATE workers SET selected_count = COALESCE(selected_count,0) + ? WHERE user_id = ?", (by, worker_user_id))
        conn.commit()
    finally:
        conn.close()

def increment_worker_ratings(worker_user_id, by=1):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    try:
        cur.execute("UPDATE workers SET ratings_received = COALESCE(ratings_received,0) + ? WHERE user_id = ?", (by, worker_user_id))
        conn.commit()
    finally:
        conn.close()

def increment_usage_on_request(user_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    try:
        # اذا هذه أول مرة يطلب فيها هذا المستخدم زِدّ total_users
        cur.execute("SELECT COUNT(*) FROM clients WHERE user_id = ?", (user_id,))
        prior = cur.fetchone()[0] or 0
        if prior == 0:
            cur.execute("UPDATE usage_stats SET total_users = COALESCE(total_users,0) + 1 WHERE id = 1")
        # دوّن الطلب كـ total_requests
        cur.execute("UPDATE usage_stats SET total_requests = COALESCE(total_requests,0) + 1 WHERE id = 1")
        conn.commit()
    finally:
        conn.close()

# ---------- DB helpers (single copy) ----------
def save_worker_to_db(user_id, state):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    lat, lon = state.get("location", (None, None))
    cur.execute("SELECT id, worker_code FROM workers WHERE user_id = ?", (user_id,))
    existing = cur.fetchone()
    if existing:
        row_id, worker_code = existing
        cur.execute("UPDATE workers SET name = ?, phone = ?, work_type = ?, lat = ?, lon = ?, education_type = ? WHERE user_id = ?",
                    (state.get("name"), state.get("phone"), state.get("work_type"), lat, lon, state.get("edu_type"), user_id))
        # apply subscription fields if present in state
        if state.get("subscription_level") or state.get("subscription_expiry") or state.get("coupon_code"):
            try:
                cur.execute("UPDATE workers SET subscription_level = ?, subscription_expiry = ?, coupon_code = ? WHERE user_id = ?",
                            (state.get("subscription_level"), state.get("subscription_expiry"), state.get("coupon_code"), user_id))
            except Exception:
                logging.debug("Could not update subscription fields for existing worker")
        if not worker_code:
            worker_code = 2000 + row_id
            try:
                cur.execute("UPDATE workers SET worker_code = ? WHERE id = ?", (worker_code, row_id))
            except Exception:
                pass
        conn.commit()
        conn.close()
        return worker_code

    cur.execute("INSERT INTO workers (user_id, name, phone, work_type, lat, lon, education_type) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user_id, state.get("name"), state.get("phone"), state.get("work_type"), lat, lon, state.get("edu_type")))
    conn.commit()
    rowid = cur.lastrowid
    worker_code = 2000 + rowid
    try:
        cur.execute("UPDATE workers SET worker_code = ? WHERE id = ?", (worker_code, rowid))
        conn.commit()
    except Exception:
        pass
    # بعد الإدراج، طبق حقول الاشتراك إن وُجدت
    try:
        if state.get("subscription_level") or state.get("subscription_expiry") or state.get("coupon_code"):
            cur.execute("UPDATE workers SET subscription_level = ?, subscription_expiry = ?, coupon_code = ? WHERE id = ?",
                        (state.get("subscription_level"), state.get("subscription_expiry"), state.get("coupon_code"), rowid))
            conn.commit()
    except Exception:
        logging.debug("Could not set subscription fields for new worker")
    conn.close()
    return worker_code

def save_client_request_to_db(user_id, state, req_id=None):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    lat, lon = state.get("location", (None, None))
    name = state.get("name")
    phone = state.get("phone")
    service = state.get("service")
    if req_id:
        cur.execute("UPDATE clients SET user_id=?, name=?, phone=?, service=?, lat=?, lon=?, created_at=CURRENT_TIMESTAMP WHERE id=?",
                    (user_id, name, phone, service, lat, lon, req_id))
        conn.commit()
        cid = req_id
    else:
        cur.execute("INSERT INTO clients (user_id, name, phone, service, lat, lon) VALUES (?,?,?,?,?,?)",
                    (user_id, name, phone, service, lat, lon))
        conn.commit()
        cid = cur.lastrowid
        # تحديث إحصاءات الاستخدام عند إنشاء طلب جديد
        try:
            increment_usage_on_request(user_id)
        except Exception:
            logging.exception("Failed to increment usage stats")
    conn.close()
    return cid


def mark_user_seen(user_id):
    """Return True if this is the first time we've seen this user (inserted), False otherwise."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM seen_users WHERE user_id = ?", (user_id,))
        if cur.fetchone():
            conn.close(); return False
        cur.execute("INSERT INTO seen_users (user_id) VALUES (?)", (user_id,))
        conn.commit(); conn.close(); return True
    except Exception:
        try:
            conn.close()
        except Exception:
            pass
        return False

def save_rating_to_db(worker_user_id, client_user_id, rating, comment=None):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO ratings (worker_user_id, client_user_id, rating, comment) VALUES (?,?,?,?)",
                    (worker_user_id, client_user_id, int(rating), comment))
        conn.commit()
        # زيادة عداد التقييمات للعامل
        try:
            increment_worker_ratings(worker_user_id, by=1)
        except Exception:
            logging.exception("Failed to increment worker ratings counter")
    finally:
        conn.close()

# ---------- Bot handlers ----------
async def redeem_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_states[user_id] = {"role": "redeem", "step": "code"}
    await update.message.reply_text("أدخل كود الشحن (الكوبون) لتفعيله:")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_states.pop(user_id, None)
    await update.message.reply_text("مرحبًا بكم في بوت خدمتي", reply_markup=MAIN_KB)

async def send_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id if update.effective_user else None
    if not ADMIN_ID or uid != ADMIN_ID:
        await update.message.reply_text("ليس لديك صلاحية الوصول لواجهة الإدارة.")
        return
    try:
        subs = fetch_subscribers()
        sub_count = len(subs)
        conn = sqlite3.connect(DB_PATH); cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM workers"); workers_count = cur.fetchone()[0] or 0
        cur.execute("SELECT id, name, phone, work_type, worker_code, subscription_level, subscription_expiry FROM workers ORDER BY id DESC LIMIT 1000"); wrows = cur.fetchall()
        conn.close()
    except Exception:
        logging.exception("send_admin_panel failed")
        await update.message.reply_text("فشل في جلب بيانات لوحة الإدارة.")
        return

    header = f"لوحة الإدارة\nالمشتركون: {sub_count}\nالعمال: {workers_count}\n\n"
    sub_lines = [f"{s['id']} | {s['name'] or '-'} | {s['phone'] or '-'}" for s in subs]
    subs_text = "المشتركون (آخر):\n" + ("\n".join(sub_lines) if sub_lines else "(لا سجلات)")
    w_lines = [f"{wid} | {name or '-'} | {phone or '-'} | {wtype or '-'} | code:{wcode or '-'} | lvl:{level or 0} | exp:{expiry or '-'}" for wid, name, phone, wtype, wcode, level, expiry in wrows]
    workers_text = "العمال (آخر):\n" + ("\n".join(w_lines) if w_lines else "(لا سجلات)")
    OUT_LIMIT = 3500
    await update.message.reply_text(header)
    if len(subs_text) > OUT_LIMIT:
        from io import BytesIO
        bio = BytesIO(subs_text.encode("utf-8")); bio.name = "subscribers.txt"
        await update.message.reply_document(bio)
    else:
        await update.message.reply_text(subs_text)
    if len(workers_text) > OUT_LIMIT:
        from io import BytesIO
        bio = BytesIO(workers_text.encode("utf-8")); bio.name = "workers.txt"
        await update.message.reply_document(bio)
    else:
        await update.message.reply_text(workers_text)

async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.message.from_user.id if update.message and update.message.from_user else None
        # greet first-time users with the full main keyboard so anyone who opens the bot
        # immediately sees the available options.
        try:
            if user_id:
                if mark_user_seen(user_id):
                    try:
                        await update.message.reply_text("مرحبًا! إليك القائمة الرئيسية:", reply_markup=MAIN_KB)
                    except Exception:
                        logging.debug("Could not send first-time welcome keyboard to user %s", user_id)
        except Exception:
            logging.debug("mark_user_seen failed for user %s", user_id)
        text_orig = ""
        contact_obj = None
        if update.message:
            contact_obj = getattr(update.message, "contact", None)
            if contact_obj and getattr(contact_obj, "phone_number", None):
                text_orig = contact_obj.phone_number
            elif update.message.text:
                text_orig = update.message.text
        logging.info("RAW_MSG repr: %r ; contact=%r ; from=%s", text_orig, contact_obj, user_id)
        text = text_orig.strip()
        text_l = text.lower()
        if "conf" in text_l:
            await send_admin_panel(update, context); return
        if text_l in CONTACT_KEYS:
            phone_local = "0916564000"; phone_international = "+218916564000"; wa_number = "218916564000"
            try:
                await update.message.reply_contact(phone_number=phone_international, first_name="فريق الدعم")
            except Exception:
                logging.debug("reply_contact failed")
            wa_btn = InlineKeyboardMarkup([[InlineKeyboardButton("مراسلتنا عبر واتساب", url=f"https://wa.me/{wa_number}")]])
            # include phone number with phone emoji in the reply
            await update.message.reply_text(f"📞 للتواصل الهاتفي: {phone_local}\n\nيمكنك أيضًا مراسلتنا عبر واتساب:", reply_markup=wa_btn)
            return
        if text_l in ABOUT_KEYS:
            about_text = (
                "بوت خدمتي | تأسس عام 2025\n\n"
                "نحن بوت تيليجرام يهدف إلى تسهيل طلب الخدمات بين العملاء والحرفيين.\n"
                "كل ما عليك هو اختيار الخدمة المناسبة ثم إرسال موقعك، وسيعرض لك البوت أقرب حرفي مع جميع بيانات التواصل.\n\n"
                "✅ الخدمة مجانية تمامًا للعملاء\n"
                "💼 واشتراك رمزي للحرفيين\n\n"
                "لأي استفسار أو دعم، لا تتردد في التواصل معنا 💬"
            )
            await update.message.reply_text(about_text, reply_markup=ReplyKeyboardRemove())
            await update.message.reply_text("الرجوع إلى القائمة الرئيسية:", reply_markup=MAIN_KB)
            return

        # If user types "التسجيل للعملاء" inform them registration removed
        if text_l == "التسجيل للعملاء":
            await update.message.reply_text("تمت إزالة خاصية تسجيل العملاء. عند رغبتك بطلب خدمة اختر 'الخدمات' ثم تابع الخطوات لمشاركة بياناتك وموقعك وسيُسجل الطلب مباشرة.")
            return

        # rest of existing logic unchanged...
        if text.isdigit() and user_id not in user_states:
            req = fetch_client_request_by_id(int(text))
            if req:
                await update.message.reply_text(f"تم العثور على طلب رقم {req['id']} — الاسم: {req['name'] or '-'} — الهاتف: {req['phone'] or '-'}")
                return
        if text_l in ("التسجيل للعملاء", "📝 التسجيل للعملاء", "التسجيل للحرفيين", "📝 التسجيل للحرفيين") or text_l in SERVICE_KEYS or text_l in ABOUT_KEYS or text_l in CONTACT_KEYS:
            user_states.pop(user_id, None)
        if text_l == "التجيل للعملاء":
            name = None
            if update.effective_user:
                fn = update.effective_user.first_name or ""; ln = update.effective_user.last_name or ""; name = (fn + " " + ln).strip() or None
            contact = getattr(update.message, "contact", None)
            phone = contact.phone_number if contact and getattr(contact, "phone_number", None) else None
            user_states[user_id] = {"role": "subscriber", "step": ("location" if phone else "phone"), "name": name, "phone": phone}
            if phone:
                kb = ReplyKeyboardMarkup([[KeyboardButton("إرسال الموقع", request_location=True)]], resize_keyboard=True, one_time_keyboard=True)
                await update.message.reply_text(f"تم استخدام اسم ملفك الشخصي: {name or 'غير متوفر'}\nالآن اضغط لإرسال موقعك:", reply_markup=kb)
            else:
                kb = ReplyKeyboardMarkup([[KeyboardButton("مشاركة جهة الاتصال", request_contact=True)]], resize_keyboard=True, one_time_keyboard=True)
                await update.message.reply_text(f"سيُستخدم اسم ملفك الشخصي: {name or 'غير متوفر'}\nالرجاء مشاركة رقم هاتفك بالزر أدناه:", reply_markup=kb)
            return
        if text_l in ("التسجيل للحرفيين", "📝 التسجيل للحرفيين"):
            user_states[user_id] = {"role": "worker", "step": "name"}
            await update.message.reply_text("سجل كعامل - يرجى إدخال اسمك:")
            return
        if text_l in SERVICE_KEYS:
            kb = ReplyKeyboardMarkup([[w] for w in WORK_TYPES], resize_keyboard=True, one_time_keyboard=True)
            await update.message.reply_text("اختر الخدمة المطلوبة:", reply_markup=kb)
            return
        if text in WORK_TYPES and user_id not in user_states:
            name = None
            if update.effective_user:
                fn = update.effective_user.first_name or ""; ln = update.effective_user.last_name or ""; name = (fn + " " + ln).strip() or None
            contact = getattr(update.message, "contact", None)
            phone = contact.phone_number if contact and getattr(contact, "phone_number", None) else None
            state = {"role": "client", "service": text, "name": name, "phone": phone}
            # If client requested educational services, ask which teaching division they want
            if text == "الخدمات التعليمية":
                state["step"] = "edu_choice"
                user_states[user_id] = state
                edu_kb = ReplyKeyboardMarkup([
                    ["تمهيدي", "إعدادي"],
                    ["ثانوي أو معهد", "اكاديمي"]
                ], resize_keyboard=True, one_time_keyboard=True)
                await update.message.reply_text(f"لقد اخترت: {text}\nاختر قسم التدريس المناسب للمعلم الذي تريده:", reply_markup=edu_kb)
                return
            if phone:
                state["step"] = "location"; user_states[user_id] = state
                kb = ReplyKeyboardMarkup([[KeyboardButton("إرسال الموقع", request_location=True)]], resize_keyboard=True, one_time_keyboard=True)
                await update.message.reply_text(f"لقد اخترت: {text}\nالاسم المستخدم: {name or 'غير متوفر'}\nالآن شارك موقعك:", reply_markup=kb)
            else:
                state["step"] = "phone"; user_states[user_id] = state
                kb = ReplyKeyboardMarkup([[KeyboardButton("مشاركة جهة الاتصال", request_contact=True)]], resize_keyboard=True, one_time_keyboard=True)
                await update.message.reply_text(f"لقد اخترت: {text}\nسيُستخدم اسم ملفك الشخصي: {name or 'غير متوفر'}\nالرجاء مشاركة رقم هاتفك بالزر أدناه:", reply_markup=kb)
            return
        if user_id in user_states:
            state = user_states[user_id]
            # subscriber flow
            if state.get("role") == "subscriber":
                if state.get("step") == "name":
                    state["name"] = text; state["step"] = "phone"
                    await update.message.reply_text("يرجى إدخال رقم هاتفك أو مشاركة جهة الاتصال:"); return
                if state.get("step") == "phone":
                    if not is_valid_phone(text):
                        await update.message.reply_text("رقم الهاتف غير صالح. ارسله بصيغة 091xxxxxxx أو 9xxxxxxx أو +2189xxxxxxx."); return
                    state["phone"] = normalize_phone(text); state["step"] = "location"
                    kb = ReplyKeyboardMarkup([[KeyboardButton("إرسال الموقع", request_location=True)]], resize_keyboard=True, one_time_keyboard=True)
                    await update.message.reply_text("الآن اضغط 'إرسال الموقع' لمشاركة موقعك:", reply_markup=kb); return
            # client flow
            if state.get("role") == "client":
                if state.get("step") == "awaiting_request_id":
                    if text.isdigit():
                        req = fetch_client_request_by_id(int(text))
                        if req:
                            state["name"] = req.get("name"); state["phone"] = req.get("phone")
                            state["step"] = "location" if state.get("phone") else "phone"
                            await update.message.reply_text("تم استرجاع بيانات الطلب. أرسل موقعك أو أدخل هاتفك:", reply_markup=ReplyKeyboardMarkup([[KeyboardButton("إرسال الموقع", request_location=True)]], resize_keyboard=True, one_time_keyboard=True)); return
                    await update.message.reply_text("رمز الطلب غير صحيح. اعد المحاولة أو اكتب اسمك."); state["step"] = "name"; return
                if state.get("step") == "name":
                    if text.isdigit():
                        sub = fetch_subscriber_by_id(int(text))
                        if sub:
                            state["name"] = sub["name"]; state["phone"] = sub.get("phone"); state["step"] = "location" if state.get("phone") else "phone"
                            await update.message.reply_text("تم استرجاع بيانات المشترك. أرسل موقعك أو أدخل هاتفك:", reply_markup=ReplyKeyboardMarkup([[KeyboardButton("إرسال الموقع", request_location=True)]], resize_keyboard=True, one_time_keyboard=True)); return
                        req = fetch_client_request_by_id(int(text))
                        if req:
                            state["request_id"] = req["id"]; state["name"] = req.get("name"); state["phone"] = req.get("phone"); state["step"] = "location" if state.get("phone") else "phone"
                            await update.message.reply_text("تم استرجاع بيانات الطلب. أرسل موقعك أو ادخل هاتفك:", reply_markup=ReplyKeyboardMarkup([[KeyboardButton("إرسال الموقع", request_location=True)]], resize_keyboard=True, one_time_keyboard=True)); return
                    state["name"] = text; state["step"] = "phone"; await update.message.reply_text("يرجى إدخال رقم هاتفك أو مشاركة جهة الاتصال:"); return
                if state.get("step") == "phone":
                    if not is_valid_phone(text):
                        await update.message.reply_text("رقم الهاتف غير صالح. ارسله بصيغة 091xxxxxxx أو +2189xxxxxxx."); return
                    state["phone"] = normalize_phone(text); state["step"] = "location"
                    await update.message.reply_text("الآن اضغط 'إرسال الموقع' لمشاركة موقعك:", reply_markup=ReplyKeyboardMarkup([[KeyboardButton("إرسال الموقع", request_location=True)]], resize_keyboard=True, one_time_keyboard=True)); return
                if state.get("step") == "edu_choice":
                    # client chose which teaching division they want
                    state["edu_type"] = text
                    # after selecting edu_type proceed to phone/location as usual
                    if state.get("phone"):
                        state["step"] = "location"
                        kb = ReplyKeyboardMarkup([[KeyboardButton("إرسال الموقع", request_location=True)]], resize_keyboard=True, one_time_keyboard=True)
                        await update.message.reply_text(f"لقد اخترت: {state.get('edu_type')}\nالآن شارك موقعك:", reply_markup=kb)
                    else:
                        state["step"] = "phone"
                        kb = ReplyKeyboardMarkup([[KeyboardButton("مشاركة جهة الاتصال", request_contact=True)]], resize_keyboard=True, one_time_keyboard=True)
                        await update.message.reply_text(f"لقد اخترت: {state.get('edu_type')}\nالرجاء مشاركة رقم هاتفك بالزر أدناه:", reply_markup=kb)
                    return
            # worker flow
            if state.get("role") == "worker":
                if state.get("step") == "name":
                    state["name"] = text; state["step"] = "work_type"
                    kb = ReplyKeyboardMarkup([[w] for w in WORK_TYPES], resize_keyboard=True, one_time_keyboard=True)
                    await update.message.reply_text("اختر نوع عملك:", reply_markup=kb); return
                if state.get("step") == "work_type":
                    if text in WORK_TYPES:
                        state["work_type"] = text
                        # Special flow for educational services: ask for specific edu type to organize later
                        if text == "الخدمات التعليمية":
                            state["step"] = "edu_type"
                            edu_kb = ReplyKeyboardMarkup([
                                ["تمهيدي", "إعدادي"],
                                ["ثانوي أو معهد", "اكاديمي"]
                            ], resize_keyboard=True, one_time_keyboard=True)
                            await update.message.reply_text("اختر قسم التدريس المناسب لك (تمهيدي / إعدادي / ثانوي أو معهد / اكاديمي):", reply_markup=edu_kb)
                        else:
                            state["step"] = "phone"
                            await update.message.reply_text("يرجى إدخال رقم هاتفك أو مشاركة جهة الاتصال:")
                    else:
                        await update.message.reply_text("الرجاء اختيار نوع العمل من الأزرار.")
                    return
                if state.get("step") == "edu_type":
                    # store the educational service subtype and continue to phone step
                    state["edu_type"] = text
                    state["step"] = "phone"
                    await update.message.reply_text("شكرًا. الآن ادخل رقم هاتفك أو شارك جهة الاتصال:")
                    return
                if state.get("step") == "phone":
                    raw = text; logging.info("Worker phone raw input: %r from user %s", raw, user_id)
                    norm = normalize_phone(raw)
                    if not norm:
                        await update.message.reply_text("رقم الهاتف غير صالح. ارسله بصيغة 0912xxxxxx أو +2189xxxxxxx. حاول مرة أخرى:"); return
                    state["phone"] = norm
                    state["step"] = "choose_sub"
                    # عرض أزرار اختيار الفئة بدل طلب الكود مباشرة
                    sub_kb = InlineKeyboardMarkup([
                        [InlineKeyboardButton("الفئة الذهبية — 100 د.ل", callback_data=f"pick_sub:gold")],
                        [InlineKeyboardButton("الفئة الفضية — 60 د.ل", callback_data=f"pick_sub:silver")]
                    ])
                    await update.message.reply_text("اختر نوع الاشتراك الذي تريد تفعيله ثم أدخل كود القسيمة المناسب:", reply_markup=sub_kb)
                    return
                if state.get("step") == "await_coupon_code":
                    code_input = text.strip()
                    if not code_input:
                        await update.message.reply_text("الرجاء إدخال كود صالح."); return

                    # ابحث عن القسيمة في DB مع بعض التحويرات (VIP-.. أو بصيغة بدون أصفار بادئة)
                    raw = re.sub(r"[^\w\-]", "", code_input.strip().upper())
                    raw_nz = re.sub(r"^0+", "", raw)
                    candidates = []
                    for cand in (raw, raw_nz):
                        if cand:
                            candidates.append(cand)
                            if not cand.startswith("VIP-"):
                                candidates.append("VIP-" + cand)
                    seen = []
                    candidates = [c for c in candidates if c and (c not in seen and not seen.append(c))]

                    conn = sqlite3.connect(DB_PATH)
                    cur = conn.cursor()
                    found = None
                    for c in candidates:
                        cur.execute("SELECT id, amount, used, code FROM coupons WHERE UPPER(code) = ?", (c.upper(),))
                        row = cur.fetchone()
                        if row:
                            found = row
                            break
                    if not found:
                        conn.close()
                        await update.message.reply_text("الكود غير موجود أو غير صالح."); return
                    cid, amount, used, actual_code = found
                    if used:
                        conn.close()
                        await update.message.reply_text("هذا الكود مُستخدم مسبقاً."); return

                    desired = state.get("desired_tier")
                    if desired == "gold" and int(amount) != 100:
                        conn.close()
                        await update.message.reply_text("هذا الكود ليس مخصصًا للفئة الذهبية. استخدم كودًا بفئة 100 د.ل."); return
                    if desired == "silver" and int(amount) != 60:
                        conn.close()
                        await update.message.reply_text("هذا الكود ليس مخصصًا للفئة الفضية. استخدم كودًا بفئة 60 د.ل."); return

                    # تحديد المستوى والمدة حسب الاختيار (التوافق مع متطلباتك)
                    if desired == "gold":
                        level = 1; days = 32; tier_name = "ذهبي"
                    else:
                        level = 2; days = 30; tier_name = "فضي"
                    expiry = datetime.utcnow() + timedelta(days=days)
                    expiry_iso = expiry.isoformat()

                    try:
                        # وسم القسيمة كمستخدمة
                        cur.execute("UPDATE coupons SET used=1, used_by_worker_user_id=?, used_at=? WHERE id=?", (user_id, expiry_iso, cid))
                        # خزّن معلومات الاشتراك مؤقتاً في state (سيتم حفظها عند حفظ العامل بعد الموقع)
                        state["subscription_level"] = level
                        state["subscription_expiry"] = expiry_iso
                        state["coupon_code"] = actual_code
                        conn.commit()
                        conn.close()
                        state["step"] = "location"
                        user_states[user_id] = state
                        kb = ReplyKeyboardMarkup([[KeyboardButton("إرسال الموقع", request_location=True)]], resize_keyboard=True, one_time_keyboard=True)
                        await update.message.reply_text(f"تم قبول الكود للفئة {tier_name}. الآن اضغط 'إرسال الموقع' لمشاركة موقعك:", reply_markup=kb)
                    except Exception:
                        conn.close()
                        logging.exception("Error while marking coupon used")
                        await update.message.reply_text("حدث خطأ أثناء تفعيل الكود. حاول مرة أخرى أو تواصل مع الدعم.")
                    return
            # redeem flow
            if state.get("role") == "redeem" and state.get("step") == "code":
                code = text.strip(); ok, msg = redeem_coupon_for_worker(code, user_id)
                await update.message.reply_text(msg); user_states.pop(user_id, None); return
    except Exception:
        logging.exception("Error in handle_buttons")
        try:
            await update.message.reply_text("حدث خطأ داخلي. أعد المحاولة أو اكتب /start.")
        except Exception:
            pass
    await update.message.reply_text("لم أفهم. استخدم الأزرار أو اكتب /start للعودة للقائمة.", reply_markup=MAIN_KB)

async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        msg = update.message
        if not msg or not msg.contact:
            return
        user_id = msg.from_user.id
        phone_raw = msg.contact.phone_number
        logging.info("handle_contact: user=%s phone=%r", user_id, phone_raw)
        if not phone_raw:
            await msg.reply_text("لم نتلقَ رقم هاتف. أعد مشاركة جهة الاتصال."); return
        phone = normalize_phone(phone_raw)
        if not phone:
            await msg.reply_text("رقم الهاتف غير صالح. استخدم 091xxxxxxx أو +2189xxxxxxx."); return
        state = user_states.get(user_id)
        if not state:
            await msg.reply_text("ابدأ من جديد بالضغط على /start."); return
        role = state.get("role"); step = state.get("step")
        if role in ("subscriber", "client") and step == "phone":
            state["phone"] = phone; state["step"] = "location"
            kb = ReplyKeyboardMarkup([[KeyboardButton("إرسال الموقع", request_location=True)]], resize_keyboard=True, one_time_keyboard=True)
            await msg.reply_text("تم استلام رقمك. الآن شارك موقعك.", reply_markup=kb); return
        if role == "worker" and step == "phone":
            state["phone"] = phone; state["step"] = "coupon"
            await msg.reply_text("أدخل كود الاشتراك لتكملة التسجيل."); return
        await msg.reply_text("تم حفظ جهة الاتصال. تابع أو اكتب /start.")
    except Exception:
        logging.exception("Error in handle_contact")
        try:
            await update.message.reply_text("حدث خطأ أثناء معالجة جهة الاتصال. أعد المحاولة أو /start.")
        except Exception:
            pass

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        if not query:
            return
        await query.answer()
        data = query.data or ""
        user_id = query.from_user.id

        # user chose subscription type during التسجيل
        if data.startswith("pick_sub:"):
            parts = data.split(":")
            if len(parts) != 2:
                await query.edit_message_text("خطأ في اختيار الفئة. حاول مرة أخرى.")
                return
            tier = parts[1]
            state = user_states.get(user_id, {})
            if state.get("role") != "worker":
                await query.edit_message_text("هذه الخاصية متاحة فقط للعاملين أثناء التسجيل.")
                return
            state["desired_tier"] = tier
            state["step"] = "await_coupon_code"
            user_states[user_id] = state
            try:
                await query.edit_message_text(f"لقد اخترت الفئة: {'ذهبية' if tier=='gold' else 'فضية'}.\nأدخل الآن كود القسيمة المناسب لهذه الفئة:")
            except Exception:
                await query.message.reply_text("أدخل الآن كود القسيمة المناسب لهذه الفئة:")
            return

        # user chose a worker for their request: format choose:{client_id}:{worker_user_id}
        if data.startswith("choose:"):
            parts = data.split(":")
            if len(parts) != 3:
                await query.edit_message_text("خطأ في اختيار العامل. حاول مرة أخرى.")
                return
            client_id = int(parts[1])
            try:
                worker_user_id = int(parts[2])
            except Exception:
                await query.edit_message_text("خطأ في معرف العامل.")
                return
            # سجل التعيين في DB وزدّ عداد الاختيار
            try:
                assign_worker_to_client(client_id, worker_user_id)
                increment_worker_selected(worker_user_id, by=1)
            except Exception:
                logging.exception("Failed to assign worker")
                await query.edit_message_text("حدث خطأ أثناء اختيار العامل. حاول مرة أخرى.")
                return
            # تأكيد للمستخدم وإعلام العامل
            await query.edit_message_text("تم اختيار هذا الحرفي وسيتم التواصل معه. شكراً.")
            try:
                # حاول إرسال إشعار للعامل إن أمكن
                await context.bot.send_message(worker_user_id, f"تم اختيارك لطلب رقم {client_id} من قبل المستخدم {user_id}.")
            except Exception:
                logging.debug("Could not notify worker (maybe hasn't started the bot).")
            return

        # فتح نافذة تقييم
        if data.startswith("open_rate:"):
            parts = data.split(":")
            if len(parts) != 2:
                await query.edit_message_text("خطأ في فتح صفحة التقييم.")
                return
            try:
                target_worker = int(parts[1])
            except Exception:
                await query.edit_message_text("خطأ في معرف العامل."); return
            # أرسل أزرار تقييم بسيطة (1-5)
            kb = InlineKeyboardMarkup([[InlineKeyboardButton(str(i), callback_data=f"rate:{target_worker}:{i}") for i in range(1,6)]])
            try:
                await query.message.reply_text("اختر تقييمك (1-5):", reply_markup=kb)
            except Exception:
                await query.edit_message_text("اختر تقييمك (1-5):")
            return

        # استلام تقييم
        if data.startswith("rate:"):
            parts = data.split(":")
            if len(parts) < 3:
                await query.edit_message_text("خطأ في التقييم.")
                return
            try:
                target_worker = int(parts[1]); score = int(parts[2])
            except Exception:
                await query.edit_message_text("خطأ في بيانات التقييم."); return
            # حفظ التقييم
            try:
                save_rating_to_db(target_worker, user_id, score, comment=None)
                await query.message.reply_text("شكراً لتقييمك.")
            except Exception:
                logging.exception("Failed saving rating")
                await query.message.reply_text("حدث خطأ أثناء حفظ التقييم.")
            return

        # ...existing callback handling for other cases...
    except Exception:
        logging.exception("Error in handle_callback")
        try:
            if update.callback_query:
                await update.callback_query.edit_message_text("حدث خطأ أثناء المعالجة.")
        except Exception:
            pass

async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.message.from_user.id
        logging.info("handle_location called for user %s ; update=%r", user_id, update)
        state = user_states.get(user_id)
        if not state:
            await update.message.reply_text("لم يتم تحديد عملية سابقة. اضغط أحد الأزرار في القائمة أو اكتب /start للبدء."); return
        if not getattr(update.message, "location", None):
            await update.message.reply_text("لم نتلقَ الموقع. الرجاء استخدام زر 'إرسال الموقع' لمشاركة موقعك."); return
        lat = update.message.location.latitude; lon = update.message.location.longitude
        # use the shared main keyboard so buttons are consistent for clients
        main_kb = MAIN_KB

        # subscriber branch removed (no more saving subscribers)

        # worker branch (unchanged)
        if state.get("role") == "worker" and state.get("step") in ("location",):
            state["location"] = (lat, lon)
            try:
                worker_id = save_worker_to_db(user_id, state)
            except Exception:
                logging.exception("Failed saving worker")
                await update.message.reply_text("حدث خطأ أثناء حفظ بيانات العامل. حاول مرة أخرى لاحقاً أو اكتب /start.")
                if ADMIN_ID:
                    tb = traceback.format_exc(); await context.bot.send_message(ADMIN_ID, f"Error saving worker {user_id}:\n{tb[:3000]}")
                return
            workers[user_id] = state.copy(); user_states.pop(user_id, None)
            await update.message.reply_text(f"شكراً لتسجيلك كعامل.\nتم حفظ بياناتك.\nرقم المعرف: {worker_id}", reply_markup=ReplyKeyboardRemove())

            sub_kb = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("اشتراك الفئة الذهبية", callback_data=f"sub:gold:{worker_id}"),
                    InlineKeyboardButton("الفئة الفضية", callback_data=f"sub:silver:{worker_id}")
                ]
            ])
            await update.message.reply_text(
                "اختر اشتراكك لتحصل على مميزات إضافية (أولوية في الظهور وغيرها):",
                reply_markup=sub_kb
            )

            await update.message.reply_text("الرجوع إلى القائمة الرئيسية:", reply_markup=main_kb); return

        # client request flow unchanged (clients are recorded as requests directly)
        if state.get("role") == "client" and state.get("step") in ("location",):
            state["location"] = (lat, lon)
            service = state.get("service")
            # If this is an educational service request, filter workers by the requested edu_type
            if service == "الخدمات التعليمية":
                db_workers = fetch_workers_by_service(service, edu_type=state.get("edu_type"))
            else:
                db_workers = fetch_workers_by_service(service)
            MAX_KM = 100.0
            workers_in_range = []
            for w in db_workers:
                try:
                    if not w.get("location") or None in w.get("location"): continue
                    dist_km = calc_distance(state["location"], w["location"])
                    if dist_km <= MAX_KM:
                        workers_in_range.append({
                            "id": w.get("id"),
                            "user_id": w.get("user_id"),
                            "name": w.get("name"),
                            "phone": w.get("phone"),
                            "work_type": w.get("work_type"),
                            "location": w.get("location"),
                            "subscription_level": int(w.get("subscription_level") or 0),
                            "subscription_expiry": w.get("subscription_expiry"),
                            "dist_km": dist_km
                        })
                except Exception:
                    logging.exception("Error computing distance for worker row: %r", w)
            try:
                client_id = save_client_request_to_db(user_id, state, req_id=state.get("request_id"))
            except Exception:
                logging.exception("Failed saving client request")
                await update.message.reply_text("حدث خطأ أثناء حفظ طلبك. حاول مرة واحدة أخرى أو اكتب /start.")
                if ADMIN_ID:
                    tb = traceback.format_exc(); await context.bot.send_message(ADMIN_ID, f"Error saving client request {user_id}:\n{tb[:3000]}")
                return
            if not workers_in_range:
                await update.message.reply_text("عذراً، لا يوجد عمال متوفرون بنفس الخدمة ضمن 100 كم.", reply_markup=ReplyKeyboardRemove())
            else:
                workers_in_range.sort(key=lambda x: (-x["subscription_level"], x["dist_km"]))
                for w in workers_in_range:
                    # زيادة ظهور الحرفي لأننا سانعرضه للمستخدم
                    try:
                        increment_worker_appearance(w['user_id'], by=1)
                    except Exception:
                        logging.debug("Failed increment appearance for worker %s", w['user_id'])
                    block = (
                        "━━━━━━━━━━━━━━━━━━━━\n"
                        f"الاسم: {w.get('name') or '-'}\n"
                        f"الخدمة: {w.get('work_type') or service}\n"
                        f"الهاتف: {w.get('phone') or '-'}\n"
                        f"المسافة: ≈{w['dist_km']:.1f} كم\n"
                        "━━━━━━━━━━━━━━━━━━━━"
                    )
                    kb = InlineKeyboardMarkup([[InlineKeyboardButton("اختر هذا الحرفي", callback_data=f"choose:{client_id}:{w['user_id']}"),
                                                InlineKeyboardButton("قيّم", callback_data=f"open_rate:{w['user_id']}")]])
                    await update.message.reply_text(block, reply_markup=kb)
            user_states.pop(user_id, None)
            await update.message.reply_text(f"شكراً. رقم الطلب الخاص بك: {client_id}", reply_markup=main_kb)
            return

        logging.info("handle_location: unexpected state for user %s -> %s", user_id, state)
        await update.message.reply_text("تعذّر إكمال العملية. الرجاء البدء من جديد بالضغط على /start أو زر في القائمة.", reply_markup=main_kb)
    except Exception:
        logging.exception("Error in handle_location")
        try:
            await update.message.reply_text("حدث خطأ داخلي عند معالجة الموقع. أعد المحاولة أو اكتب /start.")
        except Exception:
            pass
        if ADMIN_ID:
            tb = traceback.format_exc(); await context.bot.send_message(ADMIN_ID, f"Exception in handle_location for user {user_id}:\n{tb[:3000]}")

async def myid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    sub = fetch_subscriber_by_user_id(user_id)
    if not sub:
        await update.message.reply_text("أنت غير مسجل كمشترك. استخدم 'sign up for client' للتسجيل."); return
    await update.message.reply_text(f"رقم التعريف الخاص بك هو: {sub['id']}")

async def list_subscribers_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    subs = fetch_subscribers()
    if not subs:
        await update.message.reply_text("لا يوجد مشتركين مسجلين."); return
    lines = [f"{s['id']} — {s['name'] or 'لا اسم'} ({s['phone'] or 'لا هاتف'})" for s in subs[:100]]
    text = "المشتركون (آخر 100):\n" + "\n".join(lines)
    if len(text) > 4000:
        from io import BytesIO
        bio = BytesIO(text.encode("utf-8")); bio.name = "subscribers.txt"; await update.message.reply_document(bio)
    else:
        await update.message.reply_text(text)

# ---------- Helpers (phone / utils) ----------
def is_valid_phone(s):
    if not s:
        return False
    d = re.sub(r"\D", "", str(s))
    # International starting with country code 2189...
    if d.startswith("218") and len(d) >= 11 and d[3] == "9":
        return True
    # Local formats: 0XXXXXXXXX or 9XXXXXXX
    if d.startswith("0") and len(d) == 10 and d[1] == "9":
        return True
    if len(d) == 8 and d[0] == "9":
        return True
    return False

def normalize_phone(s):
    if not s:
        return None
    d = re.sub(r"\D", "", str(s))
    # drop country code 218 and ensure leading 0
    if d.startswith("218") and len(d) >= 11:
        d = d[3:]
        if not d.startswith("0"):
            d = "0" + d
    elif len(d) == 8 and d[0] == "9":
        d = "0" + d
    elif len(d) == 10 and d.startswith("0"):
        pass
    else:
        return None
    return d

def calc_distance(loc1, loc2):
    """Haversine distance in kilometers between two (lat, lon)."""
    try:
        lat1, lon1 = loc1
        lat2, lon2 = loc2
        R = 6371.0
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    except Exception:
        return float("inf")

def make_code(length=8):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

# ---------- Safe fetch helpers (add these) ----------
def fetch_workers_by_service(service, edu_type=None):
    """
    Fetch workers by work_type. If service is educational and edu_type is provided,
    filter by education_type as well so clients match only teachers of the requested division.
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        if service == "الخدمات التعليمية" and edu_type:
            cur.execute("SELECT id, user_id, name, phone, lat, lon, subscription_level, subscription_expiry, worker_code, work_type, education_type FROM workers WHERE work_type = ? AND education_type = ?", (service, edu_type))
        else:
            cur.execute("SELECT id, user_id, name, phone, lat, lon, subscription_level, subscription_expiry, worker_code, work_type, education_type FROM workers WHERE work_type = ?", (service,))
        rows = cur.fetchall()
        conn.close()
        results = []
        for r in rows:
            results.append({
                "id": r[0],
                "user_id": r[1],
                "name": r[2],
                "phone": r[3],
                "location": (r[4], r[5]),
                "subscription_level": r[6],
                "subscription_expiry": r[7],
                "worker_code": r[8],
                "work_type": r[9],
                "education_type": r[10]
            })
        return results
    except sqlite3.OperationalError:
        return []
    except Exception:
        logging.exception("fetch_workers_by_service failed")
        return []

def fetch_client_request_by_id(rid):
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT id, user_id, name, phone, service, lat, lon, assigned_worker_id FROM clients WHERE id = ?", (rid,))
        r = cur.fetchone()
        conn.close()
        if not r:
            return None
        return {"id": r[0], "user_id": r[1], "name": r[2], "phone": r[3], "service": r[4], "location": (r[5], r[6]), "assigned_worker_id": r[7]}
    except sqlite3.OperationalError:
        return None
    except Exception:
        logging.exception("fetch_client_request_by_id failed")
        return None

def fetch_subscriber_by_id(sid):
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT id, name, phone, lat, lon FROM subscribers WHERE id = ?", (sid,))
        r = cur.fetchone()
        conn.close()
        if not r:
            return None
        return {"id": r[0], "name": r[1], "phone": r[2], "location": (r[3], r[4])}
    except sqlite3.OperationalError:
        return None
    except Exception:
        logging.exception("fetch_subscriber_by_id failed")
        return None

def fetch_subscriber_by_user_id(user_id):
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT id, user_id, name, phone, lat, lon FROM subscribers WHERE user_id = ?", (user_id,))
        r = cur.fetchone()
        conn.close()
        if not r:
            return None
        return {"id": r[0], "user_id": r[1], "name": r[2], "phone": r[3], "location": (r[4], r[5])}
    except sqlite3.OperationalError:
        return None
    except Exception:
        logging.exception("fetch_subscriber_by_user_id failed")
        return None

def fetch_subscribers(limit=100):
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT id, name, phone FROM subscribers ORDER BY id DESC LIMIT ?", (limit,))
        rows = cur.fetchall()
        conn.close()
        return [{"id": r[0], "name": r[1], "phone": r[2]} for r in rows]
    except sqlite3.OperationalError:
        return []
    except Exception:
        logging.exception("fetch_subscribers failed")
        return []

# Update admin panel to use safe fetch functions
async def send_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id if update.effective_user else None
    if not ADMIN_ID or uid != ADMIN_ID:
        await update.message.reply_text("ليس لديك صلاحية الوصول لواجهة الإدارة.")
        return
    try:
        subs = fetch_subscribers()
        sub_count = len(subs)
        conn = sqlite3.connect(DB_PATH); cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM workers"); workers_count = cur.fetchone()[0] or 0
        cur.execute("SELECT id, name, phone, work_type, worker_code, subscription_level, subscription_expiry FROM workers ORDER BY id DESC LIMIT 1000"); wrows = cur.fetchall()
        conn.close()
    except Exception:
        logging.exception("send_admin_panel failed")
        await update.message.reply_text("فشل في جلب بيانات لوحة الإدارة.")
        return

    header = f"لوحة الإدارة\nالمشتركون: {sub_count}\nالعمال: {workers_count}\n\n"
    sub_lines = [f"{s['id']} | {s['name'] or '-'} | {s['phone'] or '-'}" for s in subs]
    subs_text = "المشتركون (آخر):\n" + ("\n".join(sub_lines) if sub_lines else "(لا سجلات)")
    w_lines = [f"{wid} | {name or '-'} | {phone or '-'} | {wtype or '-'} | code:{wcode or '-'} | lvl:{level or 0} | exp:{expiry or '-'}" for wid, name, phone, wtype, wcode, level, expiry in wrows]
    workers_text = "العمال (آخر):\n" + ("\n".join(w_lines) if w_lines else "(لا سجلات)")
    OUT_LIMIT = 3500
    await update.message.reply_text(header)
    if len(subs_text) > OUT_LIMIT:
        from io import BytesIO
        bio = BytesIO(subs_text.encode("utf-8")); bio.name = "subscribers.txt"
        await update.message.reply_document(bio)
    else:
        await update.message.reply_text(subs_text)
    if len(workers_text) > OUT_LIMIT:
        from io import BytesIO
        bio = BytesIO(workers_text.encode("utf-8")); bio.name = "workers.txt"
        await update.message.reply_document(bio)
    else:
        await update.message.reply_text(workers_text)

async def _global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    # Simple global handler: only log the exception server-side.
    try:
        err = getattr(context, "error", None)
        logging.exception("Unhandled exception in update: %s", err or "")
        # لا نرسل أي تفاصيل إلى الأدمن من الواجهة — فقط سجل واصلح لاحقاً على الخادم.
    except Exception:
        logging.exception("Error in global error handler")

if __name__ == "__main__":
    # تهيئة DB
    init_db()

    # تحقق من وجود قفل سابق وحاول قراءته (هادئ، لا يقاطع التشغيل)
    try:
        if os.path.exists(LOCKFILE):
            try:
                with open(LOCKFILE, "r") as f:
                    old = f.read().strip()
                    logging.info("Found lock file, previous pid: %s", old)
            except Exception:
                logging.debug("Could not read lock file")
    except Exception:
        logging.debug("Lock check failed")

    # اكتب قفل جديد مع PID الحالي
    try:
        with open(LOCKFILE, "w") as f:
            f.write(str(os.getpid()))
    except Exception:
        logging.exception("Could not write lock file")

    # إنشاء التطبيق وإضافة المعالجات
    app = Application.builder().token(TOKEN).build()

    # أوامر
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("redeem", redeem_cmd))
    app.add_handler(CommandHandler("myid", myid_cmd))
    app.add_handler(CommandHandler("list_subscribers", list_subscribers_cmd))

    # رسائل وأزرار، جهات اتصال، مواقع، واستدعاءات callback
    app.add_handler(MessageHandler(filters.CONTACT, handle_contact))
    app.add_handler(MessageHandler(filters.LOCATION, handle_location))
    app.add_handler(CallbackQueryHandler(handle_callback))
    # أي نص غير أمر يعالج بواسطة handle_buttons
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_buttons))

    # معالج أخطاء عام (صامت للأدمن كما عدّلنا)
    try:
        app.add_error_handler(_global_error_handler)
    except Exception:
        logging.debug("Could not set global error handler")

    # تشغيل البوت مع تنظيف ملف القفل عند التوقف
    try:
        logging.info("Starting Application (bot) ...")

        # Ensure an asyncio event loop exists on the main thread (fix RuntimeError: no current event loop)
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = None
        if loop is None:
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            except Exception:
                logging.debug("Could not create/set new event loop; continuing with default behavior.")

        app.run_polling(allowed_updates= ["message", "callback_query", "edited_message", "channel_post", "my_chat_member", "chat_member"])
    except Exception:
        logging.exception("Application.run_polling exited with exception")
    finally:
        try:
            if os.path.exists(LOCKFILE):
                os.remove(LOCKFILE)
        except Exception:
            logging.debug("Could not remove lock file on exit")