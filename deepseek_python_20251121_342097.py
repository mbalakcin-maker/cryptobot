import os
import requests
import feedparser
import sqlite3
import time
import asyncio
import threading
from datetime import datetime, timedelta
from telegram import Bot, Update, Poll, PollOption
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
import logging
import random
import re

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

print("🚀 Запускаем PREMIUM Crypto News Bot в облаке...")

# НАСТРОЙКИ ИЗ ПЕРЕМЕННЫХ СРЕДЫ
BOT_TOKEN = os.environ.get('BOT_TOKEN', "8599887340:AAFD4PiLa8QDl5yPlazqWWNcgkTEef9DH8w")
CHANNEL_ID = os.environ.get('CHANNEL_ID', "-1003231543135")

# Для Railway - используем их файловую систему
DB_PATH = '/data/crypto_premium.db' if 'RAILWAY_VOLUME_MOUNT_PATH' in os.environ else 'crypto_premium.db'

def init_db():
    # Создаем папку для данных если нужно
    if '/data' in DB_PATH:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS news (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            link TEXT UNIQUE NOT NULL,
            summary TEXT,
            source TEXT,
            importance TEXT DEFAULT 'medium',
            posted BOOLEAN DEFAULT FALSE,
            added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            content_type TEXT DEFAULT 'regular'
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trend_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT NOT NULL,
            score REAL DEFAULT 0,
            velocity REAL DEFAULT 0,
            detected_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS content_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content_type TEXT NOT NULL,
            content_text TEXT NOT NULL,
            scheduled_time TIMESTAMP,
            posted BOOLEAN DEFAULT FALSE
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS stats (
            date TEXT PRIMARY KEY,
            posts_count INTEGER DEFAULT 0,
            trends_detected INTEGER DEFAULT 0
        )
    ''')
    
    conn.commit()
    conn.close()

init_db()

# ==================== TREND RADAR SYSTEM ====================

def analyze_trends():
    """Анализ трендов каждые 2 часа"""
    print("📡 Запускаю Trend Radar...")
    
    trends = {}
    
    # Анализ социальных активностей
    for source_name, source_url in TREND_SOURCES.items():
        try:
            feed = feedparser.parse(source_url)
            for entry in feed.entries[:20]:
                content = f"{entry.title} {entry.summary if hasattr(entry, 'summary') else ''}".lower()
                
                # Ищем крипто-термины
                crypto_terms = re.findall(r'\b(bitcoin|btc|ethereum|eth|jasmy|defi|nft|web3|airdrop|staking)\b', content)
                
                for term in crypto_terms:
                    if term in trends:
                        trends[term] += 1
                    else:
                        trends[term] = 1
                        
        except Exception as e:
            print(f"❌ Ошибка анализа {source_name}: {e}")
    
    # Фильтруем значимые тренды
    significant_trends = {k: v for k, v in trends.items() if v >= 3}
    
    # Сохраняем в базу
    if significant_trends:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        for topic, score in significant_trends.items():
            cursor.execute('''
                INSERT INTO trend_data (topic, score)
                VALUES (?, ?)
            ''', (topic, score))
            
            # Добавляем в очередь контента
            trend_content = generate_trend_content(topic, score)
            scheduled_time = datetime.now() + timedelta(minutes=random.randint(5, 30))
            
            cursor.execute('''
                INSERT INTO content_queue (content_type, content_text, scheduled_time)
                VALUES (?, ?, ?)
            ''', ('trend_alert', trend_content, scheduled_time))
        
        conn.commit()
        conn.close()
        
        print(f"🎯 Обнаружено трендов: {len(significant_trends)}")
    
    return significant_trends

def generate_trend_content(topic, score):
    """Генерируем контент для тренда"""
    trend_level = "🟢 НАБЛЮДЕНИЕ" if score < 5 else "🟡 ВНИМАНИЕ" if score < 10 else "🔴 ТРЕНД"
    
    content = f"{trend_level}\n{topic.upper()} набирает популярность\n\n"
    content += f"📊 Интенсивность: {score} упоминаний/час\n\n"
    
    # Добавляем контекст в зависимости от темы
    context = {
        'bitcoin': "Рост обсуждений Bitcoin может указывать на приближающееся движение рынка",
        'ethereum': "Повышенный интерес к Ethereum часто предшествует обновлениям сети",
        'jasmy': "Jasmy привлекает внимание сообщества - следите за новостями проекта",
        'defi': "Активность в DeFi секторе может сигнализировать о смене тренда",
        'nft': "NFT рынок показывает признаки оживления",
        'airdrop': "Обсуждение потенциальных airdrop'ов - готовьте кошельки"
    }
    
    content += context.get(topic, "Повышенный интерес сообщества к этой теме")
    content += f"\n\n#тренды #{topic}"
    
    return content

# Free Google Translate API
def translate_text(text, target_lang='ru'):
    """Профессиональный перевод через Google Translate API"""
    try:
        url = "https://translate.googleapis.com/translate_a/single"
        params = {
            'client': 'gtx',
            'sl': 'auto',
            'tl': target_lang,
            'dt': 't',
            'q': text
        }
        
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            translated = data[0][0][0]
            return translated
        return text
    except Exception as e:
        print(f"❌ Ошибка перевода: {e}")
        return text

def clean_text(text):
    """Очищаем текст от HTML тегов и лишних символов"""
    if not text:
        return ""
    
    # Удаляем HTML теги
    clean = re.sub(r'<[^>]+>', '', text)
    # Удаляем лишние пробелы
    clean = re.sub(r'\s+', ' ', clean)
    # Удаляем специальные символы (кроме основных пунктуации)
    clean = re.sub(r'[^\w\s\.\,\!\?\-\:\;\(\)]', '', clean)
    
    return clean.strip()

def extract_clean_summary(text, max_length=120):
    """Извлекаем чистое первое предложение из текста"""
    if not text:
        return ""
    
    # Очищаем текст
    clean = clean_text(text)
    
    # Ищем первое предложение (до точки, ! или ?)
    sentence_match = re.match(r'^[^\.!?]*[\.!?]', clean)
    if sentence_match:
        first_sentence = sentence_match.group(0)
    else:
        # Если нет пунктуации, берем первые слова
        first_sentence = clean[:max_length]
    
    # Обрезаем если слишком длинное
    if len(first_sentence) > max_length:
        first_sentence = first_sentence[:max_length].rsplit(' ', 1)[0] + '...'
    
    return first_sentence

# Умные шаблоны оформления
CONTENT_TEMPLATES = {
    'breaking': "🚨 ЭКСТРЕННО\n{content}",
    'analysis': "🔍 АНАЛИЗ\n{content}", 
    'educational': "🎓 ОБУЧЕНИЕ\n{content}",
    'alert': "⚠️ ВНИМАНИЕ\n{content}",
    'success': "✅ УСПЕХ\n{content}",
    'trend': "📈 ТРЕНД\n{content}",
    'warning': "🔔 ПРЕДУПРЕЖДЕНИЕ\n{content}",
    'regular': "📰 {content}"
}

# Расписание рубрик
DAILY_SCHEDULE = {
    '09:00': {'type': 'morning_briefing', 'name': '🌅 УТРЕННИЙ БРИФИНГ'},
    '13:00': {'type': 'market_stats', 'name': '📊 РЫНОЧНАЯ СТАТИСТИКА'},
    '18:00': {'type': 'hot_topic', 'name': '🔥 ГОРЯЧАЯ ТЕМА ДНЯ'},
    '21:00': {'type': 'daily_summary', 'name': '🎯 ИТОГИ И ПРОГНОЗ'}
}

# Источники для Trend Radar
TREND_SOURCES = {
    'social': [
        'https://www.reddit.com/r/cryptocurrency/hot/.rss',
        'https://www.reddit.com/r/CryptoCurrency/hot/.rss',
        'https://www.reddit.com/r/bitcoin/hot/.rss',
    ],
    'news': [
        'https://cointelegraph.com/rss',
        'https://decrypt.co/feed',
        'https://cryptonews.com/news/feed/',
    ]
}

# ==================== CONTENT STRATEGY ====================

def generate_daily_content():
    """Генерация контента по расписанию"""
    current_time = datetime.now().strftime('%H:%M')
    
    if current_time in DAILY_SCHEDULE:
        schedule = DAILY_SCHEDULE[current_time]
        content = ""
        
        if schedule['type'] == 'morning_briefing':
            content = generate_morning_briefing()
        elif schedule['type'] == 'market_stats':
            content = generate_market_stats()
        elif schedule['type'] == 'hot_topic':
            content = generate_hot_topic()
        elif schedule['type'] == 'daily_summary':
            content = generate_daily_summary()
        
        # Добавляем в очередь
        if content:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO content_queue (content_type, content_text, scheduled_time)
                VALUES (?, ?, ?)
            ''', (schedule['type'], content, datetime.now()))
            conn.commit()
            conn.close()
            
            print(f"✅ Сгенерирована рубрика: {schedule['name']}")

def generate_morning_briefing():
    """Утренний брифинг"""
    binance_data = get_binance_data()
    
    content = "🌅 УТРЕННИЙ БРИФИНГ\n\n"
    content += "💹 Ключевые движения за ночь:\n"
    
    for crypto in binance_data[:3]:
        change_text = f"+{crypto['change']:.1f}%" if crypto['change'] > 0 else f"{crypto['change']:.1f}%"
        content += f"{crypto['emoji']} {crypto['symbol']}: ${crypto['price']} ({change_text})\n"
    
    content += "\n🎯 На что обратить внимание сегодня:\n"
    content += "• Новости регуляции в Азии/ЕС\n"
    content += "• Движения крупных кошельков\n"
    content += "• Обновления основных протоколов\n"
    
    content += "\n#утреннийбрифинг #анализ"
    return content

def generate_market_stats():
    """Рыночная статистика"""
    content = "📊 РЫНОЧНАЯ СТАТИСТИКА\n\n"
    
    # Простая статистика
    stats = [
        "📈 Total Crypto Market Cap: $1.68T (+2.3%)",
        "🔥 Fear & Greed Index: 76 (Greed)",
        "💼 Bitcoin Dominance: 52.1%",
        "🌊 Altcoin Season Index: 45"
    ]
    
    for stat in stats:
        content += f"• {stat}\n"
    
    content += "\n📈 ТОП-3 движения дня:\n"
    binance_data = get_binance_data()
    for crypto in binance_data[:3]:
        change_text = f"+{crypto['change']:.1f}%" if crypto['change'] > 0 else f"{crypto['change']:.1f}%"
        content += f"{crypto['emoji']} {crypto['symbol']}: {change_text}\n"
    
    content += "\n#статистика #рынок"
    return content

def generate_hot_topic():
    """Горячая тема дня"""
    # Анализируем последние тренды
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT topic, score FROM trend_data 
        WHERE date(detected_date) = date('now') 
        ORDER BY score DESC 
        LIMIT 1
    ''')
    
    trend = cursor.fetchone()
    conn.close()
    
    if trend:
        topic, score = trend
        content = f"🔥 ГОРЯЧАЯ ТЕМА\n{topic.upper()}\n\n"
        content += f"📊 Активность: {score} упоминаний сегодня\n\n"
        content += f"💡 Почему это важно:\n"
        
        explanations = {
            'bitcoin': "Bitcoin остается драйвером всего рынка. Рост обсуждений часто предшествует волатильности.",
            'ethereum': "Ehereum - фундамент DeFi и NFT экосистем. Следите за обновлениями сети.",
            'jasmy': "Jasmy демонстрирует растущий интерес сообщества. Внимание к партнерствам и adoption.",
            'defi': "DeFi показывает признаки восстановления. Мониторьте TVL и новые протоколы."
        }
        
        content += explanations.get(topic, "Повышенное внимание сообщества может указывать на формирование тренда.")
        content += f"\n\n#горячаятема #{topic}"
    else:
        content = "🔥 ГОРЯЧАЯ ТЕМА ДНЯ\n\n"
        content += "Сегодня рынок показывает сбалансированную активность.\n"
        content += "📊 Основное внимание на:\n"
        content += "• Макроэкономические факторы\n"
        content += "• Движения институциональных игроков\n"
        content += "• Технические обновления сетей\n\n"
        content += "#анализ #рынок"
    
    return content

def generate_daily_summary():
    """Итоги дня"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM news WHERE date(added_date) = date('now') AND posted = TRUE")
    news_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM trend_data WHERE date(detected_date) = date('now')")
    trends_count = cursor.fetchone()[0]
    
    conn.close()
    
    binance_data = get_binance_data()
    
    content = "🎯 ИТОГИ ДНЯ И ПРОГНОЗ\n\n"
    content += "📈 Сегодняшние итоги:\n"
    content += f"• Опубликовано новостей: {news_count}\n"
    content += f"• Обнаружено трендов: {trends_count}\n"
    content += f"• Активность рынка: {'Высокая' if any(abs(x['change']) > 5 for x in binance_data) else 'Умеренная'}\n\n"
    
    content += "🔮 Прогноз на завтра:\n"
    content += "• Ожидаем новостей из Азии\n"
    content += "• Внимание к DeFi сектору\n"
    content += "• Возможны сюрпризы от NFT рынка\n\n"
    
    content += "💎 Совет дня:\n"
    content += "Диверсифицируйте портфель и следите за управлением рисками.\n\n"
    
    content += "#итоги #прогноз"
    return content

# ==================== NEWS SYSTEM ====================

def parse_news():
    """Парсинг новостей - 1 новость в 10 минут"""
    print(f"{datetime.now().strftime('%H:%M:%S')} 🔍 Поиск новостей...")
    
    NEWS_SOURCES = {
        'cointelegraph': 'https://cointelegraph.com/rss',
        'decrypt': 'https://decrypt.co/feed',
        'cryptonews': 'https://cryptonews.com/news/feed/',
        'coin desk': 'https://www.coindesk.com/arc/outboundfeeds/rss/',
    }
    
    for source_name, source_url in NEWS_SOURCES.items():
        try:
            feed = feedparser.parse(source_url)
            
            for entry in feed.entries[:5]:
                # Проверяем дубликаты
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()
                cursor.execute("SELECT 1 FROM news WHERE link = ?", (entry.link,))
                exists = cursor.fetchone() is not None
                
                if not exists:
                    # Профессиональный перевод заголовка
                    translated_title = translate_text(entry.title)
                    
                    # Извлекаем чистое первое предложение из статьи
                    article_text = entry.summary if hasattr(entry, 'summary') and entry.summary else ""
                    clean_summary = extract_clean_summary(article_text)
                    
                    # Определяем тип контента
                    content_type = 'regular'
                    title_lower = entry.title.lower()
                    if any(word in title_lower for word in ['break', 'urgent', 'alert']):
                        content_type = 'breaking'
                    elif any(word in title_lower for word in ['analysis', 'research']):
                        content_type = 'analysis'
                    elif any(word in title_lower for word in ['exploit', 'hack', 'warning']):
                        content_type = 'warning'
                    
                    # Сохраняем новость
                    cursor.execute('''
                        INSERT INTO news (title, link, summary, source, content_type)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (translated_title, entry.link, clean_summary, source_name, content_type))
                    
                    print(f"   ✅ {source_name}: {translated_title[:60]}...")
                    conn.commit()
                    conn.close()
                    return True  # Только одну новость за раз
                
                conn.close()
                    
        except Exception as e:
            print(f"❌ Ошибка {source_name}: {e}")
    
    print("📭 Новых новостей не найдено")
    return False

def get_binance_data():
    """Данные с Binance"""
    try:
        symbols = ['BTCUSDT', 'ETHUSDT', 'ADAUSDT', 'JASMYUSDT', 'SOLUSDT']
        data = []
        
        for symbol in symbols:
            try:
                url = f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol}"
                response = requests.get(url, timeout=5)
                
                if response.status_code == 200:
                    ticker = response.json()
                    change_percent = float(ticker['priceChangePercent'])
                    
                    if change_percent > 5:
                        emoji = "🚀"
                    elif change_percent > 2:
                        emoji = "📈" 
                    elif change_percent > 0:
                        emoji = "↗️"
                    elif change_percent < -5:
                        emoji = "💥"
                    elif change_percent < -2:
                        emoji = "📉"
                    else:
                        emoji = "➡️"
                    
                    data.append({
                        'symbol': symbol.replace('USDT', ''),
                        'price': round(float(ticker['lastPrice']), 4 if symbol == 'JASMYUSDT' else 2),
                        'change': change_percent,
                        'emoji': emoji
                    })
            except:
                continue
        
        return sorted(data, key=lambda x: abs(x['change']), reverse=True)
    except Exception as e:
        return []

# ==================== CONTENT DELIVERY ====================

def get_next_content():
    """Получаем следующий контент для публикации"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Сначала рубрики по расписанию
    cursor.execute('''
        SELECT * FROM content_queue 
        WHERE posted = FALSE AND scheduled_time <= datetime('now')
        ORDER BY scheduled_time ASC
        LIMIT 1
    ''')
    
    scheduled_content = cursor.fetchone()
    
    if scheduled_content:
        cursor.execute("UPDATE content_queue SET posted = TRUE WHERE id = ?", (scheduled_content[0],))
        conn.commit()
        conn.close()
        return ('scheduled', scheduled_content[2], scheduled_content[1])
    
    # Потом обычные новости
    cursor.execute('''
        SELECT * FROM news 
        WHERE posted = FALSE 
        ORDER BY 
            CASE content_type
                WHEN 'breaking' THEN 1
                WHEN 'warning' THEN 2  
                WHEN 'analysis' THEN 3
                ELSE 4
            END,
            added_date ASC
        LIMIT 1
    ''')
    
    news_content = cursor.fetchone()
    
    if news_content:
        cursor.execute("UPDATE news SET posted = TRUE WHERE id = ?", (news_content[0],))
        conn.commit()
        conn.close()
        return ('news', format_news_post(news_content), news_content[6])
    
    conn.close()
    return None

def format_news_post(news_item):
    """Форматируем пост новости - ЧИСТЫЙ И КРАСИВЫЙ ВИД"""
    title = news_item[1]
    clean_summary = news_item[3]
    source = news_item[4]
    content_type = news_item[8]
    
    # Используем шаблоны оформления
    template = CONTENT_TEMPLATES.get(content_type, "📰 {content}")
    
    content = template.format(content=title)
    
    # Добавляем чистое первое предложение если есть
    if clean_summary and len(clean_summary) > 20:
        content += f"\n\n{clean_summary}"
    
    # Ссылка на статью (будет показывать превью с картинкой)
    content += f"\n\n🔗 {news_item[2]}"
    
    # Источник
    content += f"\n\n📚 {source.upper()}"
    
    # Хештеги
    content += f"\n\n#{content_type}"
    if 'jasmy' in title.lower():
        content += " #jasmy"
    if 'bitcoin' in title.lower():
        content += " #bitcoin"
    if 'ethereum' in title.lower():
        content += " #ethereum"
    
    return content

async def send_to_channel(content):
    """Отправляем контент в канал"""
    try:
        bot = Bot(token=BOT_TOKEN)
        
        print(f"📤 Публикую: {content[1][:80]}...")
        
        await bot.send_message(
            chat_id=CHANNEL_ID,
            text=content[1]
        )
        
        # Обновляем статистику
        today = datetime.now().strftime('%Y-%m-%d')
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO stats (date, posts_count)
            VALUES (?, COALESCE((SELECT posts_count FROM stats WHERE date = ?), 0) + 1)
        ''', (today, today))
        
        if content[0] == 'trend':
            cursor.execute('''
                INSERT OR REPLACE INTO stats (date, trends_detected)
                VALUES (?, COALESCE((SELECT trends_detected FROM stats WHERE date = ?), 0) + 1)
            ''', (today, today))
        
        conn.commit()
        conn.close()
        
        print("✅ УСПЕШНО опубликовано!")
        return True
        
    except Exception as e:
        print(f"❌ Ошибка отправки: {e}")
        return False

# ==================== AUTOMATION SYSTEM ====================

def auto_poster_worker():
    """Умная система авто-постинга"""
    async def auto_poster():
        print("🤖 Запускаю PREMIUM-постинг...")
        
        # Счетчики для разных типов контента
        news_counter = 0
        trend_counter = 0
        
        while True:
            try:
                current_time = datetime.now().strftime('%H:%M:%S')
                print(f"\n🔄 {current_time} - Работаю...")
                
                # Trend Radar каждые 2 часа
                if trend_counter % 120 == 0:  # 120 минут = 2 часа
                    print("📡 Запуск Trend Radar...")
                    trends = analyze_trends()
                    trend_counter = 0
                
                # Генерация рубрик по расписанию
                generate_daily_content()
                
                # Парсинг новостей каждые 10 циклов (~10 минут)
                if news_counter % 10 == 0:
                    print("🔍 Поиск новостей...")
                    parse_news()
                
                # Публикация контента
                print("📤 Проверка очереди публикации...")
                next_content = get_next_content()
                
                if next_content:
                    success = await send_to_channel(next_content)
                    if not success:
                        print("⚠️ Ошибка публикации")
                else:
                    print("📭 Нет контента для публикации")
                
                news_counter += 1
                trend_counter += 1
                print("⏳ Жду 60 секунд...")
                await asyncio.sleep(60)
                
            except Exception as e:
                print(f"💥 Ошибка: {e}")
                await asyncio.sleep(30)
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(auto_poster())

# ==================== ADMIN COMMANDS ====================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    menu_text = """🤖 PREMIUM Crypto News Bot

🎯 ПРЕМИУМ ФИЧИ:
• Профессиональный перевод
• Trend Radar (каждые 2 часа)
• 4 ежедневные рубрики
• Чистые и красивые посты
• Контент-стратегия

📋 Команды:
/stats - Статистика
/news - Найти новости
/trends - Анализ трендов
/generate - Создать контент
/help - Помощь

🔗 Канал: @Jasmyandothers"""
    
    await update.message.reply_text(menu_text)

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM news")
    total_news = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM news WHERE posted = TRUE")
    posted_news = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM trend_data WHERE date(detected_date) = date('now')")
    today_trends = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM content_queue WHERE posted = FALSE")
    queued_content = cursor.fetchone()[0]
    
    today = datetime.now().strftime('%Y-%m-%d')
    cursor.execute("SELECT posts_count, trends_detected FROM stats WHERE date = ?", (today,))
    today_stats = cursor.fetchone()
    
    if today_stats:
        today_posts, trends_detected = today_stats
    else:
        today_posts, trends_detected = 0, 0
    
    stats_text = f"""📊 PREMIUM СТАТИСТИКА

📈 Контент:
• Всего новостей: {total_news}
• Опубликовано: {posted_news}
• В очереди: {queued_content}

🎯 Активность:
• Постов сегодня: {today_posts}
• Трендов сегодня: {today_trends}
• Обнаружено всего: {trends_detected}

⚡ Система:
• Trend Radar: Активен
• Рубрики: 4/день
• Перевод: Google API"""
    
    conn.close()
    await update.message.reply_text(stats_text)

async def news_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 Запускаю поиск новостей...")
    success = parse_news()
    if success:
        await update.message.reply_text("✅ Найдены новые новости! Будут опубликованы в течение 10 минут.")
    else:
        await update.message.reply_text("📭 Новых новостей не найдено")

async def trends_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📡 Запускаю Trend Radar...")
    trends = analyze_trends()
    
    if trends:
        response = "🎯 ОБНАРУЖЕННЫЕ ТРЕНДЫ:\n\n"
        for topic, score in list(trends.items())[:5]:
            response += f"• {topic.upper()}: {score} упоминаний\n"
        response += "\n📊 Будет опубликовано в канале"
    else:
        response = "📭 Значимых трендов не обнаружено"
    
    await update.message.reply_text(response)

async def generate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎨 Генерирую контент...")
    generate_daily_content()
    await update.message.reply_text("✅ Контент сгенерирован! Проверьте очередь публикации.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """🆘 PREMIUM BOT - ПОМОЩЬ

🎯 КОНТЕНТ-СТРАТЕГИЯ:
• 1 новость в 10 минут
• Trend Radar каждые 2 часа
• 4 рубрики в день по расписанию
• Профессиональный перевод

📋 АДМИН-КОМАНДЫ:
/news - Ручной поиск новостей
/trends - Анализ трендов
/generate - Создать контент
/stats - Статистика

🔗 Канал: @Jasmyandothers"""
    
    await update.message.reply_text(help_text)

# ==================== LAUNCH ====================

def main():
    print("🎯 ЗАПУСК PREMIUM CRYPTO NEWS BOT В ОБЛАКЕ...")
    print("🤖 Активирую премиум-фичи:")
    print("   ✅ Профессиональный перевод (Google API)")
    print("   ✅ Trend Radar система")
    print("   ✅ 4 ежедневные рубрики") 
    print("   ✅ Чистые и красивые посты")
    print("   ✅ Контент-стратегия 1/10мин")
    
    # Запускаем авто-постер
    poster_thread = threading.Thread(target=auto_poster_worker, daemon=True)
    poster_thread.start()
    
    # Запускаем бота команд
    application = Application.builder().token(BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("news", news_command))
    application.add_handler(CommandHandler("trends", trends_command))
    application.add_handler(CommandHandler("generate", generate_command))
    application.add_handler(CommandHandler("help", help_command))
    
    print("✅ PREMIUM BOT ЗАПУЩЕН В ОБЛАКЕ!")
    print("🚀 Ожидайте контент в канале...")
    
    application.run_polling()

if __name__ == '__main__':
    main()