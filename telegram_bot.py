#!/usr/bin/env python3
"""
ClippedAI Telegram Bot
Автоматическое создание YouTube Shorts через Telegram
"""

import os
import sys
import logging
import asyncio
import subprocess
from pathlib import Path
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import yt_dlp
from groq import Groq
from huggingface_hub import login

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

# Авторизация в Hugging Face
login(HUGGINGFACE_TOKEN)

# Создание папок
Path("input").mkdir(exist_ok=True)
Path("output").mkdir(exist_ok=True)

# Глобальные переменные для ленивой инициализации
transcriber = None
clip_finder = None
groq_client = None

# Отслеживание активных процессов
user_processes = {}

def init_models():
    """Ленивая инициализация моделей"""
    global transcriber, clip_finder, groq_client
    if transcriber is None:
        logger.info("🤖 Инициализация AI моделей...")
        try:
            transcriber = Transcriber()
            clip_finder = ClipFinder()
            groq_client = Groq(api_key=GROQ_API_KEY)
            logger.info("✅ Модели загружены!")
        except Exception as e:
            logger.error(f"❌ Ошибка инициализации моделей: {e}")
            raise

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
        return title[:60]
    except Exception as e:
        logger.error(f"Title generation error: {e}")
        return "🔥 Amazing Moment"

def create_subtitled_video(video_path: str, transcription, clip, output_path: str) -> str:
    """Создает видео с субтитрами"""
    try:
        # Получаем слова для клипа
        word_info = [w for w in transcription.words 
                     if w.start >= clip.start_time and w.end <= clip.end_time]
        
        if not word_info:
            logger.warning("No words found for subtitles, returning original video")
            return video_path
        
        # Создаем простые субтитры через FFmpeg
        srt_file = output_path.replace('.mp4', '.srt')
        with open(srt_file, 'w', encoding='utf-8') as f:
            counter = 1
            for i in range(0, len(word_info), 5):  # Группируем по 5 слов
                words_group = word_info[i:i+5]
                start_time = words_group[0].start - clip.start_time
                end_time = words_group[-1].end - clip.start_time
                text = " ".join([w.word for w in words_group])
                
                f.write(f"{counter}\n")
                f.write(f"{format_srt_time(start_time)} --> {format_srt_time(end_time)}\n")
                f.write(f"{text}\n\n")
                counter += 1
        
        # Применяем субтитры через FFmpeg
        cmd = [
            'ffmpeg', '-i', video_path,
            '-vf', f"subtitles={srt_file}:force_style='FontName=Arial,FontSize=24,PrimaryColour=&HFFFFFF,OutlineColour=&H000000,Outline=2,Alignment=10'",
            '-c:a', 'copy',
            '-y', output_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            logger.error(f"FFmpeg subtitle error: {result.stderr}")
            return video_path
        
        # Удаляем временный SRT файл
        if os.path.exists(srt_file):
            os.remove(srt_file)
        
        return output_path
    except Exception as e:
        logger.error(f"Subtitle error: {e}")
        return video_path

def format_srt_time(seconds: float) -> str:
    """Форматирует время для SRT файла"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

async def process_video_task(video_path: str, num_clips: int, chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Обработка видео в фоне"""
    try:
        # Инициализация моделей если нужно
        init_models()
        
        # Транскрибация
        await context.bot.send_message(chat_id, "📝 Транскрибирую видео... (это может занять несколько минут)")
        transcription = transcriber.transcribe(audio_file_path=video_path)
        
        # Поиск клипов
        await context.bot.send_message(chat_id, "🎯 AI ищет лучшие моменты...")
        clips = clip_finder.find_clips(transcription=transcription)
        
        if not clips:
            await context.bot.send_message(chat_id, "❌ Не удалось найти подходящие моменты для клипов")
            return
        
        # Ограничиваем количество клипов
        clips = clips[:num_clips]
        await context.bot.send_message(chat_id, f"✂️ Создаю {len(clips)} шортов...")
        
        # Обработка каждого клипа
        for idx, clip in enumerate(clips, 1):
            try:
                await context.bot.send_message(chat_id, f"⚙️ Обрабатываю шорт {idx}/{len(clips)}...")
                
                # Генерация заголовка
                clip_words = [w.word for w in transcription.words 
                             if w.start >= clip.start_time and w.end <= clip.end_time]
                clip_text = " ".join(clip_words[:40])
                viral_title = generate_viral_title(clip_text)
                
                # Создаем временный файл для обрезанного видео
                temp_cropped = f"output/temp_cropped_{idx}.mp4"
                
                # Обрезаем видео по времени с помощью FFmpeg
                cmd = [
                    'ffmpeg', '-i', video_path,
                    '-ss', str(clip.start_time),
                    '-t', str(clip.end_time - clip.start_time),
                    '-c', 'copy',
                    '-y', temp_cropped
                ]
                subprocess.run(cmd, check=True, capture_output=True)
                
                # Изменяем размер до 9:16 (1080x1920)
                temp_resized = f"output/temp_resized_{idx}.mp4"
                cmd = [
                    'ffmpeg', '-i', temp_cropped,
                    '-vf', 'scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920',
                    '-c:a', 'copy',
                    '-y', temp_resized
                ]
                subprocess.run(cmd, check=True, capture_output=True)
                
                # Добавляем субтитры
                output_file = f"output/short_{idx}.mp4"
                final_video = create_subtitled_video(temp_resized, transcription, clip, output_file)
                
                # Отправка в Telegram
                with open(final_video, 'rb') as video:
                    await context.bot.send_video(
                        chat_id,
                        video=video,
                        caption=f"🎬 Шорт {idx}/{len(clips)}\n\n{viral_title}",
                        supports_streaming=True,
                        width=1080,
                        height=1920
                    )
                
                # Удаление временных файлов
                for temp_file in [temp_cropped, temp_resized, output_file]:
                    if os.path.exists(temp_file):
                        os.remove(temp_file)
                
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
⚙️ Модель: Whisper Large-v2
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
    logger.info("📱 Отправь ссылку YouTube в бота")
    
    # Запуск polling
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
