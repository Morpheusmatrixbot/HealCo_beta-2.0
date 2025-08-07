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
    "нутрициолог": "Ты — профессиональный нутрициолог с глубокими знаниями в диетологии и биохимии. Твоя задача — составлять рационы, анализировать продукты и отвечать на вопросы о питании. Твои ответы компетентны и основаны на науке.",
    "фитнесс-тренер": "Ты — элитный фитнес-тренер. Твоя задача — давать профессиональные рекомендации по тренировкам, восстановлению и спортивной физиологии. Твои ответы точны, научны и мотивируют как на персональной тренировке.",
    "психотерапевт": "Ты — эмпатичный и мудрый психотерапевт. Твоя задача — оказывать поддержку, помогать пользователю разбираться в своих чувствах и настроении. Ты используешь техники активного слушания и никогда не осуждаешь. Твоя речь спокойная и вселяющая уверенность.",
    "медицинский наставник": "Ты внимательный медицинский наставник. Твоя задача — давать легкие рекомендации по улучшению здоровья и анализировать общие симптомы, но всегда с оговоркой, что это не заменяет консультацию реального врача.",
    "личный наставник": "Ты — личный наставник и коуч по продуктивности. Твоя задача — помогать в организации дня, формировании полезных привычек и достижении жизненных целей. Твои ответы вдохновляющие, структурированные и поддерживающие.",
    "ты из будущего": "Ты — это сам пользователь, но из успешного будущего. Ты уже достиг всех целей, о которых пользователь мечтает. Твоя задача — давать мудрые, загадочные и невероятно мотивирующие советы, намекая на будущие успехи.",
}

# --- Клавиатуры ---
START_KEYBOARD = ReplyKeyboardMarkup([["Заполнить профиль"]], resize_keyboard=True)
MAIN_MENU_KEYBOARD = ReplyKeyboardMarkup([["Выбрать специалиста 🎭"], ["Мои дневники 📔", "Мои баллы 🏆"]], resize_keyboard=True)
ROLE_BUTTON_LABELS = [role.capitalize() for role in ROLES.keys()]
ROLE_BUTTONS = [[label] for label in ROLE_BUTTON_LABELS]
ROLE_KEYBOARD = ReplyKeyboardMarkup(ROLE_BUTTONS, one_time_keyboard=True, resize_keyboard=True)
NUTRITIONIST_KEYBOARD = ReplyKeyboardMarkup([["Составить меню на день 🍽️"], ["Анализ продукта по названию 🔍"], ["Задать вопрос нутрициологу ❓"], ["⬅️ Назад к выбору специалиста"]], resize_keyboard=True)
FITNESS_TRAINER_KEYBOARD = ReplyKeyboardMarkup([["Составить план тренировок 💪"], ["Вопрос по упражнению 🏋️"], ["Совет по восстановлению 🧘"], ["⬅️ Назад к выбору специалиста"]], resize_keyboard=True)
PSYCHOTHERAPIST_KEYBOARD = ReplyKeyboardMarkup([["Дневник настроения 🧠"], ["Техника дыхания для успокоения 🌬️"], ["Задать вопрос психотерапевту ❓"], ["⬅️ Назад к выбору специалиста"]], resize_keyboard=True)
GENERAL_SPECIALIST_KEYBOARD = ReplyKeyboardMarkup([["Задать вопрос специалисту ❓"], ["⬅️ Назад к выбору специалиста"]], resize_keyboard=True)
DIARIES_KEYBOARD = ReplyKeyboardMarkup([["Дневник питания 🥕", "Дневник тренировок 🏋️"], ["Дневник здоровья ❤️‍🩹", "Дневник настроения 📊"], ["⬅️ Назад в главное меню"]], resize_keyboard=True)
MOOD_KEYBOARD = ReplyKeyboardMarkup([["Отличное 👍", "Хорошее 🙂"], ["Нормальное 😐"], ["Плохое 😕", "Очень плохое 😔"], ["Посмотреть дневник настроения 📊", "⬅️ Назад к психотерапевту"]], resize_keyboard=True)
HEALTH_KEYBOARD_BASE = [["Записать симптом 🤧", "Посмотреть дневник 📖"], ["⬅️ Назад в главное меню"]]
PROFILE_QUESTIONS = ["profile_state_gender", "profile_state_age", "profile_state_height", "profile_state_weight", "profile_state_activity", "profile_state_goal", "profile_state_diseases", "profile_state_allergies"]
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
        default_data = {"current_role": "личный наставник", "profile_data": {}, "score": 0, "food_diary": [], "workout_diary": [], "health_diary": [], "mood_diary": [], "first_name": "", "last_name": ""}
        db[key] = json.dumps(default_data)
        return default_data

def save_user_data_to_db(user_id, data):
    key = str(user_id)
    db[key] = json.dumps(data)

# --- Вспомогательные функции ---
def encode_image(image_bytes):
    return base64.b64encode(image_bytes).decode('utf-8')

def get_personal_prompt(user_profile_data: dict, first_name: str = None) -> str:
    if not user_profile_data or not user_profile_data.get('goal'): return ""
    parts = []
    if first_name: parts.append(f"Имя пользователя: {first_name}")
    if 'gender' in user_profile_data: parts.append(f"пол: {user_profile_data['gender'].lower()}")
    if 'age' in user_profile_data: parts.append(f"возраст: {user_profile_data['age']} лет")
    if 'height' in user_profile_data: parts.append(f"рост: {user_profile_data['height']} см")
    if 'weight' in user_profile_data: parts.append(f"вес: {user_profile_data['weight']} кг")
    if 'activity' in user_profile_data: parts.append(f"образ жизни: {user_profile_data['activity'].lower()}")
    if 'goal' in user_profile_data: parts.append(f"цель: {user_profile_data['goal'].lower()}")
    if 'diseases' in user_profile_data and user_profile_data['diseases'].lower() not in ['нет', 'no']: parts.append(f"хронические заболевания: {user_profile_data['diseases']}")
    if 'allergies' in user_profile_data and user_profile_data['allergies'].lower() not in ['нет', 'no']: parts.append(f"аллергии: {user_profile_data['allergies']}")
    return f"Учитывай в ответе, что пользователь сообщил о себе: {', '.join(parts)}. " if parts else ""

# --- Навигация и Основные экраны ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    data = get_user_data_from_db(user.id)
    data["first_name"] = user.first_name
    save_user_data_to_db(user.id, data)
    keyboard = MAIN_MENU_KEYBOARD if data.get("profile_data", {}).get('goal') else START_KEYBOARD
    await update.message.reply_html(f"Привет, {user.mention_html()}! 👋\n\nЯ — твой персональный AI-консьерж по здоровью. Моя миссия — помочь тебе лучше понимать свое тело и разум, питаться осознанно, тренироваться эффективно и достигать гармонии в жизни.\n\nЧем займемся сегодня? 👇\n\n<i>I heal you! ♥️</i>", reply_markup=keyboard)

async def choose_specialist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Выберите специалиста, с которым хотите пообщаться:", reply_markup=ROLE_KEYBOARD)

async def show_diaries_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Какой дневник вы хотите посмотреть?", reply_markup=DIARIES_KEYBOARD)

# --- Роли-Специалисты ---
async def handle_role_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    requested_role_display = update.message.text
    requested_role = requested_role_display.lower().replace('-', ' ')
    data = get_user_data_from_db(user_id)
    if requested_role in ROLES:
        data["current_role"] = requested_role
        save_user_data_to_db(user_id, data)
        if requested_role == "нутрициолог": role_keyboard = NUTRITIONIST_KEYBOARD
        elif requested_role == "фитнесс-тренер": role_keyboard = FITNESS_TRAINER_KEYBOARD
        elif requested_role == "психотерапевт": role_keyboard = PSYCHOTHERAPIST_KEYBOARD
        else: role_keyboard = GENERAL_SPECIALIST_KEYBOARD
        try:
            prompt = f"Твоя новая роль: {ROLES[requested_role]}. Напиши короткое приветствие (2-3 предложения). Представься и расскажи, чем конкретно ты можешь помочь (например, 'составить меню', 'разработать план тренировок'). Твой ответ будет показан пользователю вместе с кнопками твоего функционала. Используй эмодзи для настроения."
            response = client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": prompt}], max_tokens=200, temperature=0.8)
            greeting = response.choices[0].message.content
        except Exception as e:
            logger.error(f"Ошибка генерации приветствия роли: {e}")
            greeting = f"Здравствуйте! Я ваш **{requested_role_display}**. Чем могу помочь?"
        await update.message.reply_text(greeting, reply_markup=role_keyboard, parse_mode='Markdown')
    else:
        await update.message.reply_text("Извините, я не понял такую роль.", reply_markup=MAIN_MENU_KEYBOARD)

# --- Профиль Пользователя ---
async def start_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    data = get_user_data_from_db(user_id)
    data["context_state"] = 'awaiting_profile'
    save_user_data_to_db(user_id, data)
    context.user_data['profile_questions_index'] = 0
    context.user_data['profile_data'] = {}
    await update.message.reply_text("Отлично! Начнем заполнение твоего профиля.\nНапиши `Отмена`, если захочешь прервать.", reply_markup=ReplyKeyboardRemove())
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
        question_text = "Укажи свой пол:"; reply_markup = ReplyKeyboardMarkup(GENDER_KEYBOARD, one_time_keyboard=True, resize_keyboard=True)
    elif current_question_key == "profile_state_age": question_text = "Сколько тебе полных лет?"
    elif current_question_key == "profile_state_height": question_text = "Какой у тебя рост в сантиметрах? (Например: 175)"
    elif current_question_key == "profile_state_weight": question_text = "Какой у тебя текущий вес в килограммах? (Например: 70.5)"
    elif current_question_key == "profile_state_activity":
        question_text = "Какой у тебя уровень физической активности?"; reply_markup = ReplyKeyboardMarkup(ACTIVITY_KEYBOARD, one_time_keyboard=True, resize_keyboard=True)
    elif current_question_key == "profile_state_goal":
        question_text = "Какова твоя основная цель?"; reply_markup = ReplyKeyboardMarkup(GOAL_KEYBOARD, one_time_keyboard=True, resize_keyboard=True)
    elif current_question_key == "profile_state_diseases": question_text = "Есть ли у тебя хронические заболевания? Если нет, напиши `Нет`."
    elif current_question_key == "profile_state_allergies": question_text = "Есть ли у тебя пищевые аллергии или непереносимости? Если нет, напиши `Нет`."
    await update.message.reply_text(question_text, reply_markup=reply_markup)

async def handle_profile_response(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message_text = update.message.text
    if message_text and message_text.lower() == "отмена":
        await cancel_profile(update, context); return
    question_index = context.user_data.get('profile_questions_index', 0)
    current_question_key = PROFILE_QUESTIONS[question_index]
    profile_data = context.user_data.get('profile_data', {})
    valid = True; error_message = ""
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
        valid = False; error_message = "Кажется, формат данных неверный. Попробуй еще раз."
    if not valid:
        await update.message.reply_text(error_message); return
    context.user_data['profile_data'] = profile_data
    context.user_data['profile_questions_index'] += 1
    await ask_next_profile_question(update, context)

async def finalize_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    data = get_user_data_from_db(user_id)
    data["profile_data"] = context.user_data.get('profile_data', {})
    data["score"] = data.get("score", 0) + 30
    data.pop('context_state', None)
    save_user_data_to_db(user_id, data)
    context.user_data.pop('profile_questions_index', None)
    context.user_data.pop('profile_data', None)
    await update.message.reply_text(f"Спасибо! Твой профиль заполнен. За это ты получаешь 30 баллов! Твой текущий счет: {data['score']}.\nТеперь тебе доступны все функции.", reply_markup=MAIN_MENU_KEYBOARD)

async def cancel_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    context.user_data.pop('profile_questions_index', None)
    context.user_data.pop('profile_data', None)
    data = get_user_data_from_db(user_id)
    data.pop('context_state', None)
    save_user_data_to_db(user_id, data)
    await update.message.reply_text("Заполнение профиля отменено.", reply_markup=START_KEYBOARD)

# --- Функции Специалистов ---
async def create_personalized_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    data = get_user_data_from_db(user_id)
    await update.message.reply_text("Так, минуточку... 👨‍🍳 Составляю для тебя два варианта меню. Ожидай...", reply_markup=ReplyKeyboardRemove())
    role_prompt = ROLES["нутрициолог"]
    menu_prompt = (f"Ты — {role_prompt}. Используя данные профиля пользователя, составь два варианта меню на один день: 'Базовое меню' (из простых, доступных продуктов) и 'Гурме-меню' (с более редкими, интересными продуктами).\n{get_personal_prompt(data.get('profile_data', {}), data.get('first_name'))}\nДля каждого приема пищи (завтрак, обед, ужин) в обоих меню, укажи:\n- 🍳/🥗/🍲 Название блюда\n- ⚖️ Примерный объем порции в граммах (например, ~300 г)\n- 🔥 Примерную калорийность (например, ~450 ккал)\nИспользуй эмодзи для списков. Ответ должен быть четко структурирован, дружелюбен и мотивирующ.")
    try:
        response = client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": menu_prompt}], max_tokens=1500, temperature=0.8)
        await update.message.reply_text(response.choices[0].message.content, reply_markup=NUTRITIONIST_KEYBOARD)
    except Exception as e:
        logger.error(f"Ошибка генерации меню: {e}")
        await update.message.reply_text("Произошла ошибка при создании меню. Попробуй позже.", reply_markup=NUTRITIONIST_KEYBOARD)

async def create_workout_plan_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Где ты предпочитаешь тренироваться?", reply_markup=ReplyKeyboardMarkup(WORKOUT_PLACE_KEYBOARD, one_time_keyboard=True, resize_keyboard=True))

async def create_workout_plan_final(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    data = get_user_data_from_db(user_id)
    workout_location = update.message.text.lower()
    await update.message.reply_text("💪 Отлично! Разрабатываю для тебя эффективный план тренировок... Это займет секунду.", reply_markup=ReplyKeyboardRemove())
    role_prompt = ROLES["фитнесс-тренер"]
    workout_prompt = (f"Ты — {role_prompt}. Создай подробный план тренировок на неделю (3 дня), используя данные пользователя.\nТренировки будут проходить '{workout_location}'.\n{get_personal_prompt(data.get('profile_data', {}), data.get('first_name'))}\nДля каждого тренировочного дня:\n- 🗓️ Тип тренировки\n- 💪 Упражнения (подходы/повторения)\n- 🔥 Примерное количество сжигаемых калорий\n- ❤️ Целевые пульсовые зоны: 'Упражнение', 'Отдых' и 'Прервать если'.\nИспользуй эмодзи для списков и акцентов. План должен быть супер-мотивирующим.")
    try:
        response = client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": workout_prompt}], max_tokens=1500, temperature=0.7)
        await update.message.reply_text(response.choices[0].message.content, reply_markup=FITNESS_TRAINER_KEYBOARD)
    except Exception as e:
        logger.error(f"Ошибка генерации плана тренировок: {e}")
        await update.message.reply_text("Не смог составить план. Что-то пошло не так с AI.", reply_markup=FITNESS_TRAINER_KEYBOARD)

async def analyze_product_by_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Эта функция в разработке. 🏗️", reply_markup=NUTRITIONIST_KEYBOARD)

async def handle_exercise_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Эта функция в разработке. 🏗️", reply_markup=FITNESS_TRAINER_KEYBOARD)

async def handle_breathing_technique(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Эта функция в разработке. 🌬️", reply_markup=PSYCHOTHERAPIST_KEYBOARD)

# --- Дневники ---
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    await update.message.reply_text("🧐 Анализирую твой кулинарный шедевр...", reply_markup=ReplyKeyboardRemove())
    try:
        file_obj = await context.bot.get_file(update.message.photo[-1].file_id)
        photo_bytes = await file_obj.download_as_bytes()
        base64_image = encode_image(photo_bytes)
        vision_prompt = "Это фотография еды. Проанализируй ее максимально подробно. В ответе укажи:\n1. 🍽️ **Название блюда**\n2. 📝 **Предполагаемые ингредиенты**\n3. ⚖️ **Примерный вес порции** в граммах\n4. 🔥 **Ориентировочная калорийность** (диапазон). Если не еда, так и скажи."
        response = client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": [{"type": "text", "content": vision_prompt}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}]}], max_tokens=400)
        description = response.choices[0].message.content
        data = get_user_data_from_db(user_id)
        food_title = description.split('\n')[0].replace("🍽️ **Название блюда:**", "").strip()
        data["food_diary"].append(f"{datetime.datetime.now().strftime('%H:%M %d.%m')} - {food_title}")
        save_user_data_to_db(user_id, data)
        await update.message.reply_text(f"Готово! Вот мой анализ:\n\n{description}\n\nЯ добавил это блюдо в твой дневник питания. ✅", reply_markup=MAIN_MENU_KEYBOARD, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Ошибка анализа фото: {e}")
        await update.message.reply_text("Ой, не смог распознать фото. Попробуй еще раз!", reply_markup=MAIN_MENU_KEYBOARD)

async def show_food_diary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = get_user_data_from_db(update.effective_user.id)
    diary_entries = data.get("food_diary", [])
    if not diary_entries:
        await update.message.reply_text("Твой дневник питания пока пуст.", reply_markup=DIARIES_KEYBOARD)
        return
    response_text = "Твой дневник питания (последние 15 записей):\n" + "\n".join([f"- {entry}" for entry in diary_entries[-15:]])
    await update.message.reply_text(response_text, reply_markup=DIARIES_KEYBOARD)
    
async def workout_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    data = get_user_data_from_db(user_id)
    today_str = datetime.date.today().strftime('%d.%m.%Y')
    if data.get("workout_diary") and data["workout_diary"][-1].startswith(today_str):
         await update.message.reply_text("Ты уже отчитался сегодня. Отличная работа! 💪 Так держать!", reply_markup=MAIN_MENU_KEYBOARD)
         return
    data["score"] = data.get("score", 0) + 15
    entry = f"{today_str} - Тренировка выполнена! 💪 +15 очков."
    data["workout_diary"].append(entry)
    save_user_data_to_db(user_id, data)
    await update.message.reply_text(f"Поздравляю! 🏆 Твой успех записан в дневник, и ты получаешь 15 баллов. Счет: {data['score']}.", reply_markup=MAIN_MENU_KEYBOARD)

async def show_workout_diary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = get_user_data_from_db(update.effective_user.id)
    diary_entries = data.get("workout_diary", [])
    if not diary_entries:
        await update.message.reply_text("Твой дневник тренировок пока пуст. Самое время начать! 😉", reply_markup=DIARIES_KEYBOARD)
        return
    response_text = "Твой дневник тренировок (последние 15 записей):\n\n"
    for entry in diary_entries[-15:]:
        response_text += f"✅ {entry}\n"
    await update.message.reply_text(response_text, reply_markup=DIARIES_KEYBOARD)

async def health_diary_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    profile_diseases = get_user_data_from_db(update.effective_user.id).get("profile_data", {}).get("diseases", "").lower()
    keyboard_layout = [row[:] for row in HEALTH_KEYBOARD_BASE]
    if "гипертония" in profile_diseases or "давление" in profile_diseases: keyboard_layout.insert(1, ["Записать давление 🩺"])
    if "диабет" in profile_diseases or "сахар" in profile_diseases: keyboard_layout.insert(1, ["Записать сахар в крови 🩸"])
    await update.message.reply_text("Это ваш личный Дневник здоровья. Что вы хотите сделать?", reply_markup=ReplyKeyboardMarkup(keyboard_layout, resize_keyboard=True, one_time_keyboard=True))

async def start_symptom_logging(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = get_user_data_from_db(update.effective_user.id)
    data["context_state"] = 'awaiting_symptom'
    save_user_data_to_db(update.effective_user.id, data)
    await update.message.reply_text("Пожалуйста, опишите симптомы, которые вас беспокоят. Постарайтесь быть как можно точнее.", reply_markup=ReplyKeyboardRemove())

async def show_health_diary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = get_user_data_from_db(update.effective_user.id)
    diary_entries = data.get("health_diary", [])
    if not diary_entries:
        await update.message.reply_text("Ваш Дневник здоровья пока пуст. ❤️‍🩹", reply_markup=DIARIES_KEYBOARD)
        return
    response_text = "Ваш Дневник здоровья (последние 15 записей):\n\n"
    ICONS = {"symptom": "🤧", "pressure": "🩺", "sugar": "🩸"}
    for entry in diary_entries[-15:]:
        icon = ICONS.get(entry.get("type"), "▪️")
        response_text += f"{icon} **{entry.get('date')}**: {entry.get('text')}\n"
    await update.message.reply_text(response_text, reply_markup=DIARIES_KEYBOARD, parse_mode='Markdown')

async def start_pressure_logging(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = get_user_data_from_db(update.effective_user.id)
    data["context_state"] = 'awaiting_pressure'
    save_user_data_to_db(update.effective_user.id, data)
    await update.message.reply_text("Введите ваше давление в формате '120/80'.", reply_markup=ReplyKeyboardRemove())

async def start_sugar_logging(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = get_user_data_from_db(update.effective_user.id)
    data["context_state"] = 'awaiting_sugar'
    save_user_data_to_db(update.effective_user.id, data)
    await update.message.reply_text("Введите ваш уровень сахара в крови (например, '6.5' или '6.5 ммоль/л').", reply_markup=ReplyKeyboardRemove())

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
    
async def show_score(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = get_user_data_from_db(update.effective_user.id)
    keyboard = MAIN_MENU_KEYBOARD if data.get("profile_data", {}).get('goal') else START_KEYBOARD
    await update.message.reply_text(f"Твой текущий счет: {data.get('score', 0)} баллов. 🏆", reply_markup=keyboard)

# --- Обработчики состояний ---
async def handle_symptom_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    data = get_user_data_from_db(user_id)
    data.pop('context_state', None)
    save_user_data_to_db(user_id, data)
    await update.message.reply_text("Анализирую ваши симптомы... 🧠", reply_markup=ReplyKeyboardRemove())
    prompt = f"Выступи в роли 'Медицинского советника'. Проанализируй следующие симптомы от пользователя: '{update.message.text}'. Дай краткий, общий совет о возможных причинах в дружелюбной форме. ВАЖНЕЙШИЙ ПРИОРИТЕТ: Оцени потенциальную серьезность. Если есть хоть малейший намек на что-то опасное (например, боль в груди, затрудненное дыхание, онемение, очень высокая температура, нестерпимая боль), твой ГЛАВНЫЙ ответ должен быть — немедленно и настоятельно порекомендовать обратиться к врачу или вызвать скорую помощь. В ЛЮБОМ СЛУЧАЕ, закончи свой ответ четким и ясным напоминанием: 'Помните, я — AI-ассистент, и моя консультация не заменяет визит к настоящему врачу.'"
    try:
        response = client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": prompt}], max_tokens=1000)
        ai_response = response.choices[0].message.content
    except Exception as e:
        logger.error(f"Ошибка анализа симптомов: {e}")
        ai_response = "К сожалению, не удалось проанализировать симптомы из-за технической ошибки."
    entry = {"date": datetime.date.today().strftime('%d.%m.%Y'), "type": "symptom", "text": update.message.text}
    data.setdefault("health_diary", []).append(entry)
    save_user_data_to_db(user_id, data)
    await update.message.reply_text(ai_response, reply_markup=MAIN_MENU_KEYBOARD)

async def handle_pressure_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    data = get_user_data_from_db(user_id)
    data.pop('context_state', None)
    entry = {"date": datetime.date.today().strftime('%d.%m.%Y'), "type": "pressure", "text": f"Давление: {update.message.text}"}
    data.setdefault("health_diary", []).append(entry)
    save_user_data_to_db(user_id, data)
    await update.message.reply_text("✅ Запись о давлении добавлена в ваш дневник.", reply_markup=MAIN_MENU_KEYBOARD)

async def handle_sugar_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    data = get_user_data_from_db(user_id)
    data.pop('context_state', None)
    entry = {"date": datetime.date.today().strftime('%d.%m.%Y'), "type": "sugar", "text": f"Сахар в крови: {update.message.text}"}
    data.setdefault("health_diary", []).append(entry)
    save_user_data_to_db(user_id, data)
    await update.message.reply_text("✅ Запись об уровне сахара добавлена в ваш дневник.", reply_markup=MAIN_MENU_KEYBOARD)

async def handle_specialist_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    data = get_user_data_from_db(user_id)
    data.pop('context_state', None)
    save_user_data_to_db(user_id, data)
    current_role = data.get("current_role", "личный наставник")
    role_prompt = ROLES.get(current_role)
    personal_info = get_personal_prompt(data.get("profile_data", {}), data.get("first_name"))
    await update.message.reply_text(f"Думаю над вашим вопросом для {current_role.capitalize()}...", reply_markup=ReplyKeyboardRemove())
    full_prompt = f"Твоя текущая роль: {role_prompt}. {personal_info} Ответь на вопрос пользователя, соблюдая свою роль. Вопрос: {update.message.text}. Используй эмодзи для форматирования."
    if current_role == "нутрициолог": role_keyboard = NUTRITIONIST_KEYBOARD
    elif current_role == "фитнесс-тренер": role_keyboard = FITNESS_TRAINER_KEYBOARD
    elif current_role == "психотерапевт": role_keyboard = PSYCHOTHERAPIST_KEYBOARD
    else: role_keyboard = GENERAL_SPECIALIST_KEYBOARD
    try:
        response = client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": full_prompt}], max_tokens=1500, temperature=0.7)
        await update.message.reply_text(response.choices[0].message.content, reply_markup=role_keyboard)
    except Exception as e:
        logger.error(f"Ошибка вызова OpenAI для ответа специалиста: {e}")
        await update.message.reply_text("Извини, не могу сейчас ответить. Произошла ошибка.", reply_markup=role_keyboard)

# --- Главный обработчик сообщений ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message_text = update.message.text
    user_id = update.effective_user.id
    data = get_user_data_from_db(user_id)
    
    context_state = data.get('context_state')
    if context_state:
        if context_state == 'awaiting_profile': await handle_profile_response(update, context); return
        if context_state == 'awaiting_symptom': await handle_symptom_input(update, context); return
        if context_state == 'awaiting_pressure': await handle_pressure_input(update, context); return
        if context_state == 'awaiting_sugar': await handle_sugar_input(update, context); return
        if context_state == 'awaiting_question_for_specialist': await handle_specialist_question(update, context); return

    button_map = {
        "выбрать специалиста": choose_specialist, "мои дневники": show_diaries_menu,
        "⬅️ назад в главное меню": start, "⬅️ назад к выбору специалиста": choose_specialist,
        "составить меню на день": create_personalized_menu, "анализ продукта по названию": analyze_product_by_name,
        "составить план тренировок": create_workout_plan_location, "вопрос по упражнению": handle_exercise_question,
        "совет по восстановлению": handle_exercise_question,
        "дневник настроения": mental_health_menu, "техника дыхания для успокоения": handle_breathing_technique,
        "дневник питания": show_food_diary, "дневник тренировок": show_workout_diary,
        "дневник здоровья": health_diary_menu, "посмотреть дневник настроения": show_mood_diary,
        "мои баллы": show_score, "заполнить профиль": start_profile,
        "записать симптом": start_symptom_logging, "посмотреть дневник": show_health_diary,
        "записать давление": start_pressure_logging, "записать сахар": start_sugar_logging,
        "⬅️ назад к психотерапевту": mental_health_menu,
    }
    
    if message_text.capitalize() in ROLE_BUTTON_LABELS:
        await handle_role_selection(update, context); return
        
    for key, func in button_map.items():
        if key in message_text.lower():
            await func(update, context); return
            
    if "задать вопрос" in message_text.lower():
        current_role = data.get("current_role", "специалисту")
        await update.message.reply_text(f"Конечно, я слушаю ваш вопрос для **{current_role.capitalize()}**.", parse_mode='Markdown', reply_markup=ReplyKeyboardRemove())
        data['context_state'] = 'awaiting_question_for_specialist'
        save_user_data_to_db(user_id, data)
        return

    await update.message.reply_text("Извините, я не понял команду. Пожалуйста, используйте кнопки.", reply_markup=MAIN_MENU_KEYBOARD)

def main() -> None:
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("profile", start_profile))
    application.add_handler(CommandHandler("score", show_score))
    application.add_handler(CommandHandler("workout_done", workout_done))

    application.add_handler(MessageHandler(filters.Regex(r'^(Отличное 👍|Хорошее 🙂|Нормальное 😐|Плохое 😕|Очень плохое 😔)$'), log_mood))
    application.add_handler(MessageHandler(filters.Regex(r'^(Дома|В зале|На улице)$'), create_workout_plan_final))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Бот запущен и работает...")
    application.run_polling()

if __name__ == "__main__":
    main()
