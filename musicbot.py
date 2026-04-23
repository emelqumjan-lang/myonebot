from flask import Flask
from threading import Thread

app = Flask('')
@app.route('/')
def home():
    return "Я жив!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

# Вызываем функцию ПЕРЕД запуском бота
keep_alive()
# Твой основной код бота дальше...
import os
import telebot
from telebot import types
import yt_dlp

# Твой токен от BotFather (на будущее: старайся не светить его в сети 😉)
TOKEN = '8749100939:AAFIObTVK2y1pHE_P0jSpa49wZpXIdpcVE0'
bot = telebot.TeleBot(TOKEN)

# Словарь для памяти бота (связывает чат пользователя с его ссылкой)
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

    # 1. Сообщаем, что начали думать
    status_msg = bot.send_message(chat_id, "🔍 *Анализирую ссылку...*", parse_mode='Markdown')

    try:
        # 2. Узнаем у видео все возможные форматы
        with yt_dlp.YoutubeDL({'quiet': True, 'noplaylist': True}) as ydl:
            info = ydl.extract_info(url, download=False)
            formats = info.get('formats', [])
            title = info.get('title', 'Без названия')

            # Собираем только уникальные разрешения (высоту экрана)
            resolutions = set()
            for f in formats:
                h = f.get('height')
                if h and isinstance(h, int) and f.get('vcodec') != 'none':
                    resolutions.add(h)

            # Сортируем от 4K к 144p
            resolutions = sorted(list(resolutions), reverse=True)

        # 3. Рисуем кнопки
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(types.InlineKeyboardButton("🎵 Только Звук (MP3)", callback_data="dl_mp3"))
        
        buttons = []
        for res in resolutions:
            buttons.append(types.InlineKeyboardButton(f"🎬 {res}p", callback_data=f"dl_{res}"))
        
        for i in range(0, len(buttons), 2):
            markup.add(*buttons[i:i+2])
            
        markup.add(types.InlineKeyboardButton("❌ Отмена", callback_data="dl_cancel"))

        # Запоминаем данные пользователя
        user_data[chat_id] = {'url': url, 'msg_id': msg_id}

        # 4. Обновляем сообщение с кнопками
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

    # Если нажали "Отмена"
    if action == "dl_cancel":
        bot.delete_message(chat_id, call.message.message_id)
        if chat_id in user_data:
            try: bot.delete_message(chat_id, user_data[chat_id]['msg_id'])
            except: pass
            del user_data[chat_id]
        return

    # Защита от старых кнопок
    if chat_id not in user_data:
        bot.answer_callback_query(call.id, "Ссылка устарела. Отправь заново.")
        bot.delete_message(chat_id, call.message.message_id)
        return

    url = user_data[chat_id]['url']
    user_msg_id = user_data[chat_id]['msg_id']
    
    bot.edit_message_text("⏳ *Качаю и собираю файл...* Пожалуйста, подожди.", chat_id=chat_id, message_id=call.message.message_id, parse_mode='Markdown')
    
    # Запускаем загрузку
    process_download(chat_id, url, action, user_msg_id, call.message.message_id)

# ---------------------------------------------------------
# ФУНКЦИЯ СКАЧИВАНИЯ И ОТПРАВКИ
# ---------------------------------------------------------
def process_download(chat_id, url, action, user_msg_id, status_msg_id):
    temp_folder = "downloads"
    # Создаем папку по абсолютному пути (чтобы точно знать, где она)
    abs_temp_folder = os.path.abspath(temp_folder)
    os.makedirs(abs_temp_folder, exist_ok=True)

    # Настройки yt-dlp
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
            
            # Поиск готового файла на диске
            expected_title = info.get('title', '')
            for f in os.listdir(abs_temp_folder):
                if expected_title in f or info['id'] in f:
                    file_path = os.path.join(abs_temp_folder, f)
                    break
            
            if not file_path:
                raise Exception("Файл не найден на диске после загрузки.")

        # ПРОВЕРКА РАЗМЕРА ФАЙЛА
        file_size = os.path.getsize(file_path)
        
        if file_size > 52428800: # 50 МБ в байтах
            size_mb = round(file_size / 1024 / 1024, 1)
            msg = (
                f"⚠️ *Файл слишком большой для Telegram!* ({size_mb} МБ)\n\n"
                f"Лимит бота — 50 МБ. Но я успешно скачал его и сохранил на ПК!\n\n"
                f"📁 *Ищи его тут:*\n`{file_path}`"
            )
            bot.edit_message_text(msg, chat_id=chat_id, message_id=status_msg_id, parse_mode='Markdown')
            # Важно: Не удаляем файл, оставляем на ПК
            return

        bot.edit_message_text("✅ *Отправляю в чат...*", chat_id=chat_id, message_id=status_msg_id, parse_mode='Markdown')

        # ОТПРАВКА
        with open(file_path, 'rb') as f:
            if action == "dl_mp3":
                bot.send_audio(chat_id, f, title=info.get('title', 'Трек'), performer="Твоя Музыка")
            else:
                bot.send_video(chat_id, f, caption=f"🎬 {info.get('title', 'Видео')}")

        # Уборка за собой
        try:
            bot.delete_message(chat_id, user_msg_id)
            bot.delete_message(chat_id, status_msg_id)
        except: 
            pass
        
        os.remove(file_path) # Удаляем отправленный файл с диска

    except Exception as e:
        bot.edit_message_text(f"❌ *Ошибка скачивания.* Возможно, этот формат недоступен.", chat_id=chat_id, message_id=status_msg_id, parse_mode='Markdown')
        print(f"System Error: {e}")
        
    finally:
        # В любом случае чистим память словаря
        if chat_id in user_data:
            del user_data[chat_id]

if __name__ == '__main__':
    print("🤖 БОТ-КОМБАЙН v6.0 УСПЕШНО ЗАПУЩЕН И ГОТОВ К РАБОТЕ!")
    bot.infinity_polling()