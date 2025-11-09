# 🤖 Telegram Bot Setup

Run ClippedAI directly through Telegram messenger.

## Features

- 📥 Download YouTube videos via bot commands
- 🎬 Generate multiple shorts per video
- 📊 Real-time progress notifications
- ⚡ Async processing for multiple users

## Prerequisites

1. Python 3.8+
2. All requirements from main ClippedAI project
3. Telegram Bot Token from [@BotFather](https://t.me/botfather)

## Installation

### 1. Install additional dependencies

```bash
pip install python-telegram-bot python-dotenv
```

### 2. Create Telegram Bot

1. Open [@BotFather](https://t.me/botfather) in Telegram
2. Send `/newbot`
3. Follow instructions to create bot
4. Copy your bot token (looks like `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`)

### 3. Setup environment variables

Create a `.env` file in project root:

```env
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
GROQ_API_KEY=your_groq_api_key_here
HUGGINGFACE_TOKEN=your_huggingface_token_here
```

**⚠️ IMPORTANT:** Never commit `.env` file to Git! Add it to `.gitignore`

### 4. Update .gitignore

Add this line to `.gitignore`:

```
.env
```

## Usage

### Start the bot

```bash
python telegram_bot.py
```

### Commands

- `/start` - Welcome message and instructions
- `/help` - Show usage guide
- `/status` - Check processing queue

### Send videos

Just send a YouTube link:

```
https://youtu.be/dQw4w9WgXcQ
```

Or specify number of clips (1-10):

```
https://youtu.be/dQw4w9WgXcQ 5
```

## Configuration

Edit these variables in `telegram_bot.py`:

```python
MAX_VIDEO_DURATION = 1800  # 30 minutes in seconds
DEFAULT_NUM_CLIPS = 3
MAX_NUM_CLIPS = 10
```

## Troubleshooting

**Bot not responding:**
- Check if `TELEGRAM_BOT_TOKEN` is correct in `.env`
- Verify bot is running with `python telegram_bot.py`

**Videos not processing:**
- Ensure all ClippedAI dependencies are installed
- Check `GROQ_API_KEY` and `HUGGINGFACE_TOKEN` in `.env`
- Verify video is public and under 30 minutes

**Environment variables not loading:**
```bash
pip install python-dotenv
```

Make sure `.env` file is in the same directory as `telegram_bot.py`

## Security Notes

- Never hardcode API keys in code
- Always use environment variables
- Add `.env` to `.gitignore`
- Don't share your bot token publicly

## License

Same as main ClippedAI project
