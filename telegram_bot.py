#!/usr/bin/env python3
"""
ClippedAI Telegram Bot
Автоматическое создание YouTube Shorts через Telegram
"""

import os
import sys
import logging
import asyncio
from pathlib import Path
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import yt_dlp
from groq import Groq

# Импорт ClippedAI модулей
from clipsai import Transcriber, ClipFinder, resize, MediaEditor, AudioVideoFile

# ============= НАСТРОЙКИ =============
TELEGRAM_BOT_TOKEN = "8577135156:AAFij6C6rbbzmgg761svzglXNZ4O6xL92Dg"
HUGGINGFACE_TOKEN = "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"
GROQ_API_KEY = "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"
# =====================================

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Установка переменных окружения
os.environ['HUGGINGFACE_TOKEN'] = HUGGINGFACE_TOKEN

# Создание папок
Path("input").mkdir(exist_ok=True)
Path("output").mkdir(exist_ok=True)

# Инициализация AI моделей
logger.info("🤖 Инициализация AI моделей...")
transcriber = Transcriber(model_size="base")  # base = оптимальная скорость
clip_finder = ClipFinder()
groq_client = Groq(api_key=GROQ_API_KEY)

# Отслеживание активных процессов
user_processes = {}

def download_youtube_video(url: str) -> tuple:
    """Скачивает видео с YouTube"""
    try:
        video_id = url.split('v=')[-1].split('&')[0] if 'v=' in url else url.split('/')[-1]
        output_path = f"input/{video_id}.mp4"
        
        ydl_opts = {
            'format': 'best[ext=mp4][height<=720]',
            'outtmpl': output_path,
            'quiet': True,
            'no_warnings': True,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get('title', 'Video')
            duration = info.get('duration', 0)
            
        return output_path, title, duration
    except Exception as e:
        logger.error(f"Download error: {e}")
        raise

def generate_viral_title(transcript_text: str) -> str:
    """Генерирует вирусный заголовок"""
    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{
                "role": "user",
                "content": f"Create a short, catchy YouTube Shorts title (max 50 characters) with emojis. Based on this transcript: {transcript_text[:400]}"
            }],
            temperature=0.8,
            max_tokens=50
        )
        title = response.choices[0].message.content.strip()
        return title[:60]  # Ограничение длины
    except Exception as e:
        logger.error(f"Title generation error: {e}")
        return "🔥 Amazing Moment"

async def process_video_task(video_path: str, num_clips: int, chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Обработка видео в фоне"""
    try:
        # Транскрибация
        await context.bot.send_message(chat_id, "📝 Транскрибирую видео... (это может занять несколько минут)")
        transcription = transcriber.transcribe(audio_file_path=video_path)
        
        # Поиск клипов
        await context.bot.send_message(chat_id, "🎯 AI ищет лучшие моменты...")
        clips = clip_finder.find_clips(transcription=transcription, num_clips=num_clips)
        
        if not clips:
            await context.bot.send_message(chat_id, "❌ Не удалось найти подходящие моменты для клипов")
            return
        
        await context.bot.send_message(chat_id, f"✂️ Создаю {len(clips)} шортов...")
        
        # Обработка каждого клипа
        for idx, clip in enumerate(clips, 1):
            try:
                await context.bot.send_message(chat_id, f"⚙️ Обрабатываю шорт {idx}/{len(clips)}...")
                
                # Нарезка видео
                clip.crop(video_path)
                
                # Изменение размера до 9:16
                resized_clip = resize(clip, "social_media")
                
                # Добавление субтитров
                final_clip = add_subtitles(
                    resized_clip,
                    font="Montserrat-ExtraBold",
                    font_color="white",
                    stroke_color="black",
                    stroke_width=3
                )
                
                # Генерация заголовка
                clip_words = [w.word for w in clip.transcription.words[:40]]
                clip_text = " ".join(clip_words)
                viral_title = generate_viral_title(clip_text)
                
                # Сохранение
                output_file = f"output/short_{idx}.mp4"
                final_clip.write_videofile(
                    output_file,
                    codec='libx264',
                    audio_codec='aac',
                    verbose=False,
                    logger=None
                )
                
                # Отправка в Telegram
                with open(output_file, 'rb') as video:
                    await context.bot.send_video(
                        chat_id,
                        video=video,
                        caption=f"🎬 Шорт {idx}/{len(clips)}\n\n{viral_title}",
                        supports_streaming=True,
                        width=1080,
                        height=1920
                    )
                
                # Удаление временного файла
                os.remove(output_file)
                
            except Exception as e:
                logger.error(f"Error processing clip {idx}: {e}")
                await context.bot.send_message(chat_id, f"⚠️ Ошибка при создании шорта {idx}: {str(e)}")
        
        await context.bot.send_message(chat_id, "✅ Готово! Все шорты отправлены!")
        
    except Exception as e:
        logger.error(f"Processing error: {e}")
        await context.bot.send_message(chat_id, f"❌ Ошибка обработки: {str(e)}")
    
    finally:
        # Очистка
        if os.path.exists(video_path):
            os.remove(video_path)
        if chat_id in user_processes:
            del user_processes[chat_id]

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    welcome_text = """
🎬 *ClippedAI YouTube Shorts Bot*

Привет! Я создаю вирусные YouTube Shorts из длинных видео!

📋 *Как использовать:*
Просто отправь мне ссылку на YouTube видео

*Примеры:*
`https://youtube.com/watch?v=...`
`https://youtu.be/...`

Можешь добавить число клипов:
`https://youtu.be/... 5`

🎯 *Что я умею:*
✅ AI выбирает лучшие моменты
✅ Автоматические субтитры
✅ Формат 9:16 для шортов
✅ Вирусные заголовки с эмодзи

⏱️ Обработка занимает 5-20 минут в зависимости от длины видео

💡 *Команды:*
/start - Показать это сообщение
/status - Статус бота
/help - Помощь
"""
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /status"""
    active_tasks = len(user_processes)
    status_text = f"""
📊 *Статус бота:*

🟢 Статус: Активен
⚙️ Модель: Whisper Base
📝 Активных задач: {active_tasks}
🎬 Доступность: Готов к работе
"""
    await update.message.reply_text(status_text, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /help"""
    help_text = """
❓ *Помощь*

*Поддерживаемые форматы:*
• YouTube ссылки (youtube.com, youtu.be)
• Максимальная длина видео: 30 минут

*Формат команды:*
`URL [количество_клипов]`

По умолчанию создается 3 клипа
Максимум: 10 клипов

*Примеры:*
`https://youtu.be/dQw4w9WgXcQ` - 3 клипа
`https://youtu.be/dQw4w9WgXcQ 5` - 5 клипов

*Проблемы?*
• Проверь правильность ссылки
• Убедись что видео публичное
• Подожди завершения предыдущей задачи
"""
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка текстовых сообщений"""
    chat_id = update.effective_chat.id
    message_text = update.message.text.strip()
    
    # Проверка активного процесса
    if chat_id in user_processes:
        await update.message.reply_text("⏳ Я уже обрабатываю твоё предыдущее видео. Дождись завершения!")
        return
    
    # Парсинг сообщения
    parts = message_text.split()
    if not parts:
        await update.message.reply_text("❌ Отправь ссылку на YouTube видео")
        return
    
    url = parts[0]
    num_clips = 3
    
    # Парсинг количества клипов
    if len(parts) > 1:
        try:
            num_clips = int(parts[1])
            num_clips = max(1, min(num_clips, 10))
        except ValueError:
            pass
    
    # Проверка YouTube URL
    if not ('youtube.com' in url or 'youtu.be' in url):
        await update.message.reply_text("❌ Это не похоже на YouTube ссылку. Отправь ссылку формата youtube.com или youtu.be")
        return
    
    # Отметка активного процесса
    user_processes[chat_id] = True
    
    try:
        # Скачивание видео
        await update.message.reply_text("📥 Скачиваю видео с YouTube...")
        video_path, title, duration = download_youtube_video(url)
        
        # Проверка длительности
        if duration > 1800:  # 30 минут
            os.remove(video_path)
            del user_processes[chat_id]
            await update.message.reply_text("❌ Видео слишком длинное! Максимум 30 минут")
            return
        
        duration_min = duration // 60
        await update.message.reply_text(
            f"✅ Скачано: *{title}*\n"
            f"⏱️ Длина: {duration_min} мин\n"
            f"🎬 Создаю {num_clips} шортов...\n\n"
            f"_Это займет 5-20 минут. Я пришлю шорты по готовности!_",
            parse_mode='Markdown'
        )
        
        # Запуск обработки в фоне
        asyncio.create_task(process_video_task(video_path, num_clips, chat_id, context))
        
    except Exception as e:
        logger.error(f"Error in handle_message: {e}")
        if chat_id in user_processes:
            del user_processes[chat_id]
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")

def main():
    """Запуск бота"""
    logger.info("🚀 Запуск ClippedAI Telegram Bot...")
    
    # Создание приложения
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Регистрация обработчиков
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("✅ Бот запущен и готов к работе!")
    logger.info("📱 Отправь ссылку YouTube в @MyYoutubeShortBot")
    
    # Запуск polling
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
