from flask import Flask
from threading import Thread
import os
import telebot
from telebot import types
import yt_dlp

# --- БЛОК ПОДДЕРЖКИ ЖИЗНИ (KEEP ALIVE) ---
app = Flask('')

@app.route('/')
def home():
    return "Я жив!"

def run():
    # Render использует порт 8080 по умолчанию
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

# --- НАСТРОЙКИ БОТА ---
# os.getenv вытащит токен из настроек Render, чтобы его не украли с GitHub
TOKEN = os.getenv('BOT_TOKEN') 
bot = telebot.TeleBot(TOKEN)

# Словарь для памяти бота
user_data = {}

# ---------------------------------------------------------
# ПРИВЕТСТВИЕ
# ---------------------------------------------------------
@bot.message_handler(commands=['start'])
def send_welcome(message):
    text = (
        "👋 *Привет!*\n\n"
        "Просто отправь мне ссылку на видео или трек (YouTube, TikTok, Instagram, VK и сотни других сайтов).\n\n"
        "Я быстро всё проанализирую и предложу тебе выбрать нужный формат и качество для скачивания 📥"
    )
    bot.send_message(message.chat.id, text, parse_mode='Markdown')

# ---------------------------------------------------------
# ЛОВЕЦ ССЫЛОК И АНАЛИЗАТОР
# ---------------------------------------------------------
@bot.message_handler(func=lambda message: "http://" in message.text or "https://" in message.text)
def handle_any_link(message):
    url = message.text
    chat_id = message.chat.id
    msg_id = message.message_id

    status_msg = bot.send_message(chat_id, "🔍 *Анализирую ссылку...*", parse_mode='Markdown')

    try:
        with yt_dlp.YoutubeDL({'quiet': True, 'noplaylist': True}) as ydl:
            info = ydl.extract_info(url, download=False)
            formats = info.get('formats', [])
            title = info.get('title', 'Без названия')

            resolutions = set()
            for f in formats:
                h = f.get('height')
                if h and isinstance(h, int) and f.get('vcodec') != 'none':
                    resolutions.add(h)

            resolutions = sorted(list(resolutions), reverse=True)

        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(types.InlineKeyboardButton("🎵 Только Звук (MP3)", callback_data="dl_mp3"))
        
        buttons = []
        for res in resolutions:
            buttons.append(types.InlineKeyboardButton(f"🎬 {res}p", callback_data=f"dl_{res}"))
        
        for i in range(0, len(buttons), 2):
            markup.add(*buttons[i:i+2])
            
        markup.add(types.InlineKeyboardButton("❌ Отмена", callback_data="dl_cancel"))

        user_data[chat_id] = {'url': url, 'msg_id': msg_id}

        bot.edit_message_text(
            f"🔗 *Медиа найдено!*\n🎬 `{title}`\n\nВыбери качество:", 
            chat_id=chat_id, 
            message_id=status_msg.message_id,
            reply_markup=markup, 
            parse_mode='Markdown'
        )

    except Exception as e:
        bot.edit_message_text("❌ *Ошибка:* Не удалось проанализировать ссылку. Возможно, сайт защищен.", chat_id=chat_id, message_id=status_msg.message_id, parse_mode='Markdown')
        print(f"Ошибка парсинга: {e}")

# ---------------------------------------------------------
# ОБРАБОТЧИК НАЖАТИЯ КНОПОК
# ---------------------------------------------------------
@bot.callback_query_handler(func=lambda call: call.data.startswith('dl_'))
def handle_download_callback(call):
    chat_id = call.message.chat.id
    action = call.data

    if action == "dl_cancel":
        bot.delete_message(chat_id, call.message.message_id)
        if chat_id in user_data:
            try: bot.delete_message(chat_id, user_data[chat_id]['msg_id'])
            except: pass
            del user_data[chat_id]
        return

    if chat_id not in user_data:
        bot.answer_callback_query(call.id, "Ссылка устарела. Отправь заново.")
        bot.delete_message(chat_id, call.message.message_id)
        return

    url = user_data[chat_id]['url']
    user_msg_id = user_data[chat_id]['msg_id']
    
    bot.edit_message_text("⏳ *Качаю и собираю файл...*", chat_id=chat_id, message_id=call.message.message_id, parse_mode='Markdown')
    
    process_download(chat_id, url, action, user_msg_id, call.message.message_id)

# ---------------------------------------------------------
# ФУНКЦИЯ СКАЧИВАНИЯ И ОТПРАВКИ
# ---------------------------------------------------------
def process_download(chat_id, url, action, user_msg_id, status_msg_id):
    temp_folder = "downloads"
    abs_temp_folder = os.path.abspath(temp_folder)
    os.makedirs(abs_temp_folder, exist_ok=True)

    if action == "dl_mp3":
        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '320'}],
            'outtmpl': f'{abs_temp_folder}/%(title)s.%(ext)s',
        }
    else:
        res = action.split('_')[1]
        ydl_opts = {
            'format': f'bestvideo[height<={res}][ext=mp4]+bestaudio[ext=m4a]/best[height<={res}][ext=mp4]/best',
            'merge_output_format': 'mp4',
            'outtmpl': f'{abs_temp_folder}/%(title)s_({res}p).%(ext)s',
        }

    ydl_opts.update({'noplaylist': True, 'quiet': True, 'no_warnings': True})
    file_path = None

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            expected_title = info.get('title', '')
            for f in os.listdir(abs_temp_folder):
                if expected_title in f or info['id'] in f:
                    file_path = os.path.join(abs_temp_folder, f)
                    break
            
            if not file_path:
                raise Exception("Файл не найден")

        file_size = os.path.getsize(file_path)
        
        if file_size > 52428800: # Лимит 50 МБ
            size_mb = round(file_size / 1024 / 1024, 1)
            msg = (f"⚠️ *Файл слишком большой!* ({size_mb} МБ)\n\n"
                   f"Лимит — 50 МБ. Я сохранил его в папку `downloads` на сервере.")
            bot.edit_message_text(msg, chat_id=chat_id, message_id=status_msg_id, parse_mode='Markdown')
            return

        bot.edit_message_text("✅ *Отправляю в чат...*", chat_id=chat_id, message_id=status_msg_id, parse_mode='Markdown')

        with open(file_path, 'rb') as f:
            if action == "dl_mp3":
                bot.send_audio(chat_id, f, title=info.get('title'), performer="Твоя Музыка")
            else:
                bot.send_video(chat_id, f, caption=f"🎬 {info.get('title')}")

        try:
            bot.delete_message(chat_id, user_msg_id)
            bot.delete_message(chat_id, status_msg_id)
        except: pass
        
        os.remove(file_path)

    except Exception as e:
        bot.edit_message_text(f"❌ *Ошибка скачивания.*", chat_id=chat_id, message_id=status_msg_id, parse_mode='Markdown')
        print(f"Error: {e}")
        
    finally:
        if chat_id in user_data:
            del user_data[chat_id]

if __name__ == '__main__':
    # Запускаем Flask в отдельном потоке
    keep_alive()
    print("🤖 БОТ ЗАПУЩЕН!")
    bot.infinity_polling()