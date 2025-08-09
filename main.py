import logging
import os
import asyncio
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InputFile
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
import openai
import base64
import json
import re
from replit import db
import datetime
from io import BytesIO

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
    "нутрициолог": "Ты — профессиональный нутрициолог с глубокими знаниями в диетологии и биохимии. Твоя задача — составлять рационы, анализировать продукты и отвечать на вопросы о питании. Твои ответы компетентны и основаны на науке.",
    "фитнес-тренер": "Ты — элитный фитнес-тренер. Твоя задача — давать профессиональные рекомендации по тренировкам, восстановлению и спортивной физиологии. Твои ответы точны, научны и мотивируют как на персональной тренировке.",
    "психотерапевт": "Ты — эмпатичный и мудрый психотерапевт. Твоя задача — оказывать поддержку, помогать пользователю разбираться в своих чувствах и настроении. Ты используешь техники активного слушания и никогда не осуждаешь. Твоя речь спокойная и вселяющая уверенность.",
    "медицинский наставник": "Ты внимательный медицинский наставник. Твоя задача — давать легкие рекомендации по улучшению здоровья и анализировать общие симптомы, но всегда с оговоркой, что это не заменяет консультацию реального врача.",
    "личный наставник": "Ты — личный наставник и коуч по продуктивности. Твоя задача — помогать в организации дня, формировании полезных привычек и достижении жизненных целей. Твои ответы вдохновляющие, структурированные и поддерживающие.",
    "ты из будущего": "Ты — это сам пользователь, но из успешного будущего. Ты уже достиг всех целей, о которых пользователь мечтает. Твоя задача — давать мудрые, загадочные и невероятно мотивирующие советы, а также показывать, как пользователь будет выглядеть в будущем, достигнув своих спортивных целей. Для генерации изображений используй DALL-E 3.",
}

# --- Клавиатуры ---
START_KEYBOARD = ReplyKeyboardMarkup([["Заполнить профиль"]], resize_keyboard=True)
MAIN_MENU_KEYBOARD = ReplyKeyboardMarkup([["Выбрать специалиста 🎭"], ["Мои дневники 📔", "Мои баллы 🏆"]], resize_keyboard=True)
ROLE_BUTTON_LABELS = [role.capitalize() for role in ROLES.keys()]
ROLE_BUTTONS = [[label] for label in ROLE_BUTTON_LABELS]
ROLE_KEYBOARD = ReplyKeyboardMarkup(ROLE_BUTTONS, one_time_keyboard=True, resize_keyboard=True)

NUTRITIONIST_KEYBOARD = ReplyKeyboardMarkup([["Рассчитать КБЖУ 📊", "Составить меню на день 🍽️"], ["Задать вопрос нутрициологу ❓"], ["⬅️ Назад к выбору специалиста"]], resize_keyboard=True)
FITNESS_TRAINER_KEYBOARD = ReplyKeyboardMarkup([["Составить план тренировок 💪"], ["Рассчитать ИМТ 📉", "Что такое VO2max ❓"], ["Обновить данные профиля 🔄", "Вопрос по тренажеру 🏋️"], ["Задать вопрос тренеру ❓"], ["⬅️ Назад к выбору специалиста"]], resize_keyboard=True)
PSYCHOTHERAPIST_KEYBOARD = ReplyKeyboardMarkup([["Дневник настроения 🧠"], ["Техника дыхания для успокоения 🌬️"], ["Задать вопрос психотерапевту ❓"], ["⬅️ Назад к выбору специалиста"]], resize_keyboard=True)
FUTURE_SELF_KEYBOARD = ReplyKeyboardMarkup([["Создать мое спортивное будущее 🔮"], ["⬅️ Назад к выбору специалиста"]], resize_keyboard=True)
GENERAL_SPECIALIST_KEYBOARD = ReplyKeyboardMarkup([["Задать вопрос специалисту ❓"], ["⬅️ Назад к выбору специалиста"]], resize_keyboard=True)

DIARIES_KEYBOARD = ReplyKeyboardMarkup([["Дневник питания 🥕", "Дневник тренировок 🏋️"], ["Дневник здоровья ❤️‍🩹", "Дневник настроения 📊"], ["⬅️ Назад в главное меню"]], resize_keyboard=True)
MOOD_SCALE_KEYBOARD = ReplyKeyboardMarkup([["Отличное 👍", "Хорошее 🙂"], ["Нормальное 😐"], ["Плохое 😕", "Очень плохое 😔"]], one_time_keyboard=True, resize_keyboard=True)
MOOD_TIME_KEYBOARD = ReplyKeyboardMarkup([["Утро ☀️", "День 🏙️", "Вечер 🌙"]], one_time_keyboard=True, resize_keyboard=True)
MOOD_DIARY_MENU_KEYBOARD = ReplyKeyboardMarkup([["Записать настроение ✨"], ["Посмотреть дневник 📊", "⬅️ Назад к психотерапевту"]], resize_keyboard=True)
WORKOUT_TYPE_KEYBOARD = ReplyKeyboardMarkup([["Бег 🏃", "Силовая 💪"], ["ВИИТ 🔥", "Домашняя 🏠"]], one_time_keyboard=True, resize_keyboard=True)

GENDER_KEYBOARD = ReplyKeyboardMarkup([["Мужской", "Женский"]], one_time_keyboard=True, resize_keyboard=True)
ACTIVITY_KEYBOARD = ReplyKeyboardMarkup([["Сидячий", "Умеренный", "Активный"]], one_time_keyboard=True, resize_keyboard=True)
GOAL_KEYBOARD = ReplyKeyboardMarkup([["Похудеть", "Набрать массу", "Поддерживать вес"]], one_time_keyboard=True, resize_keyboard=True)
WORKOUT_PLACE_KEYBOARD = [["Дома", "В зале", "На улице"]]

# --- Состояния для ConversationHandler ---
GENDER, AGE, HEIGHT, WEIGHT, ACTIVITY, GOAL, DISEASES, ALLERGIES = range(8)
LOCATION, EQUIPMENT = range(2)
MOOD_SELECT, TIME_SELECT = range(2)


# --- Функции для работы с базой данных ---
def get_user_data_from_db(user_id):
    key = str(user_id)
    if key in db:
        try:
            data = json.loads(db[key])
        except json.JSONDecodeError:
            data = {}
    else:
        data = {}

    data.setdefault("profile_data", {}).setdefault("last_updated", None)
    data.setdefault("workout_diary", [])
    data.setdefault("health_diary", [])
    data.setdefault("mood_diary", [])
    data.setdefault("food_diary", [])
    data.setdefault("score", 0)
    data.setdefault("first_name", "")
    return data

def save_user_data_to_db(user_id, data):
    key = str(user_id)
    db[key] = json.dumps(data)

def get_all_users_data():
    all_data = {}
    user_ids = db.keys()
    for user_id in user_ids:
        try:
            if user_id.isdigit():
                all_data[user_id] = json.loads(db[user_id])
        except (json.JSONDecodeError, TypeError):
            continue
    return all_data

# --- Вспомогательные функции ---
def encode_image(image_bytes):
    return base64.b64encode(image_bytes).decode('utf-8')

def get_personal_prompt(user_profile_data: dict, first_name: str = None) -> str:
    if not user_profile_data or not user_profile_data.get('goal'):
        return "У пользователя не заполнен профиль. Попроси его заполнить профиль для получения персонализированных рекомендаций. "
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

async def check_profile_update(update: Update, context: ContextTypes.DEFAULT_TYPES):
    user_id = update.effective_user.id
    data = get_user_data_from_db(user_id)
    last_updated_str = data.get("profile_data", {}).get("last_updated")
    if last_updated_str:
        last_updated_date = datetime.datetime.strptime(last_updated_str, '%Y-%m-%d').date()
        if (datetime.date.today() - last_updated_date).days > 30:
            await update.message.reply_text(
                "🗓️ Я заметил, что ты давно не обновлял данные своего профиля. "
                "Твой вес или уровень активности могли измениться. "
                "Чтобы мои рекомендации оставались точными, советую обновить профиль. "
                "Это можно сделать в меню Фитнес-тренера.",
                reply_markup=MAIN_MENU_KEYBOARD
            )
            return False
    return True

# --- Основные команды и навигация ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPES) -> None:
    user = update.effective_user
    data = get_user_data_from_db(user.id)
    data["first_name"] = user.first_name
    save_user_data_to_db(user.id, data)
    keyboard = MAIN_MENU_KEYBOARD if data.get("profile_data", {}).get('goal') else START_KEYBOARD
    await update.message.reply_text(
        f"Привет, {user.mention_html()}! 👋\n\n"
        "Я — твой персональный AI-консьерж по здоровью, <b>HealCo Bot</b>.\n"
        "Моя миссия — помочь тебе лучше понимать свое тело и разум, питаться осознанно, "
        "тренироваться эффективно и достигать гармонии в жизни.\n\n"
        "Чем займемся сегодня? 👇\n\n"
        "<i>I heal you! ♥️</i>",
        reply_markup=keyboard,
        parse_mode='HTML'
    )

async def choose_specialist(update: Update, context: ContextTypes.DEFAULT_TYPES) -> None:
    await update.message.reply_text("Выберите специалиста, с которым хотите пообщаться:", reply_markup=ROLE_KEYBOARD)

async def show_diaries_menu(update: Update, context: ContextTypes.DEFAULT_TYPES) -> None:
    await update.message.reply_text("Какой дневник вы хотите посмотреть или обновить?", reply_markup=DIARIES_KEYBOARD)

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPES) -> None:
    await update.message.reply_text("🏆 Собираю данные для таблицы лидеров...")
    all_users_data = get_all_users_data()
    valid_users = [
        (data.get('first_name', 'Аноним'), data.get('score', 0))
        for uid, data in all_users_data.items()
        if data.get('score', 0) > 0 and data.get('first_name')
    ]
    sorted_users = sorted(valid_users, key=lambda x: x[1], reverse=True)
    
    if not sorted_users:
        await update.message.reply_text("Пока никто не набрал баллов. Будь первым!")
        return
        
    response_text = "🏆 <b>Топ-10 пользователей:</b>\n\n"
    for i, (name, score) in enumerate(sorted_users[:10], 1):
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        response_text += f"{medals.get(i, f'<b>{i}.</b>')} {name} - {score} баллов\n"
        
    await update.message.reply_text(response_text, parse_mode='HTML')

# --- Логика Ролей-Специалистов ---
async def handle_role_selection(update: Update, context: ContextTypes.DEFAULT_TYPES) -> None:
    user_id = update.effective_user.id
    requested_role_display = update.message.text
    requested_role = next((key for key, val in ROLES.items() if key.capitalize() == requested_role_display), None)

    if not requested_role:
        await update.message.reply_text("Извините, я не понял такую роль.", reply_markup=MAIN_MENU_KEYBOARD)
        return

    data = get_user_data_from_db(user_id)
    data["current_role"] = requested_role
    save_user_data_to_db(user_id, data)

    if requested_role == "нутрициолог": role_keyboard = NUTRITIONIST_KEYBOARD
    elif requested_role == "фитнес-тренер": role_keyboard = FITNESS_TRAINER_KEYBOARD
    elif requested_role == "психотерапевт": role_keyboard = PSYCHOTHERAPIST_KEYBOARD
    elif requested_role == "ты из будущего": role_keyboard = FUTURE_SELF_KEYBOARD
    else: role_keyboard = GENERAL_SPECIALIST_KEYBOARD
    
    await update.message.reply_text("Минутку, соединяю со специалистом...", reply_markup=ReplyKeyboardRemove())

    try:
        prompt = (
            f"Твоя новая роль: {ROLES[requested_role]}. "
            "Напиши короткое приветствие от своего лица (2-3 предложения). "
            "Представься и расскажи, чем конкретно ты можешь помочь. "
            "Используй эмодзи. ВАЖНО: Не используй markdown (звездочки, решетки)."
        )
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200, temperature=0.8
        )
        greeting = response.choices[0].message.content
    except Exception as e:
        logger.error(f"Ошибка генерации приветствия роли: {e}")
        greeting = f"Здравствуйте! Я ваш {requested_role_display}. Чем могу помочь?"

    await update.message.reply_text(greeting, reply_markup=role_keyboard)

# --- Профиль Пользователя ---
async def start_profile_dialog(update: Update, context: ContextTypes.DEFAULT_TYPES) -> int:
    context.user_data['profile_data'] = {}
    await update.message.reply_text(
        "Отлично! Начнем. Пожалуйста, ответь на несколько вопросов.\n"
        "Напиши /cancel, если захочешь прервать.",
        reply_markup=ReplyKeyboardRemove()
    )
    await update.message.reply_text("Укажи свой пол:", reply_markup=GENDER_KEYBOARD)
    return GENDER

async def process_gender(update: Update, context: ContextTypes.DEFAULT_TYPES) -> int:
    text = update.message.text
    if text.lower() not in ["мужской", "женский"]:
        await update.message.reply_text("Пожалуйста, выбери один из вариантов на клавиатуре.", reply_markup=GENDER_KEYBOARD)
        return GENDER
    context.user_data['profile_data']['gender'] = text
    await update.message.reply_text("Сколько тебе полных лет?", reply_markup=ReplyKeyboardRemove())
    return AGE

async def process_age(update: Update, context: ContextTypes.DEFAULT_TYPES) -> int:
    try:
        age = int(update.message.text)
        if not (0 < age < 120): raise ValueError
        context.user_data['profile_data']['age'] = age
        await update.message.reply_text("Какой у тебя рост в сантиметрах? (Например: 175)")
        return HEIGHT
    except (ValueError, TypeError):
        await update.message.reply_text("Пожалуйста, введи корректный возраст (целое число от 1 до 119).")
        return AGE

async def process_height(update: Update, context: ContextTypes.DEFAULT_TYPES) -> int:
    try:
        height = int(update.message.text)
        if not (50 < height < 250): raise ValueError
        context.user_data['profile_data']['height'] = height
        await update.message.reply_text("Какой у тебя текущий вес в килограммах? (Например: 70.5)")
        return WEIGHT
    except (ValueError, TypeError):
        await update.message.reply_text("Пожалуйста, введи корректный рост в см (число от 51 до 249).")
        return HEIGHT

async def process_weight(update: Update, context: ContextTypes.DEFAULT_TYPES) -> int:
    try:
        weight = float(update.message.text.replace(',', '.'))
        if not (20 < weight < 300): raise ValueError
        context.user_data['profile_data']['weight'] = weight
        await update.message.reply_text("Какой у тебя уровень физической активности?", reply_markup=ACTIVITY_KEYBOARD)
        return ACTIVITY
    except (ValueError, TypeError):
        await update.message.reply_text("Пожалуйста, введи корректный вес в кг (число от 21 до 299).")
        return WEIGHT

async def process_activity(update: Update, context: ContextTypes.DEFAULT_TYPES) -> int:
    text = update.message.text
    if text.lower() not in ["сидячий", "умеренный", "активный"]:
        await update.message.reply_text("Пожалуйста, выбери один из вариантов на клавиатуре.", reply_markup=ACTIVITY_KEYBOARD)
        return ACTIVITY
    context.user_data['profile_data']['activity'] = text
    await update.message.reply_text("Какова твоя основная цель?", reply_markup=GOAL_KEYBOARD)
    return GOAL

async def process_goal(update: Update, context: ContextTypes.DEFAULT_TYPES) -> int:
    text = update.message.text
    if text.lower() not in ["похудеть", "набрать массу", "поддерживать вес"]:
        await update.message.reply_text("Пожалуйста, выбери один из вариантов на клавиатуре.", reply_markup=GOAL_KEYBOARD)
        return GOAL
    context.user_data['profile_data']['goal'] = text
    await update.message.reply_text("Есть ли у тебя хронические заболевания? Если нет, напиши 'Нет'.", reply_markup=ReplyKeyboardRemove())
    return DISEASES

async def process_diseases(update: Update, context: ContextTypes.DEFAULT_TYPES) -> int:
    context.user_data['profile_data']['diseases'] = update.message.text
    await update.message.reply_text("Есть ли у тебя пищевые аллергии или непереносимости? Если нет, напиши 'Нет'.")
    return ALLERGIES

async def process_allergies(update: Update, context: ContextTypes.DEFAULT_TYPES) -> int:
    context.user_data['profile_data']['allergies'] = update.message.text
    await finalize_profile(update, context)
    return ConversationHandler.END

async def finalize_profile(update: Update, context: ContextTypes.DEFAULT_TYPES):
    user_id = update.effective_user.id
    data = get_user_data_from_db(user_id)
    is_new_profile = not data.get("profile_data", {}).get('goal')
    
    data["profile_data"] = context.user_data['profile_data']
    data["profile_data"]["last_updated"] = datetime.date.today().strftime('%Y-%m-%d')
    
    if is_new_profile:
        data["score"] = data.get("score", 0) + 30
        await update.message.reply_text(
            f"Спасибо! Твой профиль заполнен. За это ты получаешь 30 баллов! Твой текущий счет: {data['score']}.\n"
            "Теперь тебе доступны все функции.",
            reply_markup=MAIN_MENU_KEYBOARD
        )
    else:
        await update.message.reply_text(
            "Отлично, данные твоего профиля обновлены!",
            reply_markup=FITNESS_TRAINER_KEYBOARD
        )
        
    save_user_data_to_db(user_id, data)
    context.user_data.clear()

async def cancel_dialog(update: Update, context: ContextTypes.DEFAULT_TYPES) -> int:
    context.user_data.clear()
    await update.message.reply_text("Действие отменено.", reply_markup=MAIN_MENU_KEYBOARD)
    return ConversationHandler.END


# --- Функционал Нутрициолога ---
async def calculate_kbzhu(update: Update, context: ContextTypes.DEFAULT_TYPES):
    user_id = update.effective_user.id
    data = get_user_data_from_db(user_id)
    profile = data.get("profile_data")

    if not profile or not all(k in profile for k in ['gender', 'age', 'height', 'weight', 'activity', 'goal']):
        await update.message.reply_text("Для расчета КБЖУ мне нужны данные твоего профиля. Пожалуйста, заполни его.", reply_markup=START_KEYBOARD)
        return

    try:
        weight = float(profile['weight'])
        height = float(profile['height'])
        age = int(profile['age'])
        
        if profile['gender'].lower() == 'мужской':
            brm = (10 * weight) + (6.25 * height) - (5 * age) + 5
        else:
            brm = (10 * weight) + (6.25 * height) - (5 * age) - 161
            
        activity_coeffs = {"сидячий": 1.2, "умеренный": 1.55, "активный": 1.8}
        amr = brm * activity_coeffs[profile['activity'].lower()]
        
        goal_coeffs = {"похудеть": 0.85, "набрать массу": 1.15, "поддерживать вес": 1.0}
        final_calories = amr * goal_coeffs[profile['goal'].lower()]
        
        proteins = (final_calories * 0.3) / 4
        fats = (final_calories * 0.3) / 9
        carbs = (final_calories * 0.4) / 4
        
        response_text = (
            "📊 Твоя рекомендованная норма на день:\n\n"
            f"🔥 Калории: {final_calories:.0f} ккал\n"
            f"🥩 Белки: {proteins:.0f} г\n"
            f"🥑 Жиры: {fats:.0f} г\n"
            f"🍞 Углеводы: {carbs:.0f} г\n\n"
            "Помни, это ориентировочные значения. Прислушивайся к своему организму!"
        )
        await update.message.reply_text(response_text, reply_markup=NUTRITIONIST_KEYBOARD)

    except Exception as e:
        logger.error(f"Ошибка расчета КБЖУ: {e}")
        await update.message.reply_text("Произошла ошибка при расчете. Проверь данные в своем профиле.", reply_markup=NUTRITIONIST_KEYBOARD)

async def nutritionist_consultation_info(update: Update, context: ContextTypes.DEFAULT_TYPES):
    await update.message.reply_text(
        "Я — AI-ассистент и могу дать общие рекомендации.\n\n"
        "Для получения детальной и персональной консультации я настоятельно рекомендую обратиться к "
        "сертифицированному врачу-диетологу или нутрициологу.\n\n"
        "Вы можете найти специалистов на таких платформах, как Профи.ру, DocDoc или в "
        "специализированных клиниках вашего города.",
        reply_markup=NUTRITIONIST_KEYBOARD
    )

# --- Функционал Фитнес-тренера ---
async def ask_workout_location(update: Update, context: ContextTypes.DEFAULT_TYPES) -> int:
    await update.message.reply_text("Где ты предпочитаешь тренироваться?", reply_markup=ReplyKeyboardMarkup(WORKOUT_PLACE_KEYBOARD, one_time_keyboard=True, resize_keyboard=True))
    return LOCATION

async def ask_equipment(update: Update, context: ContextTypes.DEFAULT_TYPES) -> int:
    context.user_data['workout_location'] = update.message.text
    await update.message.reply_text("У тебя есть какой-нибудь инвентарь (например, гантели, резинки, турник)? Если да, перечисли его. Если нет, напиши 'Нет'.", reply_markup=ReplyKeyboardRemove())
    return EQUIPMENT

async def generate_workout_plan(update: Update, context: ContextTypes.DEFAULT_TYPES) -> int:
    equipment = update.message.text
    location = context.user_data['workout_location']
    
    await update.message.reply_text("💪 Отлично! Разрабатываю для тебя эффективный план тренировок... Это займет секунду.", reply_markup=ReplyKeyboardRemove())
    
    user_id = update.effective_user.id
    data = get_user_data_from_db(user_id)
    role_prompt = ROLES["фитнес-тренер"]
    workout_prompt = (
        f"Твоя роль: {role_prompt}. "
        f"Создай подробный план тренировок на неделю (3 дня), используя данные пользователя.\n"
        f"Место тренировки: '{location}'.\n"
        f"Доступный инвентарь: '{equipment}'.\n"
        f"{get_personal_prompt(data.get('profile_data', {}), data.get('first_name'))}\n"
        "Для каждого тренировочного дня:\n"
        "- 🗓️ Тип тренировки\n"
        "- 💪 Упражнения (подходы/повторения)\n"
        "- 🔥 Примерное количество сжигаемых калорий\n"
        "- ❤️ Целевые пульсовые зоны (в ударах в минуту)\n"
        "Используй эмодзи для списков и акцентов. План должен быть супер-мотивирующим. "
        "ВАЖНО: Не используй markdown (звездочки, решетки)."
    )
    
    try:
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": workout_prompt}],
            max_tokens=1500, temperature=0.7
        )
        await update.message.reply_text(response.choices[0].message.content, reply_markup=FITNESS_TRAINER_KEYBOARD)
    except Exception as e:
        logger.error(f"Ошибка генерации плана тренировок: {e}")
        await update.message.reply_text("Не смог составить план. Что-то пошло не так с AI.", reply_markup=FITNESS_TRAINER_KEYBOARD)
        
    context.user_data.clear()
    return ConversationHandler.END
    
async def calculate_bmi(update: Update, context: ContextTypes.DEFAULT_TYPES):
    user_id = update.effective_user.id
    data = get_user_data_from_db(user_id)
    profile = data.get("profile_data")

    if not profile or not all(k in profile for k in ['height', 'weight', 'age', 'gender']):
        await update.message.reply_text("Для расчета ИМТ мне нужен твой рост и вес из профиля. Пожалуйста, заполни его.", reply_markup=START_KEYBOARD)
        return
        
    await update.message.reply_text("📈 Считаю твой ИМТ и анализирую результат...", reply_markup=ReplyKeyboardRemove())

    try:
        height_m = float(profile['height']) / 100
        weight_kg = float(profile['weight'])
        bmi = weight_kg / (height_m ** 2)
        
        prompt = (
            "Ты — элитный фитнес-тренер. "
            f"Проанализируй результат ИМТ пользователя. Его ИМТ = {bmi:.2f}. "
            f"Данные пользователя: пол {profile['gender']}, возраст {profile['age']}. "
            "Сравни результат с общепринятыми нормами (дефицит, норма, избыточный вес, ожирение). "
            "Дай короткий, поддерживающий и понятный комментарий. "
            "Например, объясни, что ИМТ не учитывает мышечную массу. "
            "ВАЖНО: Не используй markdown (звездочки, решетки)."
        )
        
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=400, temperature=0.7
        )
        
        result_text = f"Твой Индекс Массы Тела (ИМТ): <b>{bmi:.2f}</b>\n\n{response.choices[0].message.content}"
        await update.message.reply_text(result_text, reply_markup=FITNESS_TRAINER_KEYBOARD, parse_mode='HTML')

    except Exception as e:
        logger.error(f"Ошибка анализа ИМТ: {e}")
        await update.message.reply_text("Произошла ошибка при анализе ИМТ.", reply_markup=FITNESS_TRAINER_KEYBOARD)

async def explain_vo2max(update: Update, context: ContextTypes.DEFAULT_TYPES):
    explanation = (
        "<b>VO2 max</b> — это максимальное количество кислорода (в миллилитрах), которое человек способен "
        "потреблять в минуту на килограмм веса тела во время интенсивной физической нагрузки.\n\n"
        "Простыми словами, это <b>ключевой показатель аэробной выносливости</b>. Чем выше твой VO2 max, тем "
        "эффективнее твой организм использует кислород для производства энергии, и тем дольше ты можешь "
        "выдерживать высокие нагрузки (например, в беге, плавании, велоспорте).\n\n"
        "Измерить его точно можно в лаборатории, но многие фитнес-часы дают хорошую оценку на основе "
        "данных о твоих тренировках и пульсе."
    )
    await update.message.reply_text(explanation, reply_markup=FITNESS_TRAINER_KEYBOARD, parse_mode='HTML')

async def trainer_consultation_info(update: Update, context: ContextTypes.DEFAULT_TYPES):
    await update.message.reply_text(
        "Я — AI-тренер и могу составить хороший базовый план.\n\n"
        "Для работы с травмами, подготовки к соревнованиям или если у тебя есть специфические цели, "
        "я настоятельно рекомендую найти сертифицированного тренера для очных или онлайн-занятий.\n\n"
        "Личный контроль и коррекция техники от профессионала — ключ к безопасному и быстрому прогрессу.",
        reply_markup=FITNESS_TRAINER_KEYBOARD
    )

# --- Функционал Психотерапевта ---
async def start_mood_logging(update: Update, context: ContextTypes.DEFAULT_TYPES) -> int:
    await update.message.reply_text("Как ты себя чувствуешь прямо сейчас?", reply_markup=MOOD_SCALE_KEYBOARD)
    return MOOD_SELECT

async def ask_mood_time(update: Update, context: ContextTypes.DEFAULT_TYPES) -> int:
    context.user_data['mood_text'] = update.message.text
    await update.message.reply_text("К какому времени дня относится это настроение?", reply_markup=MOOD_TIME_KEYBOARD)
    return TIME_SELECT

async def finalize_mood_log(update: Update, context: ContextTypes.DEFAULT_TYPES) -> int:
    mood_text_full = context.user_data['mood_text']
    mood_time = update.message.text
    mood_text = mood_text_full.split(" ")[0]
    mood_map = {"Отличное": 5, "Хорошее": 4, "Нормальное": 3, "Плохое": 2, "Очень": 1}
    mood_level = mood_map.get(mood_text, 3)

    user_id = update.effective_user.id
    data = get_user_data_from_db(user_id)
    entry = {
        "date": datetime.date.today().strftime('%d.%m.%Y'),
        "time_of_day": mood_time,
        "mood_level": mood_level,
        "mood_text": mood_text_full
    }
    data.setdefault("mood_diary", []).append(entry)
    data["score"] = data.get("score", 0) + 5
    save_user_data_to_db(user_id, data)

    await update.message.reply_text(
        f"Спасибо, что поделился. Я записал твое настроение. Ты получаешь 5 баллов! ✨\n"
        f"Твой счет: {data['score']}",
        reply_markup=MOOD_DIARY_MENU_KEYBOARD
    )
    
    try:
        if mood_level <= 2:
            prompt = (f"Твоя роль: {ROLES['психотерапевт']}. Пользователь отметил, что у него '{mood_text_full}' настроение. "
                      "Напиши короткий (1-2 предложения), но очень эмпатичный и поддерживающий комментарий. "
                      "Мягко признай, что такие дни бывают и это нормально. "
                      "Не давай прямых советов, просто окажи поддержку. "
                      "ВАЖНО: Не используй markdown (звездочки, решетки).")
        else:
            prompt = (f"Твоя роль: {ROLES['психотерапевт']}. Пользователь отметил, что у него '{mood_text_full}' настроение. "
                      "Напиши короткий (1-2 предложения) поддерживающий и ободряющий комментарий. "
                      "ВАЖНО: Не используй markdown (звездочки, решетки).")
        
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150, temperature=0.9
        )
        await update.message.reply_text(f"💬 {response.choices[0].message.content}")
    except Exception as e:
        logger.error(f"Ошибка ответа на настроение: {e}")

    context.user_data.clear()
    return ConversationHandler.END

# --- Функционал "Ты из будущего" ---
async def start_future_self_image_generation(update: Update, context: ContextTypes.DEFAULT_TYPES):
    await update.message.reply_text(
        "🔮 Я вижу твое будущее... оно яркое и сильное. "
        "Чтобы показать его тебе, мне нужна твоя недавняя фотография, где хорошо видно лицо. "
        "Пришли мне одно фото.",
        reply_markup=ReplyKeyboardRemove()
    )
    user_id = update.effective_user.id
    data = get_user_data_from_db(user_id)
    data['context_state'] = 'awaiting_future_self_photo'
    save_user_data_to_db(user_id, data)

async def handle_future_self_photo(update: Update, context: ContextTypes.DEFAULT_TYPES):
    user_id = update.effective_user.id
    data = get_user_data_from_db(user_id)
    
    if data.get('context_state') != 'awaiting_future_self_photo':
        await handle_message(update, context)
        return
        
    data.pop('context_state', None)
    save_user_data_to_db(user_id, data)

    await update.message.reply_text("✨ Анализирую твой образ и заглядываю в будущее... Это может занять до минуты.", reply_markup=FUTURE_SELF_KEYBOARD)

    try:
        file_obj = await context.bot.get_file(update.message.photo[-1].file_id)
        photo_bytes = await file_obj.download_as_bytes()
        base64_image = encode_image(photo_bytes)

        vision_prompt = "Опиши ключевые черты лица человека на этом фото (форма лица, цвет глаз, цвет волос, прическа, наличие бороды/усов, особые приметы) для использования в DALL-E 3. Описание должно быть лаконичным и точным."
        vision_response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "content": vision_prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                ]
            }],
            max_tokens=200
        )
        face_description = vision_response.choices[0].message.content

        await update.message.reply_text("🧬 Создаю твою новую версию...")

        user_goal = data.get("profile_data", {}).get("goal", "поддерживать вес")
        if "похудеть" in user_goal:
            body_type = "a lean, athletic physique with well-defined muscles"
        elif "набрать массу" in user_goal:
            body_type = "a powerful, muscular build, like a bodybuilder"
        else:
            body_type = "a fit and toned body, healthy and strong"
            
        dalle_prompt = (
            f"Photorealistic image of a person with the following facial features: {face_description}. "
            f"The person has {body_type}, looking confident and happy after a workout. "
            "They are in a modern, bright gym. Cinematic lighting, high detail."
        )

        image_response = await client.images.generate(
            model="dall-e-3",
            prompt=dalle_prompt,
            n=1, size="1024x1024", quality="standard", response_format="b64_json"
        )
        
        generated_image_b64 = image_response.data[0].b64_json
        generated_image_bytes = base64.b64decode(generated_image_b64)
        
        await context.bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=BytesIO(generated_image_bytes),
            caption="Вот таким я тебя вижу в будущем. Ты можешь этого достичь. 💪",
            reply_markup=FUTURE_SELF_KEYBOARD
        )

    except Exception as e:
        logger.error(f"Ошибка генерации образа будущего: {e}")
        await update.message.reply_text("🔮 Что-то пошло не так, и линия будущего оказалась размытой. Попробуй еще раз чуть позже.", reply_markup=FUTURE_SELF_KEYBOARD)


# --- Дневники и прочее ---
async def start_workout_logging(update: Update, context: ContextTypes.DEFAULT_TYPES):
    await update.message.reply_text("Отличная работа! Какую тренировку ты сегодня выполнил?", reply_markup=WORKOUT_TYPE_KEYBOARD)

async def log_workout(update: Update, context: ContextTypes.DEFAULT_TYPES):
    workout_type = update.message.text.split(" ")[0]
    user_id = update.effective_user.id
    data = get_user_data_from_db(user_id)
    
    today_str = datetime.date.today().strftime('%d.%m.%Y')
    
    if data.get("workout_diary") and data["workout_diary"][-1].startswith(today_str):
         await update.message.reply_text("Ты уже отчитался о тренировке сегодня. Великолепно! 💪", reply_markup=DIARIES_KEYBOARD)
         return
         
    data["score"] = data.get("score", 0) + 15
    entry = f"{today_str} - Тренировка ({workout_type}) выполнена! 💪 +15 очков."
    data.setdefault("workout_diary", []).append(entry)
    save_user_data_to_db(user_id, data)
    
    await update.message.reply_text(f"Поздравляю! 🏆 Твой успех записан в дневник, и ты получаешь 15 баллов. Твой текущий счет: {data['score']}.", reply_markup=DIARIES_KEYBOARD)
    await check_profile_update(update, context)

# --- Главный обработчик сообщений ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPES) -> None:
    if not update.message or not update.message.text: return
    
    message_text = update.message.text

    button_map = {
        "выбрать специалиста 🎭": choose_specialist,
        "мои дневники 📔": show_diaries_menu,
        "мои баллы 🏆": leaderboard,
        "⬅️ назад в главное меню": start,
        "⬅️ назад к выбору специалиста": choose_specialist,
        "рассчитать кбжу 📊": calculate_kbzhu,
        "задать вопрос нутрициологу ❓": nutritionist_consultation_info,
        "рассчитать имт 📉": calculate_bmi,
        "что такое vo2max ❓": explain_vo2max,
        "задать вопрос тренеру ❓": trainer_consultation_info,
        "дневник тренировок 🏋️": start_workout_logging,
        "создать мое спортивное будущее 🔮": start_future_self_image_generation,
    }

    if message_text.capitalize() in ROLE_BUTTON_LABELS:
        await handle_role_selection(update, context)
        return

    handler_func = None
    for key, func in button_map.items():
        cleaned_key = re.sub(r'[^\w\s]', '', key).strip().lower()
        cleaned_message = re.sub(r'[^\w\s]', '', message_text).strip().lower()
        if cleaned_message == cleaned_key:
            handler_func = func
            break
            
    if handler_func:
        await handler_func(update, context)
        return

    await update.message.reply_text("Извините, я не понял команду. Пожалуйста, используйте кнопки.", reply_markup=MAIN_MENU_KEYBOARD)


def main() -> None:
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    profile_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(r'^(Заполнить профиль|Обновить данные профиля 🔄)$'), start_profile_dialog)],
        states={
            GENDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_gender)],
            AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_age)],
            HEIGHT: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_height)],
            WEIGHT: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_weight)],
            ACTIVITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_activity)],
            GOAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_goal)],
            DISEASES: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_diseases)],
            ALLERGIES: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_allergies)],
        },
        fallbacks=[CommandHandler('cancel', cancel_dialog)],
    )

    workout_plan_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(r'^(Составить план тренировок 💪)$'), ask_workout_location)],
        states={
            LOCATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_equipment)],
            EQUIPMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, generate_workout_plan)],
        },
        fallbacks=[CommandHandler('cancel', cancel_dialog)],
    )

    mood_log_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(r'^(Дневник настроения 🧠|Записать настроение ✨)$'), start_mood_logging)],
        states={
            MOOD_SELECT: [MessageHandler(filters.Regex(r'^(Отличное 👍|Хорошее 🙂|Нормальное 😐|Плохое 😕|Очень плохое 😔)$'), ask_mood_time)],
            TIME_SELECT: [MessageHandler(filters.Regex(r'^(Утро ☀️|День 🏙️|Вечер 🌙)$'), finalize_mood_log)],
        },
        fallbacks=[CommandHandler('cancel', cancel_dialog)],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("leaderboard", leaderboard))
    
    application.add_handler(profile_handler)
    application.add_handler(workout_plan_handler)
    application.add_handler(mood_log_handler)

    application.add_handler(MessageHandler(filters.Regex(r'^(Бег 🏃|Силовая 💪|ВИИТ 🔥|Домашняя 🏠)$'), log_workout))
    
    application.add_handler(MessageHandler(filters.PHOTO, handle_future_self_photo))

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Бот запущен и работает...")
    application.run_polling()

if __name__ == "__main__":
    main()

