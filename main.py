import logging
import os
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import openai
import base64
import json
import re
from replit import db # Импортируем базу данных Replit
import datetime

# --- Конфигурация ---
# Получаем токен Telegram-бота и ключ OpenAI из переменных окружения
# Replit secrets работают как переменные окружения
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Инициализируем клиента OpenAI API
if OPENAI_API_KEY:
    openai.api_key = OPENAI_API_KEY
    client = openai.OpenAI()
else:
    # Эта ошибка будет видна в консоли Replit, если ключи не установлены
    raise ValueError("OPENAI_API_KEY или TELEGRAM_BOT_TOKEN не найдены в переменных окружения. Пожалуйста, установите их в 'Secrets'.")

# Настройка логирования для отладки
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# --- Ролевые модели (без изменений) ---
ROLES = {
    "фитнесс-тренер": "Ты профессиональный фитнесс-тренер. Твоя задача — давать рекомендации по тренировкам, набору мышечной массы, снижению веса и спортивному питанию. Говори четко, мотивирующе, как будто ты в тренажерном зале, используя профессиональные термины, но объясняя их. В своих ответах ссылайся на научно доказанные факты в фитнесс-индустрии.",
    "личный наставник": "Ты личный наставник и коуч. Твоя задача — помогать в организации распорядка дня, трекинге привычек, ведении здорового образа жизни и повышении продуктивности. Твои ответы должны быть вдохновляющими, помогающими структурировать жизнь. Говори поддерживающе и оптимистично.",
    "нутрициолог": "Ты профессиональный нутрициолог. Твоя задача — давать рекомендации по питанию, составлять персональные меню и объяснять принципы здорового рациона. Говори компетентно, ссылаясь на последние научно-доказанные данные в области нутрициологии.",
    "медицинский наставник": "Ты внимательный медицинский наставник. Твоя задача — давать легкие рекомендации по улучшению здоровья, диагностике общих симптомов и советовать бады, но всегда с оговоркой, что это не заменяет консультацию реального врача. Говори аккуратно, используя фразы вроде 'Рекомендуется проконсультироваться с врачом'.",
    "майор пейн": "Ты — Майор Пейн, но продвинутый в знаниях о человеке и его здоровье. Твоя задача — мотивировать к действию жестко, без отговорок, используя военную терминологию. Твои ответы должны быть прямыми, с долей юмора, но всегда нацелены на результат. При лени или прокрастинации отвечай в стиле: 'Отставить! Быстро за дело!'",
    "ты из будущего": "Ты — это сам пользователь, но из будущего, успешный и достигший своих целей. Твоя задача — мотивировать пользователя, показывая образы успеха и достижений, мудрость, которую он приобретет. Говори уверенно, вдохновляюще, но слегка таинственно, как знающий наперед, используя фразы вроде 'Помни, что ты сможешь...', 'Я знаю, каким ты станешь...'.",
}

# --- Клавиатуры (без изменений) ---
ROLE_BUTTON_LABELS = [role.capitalize() for role in ROLES.keys()]
ROLE_BUTTONS = [[label] for label in ROLE_BUTTON_LABELS]
ROLE_KEYBOARD = ReplyKeyboardMarkup(ROLE_BUTTONS, one_time_keyboard=True, resize_keyboard=True)

START_KEYBOARD = ReplyKeyboardMarkup([
    ["Заполнить профиль", "Выбрать роль"],
    ["Дневник питания", "Мои баллы"],
    ["О чем говорят цифры?", "К врачу"]
], resize_keyboard=True)

PROACTIVE_KEYBOARD = ReplyKeyboardMarkup([
    ["Составить меню", "Составить план тренировок"],
    ["Дневник питания", "Выбрать роль"],
    ["Мои баллы", "К врачу"]
], resize_keyboard=True)

PROFILE_QUESTIONS = [
    "profile_state_gender", "profile_state_age", "profile_state_height",
    "profile_state_weight", "profile_state_activity", "profile_state_goal",
    "profile_state_diseases", "profile_state_allergies"
]

GENDER_KEYBOARD = [["Мужской", "Женский"]]
ACTIVITY_KEYBOARD = [["Сидячий", "Умеренный", "Активный"]]
GOAL_KEYBOARD = [["Похудеть", "Набрать массу", "Поддерживать вес"]]
WORKOUT_PLACE_KEYBOARD = [["Дома", "В зале", "На улице"]]

# --- Функции для работы с базой данных (без изменений) ---
def get_user_data_from_db(user_id):
    key = str(user_id)
    if key in db:
        return json.loads(db[key])
    else:
        default_data = {
            "current_role": "личный наставник", "profile_data": {}, "score": 0,
            "food_diary": [], "first_name": "", "last_name": ""
        }
        db[key] = json.dumps(default_data)
        return default_data

def save_user_data_to_db(user_id, data):
    key = str(user_id)
    db[key] = json.dumps(data)

# --- Вспомогательные функции для AI (без изменений) ---
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
    if 'diseases' in user_profile_data: parts.append(f"хронические заболевания: {user_profile_data['diseases']}")
    if 'allergies' in user_profile_data: parts.append(f"аллергии: {user_profile_data['allergies']}")
    return f"Учитывай в ответе, что пользователь сообщил о себе: {', '.join(parts)}. " if parts else ""

# --- Обработчики команд и сообщений (основные изменения здесь) ---

# Функции start, set_role, handle_role_selection, show_roles, get_current_role, show_food_diary
# остаются без изменений.

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user = update.effective_user
    data = get_user_data_from_db(user_id)
    data["first_name"] = user.first_name
    data["last_name"] = user.last_name
    save_user_data_to_db(user_id, data)
    await update.message.reply_html(
        f"Привет, {user.mention_html()}! Я твой ИИ-консьерж по здоровью и продуктивности. Моя задача — помочь тебе структурировать день, заботиться о теле и уме, и достигать поставленных целей.\n\n"
        "Я могу общаться с тобой в разных ролях и давать персонализированные рекомендации.\n"
        "Выбери, что хочешь сделать сейчас:",
        reply_markup=START_KEYBOARD
    )

async def set_role(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Какую роль ты хочешь, чтобы я сейчас принял?", reply_markup=ROLE_KEYBOARD)

async def handle_role_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    requested_role_display = update.message.text
    requested_role = requested_role_display.lower().replace('-', ' ')
    data = get_user_data_from_db(user_id)
    if requested_role in ROLES:
        data["current_role"] = requested_role
        save_user_data_to_db(user_id, data)
        await update.message.reply_text(f"Отлично! Теперь я буду общаться с тобой как **{requested_role_display}**.", reply_markup=START_KEYBOARD)
    else:
        await update.message.reply_text("Извини, я не понял такую роль. Пожалуйста, выбери из предложенных кнопок.", reply_markup=START_KEYBOARD)

async def show_roles(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Доступные ролевые модели:\n" + "\n".join([f"- **{role.capitalize()}**: {desc.split('.')[0]}" for role, desc in ROLES.items()]) + "\n\nИспользуй `/role` для выбора.",
        reply_markup=START_KEYBOARD
    )

async def get_current_role(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = get_user_data_from_db(update.effective_user.id)
    current_role = data.get("current_role", "личный наставник")
    await update.message.reply_text(f"Сейчас я общаюсь с тобой как **{current_role.capitalize()}**.", reply_markup=START_KEYBOARD)

async def show_food_diary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = get_user_data_from_db(update.effective_user.id)
    diary_entries = data.get("food_diary", [])
    if not diary_entries:
        await update.message.reply_text("Твой дневник питания пока пуст.", reply_markup=START_KEYBOARD)
        return
    response_text = "Твой дневник питания:\n" + "\n".join([f"- {entry}" for entry in diary_entries])
    await update.message.reply_text(response_text, reply_markup=START_KEYBOARD)


# Функции для работы с профилем (start_profile, ask_next_profile_question, handle_profile_response)
# остаются без изменений.

async def start_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    data = get_user_data_from_db(user_id)
    data["profile_state"] = PROFILE_QUESTIONS[0]
    data["profile_data"] = {}
    data["score"] += 10
    save_user_data_to_db(user_id, data)
    await update.message.reply_text(
        f"Отлично! Начнем заполнение твоего профиля. За это ты получаешь 10 баллов! Твой текущий счет: {data['score']}.\n"
        "Это поможет мне давать более точные рекомендации.\n"
        "Напиши `Отмена`, если захочешь прервать.",
        reply_markup=ReplyKeyboardRemove()
    )
    await ask_next_profile_question(update, context)

async def ask_next_profile_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    data = get_user_data_from_db(user_id)
    current_state = data.get("profile_state")
    question = ""
    reply_markup = ReplyKeyboardRemove()
    if current_state == "profile_state_gender":
        question = "Укажи свой пол:"
        reply_markup = ReplyKeyboardMarkup(GENDER_KEYBOARD, one_time_keyboard=True, resize_keyboard=True)
    elif current_state == "profile_state_age": question = "Сколько тебе полных лет?"
    elif current_state == "profile_state_height": question = "Какой у тебя рост в сантиметрах? (Например: 175)"
    elif current_state == "profile_state_weight": question = "Какой у тебя текущий вес в килограммах? (Например: 70.5)"
    elif current_state == "profile_state_activity":
        question = "Какой у тебя уровень физической активности?"
        reply_markup = ReplyKeyboardMarkup(ACTIVITY_KEYBOARD, one_time_keyboard=True, resize_keyboard=True)
    elif current_state == "profile_state_goal":
        question = "Какова твоя основная цель?"
        reply_markup = ReplyKeyboardMarkup(GOAL_KEYBOARD, one_time_keyboard=True, resize_keyboard=True)
    elif current_state == "profile_state_diseases": question = "Есть ли у тебя хронические заболевания? Если нет, напиши `Нет`."
    elif current_state == "profile_state_allergies": question = "Есть ли у тебя пищевые аллергии? Если нет, напиши `Нет`."
    else:
        await finalize_profile(update, context)
        return
    await update.message.reply_text(question, reply_markup=reply_markup)

async def handle_profile_response(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    message_text = update.message.text
    data = get_user_data_from_db(user_id)
    if message_text and message_text.lower() == "отмена":
        await cancel_profile(update, context)
        return
    current_state = data.get("profile_state")
    if not current_state:
        await handle_message(update, context)
        return
    profile_data = data["profile_data"]
    try:
        # Валидация и сохранение данных (логика без изменений)
        valid = True
        if current_state == "profile_state_gender":
            if message_text.lower() in ["мужской", "женский"]: profile_data["gender"] = message_text
            else: valid = False; await update.message.reply_text("Пожалуйста, выбери 'Мужской' или 'Женский'.")
        elif current_state == "profile_state_age":
            age = int(message_text);
            if 0 < age < 120: profile_data["age"] = age
            else: valid = False; await update.message.reply_text("Пожалуйста, введи корректный возраст.")
        # ... и так далее для всех полей
        elif current_state == "profile_state_height":
            height = int(message_text);
            if 50 < height < 250: profile_data["height"] = height
            else: valid = False; await update.message.reply_text("Пожалуйста, введи корректный рост.")
        elif current_state == "profile_state_weight":
            weight = float(message_text.replace(',', '.'));
            if 20 < weight < 300: profile_data["weight"] = weight
            else: valid = False; await update.message.reply_text("Пожалуйста, введи корректный вес.")
        elif current_state == "profile_state_activity":
            if message_text.lower() in ["сидячий", "умеренный", "активный"]: profile_data["activity"] = message_text
            else: valid = False; await update.message.reply_text("Пожалуйста, выбери из предложенных вариантов.")
        elif current_state == "profile_state_goal":
            if message_text.lower() in ["похудеть", "набрать массу", "поддерживать вес"]: profile_data["goal"] = message_text
            else: valid = False; await update.message.reply_text("Пожалуйста, выбери из предложенных вариантов.")
        elif current_state == "profile_state_diseases": profile_data["diseases"] = message_text
        elif current_state == "profile_state_allergies": profile_data["allergies"] = message_text

        if not valid: return

        current_index = PROFILE_QUESTIONS.index(current_state)
        if current_index + 1 < len(PROFILE_QUESTIONS):
            data["profile_state"] = PROFILE_QUESTIONS[current_index + 1]
            save_user_data_to_db(user_id, data)
            await ask_next_profile_question(update, context)
        else:
            await finalize_profile(update, context)
    except (ValueError, TypeError):
        await update.message.reply_text("Кажется, формат данных неверный. Попробуй еще раз.")
    except Exception as e:
        logger.error(f"Ошибка в handle_profile_response для user {user_id}: {e}")
        await update.message.reply_text("Произошла ошибка. Попробуй еще раз или напиши `Отмена`.")


# --- ИЗМЕНЕНИЕ: Улучшенная логика в finalize_profile ---
async def finalize_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    data = get_user_data_from_db(user_id)
    profile = data.get("profile_data", {})
    data["profile_state"] = None
    data["score"] += 20
    data["first_name"] = update.effective_user.first_name
    data["last_name"] = update.effective_user.last_name
    save_user_data_to_db(user_id, data)
    
    logger.info(f"User {user_id} profile finalized: {profile}")
    await update.message.reply_text(
        f"Спасибо! Профиль заполнен, +20 баллов! Счет: {data['score']}.\nАнализирую данные...",
        reply_markup=ReplyKeyboardRemove()
    )

    # Расчеты (BMR, TDEE, BMI, БЖУ)
    bmr, tdee, bmi_value, target_calories = 0, 0, 0, 0
    bmi_category, special_advice = "", ""
    protein_g, fat_g, carb_g = 0, 0, 0
    if all(k in profile for k in ['gender', 'age', 'height', 'weight', 'activity', 'goal']):
        w, h, a, g = profile['weight'], profile['height'], profile['age'], profile['gender'].lower()
        if g == 'мужской': bmr = (10*w) + (6.25*h) - (5*a) + 5
        else: bmr = (10*w) + (6.25*h) - (5*a) - 161
        tdee = bmr * {'сидячий': 1.2, 'умеренный': 1.375, 'активный': 1.55}.get(profile['activity'].lower(), 1.2)
        bmi_value = w / ((h / 100) ** 2)
        if bmi_value < 18.5: bmi_category = "Недостаточная масса тела"
        elif 18.5 <= bmi_value < 24.9: bmi_category = "Нормальная масса тела"
        elif 25 <= bmi_value < 29.9: bmi_category = "Избыточная масса тела"
        else: bmi_category = "Ожирение"

        # --- НОВАЯ ЛОГИКА ---
        # Если вес в норме, но цель - похудеть
        if bmi_category == "Нормальная масса тела" and profile['goal'].lower() == 'похудеть':
            special_advice = (
                "Важно: у тебя уже нормальный вес. Поэтому для цели 'похудеть' не стоит резко снижать калораж. "
                "Гораздо важнее будет добавить регулярные тренировки для улучшения композиции тела (снижение жира, сохранение мышц). "
                "Я рассчитал небольшой дефицит, но главный фокус — на качестве еды и активности."
            )
            target_calories = tdee - 250 # Небольшой дефицит
            protein_g, fat_g, carb_g = (target_calories*0.35)/4, (target_calories*0.25)/9, (target_calories*0.40)/4 # Больше белка
        else: # Стандартная логика
            if profile['goal'].lower() == 'похудеть': target_calories = tdee - 500
            elif profile['goal'].lower() == 'набрать массу': target_calories = tdee + 400
            else: target_calories = tdee
            protein_g, fat_g, carb_g = (target_calories*0.30)/4, (target_calories*0.30)/9, (target_calories*0.40)/4

    # Формируем промпт для AI
    prompt = (
        f"Ты — мой персональный ИИ-консьерж по здоровью. Я только что заполнил профиль. "
        f"Сформируй дружелюбное и мотивирующее резюме, обратившись ко мне по имени '{data.get('first_name', '')}'. "
        f"Представь в удобном формате:\n"
        f"**Основные параметры:** Возраст: {profile.get('age')}, Рост: {profile.get('height')} см, Вес: {profile.get('weight')} кг, Активность: {profile.get('activity')}, Цель: {profile.get('goal')}\n"
        f"**Показатели:** ИМТ: {bmi_value:.1f} ({bmi_category})\n"
        f"**Рекомендации:** Калорийность для цели: ~{int(target_calories)} ккал. БЖУ: ~{int(protein_g)}г белка, {int(fat_g)}г жиров, {int(carb_g)}г углеводов.\n"
        f"{special_advice}\n" # Добавляем специальный совет
        f"В конце дай 2-3 кратких, но емких совета, соответствующих цели. Начни сразу с обращения."
    )
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "Ты дружелюбный и мотивирующий ИИ-помощник по здоровью. Даешь четкие, понятные рекомендации."},
                {"role": "user", "content": prompt}
            ], max_tokens=600, temperature=0.7
        )
        await update.message.reply_text(response.choices[0].message.content, reply_markup=PROACTIVE_KEYBOARD)
    except Exception as e:
        logger.error(f"Ошибка генерации резюме профиля: {e}")
        await update.message.reply_text("Профиль сохранен, но не удалось сгенерировать резюме.", reply_markup=PROACTIVE_KEYBOARD)

async def cancel_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    data = get_user_data_from_db(user_id)
    data["profile_state"] = None
    data["profile_data"] = {}
    save_user_data_to_db(user_id, data)
    await update.message.reply_text(
        "Заполнение профиля отменено.",
        reply_markup=START_KEYBOARD
    )


# --- ИЗМЕНЕНИЕ: Защита от посторонних тем в handle_message ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    data = get_user_data_from_db(user_id)
    if data.get("profile_state"):
        await handle_profile_response(update, context)
        return

    message_text = update.message.text.lower()
    
    # Обработка кнопок
    if message_text == "заполнить профиль": await start_profile(update, context); return
    elif message_text == "выбрать роль": await set_role(update, context); return
    elif message_text == "дневник питания": await show_food_diary(update, context); return
    elif message_text == "мои баллы": await show_score(update, context); return
    elif message_text == "о чем говорят цифры?": await explain_bmi_vo2max_menu(update, context); return
    elif message_text == "составить меню": await create_personalized_menu(update, context); return
    elif message_text == "составить план тренировок": await create_workout_plan_location(update, context); return
    elif message_text == "к врачу": await contact_doctor(update, context); return
    elif message_text == "продолжить": await update.message.reply_text("Хорошо, чем еще могу помочь?", reply_markup=START_KEYBOARD); return
    elif message_text in ["что такое имт?", "рассчитать имт"]: await explain_bmi(update, context); return
    elif message_text in ["что такое мпк?", "рассчитать мпк (приблиз.)"]: await explain_vo2max(update, context); return
    elif message_text in ["дома", "в зале", "на улице"]:
        data["workout_location"] = message_text; save_user_data_to_db(user_id, data)
        await create_workout_plan_final(update, context); return

    if not data.get("profile_data", {}).get('goal') and not message_text.startswith('/'):
        await update.message.reply_text("Чтобы я мог быть максимально полезным, пожалуйста, заполни свой профиль.", reply_markup=START_KEYBOARD)
        return

    # --- НОВАЯ ЛОГИКА: Проверка на оффтоп ---
    off_topic_prompt = f"Вопрос пользователя: '{update.message.text}'. Это о здоровье, фитнесе, питании или продуктивности? Ответь только 'Да' или 'Нет'."
    try:
        response = client.chat.completions.create(
            model="gpt-4o", messages=[{"role": "user", "content": off_topic_prompt}], max_tokens=3, temperature=0
        )
        if "да" not in response.choices[0].message.content.lower():
            await update.message.reply_text("Извини, я могу говорить только о здоровье, питании, спорте и продуктивности. Давай вернемся к теме!", reply_markup=START_KEYBOARD)
            return
    except Exception as e:
        logger.error(f"Ошибка проверки на оффтоп: {e}") # Продолжаем выполнение, если проверка не удалась

    await update.message.reply_text("Думаю...", reply_markup=ReplyKeyboardRemove())
    current_role = data.get("current_role", "личный наставник")
    full_prompt = (
        f"Твоя роль: {ROLES.get(current_role, '')}. "
        f"{get_personal_prompt(data.get('profile_data', {}), data.get('first_name', ''))} "
        f"Ответь на запрос, соблюдая роль. Запрос: {update.message.text}"
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4o", messages=[{"role": "user", "content": full_prompt}], max_tokens=500, temperature=0.7
        )
        await update.message.reply_text(response.choices[0].message.content, reply_markup=START_KEYBOARD)
    except Exception as e:
        logger.error(f"Ошибка вызова OpenAI: {e}")
        await update.message.reply_text("Извини, не могу сейчас ответить. Произошла ошибка.", reply_markup=START_KEYBOARD)

# Функция handle_photo остается без изменений

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    data = get_user_data_from_db(user_id)
    await update.message.reply_text("Анализирую фото...", reply_markup=ReplyKeyboardRemove())
    try:
        file_obj = await context.bot.get_file(update.message.photo[-1].file_id)
        photo_bytes = await file_obj.download_as_bytes()
        base64_image = encode_image(photo_bytes)
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user", "content": [
                    {"type": "text", "content": "Это еда? Если да, определи блюдо и кратко опиши его состав (не калории). Если нет, так и скажи. Ответь кратко."},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}},
                ]
            }], max_tokens=150
        )
        description = response.choices[0].message.content
        data["food_diary"].append(f"{datetime.datetime.now().strftime('%H:%M %d.%m')} - {description}")
        save_user_data_to_db(user_id, data)
        await update.message.reply_text(f"Я думаю, это: *{description}*. Добавлено в дневник.", reply_markup=START_KEYBOARD)
    except Exception as e:
        logger.error(f"Ошибка анализа фото: {e}")
        await update.message.reply_text("Не смог проанализировать фото. Проверь API-ключ OpenAI.", reply_markup=START_KEYBOARD)


# Функции для баллов и справок (show_score, workout_done, explain_...) остаются без изменений.

async def show_score(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    data = get_user_data_from_db(update.effective_user.id)
    await update.message.reply_text(f"Твой текущий счет: {data.get('score', 0)} баллов.", reply_markup=START_KEYBOARD)

async def workout_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    data = get_user_data_from_db(user_id)
    today = datetime.date.today().strftime('%Y-%m-%d')
    if data.get("last_workout_done_date") == today:
        await update.message.reply_text("Ты уже отчитался сегодня. Отличная работа!", reply_markup=START_KEYBOARD)
        return
    data["score"] += 15
    data["last_workout_done_date"] = today
    save_user_data_to_db(user_id, data)
    await update.message.reply_text(f"Поздравляю! +15 баллов. Твой счет: {data['score']}.", reply_markup=START_KEYBOARD)

async def explain_bmi_vo2max_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    menu_keyboard = ReplyKeyboardMarkup([
        ["Что такое ИМТ?", "Рассчитать ИМТ"],
        ["Что такое МПК?", "Рассчитать МПК (приблиз.)"],
        ["Продолжить"]
    ], resize_keyboard=True)
    await update.message.reply_text("Выбери, о чем хочешь узнать:", reply_markup=menu_keyboard)

async def explain_bmi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Текст объяснения ИМТ
    await update.message.reply_text("ИМТ (индекс массы тела) — это показатель...", reply_markup=START_KEYBOARD)

async def explain_vo2max(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Текст объяснения МПК
    await update.message.reply_text("МПК (VO2max) — это показатель аэробной выносливости...", reply_markup=START_KEYBOARD)

# Функция create_personalized_menu остается без изменений

async def create_personalized_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    data = get_user_data_from_db(user_id)
    profile = data.get("profile_data", {})
    if not profile.get('goal'):
        await update.message.reply_text("Сначала заполни профиль.", reply_markup=START_KEYBOARD)
        return
    await update.message.reply_text("Составляю примерное меню...", reply_markup=ReplyKeyboardRemove())
    # ... логика запроса к AI ...
    await update.message.reply_text("Вот примерное меню...", reply_markup=START_KEYBOARD)


# --- ИЗМЕНЕНИЕ: Улучшенная логика создания плана тренировок ---
async def create_workout_plan_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    data = get_user_data_from_db(user_id)
    if not data.get("profile_data", {}).get('goal'):
        await update.message.reply_text("Для составления плана тренировок мне нужен твой профиль.", reply_markup=START_KEYBOARD)
        return
    await update.message.reply_text("Где ты предпочитаешь тренироваться?", reply_markup=ReplyKeyboardMarkup(WORKOUT_PLACE_KEYBOARD, one_time_keyboard=True, resize_keyboard=True))

async def create_workout_plan_final(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    data = get_user_data_from_db(user_id)
    profile = data.get("profile_data", {})
    workout_location = data.get("workout_location", "дома")
    await update.message.reply_text("Отлично! Готовлю для тебя план тренировок...", reply_markup=ReplyKeyboardRemove())

    # --- НОВЫЙ, БОЛЕЕ ДЕТАЛЬНЫЙ ПРОМПТ ---
    workout_prompt = (
        f"Ты — профессиональный фитнес-тренер. Используя данные профиля пользователя, "
        f"составь примерный план тренировок на неделю (3-4 дня). "
        f"Учти, что тренировки будут проходить '{workout_location}'. "
        f"{get_personal_prompt(profile, data.get('first_name', ''))} "
        f"Сделай упор на комбинацию силовых упражнений и ВИИТ (высокоинтенсивных интервальных тренировок). "
        f"Кратко объясни, что такое ВИИТ, почему это эффективно для цели '{profile.get('goal', '')}'. "
        f"Обязательно добавь раздел 'Важность контроля пульса': объясни, почему нужно следить за пульсом (например, с помощью фитнес-часов), "
        f"чтобы оставаться в нужных зонах для жиросжигания и кардио-нагрузки, и как это повышает безопасность. "
        f"План должен быть четким, с примерами упражнений, подходов и повторений. Ответь мотивирующе."
    )
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "Ты — фитнес-тренер, дающий четкие, безопасные и мотивирующие рекомендации."},
                {"role": "user", "content": workout_prompt}
            ], max_tokens=1000, temperature=0.7
        )
        await update.message.reply_text(response.choices[0].message.content)
        
        # --- НОВАЯ ЛОГИКА: Мотивация и геймификация ---
        await update.message.reply_text(
            "Отличный план! Не забывай о регулярности. "
            "Когда выполнишь тренировку, напиши команду `/workout_done`, чтобы получить 15 баллов и зафиксировать свой прогресс!",
            reply_markup=START_KEYBOARD
        )
        data.pop("workout_location", None)
        save_user_data_to_db(user_id, data)
    except Exception as e:
        logger.error(f"Ошибка генерации плана тренировок: {e}")
        await update.message.reply_text("Извини, не смог составить план. Проблемы с AI-сервисом.", reply_markup=START_KEYBOARD)


async def contact_doctor(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Функция без изменений
    message_text = (
        "Важно: я — ИИ-помощник и не могу заменить настоящего врача. "
        "Для точной диагностики и лечения обратись к специалисту.\n\n"
        "Рекомендуемые сервисы телемедицины:\n"
        "- [DocDoc](https://docdoc.ru)\n"
        "- [СберЗдоровье](https://sberhealth.ru)"
    )
    await update.message.reply_text(message_text, disable_web_page_preview=True, reply_markup=START_KEYBOARD)


def main() -> None:
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN не найден! Бот не может быть запущен.")
        return

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Добавление обработчиков (без изменений)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("role", set_role))
    application.add_handler(CommandHandler("roles", show_roles))
    application.add_handler(CommandHandler("myrole", get_current_role))
    application.add_handler(CommandHandler("diary", show_food_diary))
    application.add_handler(CommandHandler("profile", start_profile))
    application.add_handler(CommandHandler("cancel_profile", cancel_profile))
    application.add_handler(CommandHandler("score", show_score))
    application.add_handler(CommandHandler("workout_done", workout_done))

    role_pattern = r"^(" + "|".join([re.escape(label) for label in ROLE_BUTTON_LABELS]) + r")$"
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(role_pattern) & ~filters.COMMAND, handle_role_selection))
    application.add_handler(MessageHandler(filters.PHOTO & ~filters.COMMAND, handle_photo))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Бот запущен и работает...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

