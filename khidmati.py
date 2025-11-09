from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters, CallbackQueryHandler
import sqlite3
import os
import logging
import re
from dotenv import load_dotenv
import math
import datetime

load_dotenv()
logging.basicConfig(level=logging.INFO)
TOKEN = os.getenv("BOT_TOKEN") or ""
ADMIN_ID = int(os.getenv("ADMIN_USER_ID", "0")) or 0
DB_PATH = os.path.join(os.path.dirname(__file__), "data.db")

# Categories -> services mapping (category first UX)
SERVICE_CATEGORIES = {
    "🏠 الصيانة المنزلية": ["🔧سباكة", "🎨طلاء منازل", "🪑تركيب الأثاث", "🧱أرضيات"],
    "👩‍🔧 خدمات النظافة المنزلية": ["🧹عاملات نظافة وأشغال عامة", "🧺تنظيف السجاد والمفروشات في المنزل"],
    "🔌 الخدمات الكهربائية والتقنية🔌": ["🔧تركيب الكاميرات", "💻فني انترنت", "⚡كهربائي منازل"],
    "🚚 النقل والخدمات الميدانية 🚚": ["🚹توصيل رجالي", "🚺توصيل نسائي", "🚘سيارات إسعاف", "🚚 سيارات نقل", "💧سيارات مياه صالحة للشرب"],
    "📚 الخدمات التعليمية": ["📚 تمهيدي", "📚 اعدادي", "📚 ثانوي أو معهد", "📚 اكاديمي"],
    "💈 حلاقتك في حوشك": [],
    "🎊تصوير و تنسيق الحدائق": ["📸 تصوير المناسبات", "🌿 تنسيق الحدائق"]
}

WORK_TYPES = []
# Build work types list from SERVICE_CATEGORIES. If a category has sub-services,
# include them; if a category has no sub-services (like the "حلاقتك في حوشك" entry)
# include the category key itself so it can be selected directly by clients.
for cat, vals in SERVICE_CATEGORIES.items():
    if vals:
        WORK_TYPES.extend(vals)
    else:
        WORK_TYPES.append(cat)

# (WORK_TYPES_NORMALIZED will be built after normalize_label is defined)

SERVICE_KEYS = {"الخدمات", "🛠️ الخدمات", "الخدمة", "خدمات", "عرض الخدمات", "سيرفز", "سرفز"}
CONTACT_KEYS = {"تواصل معنا", "اتصل بنا", "تواصل", "اتصل", "📞 تواصل معنا"}
ABOUT_KEYS = {"نبذة عنا", "📜 نبذة عنا", "📜نبذة عنا", "نبذة", "عن التطبيق", "من نحن"}


def normalize_label(s: str) -> str:
    """Normalize a label by removing emojis/special chars and lowercasing for matching."""
    if not s:
        return ""
    # keep Arabic letters, Latin letters, digits and spaces
    import re
    cleaned = re.sub(r"[^\w\u0600-\u06FF\s]", "", s)
    # remove spaces after the Arabic conjunction 'و' (e.g. 'و المفروشات' -> 'والمفروشات')
    cleaned = re.sub(r"و\s+", "و", cleaned)
    # collapse multiple whitespace to single space
    cleaned = re.sub(r"\s+", " ", cleaned)
    # remove Arabic diacritics (tashkeel)
    cleaned = re.sub(r"[\u064B-\u0652]", "", cleaned)
    # normalize Alef/Hamza variants to bare Alef
    cleaned = re.sub(r"[إأآ]", "ا", cleaned)
    # normalize final Alef Maqsura to Ya
    cleaned = cleaned.replace("ى", "ي")
    # remove tatweel/kashida
    cleaned = cleaned.replace("ـ", "")
    return cleaned.strip().lower()


def strip_definite_article(s: str) -> str:
    """Remove Arabic definite article 'ال' from the start of words to allow matching
    user input without the article (e.g. 'تركيب كاميرات' -> match 'تركيب الكاميرات')."""
    if not s:
        return s
    parts = []
    for w in s.split():
        if w.startswith("ال") and len(w) > 2:
            parts.append(w[2:])
        else:
            parts.append(w)
    return " ".join(parts)

# build reverse map: normalized -> canonical category key
CATEGORY_NORMALIZED = {normalize_label(k): k for k in SERVICE_CATEGORIES.keys()}
SERVICE_KEYS_NORMALIZED = {normalize_label(s) for s in SERVICE_KEYS}

MAIN_MENU_LAYOUT = [["🛠️ الخدمات", "📝 التسجيل للحرفيين"], ["🔓 تفعيل الاشتراك", "📊حسابي"], ["📜 نبذة عنا", "📞 تواصل معنا"]]
MAIN_KB = ReplyKeyboardMarkup(MAIN_MENU_LAYOUT, resize_keyboard=True)

# normalized reverse map for work types so users can type without emojis
# e.g. "تركيب كاميرات" -> canonical "🔧تركيب الكاميرات"
WORK_TYPES_NORMALIZED = {}
# include both the plain normalized label and a version with the definite article
for w in WORK_TYPES:
    k = normalize_label(w)
    WORK_TYPES_NORMALIZED.setdefault(k, w)
    k2 = strip_definite_article(k)
    if k2 and k2 != k:
        WORK_TYPES_NORMALIZED.setdefault(k2, w)

user_states = {}


def make_reply_kb(rows, include_back=True):
    """Create a ReplyKeyboardMarkup from rows where each row is a list of strings or KeyboardButton.
    Optionally append a 'رجوع' row.
    """
    kb_rows = []
    for r in rows:
        row = []
        for item in r:
            if isinstance(item, KeyboardButton):
                row.append(item)
            else:
                row.append(KeyboardButton(str(item)))
        kb_rows.append(row)
    if include_back:
        kb_rows.append([KeyboardButton("رجوع")])
    return ReplyKeyboardMarkup(kb_rows, resize_keyboard=True)

# Build the main keyboard without an extra "رجوع" row per request.
# The global back button will still be available in sub-menus, but the
# main menu should not include a persistent "رجوع" button.
MAIN_KB = make_reply_kb(MAIN_MENU_LAYOUT, include_back=False)


def haversine(lat1, lon1, lat2, lon2):
    # return distance in kilometers
    R = 6371.0
    try:
        phi1 = math.radians(float(lat1))
        phi2 = math.radians(float(lat2))
        dphi = math.radians(float(lat2) - float(lat1))
        dlambda = math.radians(float(lon2) - float(lon1))
    except Exception:
        return 99999.0
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    # base table (keep compatible with create_db.py)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS workers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER UNIQUE,
        name TEXT,
        phone TEXT,
        work_type TEXT,
        worker_code INTEGER
    )
    """)
    # Ensure optional columns exist (safe migrations)
    existing = {r[1] for r in cur.execute("PRAGMA table_info(workers)").fetchall()}
    extras = {
        'lat': 'REAL', 'lon': 'REAL', 'vehicle_type': 'TEXT', 'edu_specialty': 'TEXT',
        'floor_type': 'TEXT', 'tier': 'TEXT', 'appearance_count': 'INTEGER DEFAULT 0',
        'selection_count': 'INTEGER DEFAULT 0', 'avg_rating': 'REAL DEFAULT 0', 'ratings_received': 'INTEGER DEFAULT 0', 'subscription_end': 'TEXT',
        'subscription_level': 'INTEGER', 'subscription_expiry': 'TEXT', 'coupon_code': 'TEXT'
    }
    for col, coldef in extras.items():
        if col not in existing:
            try:
                cur.execute(f"ALTER TABLE workers ADD COLUMN {col} {coldef}")
            except Exception:
                pass
    # coupons table (used by coupon generation script)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS coupons (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE,
        amount INTEGER,
        used INTEGER DEFAULT 0
    )
    """)
    # ensure coupon metadata columns exist
    existing_c = {r[1] for r in cur.execute("PRAGMA table_info(coupons)").fetchall()}
    c_extras = {
        'used_by_worker_user_id': 'INTEGER', 'used_at': 'TEXT'
    }
    for col, coldef in c_extras.items():
        if col not in existing_c:
            try:
                cur.execute(f"ALTER TABLE coupons ADD COLUMN {col} {coldef}")
            except Exception:
                pass
    conn.commit(); conn.close()

def save_worker_to_db(user_id, state):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT id, worker_code FROM workers WHERE user_id = ?", (user_id,))
    r = cur.fetchone()
    if r:
        cur.execute(
            "UPDATE workers SET name=?, phone=?, work_type=?, lat=?, lon=?, vehicle_type=?, edu_specialty=?, floor_type=?, tier=?, subscription_end=? WHERE user_id=?",
            (state.get("name"), state.get("phone"), state.get("work_type"), state.get("lat"), state.get("lon"), state.get("vehicle_type"), state.get("edu_specialty"), state.get("floor_type"), state.get("tier"), state.get("subscription_end"), user_id)
        )
    else:
        cur.execute(
            "INSERT INTO workers (user_id, name, phone, work_type, lat, lon, vehicle_type, edu_specialty, floor_type, tier, subscription_end) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (user_id, state.get("name"), state.get("phone"), state.get("work_type"), state.get("lat"), state.get("lon"), state.get("vehicle_type"), state.get("edu_specialty"), state.get("floor_type"), state.get("tier"), state.get("subscription_end"))
        )
        # ensure worker_code exists
        cur.execute("SELECT id, worker_code FROM workers WHERE user_id = ?", (user_id,))
        new = cur.fetchone()
        if new and (not new[1]):
            code = 2000 + new[0]
            try:
                cur.execute("UPDATE workers SET worker_code=? WHERE id=?", (code, new[0]))
            except Exception:
                pass
    conn.commit(); conn.close()

def fetch_worker_by_code(code):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT id, user_id, name, phone, work_type, worker_code, lat, lon, tier, appearance_count, selection_count, avg_rating, subscription_end, subscription_level, subscription_expiry, coupon_code FROM workers WHERE worker_code=?", (code,))
    r = cur.fetchone()
    conn.close()
    if not r:
        return None
    keys = ['id','user_id','name','phone','work_type','worker_code','lat','lon','tier','appearance_count','selection_count','avg_rating','subscription_end','subscription_level','subscription_expiry','coupon_code']
    return dict(zip(keys, r))


def redeem_coupon_for_worker(code_input, requesting_user_id, target_worker_user_id=None, desired_tier=None):
    code = (code_input or "").strip().upper()
    if not code:
        return False, "الكود فارغ."
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    # allow multiple candidate formats: raw, with hyphens
    candidates = [code]
    if '-' in code:
        candidates.append(code.replace('-', ''))
    try:
        found = None
        for c in candidates:
            cur.execute("SELECT id, amount, used, code FROM coupons WHERE UPPER(code)=?", (c.upper(),))
            row = cur.fetchone()
            if row:
                found = row
                break
        if not found:
            conn.close()
            return False, "الكود غير موجود أو غير صالح."
        cid, amount, used, actual_code = found
        if used:
            conn.close()
            return False, "هذا الكود مُستخدم مسبقاً."

        # Validate desired_tier vs coupon amount
        if desired_tier:
            if desired_tier == "gold" and int(amount) != 100:
                conn.close(); return False, "هذا الكود ليس مخصصًا للفئة الذهبية. استخدم كودًا بقيمة 100 د.ل."
            if desired_tier == "silver" and int(amount) != 60:
                conn.close(); return False, "هذا الكود ليس مخصصًا للفئة الفضية. استخدم كودًا بقيمة 60 د.ل."
        else:
            # infer from amount
            if int(amount) == 100:
                desired_tier = "gold"
            elif int(amount) == 60:
                desired_tier = "silver"
            else:
                desired_tier = "custom"

        if desired_tier == "gold":
            # New mapping: gold -> 1, silver -> 0 (gold gets star when level == 1)
            level = 1; days = 32; tier_name = "ذهبي"
        elif desired_tier == "silver":
            level = 0; days = 30; tier_name = "فضي"
        else:
            level = 0; days = 30; tier_name = f"({amount})"

        import datetime
        expiry = datetime.datetime.utcnow() + datetime.timedelta(days=days)
        expiry_iso = expiry.isoformat()

        # choose target worker
        if not target_worker_user_id:
            target_worker_user_id = requesting_user_id

        # mark coupon used and update worker
        try:
            cur.execute("UPDATE coupons SET used=1, used_by_worker_user_id=?, used_at=? WHERE id=?", (target_worker_user_id, expiry_iso, cid))
            cur.execute("UPDATE workers SET subscription_level = ?, subscription_expiry = ?, coupon_code = ? WHERE user_id = ?",
                        (level, expiry_iso, actual_code, target_worker_user_id))
            conn.commit()
            conn.close()
            return True, f"تم تفعيل الاشتراك للفئة {tier_name}. سينتهي الاشتراك بتاريخ {expiry_iso}."
        except Exception:
            conn.close()
            logging.exception("Error while marking coupon used in redeem_coupon_for_worker")
            return False, "حدث خطأ أثناء تفعيل الكود. حاول مرة أخرى أو تواصل مع الدعم."
    except Exception:
        conn.close()
        return False, "حدث خطأ أثناء معالجة الكود."

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_states.pop(update.effective_user.id, None)
    await update.message.reply_text("مرحبًا بكم في بوت خدمتي", reply_markup=MAIN_KB)

async def redeem_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_states[update.effective_user.id] = {"role": "redeem", "step": "code"}
    await update.message.reply_text("أدخل كود الشحن (الكوبون) لتفعيله:")

async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.contact:
        return
    user_id = msg.from_user.id
    st = user_states.get(user_id)
    if not st:
        await msg.reply_text("ابدأ من جديد بالضغط على /start.")
        return
    # Worker shared contact during registration
    if st.get("role") == "worker" and st.get("step") == "phone":
        # Do not accept shared contact for workers — require manual entry
        await msg.reply_text("الرجاء إدخال رقم الهاتف يدوياً بصيغة 09XXXXXXXX. مشاركة جهة الاتصال غير مقبولة أثناء التسجيل.", reply_markup=ReplyKeyboardRemove())
        return
    # Client shared contact as a convenience during ordering; store in-memory and ask for location
    if st.get("role") == "client" and st.get("step") == "awaiting_location":
        st["contact"] = msg.contact.phone_number
        user_states[user_id] = st
        kb = make_reply_kb([[KeyboardButton("إرسال الموقع", request_location=True)]])
        await msg.reply_text("تم حفظ جهة اتصالك مؤقتًا. الآن أرسل موقعك لتجد الحرفيين الأقرب:", reply_markup=kb)
        return

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer()
    data = query.data or ""
    if data == "reg_back":
        uid = query.from_user.id
        st = user_states.get(uid, {})
        # return to subscription selection
        st["step"] = "choose_subscription"
        user_states[uid] = st
        sub_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("الفئة الذهبية — 100 د.ل", callback_data="reg_sub:gold")],
            [InlineKeyboardButton("الفئة الفضية — 60 د.ل", callback_data="reg_sub:silver")]
        ])
        await query.edit_message_text("تم الرجوع. اختر فئة الاشتراك المطلوبة:", reply_markup=sub_kb)
        return

    # Registration subscription selection (during worker registration)
    if data.startswith("reg_sub:"):
        parts = data.split(":", 1)
        if len(parts) != 2:
            await query.edit_message_text("خطأ في اختيار الفئة. حاول مرة أخرى.")
            return
        tier = parts[1]
        uid = query.from_user.id
        st = user_states.get(uid, {})
        st["tier"] = tier
        # persist chosen tier to worker record (partial)
        try:
            save_worker_to_db(uid, st)
        except Exception:
            logging.exception("Failed to save worker tier during registration")
        # after selecting subscription, ask worker to enter coupon code (optional)
        st["step"] = "awaiting_coupon_reg"
        user_states[uid] = st
        try:
            await query.edit_message_text(f"لقد اخترت الفئة: {'الذهبية' if tier=='gold' else 'الفضية'}\nإذا لديك كود القسيمة أدخله الآن، أو اضغط رجوع للعودة للخلف.")
        except Exception:
            await query.message.reply_text("إذا لديك كود القسيمة أدخله الآن، أو اضغط رجوع للعودة للخلف.")
        # show a back button (reg_back handled above)
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("رجوع", callback_data="reg_back")]])
        await query.message.reply_text("أدخل كود القسيمة أو اضغط رجوع:", reply_markup=kb)
        return

    # Admin / activation pick handler
    if data.startswith("pick_activate:"):
        parts = data.split(":")
        if len(parts) != 3:
            await query.edit_message_text("خطأ في اختيار الفئة. حاول مرة أخرى.")
            return
        tier = parts[1]
        try:
            target_user = int(parts[2])
        except Exception:
            await query.edit_message_text("خطأ في معرّف العامل. حاول مرة أخرى.")
            return
        uid = query.from_user.id
        state = user_states.get(uid, {})
        # store desired tier and target, move to waiting for coupon code
        state["desired_tier"] = tier
        state["target_user_id"] = target_user
        state["step"] = "awaiting_coupon"
        user_states[uid] = state
        try:
            await query.edit_message_text(f"لقد اخترت الفئة: {'ذهبية' if tier=='gold' else 'فضية'}\.\nأدخل الآن كود القسيمة المناسب لهذه الفئة:")
        except Exception:
            await query.message.reply_text("أدخل الآن كود القسيمة المناسب لهذه الفئة:")
        return

    # Client selects a worker from the inline button list
    if data.startswith("select:"):
        try:
            parts = data.split(":", 1)
            code = int(parts[1])
        except Exception:
            await query.edit_message_text("خطأ في اختيار العامل. حاول مرة أخرى.")
            return
        # find worker
        w = fetch_worker_by_code(code)
        if not w:
            await query.edit_message_text("لم يتم العثور على معلومات هذا العامل. ربما تم حذفه.")
            return
        # increment selection_count
        try:
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute("UPDATE workers SET selection_count = COALESCE(selection_count,0)+1 WHERE user_id=?", (w.get('user_id'),))
            conn.commit()
            conn.close()
        except Exception:
            logging.exception("Failed to increment selection_count")
        # confirm to the user and provide contact info (phone)
        # Do NOT reveal worker_code to customers; it's private for the worker.
        reply_text = f"تم اختيار العامل:\nالاسم: {w.get('name') or '-'}\nالهاتف: {w.get('phone') or '-'}\nالعمل: {w.get('work_type') or '-'}"
        # attach rating buttons plus the select button
        rate_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("اختيار هذا الحرفي", callback_data=f"select:{w.get('worker_code')}")],
            [InlineKeyboardButton("⭐ 1", callback_data=f"rate:{w.get('worker_code')}:1"), InlineKeyboardButton("⭐ 2", callback_data=f"rate:{w.get('worker_code')}:2"), InlineKeyboardButton("⭐ 3", callback_data=f"rate:{w.get('worker_code')}:3")],
            [InlineKeyboardButton("⭐ 4", callback_data=f"rate:{w.get('worker_code')}:4"), InlineKeyboardButton("⭐ 5", callback_data=f"rate:{w.get('worker_code')}:5")]
        ])
        try:
            # edit the original inline message to indicate selection and attach rating buttons
            await query.edit_message_text(reply_text, reply_markup=rate_kb)
        except Exception:
            await query.message.reply_text(reply_text, reply_markup=rate_kb)
        return

    # Rating callbacks: rate:<worker_code>:<score>
    if data.startswith("rate:"):
        try:
            _, code_s, score_s = data.split(":")
            code = int(code_s); score = int(score_s)
        except Exception:
            await query.answer(text="خطأ في التقييم.", show_alert=True)
            return
        w = fetch_worker_by_code(code)
        if not w:
            await query.answer(text="العامل غير موجود.", show_alert=True)
            return
        # update avg_rating and ratings_received
        try:
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute("SELECT avg_rating, ratings_received FROM workers WHERE user_id=?", (w.get('user_id'),))
            row = cur.fetchone()
            if row:
                old_avg = float(row[0] or 0.0); old_count = int(row[1] or 0)
            else:
                old_avg = 0.0; old_count = 0
            new_count = old_count + 1
            new_avg = (old_avg * old_count + score) / new_count
            cur.execute("UPDATE workers SET avg_rating=?, ratings_received=? WHERE user_id=?", (new_avg, new_count, w.get('user_id')))
            conn.commit(); conn.close()
            await query.edit_message_text(f"شكرًا لتقييمك! التقييم الحالي للعامل {w.get('name') or '-'} هو {new_avg:.2f} ({new_count} تقييمات)")
        except Exception:
            logging.exception("Failed to save rating")
            await query.answer(text="حدث خطأ أثناء حفظ التقييم.", show_alert=True)
        return

async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return
    user_id = msg.from_user.id
    text = (msg.text or "").strip()
    text_l = (text or "").lower()
    cleaned_label = re.sub(r"^[^\w\u0600-\u06FF]*", "", text).strip()
    # load current user state early so we can branch client vs worker flows
    st = user_states.get(user_id)

    # handle contact/about shortcuts early
    if text_l in CONTACT_KEYS:
        phone_local = "0916564000"; phone_international = "+218916564000"; wa_number = "218916564000"
        try:
            await msg.reply_contact(phone_number=phone_international, first_name="فريق الدعم")
        except Exception:
            logging.debug("reply_contact failed")
        wa_btn = InlineKeyboardMarkup([[InlineKeyboardButton("مراسلتنا عبر واتساب", url=f"https://wa.me/{wa_number}")]] )
        await msg.reply_text(f"📞 للتواصل الهاتفي: {phone_local}\n\nيمكنك أيضًا مراسلتنا عبر واتساب:", reply_markup=wa_btn)
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
        await msg.reply_text(about_text, reply_markup=ReplyKeyboardRemove())
        await msg.reply_text("القائمة الرئيسية:", reply_markup=MAIN_KB)
        return
    # Global back button handling
    if text == "رجوع":
        st = user_states.get(user_id)
        if not st:
            await msg.reply_text("القائمة الرئيسية:", reply_markup=MAIN_KB)
            return
        role = st.get("role")
        step = st.get("step")
        # browsing role
        if role == 'browsing':
            if step == 'services':
                # go back to categories
                user_states[user_id] = {"role": "browsing", "step": "categories"}
                cats = list(SERVICE_CATEGORIES.keys())
                kb = make_reply_kb([[c] for c in cats])
                await msg.reply_text("اختر الفئة:", reply_markup=kb)
                return
            else:
                # default to main menu
                user_states.pop(user_id, None)
                await msg.reply_text("الرجوع إلى القائمة الرئيسية:", reply_markup=MAIN_KB)
                return
        # client role
        if role == 'client':
            if step == 'awaiting_location':
                prev_cat = st.get('prev_category')
                if prev_cat:
                    # return to browsing services of prev_cat
                    user_states[user_id] = {"role": "browsing", "step": "services", "category": prev_cat}
                    services = SERVICE_CATEGORIES.get(prev_cat) or []
                    kb = make_reply_kb([[s] for s in services])
                    await msg.reply_text(f"اختر الخدمة من فئة {prev_cat}:", reply_markup=kb)
                    return
                else:
                    user_states.pop(user_id, None)
                    await msg.reply_text("الرجوع إلى القائمة الرئيسية:", reply_markup=MAIN_KB)
                    return
            if step == 'choose_worker':
                # go back to awaiting_location prompt
                st['step'] = 'awaiting_location'
                user_states[user_id] = st
                kb = make_reply_kb([[KeyboardButton("إرسال الموقع", request_location=True)]])
                await msg.reply_text("الرجاء ارسال موقعك:", reply_markup=kb)
                return
        # worker role handled in worker-specific block below
    # continue handling text input
    if text in ("/start", "start"):
        await start(update, context); return
    # Activation flow entrance (button in main menu)
    norm = normalize_label(text)
    if text in ("تفعيل الاشتراك", "� تفعيل الاشتراك", "تفعيل") or norm == 'تفعيل الاشتراك' or 'تفعيل' in norm:
        user_states[user_id] = {"role": "activate_subscription", "step": "enter_worker_code"}
        await msg.reply_text("أدخل رقم المعرف الخاص بك (worker code) لتفعيل أو تجديد اشتراكك:")
        return
    # Services / categories handling: be robust to emoji/label variants using normalized map
    # Only show categories to browsing/clients — do not intercept worker registration
    if (not st or st.get("role") != "worker") and norm in SERVICE_KEYS_NORMALIZED:
        cats = list(SERVICE_CATEGORIES.keys())
        kb = make_reply_kb([[c] for c in cats])
        user_states[user_id] = {"role": "browsing", "step": "categories"}
        await msg.reply_text("اختر الفئة:", reply_markup=kb)
        return
    # If user selected a category name (possibly with emoji), map via normalized map
    if (not st or st.get("role") != "worker") and norm in CATEGORY_NORMALIZED:
        canonical = CATEGORY_NORMALIZED.get(norm)
        services = SERVICE_CATEGORIES.get(canonical) or []
        if services:
            kb = make_reply_kb([[s] for s in services])
            user_states[user_id] = {"role": "browsing", "step": "services", "category": canonical}
            await msg.reply_text(f"اختر الخدمة من فئة {canonical}:", reply_markup=kb)
            return
            return
        else:
            # direct mapping to a service label
            text = canonical
    # Activation flow: user entered worker code to start activation flow
    st = user_states.get(user_id)
    if st and st.get("role") == "activate_subscription" and st.get("step") == "enter_worker_code":
        if not text.isdigit():
            await msg.reply_text("رقم المعرف يجب أن يكون رقماً. أدخل رقم المعرف الخاص بك (مثل 2001):")
            return
        w = fetch_worker_by_code(int(text))
        if not w:
            await msg.reply_text("لم يتم العثور على عامل بهذا الرقم. تأكد من رقم المعرف وحاول مرة أخرى.")
            return
        # store target worker and ask to pick tier
        st["target_user_id"] = w["user_id"]
        st["step"] = "awaiting_tier_choice"
        user_states[user_id] = st
        sub_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("الفئة الذهبية — 100 د.ل", callback_data=f"pick_activate:gold:{w['user_id']}")],
            [InlineKeyboardButton("الفئة الفضية — 60 د.ل", callback_data=f"pick_activate:silver:{w['user_id']}")]
        ])
        await msg.reply_text(f"تم العثور على العامل: {w.get('name') or '-'}\nاختر الفئة المطلوبة:", reply_markup=sub_kb)
        return
    # Accept service selection even when user types without emoji by
    # mapping normalized input to canonical work_type labels.
    # Accept service selection only for clients (do not override worker registration flow)
    canonical_service = None
    if not (st and st.get("role") == "worker"):
        if text in WORK_TYPES:
            canonical_service = text
        else:
            canonical_service = WORK_TYPES_NORMALIZED.get(norm) or WORK_TYPES_NORMALIZED.get(strip_definite_article(norm))
    if canonical_service:
        name = (update.effective_user.first_name or "")
        # preserve previous browsing category if any so 'رجوع' can restore it
        prev_cat = None
        prev = user_states.get(user_id) or {}
        prev_cat = prev.get("category")
        state = {"role": "client", "service": canonical_service, "name": name, "step": "awaiting_location", "prev_category": prev_cat}
        user_states[user_id] = state
        # First stage: ask only for contact sharing. After contact is received
        # handle_contact will prompt the user to send their location with a single button.
        kb = make_reply_kb([[KeyboardButton("مشاركة جهة الاتصال", request_contact=True)]])
        await msg.reply_text(f"لقد اخترت: {canonical_service}\nالرجاء مشاركة جهة اتصالك عبر الزر أدناه:", reply_markup=kb)
        return
    if text in ("📝 التسجيل للحرفيين", "التسجيل للحرفيين"):
        user_states[user_id] = {"role": "worker", "step": "name", "stage": 1}
        await msg.reply_text("التسجيل كحرفي:\nأدخل اسمك بالكامل:")
        return
    st = user_states.get(user_id)
    if st and st.get("role") == "worker":
        step = st.get("step")
        # Generic back navigation for worker registration steps
        if text == "رجوع":
            prev_map = {
                'location': 'awaiting_coupon_reg',
                'awaiting_coupon_reg': 'choose_subscription',
                'choose_subscription': 'phone',
                'phone': 'work_type',
                'vehicle': 'work_type',
                'edu_specialty': 'work_type',
                'floor_type': 'work_type',
                'work_type': 'name',
                'name': None
            }
            cur = step
            prev = prev_map.get(cur)
            if not prev:
                # nothing to go back to; show main menu
                user_states.pop(user_id, None)
                await msg.reply_text("تم الرجوع إلى القائمة الرئيسية.", reply_markup=MAIN_KB)
                return
            st['step'] = prev
            user_states[user_id] = st
            # render appropriate prompt for previous step
            if prev == 'name':
                await msg.reply_text('سجل كعامل - اكتب اسمك:')
                return
            if prev == 'work_type':
                cats = list(SERVICE_CATEGORIES.keys())
                kb = make_reply_kb([[c] for c in cats])
                await msg.reply_text('اختر الفئة/الخدمة:', reply_markup=kb)
                return
            if prev == 'choose_subscription':
                sub_kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton('الفئة الذهبية — 100 د.ل', callback_data='reg_sub:gold')],
                    [InlineKeyboardButton('الفئة الفضية — 60 د.ل', callback_data='reg_sub:silver')]
                ])
                await msg.reply_text('اختر فئة الاشتراك المطلوبة:', reply_markup=sub_kb)
                return
            if prev == 'awaiting_coupon_reg':
                kb = InlineKeyboardMarkup([[InlineKeyboardButton('رجوع', callback_data='reg_back')]])
                await msg.reply_text('أدخل كود القسيمة أو اضغط رجوع:', reply_markup=kb)
                return
            if prev == 'phone':
                kb = make_reply_kb([[KeyboardButton('دخل رقم الهاتف')]])
                await msg.reply_text('الرجاء إدخال رقمك يدوياً بصيغة 09XXXXXXXX ثم اضغط رجوع إن أردت التراجع:', reply_markup=kb)
                return
        # allow worker to enter coupon code during registration
        if step == "awaiting_coupon_reg":
            code = text.strip()
            if not code:
                await msg.reply_text("لم تدخل كودًا. أدخل كود القسيمة أو اضغط رجوع.")
                return
            ok, resp = redeem_coupon_for_worker(code, user_id, target_worker_user_id=user_id, desired_tier=st.get("tier"))
            if ok:
                st["coupon_code"] = code
                # coupon accepted -> ask for location to finish registration
                st["step"] = "location"
                user_states[user_id] = st
                await msg.reply_text('تم حفظ كود القسيمة وتفعيل الاشتراك. الآن الرجاء إرسال موقعك عبر زر "إرسال الموقع" ليتم إكمال تسجيلك.', reply_markup=make_reply_kb([[KeyboardButton("إرسال الموقع", request_location=True)]]))
                return
            else:
                await msg.reply_text(resp + "\nإذا رغبت يمكنك المحاولة مرة أخرى أو الضغط على رجوع.")
                return
        # If worker is at phone step and sent manual text, accept it as phone number
        if step == "phone":
            # accept manual phone input and validate format (09XXXXXXXX)
            raw = text or ""
            digits = re.sub(r"\D", "", raw)
            phone = digits[-10:] if len(digits) >= 10 else digits
            if not (len(phone) == 10 and phone.startswith("09")):
                await msg.reply_text("رقم الهاتف غير صالح. الرجاء إدخال رقم مكون من 10 أرقام يبدأ بـ 09 (مثال: 0912345678)")
                return
            st["phone"] = phone
            # persist partial worker record after phone
            save_worker_to_db(user_id, st)
            # after saving phone, ask for service/category selection
            st["step"] = "work_type"
            st["stage"] = 3
            user_states[user_id] = st
            cats = list(SERVICE_CATEGORIES.keys())
            kb = make_reply_kb([[c] for c in cats])
            await msg.reply_text("اختر فئة عملك:", reply_markup=kb)
            return
        if step == "name":
            st["name"] = text.strip()
            # persist partial worker record after name
            save_worker_to_db(user_id, st)
            st["step"] = "phone"
            st["stage"] = 2
            user_states[user_id] = st
            await msg.reply_text("أدخل رقم هاتفك يدوياً بصيغة 09XXXXXXXX:")
            return
        if step == "work_type":
            if text in SERVICE_CATEGORIES:
                services = SERVICE_CATEGORIES.get(text) or []
                if services:
                    kb = make_reply_kb([[s] for s in services])
                    st["step"] = "work_type"
                    user_states[user_id] = st
                    await msg.reply_text(f"اختر الخدمة من {text}:", reply_markup=kb)
                    return
                else:
                    st["work_type"] = text
                    # if the selected category is a direct work type without subservices
                    # Compare normalized labels so emoji/no-emoji variants match
                    if normalize_label(st.get("work_type")) == normalize_label("سيارات نقل"):
                        st["step"] = "vehicle"
                        user_states[user_id] = st
                        await msg.reply_text("ما نوع السيارة لديك؟")
                        return
                    if normalize_label(st.get("work_type")) == normalize_label("أرضيات"):
                        st["step"] = "floor_type"
                        user_states[user_id] = st
                        await msg.reply_text("ما نوع الأرضيات التي تتقنها؟")
                        return
                    # if we already have a phone for this worker (in-memory or in DB),
                    # proceed to subscription selection; otherwise ask for phone.
                    has_phone = bool(st.get("phone"))
                    if not has_phone:
                        try:
                            conn = sqlite3.connect(DB_PATH)
                            cur = conn.cursor()
                            cur.execute("SELECT phone FROM workers WHERE user_id=?", (user_id,))
                            row = cur.fetchone()
                            if row and row[0]:
                                has_phone = True
                            conn.close()
                        except Exception:
                            logging.exception("Failed to check existing phone for worker")
                    if has_phone:
                        # go directly to subscription selection
                        st["step"] = "choose_subscription"
                        st["stage"] = 4
                        user_states[user_id] = st
                        sub_kb = InlineKeyboardMarkup([
                            [InlineKeyboardButton('الفئة الذهبية — 100 د.ل', callback_data='reg_sub:gold')],
                            [InlineKeyboardButton('الفئة الفضية — 60 د.ل', callback_data='reg_sub:silver')]
                        ])
                        await msg.reply_text('اختر فئة الاشتراك المطلوبة:', reply_markup=sub_kb)
                        return
                    # persist selected work_type then ask for phone
                    save_worker_to_db(user_id, st)
                    st["step"] = "phone"
                    st["stage"] = 3
                    user_states[user_id] = st
                    await msg.reply_text('الرجاء إدخال رقم هاتفك يدوياً بصيغة 09XXXXXXXX:')
                    return
            # accept non-emoji typed services by mapping normalized input
            canonical_w = None
            if text in WORK_TYPES:
                canonical_w = text
            else:
                canonical_w = WORK_TYPES_NORMALIZED.get(norm) or WORK_TYPES_NORMALIZED.get(strip_definite_article(norm))
            if canonical_w:
                st["work_type"] = canonical_w
                # special prompts based on chosen work_type
                if normalize_label(st.get("work_type")) == normalize_label("سيارات نقل"):
                    st["step"] = "vehicle"
                    user_states[user_id] = st
                    await msg.reply_text("ما نوع السيارة لديك؟")
                    return
                if normalize_label(st.get("work_type")) == normalize_label("أرضيات"):
                    st["step"] = "floor_type"
                    user_states[user_id] = st
                    await msg.reply_text("ما نوع الأرضيات التي تتقنها؟")
                    return
                if st["work_type"] in ("📚 تمهيدي", "📚 اعدادي", "📚 ثانوي أو معهد", "📚 اكاديمي"):
                    st["step"] = "edu_specialty"
                    user_states[user_id] = st
                    await msg.reply_text("ما تخصصك الدراسي؟")
                    return
                # if no special handling above, persist work_type and ask for phone
                # if worker already has phone, skip asking again and move to subscription
                has_phone = bool(st.get("phone"))
                if not has_phone:
                    try:
                        conn = sqlite3.connect(DB_PATH)
                        cur = conn.cursor()
                        cur.execute("SELECT phone FROM workers WHERE user_id=?", (user_id,))
                        row = cur.fetchone()
                        if row and row[0]:
                            has_phone = True
                        conn.close()
                    except Exception:
                        logging.exception("Failed to check existing phone for worker")
                if has_phone:
                    st["step"] = "choose_subscription"
                    st["stage"] = 4
                    user_states[user_id] = st
                    sub_kb = InlineKeyboardMarkup([
                        [InlineKeyboardButton('الفئة الذهبية — 100 د.ل', callback_data='reg_sub:gold')],
                        [InlineKeyboardButton('الفئة الفضية — 60 د.ل', callback_data='reg_sub:silver')]
                    ])
                    await msg.reply_text('اختر فئة الاشتراك المطلوبة:', reply_markup=sub_kb)
                    return
                save_worker_to_db(user_id, st)
                st["step"] = "phone"
                st["stage"] = 3
                user_states[user_id] = st
                await msg.reply_text('الرجاء إدخال رقم هاتفك يدوياً بصيغة 09XXXXXXXX:')
                return

        if step == "vehicle":
            st["vehicle_type"] = text
            save_worker_to_db(user_id, st)
            # after vehicle type, move to subscription selection
            st["step"] = "choose_subscription"
            st["stage"] = 4
            user_states[user_id] = st
            sub_kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("الفئة الذهبية — 100 د.ل", callback_data="reg_sub:gold")],
                [InlineKeyboardButton("الفئة الفضية — 60 د.ل", callback_data="reg_sub:silver")]
            ])
            await msg.reply_text('اختر فئة الاشتراك المطلوبة:', reply_markup=sub_kb)
            return
        if step == "edu_specialty":
            st["edu_specialty"] = text
            save_worker_to_db(user_id, st)
            st["step"] = "choose_subscription"
            st["stage"] = 4
            user_states[user_id] = st
            sub_kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("الفئة الذهبية — 100 د.ل", callback_data="reg_sub:gold")],
                [InlineKeyboardButton("الفئة الفضية — 60 د.ل", callback_data="reg_sub:silver")]
            ])
            await msg.reply_text('اختر فئة الاشتراك المطلوبة:', reply_markup=sub_kb)
            return
        if step == "floor_type":
            st["floor_type"] = text
            save_worker_to_db(user_id, st)
            st["step"] = "choose_subscription"
            st["stage"] = 4
            user_states[user_id] = st
            sub_kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("الفئة الذهبية — 100 د.ل", callback_data="reg_sub:gold")],
                [InlineKeyboardButton("الفئة الفضية — 60 د.ل", callback_data="reg_sub:silver")]
            ])
            await msg.reply_text('اختر فئة الاشتراك المطلوبة:', reply_markup=sub_kb)
            return
    if st and st.get("role") == "redeem" and st.get("step") == "code":
        code = text.strip()
        ok, msg_text = redeem_coupon_for_worker(code, user_id)
        await msg.reply_text(msg_text)
        user_states.pop(user_id, None)
        return
    # account flow: worker wants stats
    if text in ("📊حسابي", "حسابي"):
        user_states[user_id] = {"role": "account", "step": "enter_code"}
        await msg.reply_text("أدخل رقم المعرف (worker code) لعرض إحصائياتك:")
        return
    if st and st.get("role") == "account" and st.get("step") == "enter_code":
        if not text.isdigit():
            await msg.reply_text("رقم المعرف يجب أن يكون رقماً. أعد المحاولة:")
            return
        w = fetch_worker_by_code(int(text))
        if not w:
            await msg.reply_text("لم يتم العثور على عامل بهذا الرقم.")
            return
        # new mapping: 1 = ذهبي, 0 = فضي, None/other = لا يوجد
        tier_map = {1: 'ذهبي', 0: 'فضي'}
        lvl = w.get('subscription_level')
        tier_text = tier_map.get(lvl, 'لا يوجد')
        resp = f"الاسم: {w.get('name') or '-'}\nالفئة: {tier_text}\nانتهاء الاشتراك: {w.get('subscription_expiry') or '-'}\nمرات الظهور: {w.get('appearance_count') or 0}\nمرات الاختيار: {w.get('selection_count') or 0}\nمتوسط التقييم: {w.get('avg_rating') or 0}"
        await msg.reply_text(resp)
        user_states.pop(user_id, None)
        return
    await msg.reply_text("لم أفهم. استخدم الأزرار أو اكتب /start للعودة للقائمة.", reply_markup=MAIN_KB)
    # Do not allow clients to select a worker by typing the worker code.
    # The worker code is private and shown only to the worker (after registration).
    if st and st.get("role") == "client" and st.get("step") == "choose_worker" and text.isdigit():
        await msg.reply_text("لأسباب تتعلق بالخصوصية، لا يمكن اختيار الحرفي بإدخال رمز العامل.\nالرجاء استخدام زر 'اختيار هذا الحرفي' الموجود في بطاقة الحرفي.")
        return

async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.location:
        return
    user_id = msg.from_user.id
    st = user_states.get(user_id, {})
    lat = msg.location.latitude
    lon = msg.location.longitude
    # Worker sending location to save profile
    if st and st.get("role") == "worker" and st.get("step") == "location":
        st["lat"] = lat; st["lon"] = lon
        save_worker_to_db(user_id, st)
        # fetch assigned worker_code to show to the user
        try:
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute("SELECT worker_code FROM workers WHERE user_id=?", (user_id,))
            r = cur.fetchone()
            conn.close()
            worker_code = r[0] if r and r[0] else None
        except Exception:
            logging.exception("Failed to fetch worker_code after saving location")
            worker_code = None
        # clear in-memory state
        user_states.pop(user_id, None)
        # send short thank-you and the worker code (if available)
        if worker_code:
            await msg.reply_text(f"شكرًا لتسجيلك في منصة خدمتي.\nرقم المعرف الخاص بك: {worker_code}")
        else:
            await msg.reply_text("شكرًا لتسجيلك في منصة خدمتي. تم حفظ بياناتك.")
        return
    # Client sending location to find nearest workers
    if st and st.get("role") == "client" and st.get("step") in ("categories", "services", "awaiting_location"):
        service = st.get("service")
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        # select workers with non-null lat/lon and matching work_type
        cur.execute("SELECT user_id,name,phone,work_type,lat,lon,worker_code,subscription_level,subscription_expiry,avg_rating FROM workers WHERE lat IS NOT NULL AND lon IS NOT NULL AND work_type=?", (service,))
        rows = cur.fetchall()
        candidates = []
        now = datetime.datetime.utcnow()
        for r in rows:
            uid, name, phone, work_type, wlat, wlon, wcode, level, expiry, avg_rating = r
            # skip if no location
            if wlat is None or wlon is None:
                continue
                # skip if no active subscription: require subscription_level not None and expiry present
                try:
                    if level is None or not expiry:
                        continue
                    # parse expiry
                    exp_dt = datetime.datetime.fromisoformat(expiry)
                    if exp_dt <= now:
                        # expired -> do not show
                        continue
                except Exception:
                    # if parsing fails, skip this worker
                    continue
            dist = haversine(lat, lon, wlat, wlon)
            # store as (level, dist, ...)
            candidates.append((level or 0, dist, uid, name, phone, work_type, wcode, avg_rating))
        # only keep workers within 40 km
        candidates = [c for c in candidates if c[1] <= 40.0]
        # sort by level (higher first), then distance (lower first)
        candidates.sort(key=lambda x: (-int(x[0] or 0), x[1]))
        if not candidates:
            await msg.reply_text("عذراً، لا يوجد حرفيون مسجلون لهذه الخدمة ضمن نطاق 40 كم من موقعك.")
            conn.close(); return
        # increment appearance_count for shown workers
        for level, dist, uid, name, phone, work_type, wcode, avg_rating in candidates:
            try:
                cur.execute("UPDATE workers SET appearance_count = COALESCE(appearance_count,0)+1 WHERE user_id=?", (uid,))
            except Exception:
                pass
        conn.commit()
        # reply with each worker in its own box; cap to avoid huge messages
        MAX_SHOW = 50
        to_show = candidates[:MAX_SHOW]
        for level, dist, uid, name, phone, work_type, wcode, avg_rating in to_show:
            # show golden star when subscription_level == 1
            star = " ⭐️" if int(level if level is not None else -1) == 1 else ""
            # fetch specialty fields if present
            spec_parts = []
            try:
                cur2 = conn.cursor()
                cur2.execute("SELECT vehicle_type, edu_specialty, floor_type FROM workers WHERE user_id=?", (uid,))
                rp = cur2.fetchone()
                if rp:
                    vehicle_type, edu_specialty, floor_type = rp
                    if vehicle_type:
                        spec_parts.append(f"نوع السيارة: {vehicle_type}")
                    if edu_specialty:
                        spec_parts.append(f"تخصص دراسي: {edu_specialty}")
                    if floor_type:
                        spec_parts.append(f"نوع الأرضيات: {floor_type}")
            except Exception:
                pass
            spec_text = ("\n" + "\n".join(spec_parts)) if spec_parts else ""
            # include average rating in the profile box
            avg_text = f"{(float(avg_rating) if avg_rating is not None else 0):.1f}" if avg_rating is not None else "-"
            box = f"الاسم:{star} {name or '-'}\nالهاتف: {phone or '-'}\nالعمل: {work_type}{spec_text}\nمتوسط التقييم: {avg_text}\nالمسافة: {dist:.2f} كم"
            # attach selection and rating buttons
            rate_kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("اختيار هذا الحرفي", callback_data=f"select:{wcode}")],
                [InlineKeyboardButton("⭐ 1", callback_data=f"rate:{wcode}:1"), InlineKeyboardButton("⭐ 2", callback_data=f"rate:{wcode}:2"), InlineKeyboardButton("⭐ 3", callback_data=f"rate:{wcode}:3")],
                [InlineKeyboardButton("⭐ 4", callback_data=f"rate:{wcode}:4"), InlineKeyboardButton("⭐ 5", callback_data=f"rate:{wcode}:5")]
            ])
            await msg.reply_text(box, reply_markup=rate_kb)
        # if too many, tell user we truncated
        if len(candidates) > MAX_SHOW:
            await msg.reply_text(f"\nوتم عرض {MAX_SHOW} من أصل {len(candidates)} حرفيين داخل 40 كم.")
        # set client state to allow selection by button (choose_worker)
        st["step"] = "choose_worker"
        user_states[user_id] = st
        conn.close()
        return
        
    # otherwise ignore
    await msg.reply_text("لاستخدام الموقع: اختر خدمة ثم أرسل الموقع عبر الزر.")

def main():
    init_db()
    if not TOKEN:
        logging.info("BOT_TOKEN missing; exiting main without starting bot.")
        return
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("redeem", redeem_cmd))
    # conf_cmd will be registered later after its definition to avoid NameError
    app.add_handler(CallbackQueryHandler(handle_callback))
    # register conf handler now that function exists
    try:
        app.add_handler(CommandHandler("conf", conf_cmd))
    except Exception:
        logging.exception("Failed to register conf handler")
    app.add_handler(MessageHandler(filters.CONTACT, handle_contact))
    app.add_handler(MessageHandler(filters.LOCATION, handle_location))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_buttons))
    logging.info("Starting khidmati_fixed bot")
    app.run_polling()


async def conf_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    # Restrict /conf to the configured ADMIN_ID. If a non-admin tries to run it,
    # return a short message and log the attempt.
    if ADMIN_ID and uid != ADMIN_ID:
        logging.info(f"/conf access denied for user_id={uid}")
        await update.message.reply_text("أمر محصور للمشرف فقط.")
        return
    logging.info(f"/conf invoked by admin user_id={uid}")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT user_id, name, phone, work_type, subscription_level, subscription_expiry FROM workers ORDER BY id")
    rows = cur.fetchall()
    total = len(rows)
    parts = [f"إجمالي الحرفيين: {total}"]
    for r in rows:
        user_id, name, phone, work_type, level, expiry = r
        parts.append(f"{name or '-'} | {phone or '-'} | {work_type or '-'} | lvl:{level or 0} | exp:{expiry or '-'}")
    conn.close()
    # split into chunks if long
    out = "\n".join(parts)
    for chunk in [out[i:i+3900] for i in range(0, len(out), 3900)]:
        await update.message.reply_text(chunk)

# Register conf handler after its definition by patching Application in main at runtime.


if __name__ == '__main__':
    main()
