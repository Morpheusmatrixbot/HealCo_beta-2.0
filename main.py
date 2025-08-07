import logging
import os
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import openai
import base64
import json
import re
from replit import db
import datetime

# --- Конфигурация ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not TELEGRAM_BOT_TOKEN or not OPENAI_API_KEY:
    raise ValueError("Ключи TELEGRAM_BOT_TOKEN или OPENAI_API_KEY не найдены в Secrets!")

client = openai.OpenAI(api_key=OPENAI_API_KEY)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# --- Ролевые модели ---
ROLES = {
    "фитнесс-тренер": "Ты — элитный фитнес-тренер. Твоя задача — давать профессиональные рекомендации по тренировкам, восстановлению и спортивной физиологии. Твои ответы точны, научны и мотивируют как на персональной тренировке.",
    "личный наставник": "Ты — личный наставник и коуч по продуктивности. Твоя задача — помогать в организации дня, формировании полезных привычек и достижении жизненных целей. Твои ответы вдохновляющие, структурированные и поддерживающие.",
    "нутрициолог": "Ты — профессиональный нутрициолог с глубокими знаниями в диетологии и биохимии. Твоя задача — составлять рационы, объяснять принципы здорового питания и роль микро/макронутриентов. Твои ответы компетентны и основаны на науке.",
    "медицинский наставник": "Ты внимательный медицинский наставник. Твоя задача — давать легкие рекомендации по улучшению здоровья, диагностике общих симптомов, но всегда с оговоркой, что это не заменяет консультацию реального врача. Говори аккуратно, используя фразы вроде 'Рекомендуется проконсультироваться с врачом'.",
    "психотерапевт": "Ты — эмпатичный и мудрый психотерапевт. Твоя задача — оказывать поддержку, помогать пользователю разбираться в своих чувствах и настроении. Ты используешь техники активного слушания, задаешь мягкие наводящие вопросы и никогда не осуждаешь. Твоя речь спокойная и вселяющая уверенность.",
    "ты из будущего": "Ты — это сам пользователь, но из успешного будущего. Ты уже достиг всех целей, о которых пользователь мечтает. Твоя задача — давать мудрые, загадочные и невероятно мотивирующие советы, намекая на будущие успехи. Говори уверенно, используя фразы 'Я помню, как ты с этим справился...', 'Не сомневайся, этот шаг приведет тебя к...'.",
}

# --- Клавиатуры ---
START_KEYBOARD = ReplyKeyboardMarkup([
    ["Заполнить профиль", "Выбрать роль"],
    ["Дневник питания", "Мои баллы"],
], resize_keyboard=True)

COMPLETED_PROFILE_KEYBOARD = ReplyKeyboardMarkup([
    ["Составить меню 🍽️", "План тренировок 💪"],
    ["Дневник здоровья ❤️‍🩹", "Психическое здоровье 🧠"],
    ["Дневник питания 🥕", "Дневник тренировок 🏋️"],
    ["Выбрать роль 🎭", "Мои баллы 🏆"]
], resize_keyboard=True)

HEALTH_KEYBOARD_BASE = [
    ["Записать симптом 🤧", "Посмотреть дневник 📖"],
    ["Вернуться в главное меню ↩️"]
]

MOOD_KEYBOARD = ReplyKeyboardMarkup([
    ["Отличное 👍", "Хорошее 🙂"],
    ["Нормальное 😐"],
    ["Плохое 😕", "Очень плохое 😔"],
    ["Посмотреть дневник настроения 📊", "Вернуться в главное меню ↩️"]
], resize_keyboard=True)

ROLE_BUTTON_LABELS = [role.capitalize() for role in ROLES.keys()]
ROLE_BUTTONS = [[label] for label in ROLE_BUTTON_LABELS]
ROLE_KEYBOARD = ReplyKeyboardMarkup(ROLE_BUTTONS, one_time_keyboard=True, resize_keyboard=True)

PROFILE_QUESTIONS = [
    "profile_state_gender", "profile_state_age", "profile_state_height",
    "profile_state_weight", "profile_state_activity", "profile_state_goal",
    "profile_state_diseases", "profile_state_allergies"
]
GENDER_KEYBOARD = [["Мужской", "Женский"]]
ACTIVITY_KEYBOARD = [["Сидячий", "Умеренный", "Активный"]]
GOAL_KEYBOARD = [["Похудеть", "Набрать массу", "Поддерживать вес"]]
WORKOUT_PLACE_KEYBOARD = [["Дома", "В зале", "На улице"]]

# --- Функции для работы с базой данных ---
def get_user_data_from_db(user_id):
    key = str(user_id)
    if key in db:
        data = json.loads(db[key])
        data.setdefault("workout_diary", [])
        data.setdefault("health_diary", [])
        data.setdefault("mood_diary", [])
        return data
    else:
        default_data = {
            "current_role": "личный наставник", "profile_data": {}, "score": 0,
            "food_diary": [], "workout_diary": [], "health_diary": [], "mood_diary": [],
            "first_name": "", "last_name": ""
        }
        db[key] = json.dumps(default_data)
        return default_data

def save_user_data_to_db(user_id, data):
    key = str(user_id)
    db[key] = json.dumps(data)

# --- Вспомогательные функции ---
def encode_image(image_bytes):
    return base64.b64encode(image_bytes).decode('utf-8')

def get_personal_prompt(user_profile_data: dict, first_name: str = None) -> str:
    if not user_profile_data or not user_profile_data.get('goal'):
        return ""
    parts = []
    if first_name: parts.append(f"Имя пользователя: {first_name}")
    if 'gender' in user_profile_data: parts.append(f"пол: {user_profile_data['gender'].lower()}")
    if 'age' in user_profile_data: parts.append(f"возраст: {user_profile_data['age']} лет")
    if 'height' in user_profile_data: parts.append(f"рост: {user_profile_data['height']} см")
    if 'weight' in user_profile_data: parts.append(f"вес: {user_profile_data['weight']} кг")
    if 'activity' in user_profile_data: parts.append(f"образ жизни: {user_profile_data['activity'].lower()}")
    if 'goal' in user_profile_data: parts.append(f"цель: {user_profile_data['goal'].lower()}")
    if 'diseases' in user_profile_data and user_profile_data['diseases'].lower() not in ['нет', 'no']:
        parts.append(f"хронические заболевания: {user_profile_data['diseases']}")
    if 'allergies' in user_profile_data and user_profile_data['allergies'].lower() not in ['нет', 'no']:
        parts.append(f"аллергии: {user_profile_data['allergies']}")
    return f"Учитывай в ответе, что пользователь сообщил о себе: {', '.join(parts)}. " if parts else ""

# --- Основные функции бота ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    data = get_user_data_from_db(user.id)
    data["first_name"] = user.first_name
    save_user_data_to_db(user.id, data)
    keyboard = COMPLETED_PROFILE_KEYBOARD if data.get("profile_data", {}).get('goal') else START_KEYBOARD
    await update.message.reply_html(
        f"Привет, {user.mention_html()}! 👋\n\n"
        "Я — твой персональный AI-консьерж по здоровью. Моя миссия — помочь тебе лучше понимать свое тело и разум, питаться осознанно, тренироваться эффективно и достигать гармонии в жизни.\n\n"
        "Чем займемся сегодня? 👇\n\n"
        "<i>I heal you! ♥️</i>",
        reply_markup=keyboard
    )

async def set_role(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Какую роль ты хочешь, чтобы я сейчас принял?", reply_markup=ROLE_KEYBOARD)

async def handle_role_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    requested_role_display = update.message.text
    requested_role = requested_role_display.lower().replace('-', ' ')
    data = get_user_data_from_db(user_id)
    keyboard = COMPLETED_PROFILE_KEYBOARD if data.get("profile_data", {}).get('goal') else START_KEYBOARD

    if requested_role in ROLES:
        data["current_role"] = requested_role
        save_user_data_to_db(user_id, data)
        try:
            prompt = f"Твоя новая роль: {ROLES[requested_role]}. Напиши ОЧЕНЬ короткое (1-2 предложения) приветственное сообщение пользователю от лица этой роли, подтверждая, что ты готов к работе. Будь креативным и полностью вживись в роль."
            response = client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": prompt}], max_tokens=100, temperature=0.8)
            greeting = response.choices[0].message.content
        except Exception as e:
            logger.error(f"Ошибка генерации приветствия роли: {e}")
            greeting = f"Отлично! Теперь я буду общаться с тобой как **{requested_role_display}**."
        await update.message.reply_text(greeting, reply_markup=keyboard, parse_mode='Markdown')
    else:
        await update.message.reply_text("Извини, я не понял такую роль.", reply_markup=keyboard)

async def show_roles(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = get_user_data_from_db(update.effective_user.id)
    keyboard = COMPLETED_PROFILE_KEYBOARD if data.get("profile_data", {}).get('goal') else START_KEYBOARD
    await update.message.reply_text("Доступные ролевые модели:\n" + "\n".join([f"- **{role.capitalize()}**: {desc.split('.')[0]}" for role, desc in ROLES.items()]) + "\n\nИспользуй /role для выбора.", reply_markup=keyboard, parse_mode='Markdown')

async def reminders_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = get_user_data_from_db(update.effective_user.id)
    keyboard = COMPLETED_PROFILE_KEYBOARD if data.get("profile_data", {}).get('goal') else START_KEYBOARD
    await update.message.reply_text(
        "⏰ **О напоминаниях** ⏰\n\n"
        "На данный момент я не умею устанавливать напоминания на конкретное время (например, 'напомни поесть в 14:00'). Это очень сложная техническая функция.\n\n"
        "**Но есть кое-что получше для мотивации!** 👇\n"
        "После каждой тренировки используй команду /workout_done. Ты не только получишь 🏆 **15 баллов**, но и сможешь отследить свою регулярность. Это лучший способ оставаться в тонусе!\n\n"
        "I heal you! ♥️",
        reply_markup=keyboard
    )

# --- Раздел Психического здоровья ---
async def mental_health_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Забота о ментальном здоровье так же важна, как и о физическом. Как ты себя чувствуешь сегодня?", reply_markup=MOOD_KEYBOARD)

async def log_mood(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    mood_text_full = update.message.text
    mood_text = mood_text_full.split(" ")[0]
    mood_map = {"Отличное": 5, "Хорошее": 4, "Нормальное": 3, "Плохое": 2, "Очень": 1}
    mood_level = mood_map.get(mood_text, 3)

    user_id = update.effective_user.id
    data = get_user_data_from_db(user_id)
    entry = {"date": datetime.date.today().strftime('%d.%m.%Y'), "mood_level": mood_level, "mood_text": mood_text_full}
    data["mood_diary"].append(entry)
    save_user_data_to_db(user_id, data)

    await update.message.reply_text(f"Спасибо, что поделился. Я записал твое настроение: **{mood_text_full}**. ✨", reply_markup=MOOD_KEYBOARD, parse_mode='Markdown')

    try:
        if mood_level <= 2:
            prompt = f"Пользователь отметил, что у него '{mood_text}' настроение. Напиши короткий (1-2 предложения), но очень эмпатичный и поддерживающий комментарий. Мягко признай, что такие дни бывают и это нормально. Не давай прямых советов, просто окажи поддержку. Твоя роль: {ROLES['психотерапевт']}"
        else:
            prompt = f"Пользователь отметил, что у него '{mood_text}' настроение. Напиши короткий (1-2 предложения) поддерживающий и ободряющий комментарий. Твоя роль: {ROLES['психотерапевт']}"
        response = client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": prompt}], max_tokens=150, temperature=0.9)
        await update.message.reply_text(f"👩‍⚕️💬 *{response.choices[0].message.content}*", parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Ошибка ответа на настроение: {e}")

async def show_mood_diary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = get_user_data_from_db(update.effective_user.id)
    diary_entries = data.get("mood_diary", [])
    if not diary_entries:
        await update.message.reply_text("Дневник настроения пока пуст. Не забывай отмечать свое состояние.", reply_markup=MOOD_KEYBOARD)
        return
    response_text = "Твой дневник настроения (последние 15 записей):\n\n"
    ICONS = {5: "👍", 4: "🙂", 3: "😐", 2: "😕", 1: "😔"}
    for entry in diary_entries[-15:]:
        icon = ICONS.get(entry.get("mood_level"), "▪️")
        response_text += f"{icon} **{entry.get('date')}**: {entry.get('mood_text')}\n"
    await update.message.reply_text(response_text, reply_markup=MOOD_KEYBOARD, parse_mode='Markdown')

# --- Раздел Дневника Здоровья ---
async def health_diary_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    profile_diseases = get_user_data_from_db(update.effective_user.id).get("profile_data", {}).get("diseases", "").lower()
    keyboard_layout = [row[:] for row in HEALTH_KEYBOARD_BASE]
    if "гипертония" in profile_diseases or "давление" in profile_diseases:
        keyboard_layout.insert(1, ["Записать давление 🩺"])
    if "диабет" in profile_diseases or "сахар" in profile_diseases:
        keyboard_layout.insert(1, ["Записать сахар в крови 🩸"])
    await update.message.reply_text("Это ваш личный Дневник здоровья. Он поможет отслеживать самочувствие и важные показатели. Что вы хотите сделать?",
        reply_markup=ReplyKeyboardMarkup(keyboard_layout, resize_keyboard=True, one_time_keyboard=True))

async def start_symptom_logging(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data['context_state'] = 'awaiting_symptom'
    await update.message.reply_text("Пожалуйста, опишите симптомы, которые вас беспокоят. Постарайтесь быть как можно точнее.", reply_markup=ReplyKeyboardRemove())

async def show_health_diary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = get_user_data_from_db(update.effective_user.id)
    keyboard = COMPLETED_PROFILE_KEYBOARD if data.get("profile_data", {}).get('goal') else START_KEYBOARD
    diary_entries = data.get("health_diary", [])
    if not diary_entries:
        await update.message.reply_text("Ваш Дневник здоровья пока пуст. ❤️‍🩹", reply_markup=keyboard)
        return
    response_text = "Ваш Дневник здоровья (последние 15 записей):\n\n"
    ICONS = {"symptom": "🤧", "pressure": "🩺", "sugar": "🩸"}
    for entry in diary_entries[-15:]:
        icon = ICONS.get(entry.get("type"), "▪️")
        response_text += f"{icon} **{entry.get('date')}**: {entry.get('text')}\n"
    await update.message.reply_text(response_text, reply_markup=keyboard, parse_mode='Markdown')

async def start_pressure_logging(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data['context_state'] = 'awaiting_pressure'
    await update.message.reply_text("Введите ваше давление в формате '120/80'.", reply_markup=ReplyKeyboardRemove())

async def start_sugar_logging(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data['context_state'] = 'awaiting_sugar'
    await update.message.reply_text("Введите ваш уровень сахара в крови (например, '6.5' или '6.5 ммоль/л').", reply_markup=ReplyKeyboardRemove())

# --- Профиль и его обработка ---
async def start_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    data = get_user_data_from_db(user_id)
    data["profile_state"] = "awaiting_profile" # Используем общее состояние
    context.user_data['profile_questions_index'] = 0
    context.user_data['profile_data'] = {}
    
    data["score"] += 10
    save_user_data_to_db(user_id, data)

    await update.message.reply_text(f"Отлично! Начнем заполнение твоего профиля. За это ты получаешь 10 баллов! Твой текущий счет: {data['score']}.\n"
                                    "Это поможет мне давать более точные рекомендации.\n"
                                    "Напиши `Отмена`, если захочешь прервать опрос в любой момент.",
                                    reply_markup=ReplyKeyboardRemove())
    await ask_next_profile_question(update, context)

async def ask_next_profile_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    question_index = context.user_data.get('profile_questions_index', 0)
    
    if question_index >= len(PROFILE_QUESTIONS):
        await finalize_profile(update, context)
        return

    current_question_key = PROFILE_QUESTIONS[question_index]
    question_text = ""
    reply_markup = ReplyKeyboardRemove()

    if current_question_key == "profile_state_gender":
        question_text = "Укажи свой пол:"
        reply_markup = ReplyKeyboardMarkup(GENDER_KEYBOARD, one_time_keyboard=True, resize_keyboard=True)
    elif current_question_key == "profile_state_age": question_text = "Сколько тебе полных лет?"
    elif current_question_key == "profile_state_height": question_text = "Какой у тебя рост в сантиметрах? (Например: 175)"
    elif current_question_key == "profile_state_weight": question_text = "Какой у тебя текущий вес в килограммах? (Например: 70.5)"
    elif current_question_key == "profile_state_activity":
        question_text = "Какой у тебя уровень физической активности?"
        reply_markup = ReplyKeyboardMarkup(ACTIVITY_KEYBOARD, one_time_keyboard=True, resize_keyboard=True)
    elif current_question_key == "profile_state_goal":
        question_text = "Какова твоя основная цель?"
        reply_markup = ReplyKeyboardMarkup(GOAL_KEYBOARD, one_time_keyboard=True, resize_keyboard=True)
    elif current_question_key == "profile_state_diseases": question_text = "Есть ли у тебя хронические заболевания? Если нет, напиши `Нет`."
    elif current_question_key == "profile_state_allergies": question_text = "Есть ли у тебя пищевые аллергии или непереносимости? Если нет, напиши `Нет`."
    
    await update.message.reply_text(question_text, reply_markup=reply_markup)

async def handle_profile_response(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    message_text = update.message.text
    
    if message_text and message_text.lower() == "отмена":
        await cancel_profile(update, context)
        return

    question_index = context.user_data.get('profile_questions_index', 0)
    current_question_key = PROFILE_QUESTIONS[question_index]
    profile_data = context.user_data.get('profile_data', {})
    
    valid = True
    error_message = ""
    
    try:
        if current_question_key == "profile_state_gender":
            if message_text.lower() in ["мужской", "женский"]: profile_data["gender"] = message_text
            else: valid = False; error_message = "Пожалуйста, выбери 'Мужской' или 'Женский'."
        elif current_question_key == "profile_state_age":
            age = int(message_text)
            if 0 < age < 120: profile_data["age"] = age
            else: valid = False; error_message = "Пожалуйста, введи корректный возраст."
        elif current_question_key == "profile_state_height":
            height = int(message_text)
            if 50 < height < 250: profile_data["height"] = height
            else: valid = False; error_message = "Пожалуйста, введи корректный рост."
        elif current_question_key == "profile_state_weight":
            weight = float(message_text.replace(',', '.'))
            if 20 < weight < 300: profile_data["weight"] = weight
            else: valid = False; error_message = "Пожалуйста, введи корректный вес."
        elif current_question_key == "profile_state_activity":
            if message_text.lower() in ["сидячий", "умеренный", "активный"]: profile_data["activity"] = message_text
            else: valid = False; error_message = "Пожалуйста, выбери из предложенных вариантов."
        elif current_question_key == "profile_state_goal":
            if message_text.lower() in ["похудеть", "набрать массу", "поддерживать вес"]: profile_data["goal"] = message_text
            else: valid = False; error_message = "Пожалуйста, выбери из предложенных вариантов."
        elif current_question_key == "profile_state_diseases": profile_data["diseases"] = message_text
        elif current_question_key == "profile_state_allergies": profile_data["allergies"] = message_text
    except (ValueError, TypeError):
        valid = False
        error_message = "Кажется, формат данных неверный. Попробуй еще раз."

    if not valid:
        await update.message.reply_text(error_message)
        return

    context.user_data['profile_data'] = profile_data
    context.user_data['profile_questions_index'] += 1
    
    await ask_next_profile_question(update, context)

async def finalize_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    data = get_user_data_from_db(user_id)
    
    data["profile_data"] = context.user_data.get('profile_data', {})
    data["score"] += 20
    save_user_data_to_db(user_id, data)
    
    context.user_data.pop('profile_questions_index', None)
    context.user_data.pop('profile_data', None)
    data = get_user_data_from_db(user_id) # перечитываем данные, чтобы убедиться
    data.pop('profile_state', None) # Удаляем состояние
    save_user_data_to_db(user_id, data)

    await update.message.reply_text(f"Спасибо! Твой профиль заполнен, за это ты получаешь 20 баллов! Твой текущий счет: {data['score']}.", reply_markup=COMPLETED_PROFILE_KEYBOARD)

async def cancel_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    context.user_data.pop('profile_questions_index', None)
    context.user_data.pop('profile_data', None)
    data = get_user_data_from_db(user_id)
    data.pop('profile_state', None)
    save_user_data_to_db(user_id, data)
    await update.message.reply_text("Заполнение профиля отменено.", reply_markup=START_KEYBOARD)

async def create_personalized_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # ... Полный код из предыдущих версий
    pass
    
async def create_workout_plan_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # ... Полный код из предыдущих версий
    pass

async def create_workout_plan_final(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # ... Полный код из предыдущих версий
    pass
    
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # ... Полный код из предыдущих версий
    pass

async def show_food_diary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # ... Полный код из предыдущих версий
    pass

async def show_score(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # ... Полный код из предыдущих версий
    pass

async def workout_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # ... Полный код из предыдущих версий
    pass

async def show_workout_diary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # ... Полный код из предыдущих версий
    pass

# --- Обработчики состояний ---
async def handle_symptom_input(update, context):
    context.user_data.pop('context_state')
    await update.message.reply_text("Анализирую ваши симптомы... 🧠", reply_markup=ReplyKeyboardRemove())
    prompt = f"Выступи в роли 'Медицинского советника'. Проанализируй следующие симптомы от пользователя: '{update.message.text}'. Дай краткий, общий совет о возможных причинах в дружелюбной форме. ВАЖНЕЙШИЙ ПРИОРИТЕТ: Оцени потенциальную серьезность. Если есть хоть малейший намек на что-то опасное (например, боль в груди, затрудненное дыхание, онемение, очень высокая температура, нестерпимая боль), твой ГЛАВНЫЙ ответ должен быть — немедленно и настоятельно порекомендовать обратиться к врачу или вызвать скорую помощь. В ЛЮБОМ СЛУЧАЕ, закончи свой ответ четким и ясным напоминанием: 'Помните, я — AI-ассистент, и моя консультация не заменяет визит к настоящему врачу.'"
    try:
        response = client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": prompt}], max_tokens=400)
        ai_response = response.choices[0].message.content
    except Exception as e:
        logger.error(f"Ошибка анализа симптомов: {e}")
        ai_response = "К сожалению, не удалось проанализировать симптомы из-за технической ошибки."
    data = get_user_data_from_db(update.effective_user.id)
    entry = {"date": datetime.date.today().strftime('%d.%m.%Y'), "type": "symptom", "text": update.message.text}
    data.setdefault("health_diary", []).append(entry)
    save_user_data_to_db(update.effective_user.id, data)
    await update.message.reply_text(ai_response, reply_markup=COMPLETED_PROFILE_KEYBOARD)

async def handle_pressure_input(update, context):
    context.user_data.pop('context_state')
    data = get_user_data_from_db(update.effective_user.id)
    entry = {"date": datetime.date.today().strftime('%d.%m.%Y'), "type": "pressure", "text": f"Давление: {update.message.text}"}
    data.setdefault("health_diary", []).append(entry)
    save_user_data_to_db(update.effective_user.id, data)
    await update.message.reply_text("✅ Запись о давлении добавлена в ваш дневник.", reply_markup=COMPLETED_PROFILE_KEYBOARD)

async def handle_sugar_input(update, context):
    context.user_data.pop('context_state')
    data = get_user_data_from_db(update.effective_user.id)
    entry = {"date": datetime.date.today().strftime('%d.%m.%Y'), "type": "sugar", "text": f"Сахар в крови: {update.message.text}"}
    data.setdefault("health_diary", []).append(entry)
    save_user_data_to_db(update.effective_user.id, data)
    await update.message.reply_text("✅ Запись об уровне сахара добавлена в ваш дневник.", reply_markup=COMPLETED_PROFILE_KEYBOARD)

# --- Главный обработчик сообщений ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    message_text = update.message.text

    # --- Сначала проверяем состояния ---
    context_state = context.user_data.get('context_state')
    if context_state == 'awaiting_symptom':
        await handle_symptom_input(update, context)
        return
    if context_state == 'awaiting_pressure':
        await handle_pressure_input(update, context)
        return
    if context_state == 'awaiting_sugar':
        await handle_sugar_input(update, context)
        return
    
    data = get_user_data_from_db(user_id)
    if data.get('profile_state') == 'awaiting_profile':
         await handle_profile_response(update, context)
         return

    # --- Затем обрабатываем кнопки ---
    button_map = {
        "составить меню": create_personalized_menu, "план тренировок": create_workout_plan_location,
        "дневник здоровья": health_diary_menu, "психическое здоровье": mental_health_menu,
        "дневник питания": show_food_diary, "дневник тренировок": show_workout_diary,
        "выбрать роль": set_role, "мои баллы": show_score,
        "вернуться в главное меню": start, "записать симптом": start_symptom_logging,
        "посмотреть дневник": show_health_diary, "записать давление": start_pressure_logging,
        "записать сахар": start_sugar_logging, "посмотреть дневник настроения": show_mood_diary,
        "заполнить профиль": start_profile
    }
    for key, func in button_map.items():
        if key in message_text.lower():
            await func(update, context)
            return

    # --- Ответ AI на общие вопросы ---
    if not data.get("profile_data", {}).get('goal'):
        await update.message.reply_text("Чтобы я мог быть максимально полезным, пожалуйста, заполни свой профиль.", reply_markup=START_KEYBOARD)
        return

    current_role_name = data.get("current_role", "личный наставник")
    role_prompt = ROLES.get(current_role_name, ROLES["личный наставник"])
    personal_info = get_personal_prompt(data.get("profile_data", {}), data.get("first_name"))
    full_prompt = f"Твоя текущая роль: {role_prompt}. {personal_info} Ответь на запрос пользователя, соблюдая свою роль. Запрос: {message_text}"
    
    await update.message.reply_chat_action(action='typing')
    try:
        response = client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": full_prompt}], max_tokens=500, temperature=0.7)
        await update.message.reply_text(response.choices[0].message.content, reply_markup=COMPLETED_PROFILE_KEYBOARD)
    except Exception as e:
        logger.error(f"Ошибка вызова OpenAI для общего ответа: {e}")
        await update.message.reply_text("Извини, не могу сейчас ответить. Произошла ошибка.", reply_markup=COMPLETED_PROFILE_KEYBOARD)

def main() -> None:
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("role", set_role))
    application.add_handler(CommandHandler("roles", show_roles))
    application.add_handler(CommandHandler("profile", start_profile))
    application.add_handler(CommandHandler("score", show_score))
    application.add_handler(CommandHandler("reminders", reminders_info))
    application.add_handler(CommandHandler("myworkouts", show_workout_diary))
    application.add_handler(CommandHandler("health", health_diary_menu))
    application.add_handler(CommandHandler("mental_health", mental_health_menu))

    application.add_handler(MessageHandler(filters.Regex(r'^(Отличное 👍|Хорошее 🙂|Нормальное 😐|Плохое 😕|Очень плохое 😔)$'), log_mood))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Бот запущен и работает...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
