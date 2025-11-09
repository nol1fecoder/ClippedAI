#!/usr/bin/env python3
"""
ClippedAI Telegram Bot
Automatically create YouTube Shorts through Telegram
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
from dotenv import load_dotenv

from clipsai import Transcriber, ClipFinder, resize, MediaEditor, AudioVideoFile

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
HUGGINGFACE_TOKEN = os.getenv('HUGGINGFACE_TOKEN')
GROQ_API_KEY = os.getenv('GROQ_API_KEY')

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

login(HUGGINGFACE_TOKEN)

Path("input").mkdir(exist_ok=True)
Path("output").mkdir(exist_ok=True)

transcriber = None
clip_finder = None
groq_client = None

user_processes = {}

def init_models():
    global transcriber, clip_finder, groq_client
    if transcriber is None:
        logger.info("🤖 Initializing AI models...")
        try:
            transcriber = Transcriber()
            clip_finder = ClipFinder()
            groq_client = Groq(api_key=GROQ_API_KEY)
            logger.info("✅ Models loaded!")
        except Exception as e:
            logger.error(f"❌ Model initialization error: {e}")
            raise

def download_youtube_video(url: str) -> tuple:
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
    try:
        word_info = [w for w in transcription.words 
                     if w.start >= clip.start_time and w.end <= clip.end_time]
        
        if not word_info:
            logger.warning("No words found for subtitles, returning original video")
            return video_path
        
        srt_file = output_path.replace('.mp4', '.srt')
        with open(srt_file, 'w', encoding='utf-8') as f:
            counter = 1
            for i in range(0, len(word_info), 5):
                words_group = word_info[i:i+5]
                start_time = words_group[0].start - clip.start_time
                end_time = words_group[-1].end - clip.start_time
                text = " ".join([w.word for w in words_group])
                
                f.write(f"{counter}\n")
                f.write(f"{format_srt_time(start_time)} --> {format_srt_time(end_time)}\n")
                f.write(f"{text}\n\n")
                counter += 1
        
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
        
        if os.path.exists(srt_file):
            os.remove(srt_file)
        
        return output_path
    except Exception as e:
        logger.error(f"Subtitle error: {e}")
        return video_path

def format_srt_time(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

async def process_video_task(video_path: str, num_clips: int, chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    try:
        init_models()
        
        await context.bot.send_message(chat_id, "📝 Transcribing video... (this may take a few minutes)")
        transcription = transcriber.transcribe(audio_file_path=video_path)
        
        await context.bot.send_message(chat_id, "🎯 AI is finding the best moments...")
        clips = clip_finder.find_clips(transcription=transcription)
        
        if not clips:
            await context.bot.send_message(chat_id, "❌ Failed to find suitable moments for clips")
            return
        
        clips = clips[:num_clips]
        await context.bot.send_message(chat_id, f"✂️ Creating {len(clips)} shorts...")
        
        for idx, clip in enumerate(clips, 1):
            try:
                await context.bot.send_message(chat_id, f"⚙️ Processing short {idx}/{len(clips)}...")
                
                clip_words = [w.word for w in transcription.words 
                             if w.start >= clip.start_time and w.end <= clip.end_time]
                clip_text = " ".join(clip_words[:40])
                viral_title = generate_viral_title(clip_text)
                
                temp_cropped = f"output/temp_cropped_{idx}.mp4"
                
                cmd = [
                    'ffmpeg', '-i', video_path,
                    '-ss', str(clip.start_time),
                    '-t', str(clip.end_time - clip.start_time),
                    '-c', 'copy',
                    '-y', temp_cropped
                ]
                subprocess.run(cmd, check=True, capture_output=True)
                
                temp_resized = f"output/temp_resized_{idx}.mp4"
                cmd = [
                    'ffmpeg', '-i', temp_cropped,
                    '-vf', 'scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920',
                    '-c:a', 'copy',
                    '-y', temp_resized
                ]
                subprocess.run(cmd, check=True, capture_output=True)
                
                output_file = f"output/short_{idx}.mp4"
                final_video = create_subtitled_video(temp_resized, transcription, clip, output_file)
                
                with open(final_video, 'rb') as video:
                    await context.bot.send_video(
                        chat_id,
                        video=video,
                        caption=f"🎬 Short {idx}/{len(clips)}\n\n{viral_title}",
                        supports_streaming=True,
                        width=1080,
                        height=1920
                    )
                
                for temp_file in [temp_cropped, temp_resized, output_file]:
                    if os.path.exists(temp_file):
                        os.remove(temp_file)
                
            except Exception as e:
                logger.error(f"Error processing clip {idx}: {e}")
                await context.bot.send_message(chat_id, f"⚠️ Error creating short {idx}: {str(e)}")
        
        await context.bot.send_message(chat_id, "✅ Done! All shorts sent!")
        
    except Exception as e:
        logger.error(f"Processing error: {e}")
        await context.bot.send_message(chat_id, f"❌ Processing error: {str(e)}")
    
    finally:
        if os.path.exists(video_path):
            os.remove(video_path)
        if chat_id in user_processes:
            del user_processes[chat_id]

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = """
🎬 *ClippedAI YouTube Shorts Bot*

Hello! I create viral YouTube Shorts from long videos!

📋 *How to use:*
Just send me a YouTube video link

*Examples:*
`https://youtube.com/watch?v=...`
`https://youtu.be/...`

You can add number of clips:
`https://youtu.be/... 5`

🎯 *What I can do:*
✅ AI selects best moments
✅ Automatic subtitles
✅ 9:16 format for shorts
✅ Viral titles with emojis

⏱️ Processing takes 5-20 minutes depending on video length

💡 *Commands:*
/start - Show this message
/status - Bot status
/help - Help
"""
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    active_tasks = len(user_processes)
    status_text = f"""
📊 *Bot Status:*

🟢 Status: Active
⚙️ Model: Whisper Large-v2
📝 Active tasks: {active_tasks}
🎬 Availability: Ready to work
"""
    await update.message.reply_text(status_text, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
❓ *Help*

*Supported formats:*
• YouTube links (youtube.com, youtu.be)
• Maximum video length: 30 minutes

*Command format:*
`URL [number_of_clips]`

Default: 3 clips
Maximum: 10 clips

*Examples:*
`https://youtu.be/dQw4w9WgXcQ` - 3 clips
`https://youtu.be/dQw4w9WgXcQ 5` - 5 clips

*Issues?*
• Check if link is correct
• Make sure video is public
• Wait for previous task to complete
"""
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    message_text = update.message.text.strip()
    
    if chat_id in user_processes:
        await update.message.reply_text("⏳ Already processing your previous video. Please wait!")
        return
    
    parts = message_text.split()
    if not parts:
        await update.message.reply_text("❌ Send a YouTube video link")
        return
    
    url = parts[0]
    num_clips = 3
    
    if len(parts) > 1:
        try:
            num_clips = int(parts[1])
            num_clips = max(1, min(num_clips, 10))
        except ValueError:
            pass
    
    if not ('youtube.com' in url or 'youtu.be' in url):
        await update.message.reply_text("❌ Invalid YouTube link. Send youtube.com or youtu.be format")
        return
    
    user_processes[chat_id] = True
    
    try:
        await update.message.reply_text("📥 Downloading video from YouTube...")
        video_path, title, duration = download_youtube_video(url)
        
        if duration > 1800:
            os.remove(video_path)
            del user_processes[chat_id]
            await update.message.reply_text("❌ Video too long! Maximum 30 minutes")
            return
        
        duration_min = duration // 60
        await update.message.reply_text(
            f"✅ Downloaded: *{title}*\n"
            f"⏱️ Duration: {duration_min} min\n"
            f"🎬 Creating {num_clips} shorts...\n\n"
            f"_This will take 5-20 minutes. I'll send clips when ready!_",
            parse_mode='Markdown'
        )
        
        asyncio.create_task(process_video_task(video_path, num_clips, chat_id, context))
        
    except Exception as e:
        logger.error(f"Error in handle_message: {e}")
        if chat_id in user_processes:
            del user_processes[chat_id]
        await update.message.reply_text(f"❌ Error: {str(e)}")

def main():
    logger.info("🚀 Starting ClippedAI Telegram Bot...")
    
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("✅ Bot started and ready!")
    logger.info("📱 Send YouTube link to bot")
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
