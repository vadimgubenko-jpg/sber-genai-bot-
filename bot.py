"""
SberGenAI A2A Telegram Bot
6 агентов: Orchestrator, Assessor, Tutor, Analyst, Challenger, Reporter
"""
import asyncio
import logging
import json
import os
import uuid
import requests
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === CONFIG ===
BOT_TOKEN = "8580325068:AAHa_KR3A906dr3KXExEc5VRWFDZ649oc_A"
GIGACHAT_KEY = "MDE5ZGVhZTktNTdhOC03NTBhLWE4ZDctYjgwMmY1OGExZTA1OjYyOTkxMzNhLWEzMDUtNDUxZC1hZjg0LTJiZmM3YTQ2ZTExOQ=="

# === USER PROFILES (in-memory) ===
user_profiles = {}
user_sessions = {}

def get_profile(user_id: int, name: str = "Менеджер") -> dict:
    if user_id not in user_profiles:
        user_profiles[user_id] = {
            "name": name,
            "ratings": {
                "llm": 1.0, "prompt": 1.0, "rag": 1.0,
                "banking_ai": 1.0, "ethics": 1.0, "pm": 1.0
            },
            "sessions": 0,
            "last_topic": None,
            "debate_mode": None,
            "history": []
        }
    return user_profiles[user_id]

# === GIGACHAT API ===
_gc_token = None
_gc_token_expires = 0

def get_gigachat_token() -> str:
    global _gc_token, _gc_token_expires
    now = datetime.now().timestamp()
    if _gc_token and now < _gc_token_expires:
        return _gc_token
    try:
        resp = requests.post(
            "https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
            headers={
                "Authorization": f"Basic {GIGACHAT_KEY}",
                "RqUID": str(uuid.uuid4()),
                "Content-Type": "application/x-www-form-urlencoded"
            },
            data="scope=GIGACHAT_API_PERS",
            verify=False,
            timeout=10
        )
        data = resp.json()
        _gc_token = data.get("access_token")
        _gc_token_expires = now + data.get("expires_at", 1800) / 1000 - 60
        return _gc_token
    except Exception as e:
        logger.error(f"GigaChat token error: {e}")
        return None

def gigachat_chat(messages: list, system: str = None) -> str:
    token = get_gigachat_token()
    if not token:
        return "⚠️ Ошибка подключения к GigaChat. Попробуйте позже."
    msgs = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.extend(messages)
    try:
        resp = requests.post(
            "https://gigachat.devices.sberbank.ru/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"model": "GigaChat", "messages": msgs, "max_tokens": 1000, "temperature": 0.7},
            verify=False,
            timeout=30
        )
        return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"GigaChat error: {e}")
        return "⚠️ Временная ошибка. Попробуйте ещё раз."

# === AGENTS ===

def agent_orchestrator_route(text: str, profile: dict) -> str:
    """Определяет какой агент нужен"""
    text_lower = text.lower()
    if any(w in text_lower for w in ["тест", "проверь", "оцени", "экзамен", "quiz", "вопрос"]):
        return "assessor"
    elif any(w in text_lower for w in ["дебат", "оппон", "защит", "директор", "регулят", "challenger"]):
        return "challenger"
    elif any(w in text_lower for w in ["новост", "тренд", "дайджест", "что нового", "рынок", "analyst"]):
        return "analyst"
    elif any(w in text_lower for w in ["прогресс", "рейтинг", "статистик", "отчёт", "report"]):
        return "reporter"
    else:
        return "tutor"

def agent_assessor(topic: str, profile: dict) -> str:
    avg = sum(profile["ratings"].values()) / len(profile["ratings"])
    level = "начальный" if avg < 2 else "средний" if avg < 3.5 else "продвинутый"
    system = f"""Ты Assessor — агент-экзаменатор корпоративной системы обучения GenAI Сбербанка.
Уровень пользователя: {level} (средний рейтинг {avg:.1f}/5).
Задай ОДИН конкретный вопрос по теме с 4 вариантами ответа (А, Б, В, Г).
Вопрос должен быть практическим, с примерами из банковской сферы.
Формат: сначала вопрос, потом варианты. Без лишних слов."""
    return gigachat_chat(
        [{"role": "user", "content": f"Тема для вопроса: {topic}"}],
        system=system
    )

def agent_tutor(topic: str, profile: dict) -> str:
    avg = sum(profile["ratings"].values()) / len(profile["ratings"])
    system = f"""Ты Tutor — персональный ИИ-тьютор для менеджеров среднего звена Сбербанка.
Уровень пользователя: {avg:.1f}/5. Имя: {profile['name']}.
Объясняй тему доступно, используй аналогии из банковской сферы и реальные примеры из Сбера.
Структура ответа: 1) Простое определение 2) Аналогия из Сбера 3) Практический пример 4) Совет что изучить дальше.
Ответ до 300 слов. Используй эмодзи умеренно."""
    return gigachat_chat(
        [{"role": "user", "content": topic}],
        system=system
    )

def agent_analyst(query: str, profile: dict) -> str:
    system = """Ты Analyst — агент мониторинга трендов GenAI для Сбербанка.
Предоставляй актуальную информацию о трендах генеративного ИИ с фокусом на банковскую сферу.
Формат: 3-5 ключевых тренда/новости, каждый с кратким объяснением почему это важно для Сбера.
Добавь практическую рекомендацию в конце."""
    return gigachat_chat(
        [{"role": "user", "content": query}],
        system=system
    )

def agent_challenger(topic: str, role: str, profile: dict, history: list) -> str:
    roles = {
        "risk": "Директор по рискам Сбербанка — скептик, требует доказательств и ROI",
        "cbr": "Представитель ЦБ РФ — фокус на регуляторике 152-ФЗ, 353-ФЗ, объяснимости моделей",
        "cto": "CTO по информационной безопасности — беспокоится о prompt injection, утечках данных, vendor lock-in",
        "cfo": "CFO — требует CAPEX/OPEX расчёты, payback period, сравнение с альтернативами",
    }
    role_desc = roles.get(role, roles["risk"])
    system = f"""Ты Challenger — агент для тренировки защиты AI-решений. Играешь роль: {role_desc}.
Задавай ЖЁСТКИЕ, конкретные вопросы. Указывай на слабые места в аргументации.
Если пользователь допустил фактическую ошибку — укажи на неё.
Отвечай коротко и остро, как настоящий скептичный руководитель на совещании."""
    msgs = history[-6:] if history else []
    msgs.append({"role": "user", "content": topic})
    return gigachat_chat(msgs, system=system)

def agent_reporter(profile: dict) -> str:
    ratings = profile["ratings"]
    names = {
        "llm": "LLM Fundamentals", "prompt": "Prompt Engineering",
        "rag": "RAG & Retrieval", "banking_ai": "AI в банкинге",
        "ethics": "AI Ethics", "pm": "AI Project Mgmt"
    }
    lines = "\n".join([f"• {names[k]}: {v:.1f}/5" for k, v in ratings.items()])
    avg = sum(ratings.values()) / len(ratings)
    level = "Новичок" if avg < 1.5 else "Базовый" if avg < 2.5 else "Уверенный" if avg < 3.5 else "Продвинутый" if avg < 4.5 else "Эксперт"
    weak = min(ratings, key=ratings.get)
    strong = max(ratings, key=ratings.get)
    report = f"""📈 *Ваш прогресс*

👤 {profile['name']} · Сессий: {profile['sessions']}
⭐ Средний рейтинг: *{avg:.1f}/5* — {level}

*Детали по доменам:*
{lines}

✅ *Сильная сторона:* {names[strong]} ({ratings[strong]:.1f})
⚠️ *Зона роста:* {names[weak]} ({ratings[weak]:.1f})

🎯 *Цель к Q3:* 3.5/5 — прогресс {int(avg/3.5*100)}%

💡 Рекомендую: /learn {names[weak].lower()}"""
    return report

# === KEYBOARDS ===

def main_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.button(text="📊 Тест знаний")
    builder.button(text="📚 Учиться")
    builder.button(text="⚡ Дебаты")
    builder.button(text="📰 Дайджест")
    builder.button(text="📈 Мой прогресс")
    builder.button(text="❓ Помощь")
    builder.adjust(2, 2, 2)
    return builder.as_markup(resize_keyboard=True)

def debate_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="😤 Директор по рискам", callback_data="debate_risk")
    builder.button(text="🏛️ Регулятор ЦБ РФ", callback_data="debate_cbr")
    builder.button(text="🔒 CTO по безопасности", callback_data="debate_cto")
    builder.button(text="💰 CFO", callback_data="debate_cfo")
    builder.button(text="❌ Выйти из дебатов", callback_data="debate_exit")
    builder.adjust(2, 2, 1)
    return builder.as_markup()

def topics_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🤖 LLM основы", callback_data="learn_llm")
    builder.button(text="✍️ Prompt Engineering", callback_data="learn_prompt")
    builder.button(text="🔍 RAG", callback_data="learn_rag")
    builder.button(text="🏦 AI в банкинге", callback_data="learn_banking")
    builder.button(text="⚖️ AI Ethics", callback_data="learn_ethics")
    builder.button(text="📋 AI Project Mgmt", callback_data="learn_pm")
    builder.adjust(2, 2, 2)
    return builder.as_markup()

def test_keyboard():
    builder = InlineKeyboardBuilder()
    for t in ["LLM", "Prompt Engineering", "RAG", "AI в банкинге", "AI Ethics"]:
        builder.button(text=t, callback_data=f"test_{t.lower().replace(' ', '_')}")
    builder.adjust(2)
    return builder.as_markup()

# === BOT INIT ===
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
dp = Dispatcher()

# === HANDLERS ===

@dp.message(CommandStart())
async def cmd_start(message: Message):
    profile = get_profile(message.from_user.id, message.from_user.first_name)
    await message.answer(
        f"👋 Привет, *{message.from_user.first_name}*\\!\n\n"
        "Я — *SberGenAI Tutor*, ваш персональный ИИ\\-тренер по генеративному ИИ от Сбербанка\\.\n\n"
        "За мной работают *6 специализированных агентов*:\n"
        "🧠 Orchestrator · 📊 Assessor · 📚 Tutor\n"
        "🔍 Analyst · ⚡ Challenger · 📈 Reporter\n\n"
        f"📊 Ваш текущий рейтинг: *1\\.0/5* — Новичок\n"
        "🎯 Цель к Q3: *3\\.5/5*\n\n"
        "Что начнём?",
        reply_markup=main_keyboard(),
        parse_mode="MarkdownV2"
    )

@dp.message(Command("help"))
@dp.message(F.text == "❓ Помощь")
async def cmd_help(message: Message):
    await message.answer(
        "📖 *Доступные команды:*\n\n"
        "/test — Пройти тест по выбранной теме\n"
        "/learn \\[тема\\] — Изучить тему\n"
        "/debate — Тренировка дебатов\n"
        "/news — Дайджест трендов GenAI\n"
        "/progress — Мой прогресс и рейтинг\n"
        "/plan — План обучения на неделю\n\n"
        "💬 Или просто напишите свой вопрос — я разберусь сам\\!",
        parse_mode="MarkdownV2",
        reply_markup=main_keyboard()
    )

@dp.message(Command("progress"))
@dp.message(F.text == "📈 Мой прогресс")
async def cmd_progress(message: Message):
    profile = get_profile(message.from_user.id, message.from_user.first_name)
    report = agent_reporter(profile)
    await message.answer(report, reply_markup=main_keyboard())

@dp.message(Command("test"))
@dp.message(F.text == "📊 Тест знаний")
async def cmd_test(message: Message):
    await message.answer(
        "📊 *Выберите тему для теста:*",
        reply_markup=test_keyboard()
    )

@dp.message(Command("news"))
@dp.message(F.text == "📰 Дайджест")
async def cmd_news(message: Message):
    profile = get_profile(message.from_user.id, message.from_user.first_name)
    await message.answer("🔍 Analyst собирает свежие тренды GenAI\\.\\.\\.", parse_mode="MarkdownV2")
    result = agent_analyst("Топ-5 актуальных трендов GenAI в банковской сфере на эту неделю", profile)
    await message.answer(f"📰 *Дайджест от Analyst:*\n\n{result}", reply_markup=main_keyboard())

@dp.message(Command("debate"))
@dp.message(F.text == "⚡ Дебаты")
async def cmd_debate(message: Message):
    await message.answer(
        "⚡ *Режим дебатов*\n\nВыберите роль оппонента\\. Challenger будет жёстко оспаривать ваши аргументы по внедрению GenAI в Сбере\\.",
        reply_markup=debate_keyboard(),
        parse_mode="MarkdownV2"
    )

@dp.message(F.text == "📚 Учиться")
async def cmd_learn_menu(message: Message):
    await message.answer(
        "📚 *Выберите тему для изучения:*",
        reply_markup=topics_keyboard()
    )

@dp.message(Command("learn"))
async def cmd_learn(message: Message):
    profile = get_profile(message.from_user.id, message.from_user.first_name)
    topic = message.text.replace("/learn", "").strip()
    if not topic:
        await message.answer("📚 *Выберите тему:*", reply_markup=topics_keyboard())
        return
    profile["sessions"] += 1
    await message.answer(f"📚 Tutor готовит объяснение по теме: *{topic}*\\.\\.\\.", parse_mode="MarkdownV2")
    result = agent_tutor(topic, profile)
    await message.answer(result, reply_markup=main_keyboard())

# === CALLBACKS ===

@dp.callback_query(F.data.startswith("test_"))
async def cb_test(callback: CallbackQuery):
    profile = get_profile(callback.from_user.id, callback.from_user.first_name)
    topic = callback.data.replace("test_", "").replace("_", " ")
    await callback.message.edit_text(f"📊 *Assessor генерирует вопрос по теме: {topic}*\\.\\.\\.\\.", parse_mode="MarkdownV2")
    question = agent_assessor(topic, profile)
    profile["last_topic"] = topic
    profile["sessions"] += 1
    builder = InlineKeyboardBuilder()
    builder.button(text="А", callback_data="ans_A")
    builder.button(text="Б", callback_data="ans_B")
    builder.button(text="В", callback_data="ans_V")
    builder.button(text="Г", callback_data="ans_G")
    builder.adjust(4)
    await callback.message.answer(question, reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data.startswith("ans_"))
async def cb_answer(callback: CallbackQuery):
    profile = get_profile(callback.from_user.id, callback.from_user.first_name)
    answer = callback.data.replace("ans_", "")
    topic = profile.get("last_topic", "GenAI")
    system = f"""Ты Assessor. Пользователь ответил "{answer}" на вопрос по теме {topic}.
Дай краткий разбор: правильный ли ответ (можешь сам определить наиболее вероятный правильный),
объясни почему, дай совет. Обнови мотивацию. 2-3 предложения. Используй эмодзи."""
    feedback = gigachat_chat([{"role": "user", "content": f"Мой ответ: {answer}"}], system=system)
    # Немного повышаем рейтинг за участие
    domain = "llm"
    if "prompt" in topic.lower(): domain = "prompt"
    elif "rag" in topic.lower(): domain = "rag"
    elif "банк" in topic.lower(): domain = "banking_ai"
    elif "ethics" in topic.lower() or "этик" in topic.lower(): domain = "ethics"
    profile["ratings"][domain] = min(5.0, profile["ratings"][domain] + 0.1)
    await callback.message.edit_text(f"Ответ: *{answer}*\n\n{feedback}", reply_markup=None)
    await callback.message.answer("Продолжим?", reply_markup=main_keyboard())
    await callback.answer()

@dp.callback_query(F.data.startswith("learn_"))
async def cb_learn(callback: CallbackQuery):
    profile = get_profile(callback.from_user.id, callback.from_user.first_name)
    topics = {
        "learn_llm": "Большие языковые модели (LLM): как работают, трансформеры, токены, температура",
        "learn_prompt": "Prompt Engineering: техники составления промптов, chain-of-thought, few-shot",
        "learn_rag": "RAG (Retrieval-Augmented Generation): архитектура, векторный поиск, применение в Сбере",
        "learn_banking": "Применение GenAI в банковской сфере: скоринг, AML, клиентский сервис",
        "learn_ethics": "Этика и риски ИИ: bias, hallucination, регуляторика, 152-ФЗ",
        "learn_pm": "Управление AI-проектами: MLOps, data contracts, model cards, roadmap"
    }
    topic = topics.get(callback.data, callback.data)
    await callback.message.edit_text(f"📚 Tutor готовит материал\\.\\.\\.", parse_mode="MarkdownV2")
    profile["sessions"] += 1
    result = agent_tutor(topic, profile)
    # Повышаем рейтинг
    domain_map = {"llm": "llm", "prompt": "prompt", "rag": "rag", "banking": "banking_ai", "ethics": "ethics", "pm": "pm"}
    for k, v in domain_map.items():
        if k in callback.data:
            profile["ratings"][v] = min(5.0, profile["ratings"][v] + 0.15)
    builder = InlineKeyboardBuilder()
    builder.button(text="📝 Мини-тест по теме", callback_data=f"test_{callback.data.replace('learn_', '')}")
    builder.button(text="🏠 Главное меню", callback_data="main_menu")
    builder.adjust(2)
    await callback.message.answer(result, reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data.startswith("debate_"))
async def cb_debate(callback: CallbackQuery):
    profile = get_profile(callback.from_user.id, callback.from_user.first_name)
    if callback.data == "debate_exit":
        profile["debate_mode"] = None
        user_sessions[callback.from_user.id] = None
        await callback.message.edit_text("✅ Вышли из режима дебатов\\.", parse_mode="MarkdownV2")
        await callback.message.answer("Чем займёмся дальше?", reply_markup=main_keyboard())
        await callback.answer()
        return
    role = callback.data.replace("debate_", "")
    roles_names = {"risk": "Директора по рискам", "cbr": "Регулятора ЦБ РФ", "cto": "CTO по безопасности", "cfo": "CFO"}
    role_name = roles_names.get(role, "Директора")
    profile["debate_mode"] = role
    user_sessions[callback.from_user.id] = {"mode": "debate", "role": role, "history": []}
    opening = agent_challenger(
        "Начни дебаты — представься в своей роли и задай первый жёсткий вопрос по внедрению GenAI в банке",
        role, profile, []
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Завершить дебаты", callback_data="debate_exit")
    await callback.message.edit_text(
        f"⚡ *Дебаты начались\\!* Вы против {role_name}\\.\n\nПросто отвечайте на вопросы оппонента\\.",
        parse_mode="MarkdownV2"
    )
    await callback.message.answer(f"_{opening}_", parse_mode="Markdown", reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "main_menu")
async def cb_main_menu(callback: CallbackQuery):
    await callback.message.answer("Главное меню:", reply_markup=main_keyboard())
    await callback.answer()

# === FREE TEXT HANDLER ===

@dp.message(F.text)
async def handle_message(message: Message):
    profile = get_profile(message.from_user.id, message.from_user.first_name)
    session = user_sessions.get(message.from_user.id)

    # Режим дебатов
    if session and session.get("mode") == "debate":
        role = session["role"]
        history = session.get("history", [])
        history.append({"role": "user", "content": message.text})
        await message.answer("⚡ Challenger думает\\.\\.\\.", parse_mode="MarkdownV2")
        response = agent_challenger(message.text, role, profile, history)
        history.append({"role": "assistant", "content": response})
        session["history"] = history[-10:]
        builder = InlineKeyboardBuilder()
        builder.button(text="❌ Завершить дебаты", callback_data="debate_exit")
        await message.answer(f"_{response}_", parse_mode="Markdown", reply_markup=builder.as_markup())
        return

    # Умный роутинг
    agent = agent_orchestrator_route(message.text, profile)
    profile["sessions"] += 1
    profile["last_topic"] = message.text[:50]

    if agent == "assessor":
        await message.answer("📊 Assessor готовит вопрос\\.\\.\\.", parse_mode="MarkdownV2")
        response = agent_assessor(message.text, profile)
    elif agent == "analyst":
        await message.answer("🔍 Analyst ищет актуальную информацию\\.\\.\\.", parse_mode="MarkdownV2")
        response = agent_analyst(message.text, profile)
    elif agent == "reporter":
        response = agent_reporter(profile)
    elif agent == "challenger":
        user_sessions[message.from_user.id] = {"mode": "debate", "role": "risk", "history": []}
        profile["debate_mode"] = "risk"
        await message.answer("⚡ Включаю режим дебатов\\.\\.\\.", parse_mode="MarkdownV2")
        response = agent_challenger(message.text, "risk", profile, [])
    else:
        await message.answer("📚 Tutor готовит ответ\\.\\.\\.", parse_mode="MarkdownV2")
        response = agent_tutor(message.text, profile)

    await message.answer(response, reply_markup=main_keyboard())

async def main():
    logger.info("🚀 SberGenAI Bot starting...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
