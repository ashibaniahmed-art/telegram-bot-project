
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

TOKEN = "8474550333:AAHEyI-V76fN9SJ7E4JarUsd22F8tU6qR3A"

# تخزين حالة المستخدمين
user_states = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        ["sign up for client", "sign up for worker"],
        ["services", "about us"],
        ["contact us"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(
        "welcome to our bot ",
        reply_markup=reply_markup
    )

async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.message.from_user.id

    if text == "sign up for client" or text == "sign up for worker":
        user_states[user_id] = {"role": text, "step": "name"}
        await update.message.reply_text("Please enter your name:")

    elif user_id in user_states:
        state = user_states[user_id]
        if state["step"] == "name":
            state["name"] = text
            state["step"] = "phone"
            await update.message.reply_text("Please enter your phone number:")
        elif state["step"] == "phone":
            state["phone"] = text
            state["step"] = "location"
            # زر مشاركة الموقع
            location_keyboard = ReplyKeyboardMarkup(
                [[KeyboardButton("Send location", request_location=True)]], resize_keyboard=True
            )
            await update.message.reply_text("Please share your location:", reply_markup=location_keyboard)
        elif state["step"] == "location":
            # سيتم استقبال الموقع في handle_location
            pass

async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id in user_states and user_states[user_id]["step"] == "location":
        location = update.message.location
        user_states[user_id]["location"] = location
        user_states[user_id]["step"] = "done"
        await update.message.reply_text("Thank you! Your data has been saved.")

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_buttons))
    app.add_handler(MessageHandler(filters.LOCATION, handle_location))
    app.run_polling()

if __name__ == "__main__":
    main()

    




