from aiogram.types import callback_query

import config
import logging
import sqlite3
from datetime import datetime, timedelta
import asyncio

from aiogram import Bot, Dispatcher, executor, types
from aiogram.types.message import ContentType

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Инициализация бота и диспетчера
bot = Bot(token=config.TOKEN)
dp = Dispatcher(bot)

# Подключение к базе данных
conn = sqlite3.connect('subscriptions.db')
cursor = conn.cursor()

# Создание таблицы подписок, если она не существует
cursor.execute('''CREATE TABLE IF NOT EXISTS subscriptions
                  (user_id INTEGER PRIMARY KEY, username TEXT, expiry_date TEXT, transaction_id TEXT, notification_sent INTEGER)''')
conn.commit()

# Настройки валюты
CURRENCY = "SOL"

# Цены подписок на разные сроки (время указано в секундах для удобства тестирования)
SUBSCRIPTION_PRICES = {
    '10_seconds': types.LabeledPrice(label="Subscription for 10 seconds", amount=10 * 100),
    '20_seconds': types.LabeledPrice(label="Subscription for 20 seconds", amount=20 * 100),
    '30_seconds': types.LabeledPrice(label="Subscription for 30 seconds", amount=30 * 100),
    '60_seconds': types.LabeledPrice(label="Subscription for 60 seconds", amount=60 * 100)
}

# Список доступных команд
AVAILABLE_COMMANDS = [
    "/start - start the bot",
    "/help - get the list of available commands",
    "/subscribe - activate a subscription",
    "/subscription_status - check subscription status"
]

# Обработчик команды /help для отправки списка доступных команд
@dp.message_handler(commands=['help'])
async def help_command(message: types.Message):
    # Формирование списка доступных команд
    help_message = "Here are the available commands:\n"
    help_message += "\n".join(AVAILABLE_COMMANDS)

    # Отправка списка доступных команд
    await message.answer(help_message)


# Функция для добавления новой подписки в базу данных
def add_subscription(user_id, username, expiry_date, transaction_id):
    cursor.execute("INSERT OR REPLACE INTO subscriptions (user_id, username, expiry_date, transaction_id, notification_sent) VALUES (?, ?, ?, ?, ?)",
                   (user_id, username, expiry_date, transaction_id, 0))  # Устанавливаем значение notification_sent в 0 (не отправлено)
    conn.commit()


# Функция для проверки срока истечения подписки
async def check_subscription_expiry():
    current_date = datetime.now()
    cursor.execute("SELECT user_id, username, expiry_date FROM subscriptions")
    for user_id, username, expiry_date in cursor.fetchall():
        if datetime.strptime(expiry_date, "%Y-%m-%d %H:%M:%S") <= current_date:
            yield user_id


# Функция для отправки уведомления об истечении подписки
async def send_subscription_expiry_notification(user_id):
    await bot.send_message(user_id, "Your subscription has expired. You can /subscribe again at any time")
    cursor.execute("UPDATE subscriptions SET notification_sent = ? WHERE user_id = ?", (1, user_id))  # Устанавливаем значение notification_sent в 1 (отправлено)
    conn.commit()


# Функция для проверки срока истечения подписки
async def check_subscription_expiry_task():
    while True:
        async for user_id in check_subscription_expiry():
            # Проверяем, было ли уже отправлено уведомление
            cursor.execute("SELECT notification_sent FROM subscriptions WHERE user_id = ?", (user_id,))
            notification_sent = cursor.fetchone()[0]
            if not notification_sent:
                await send_subscription_expiry_notification(user_id)
        await asyncio.sleep(60)  # Проверяем каждую минуту



# Обработчик команды /start для приветствия и отправки списка команд
@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    # Формирование приветственного сообщения и списка команд
    start_message = "Welcome to our subscription service!\n"
    start_message += "Here are the available commands:\n"
    start_message += "\n".join(AVAILABLE_COMMANDS)

    # Отправка приветственного сообщения и списка команд
    await message.answer(start_message)


# Обработчик команды /subscribe для выбора срока подписки
@dp.message_handler(commands=['subscribe'])
async def subscribe(message: types.Message):
    # Создание кнопок для выбора срока подписки
    markup = types.InlineKeyboardMarkup()
    for subscription_id, price in SUBSCRIPTION_PRICES.items():
        button = types.InlineKeyboardButton(f"{price.label} - {price.amount // 100} {CURRENCY}",
                                             callback_data=subscription_id)
        markup.add(button)


    # Отправка сообщения с кнопками выбора срока подписки
    await message.answer("Choose the subscription period:", reply_markup=markup)

# Обработчик команды /subscription_status для проверки статуса подписки пользователя
@dp.message_handler(commands=['subscription_status'])
async def check_subscription_status(message: types.Message):
    # Проверяем, есть ли у пользователя активная подписка
    cursor.execute("SELECT expiry_date FROM subscriptions WHERE user_id = ? AND expiry_date > ?",
                   (message.from_user.id, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    subscription_info = cursor.fetchone()

    if subscription_info:
        expiry_date = subscription_info[0]
        # Отправляем информацию о подписке и её сроке истечения
        await message.answer(f"You have an active subscription. Expiry date: {expiry_date}")
    else:
        # Отправляем информацию о том, что у пользователя нет активной подписки
        await message.answer("You don't have an active subscription.")


# Инициализация словаря для отслеживания выбранных подписок по идентификатору пользователя
user_subscriptions = {}

# Обработчик нажатия на кнопку выбора срока подписки
@dp.callback_query_handler(lambda c: c.data in SUBSCRIPTION_PRICES.keys())
async def process_subscription_choice(callback_query: types.CallbackQuery):
    # Получение информации о выбранной подписке
    chosen_subscription = SUBSCRIPTION_PRICES[callback_query.data]

    # Сохранение выбранной подписки в словаре
    user_subscriptions[callback_query.from_user.id] = chosen_subscription.label

    # Создание кнопки для подтверждения оплаты
    confirm_button = types.InlineKeyboardButton("Confirm payment", callback_data="confirm_payment")

    # Отправка сообщения с информацией о подписке и кнопкой для подтверждения оплаты
    await bot.send_message(callback_query.from_user.id,
                           f"🔔 Subscription Activation 🔔\n\n"
                           f"To activate your subscription, please make a payment of {SUBSCRIPTION_PRICES[callback_query.data]}"
                           " SOL to the following address:\n"
                           "GURQMAvEJgaHsot3Pb5QkbhMtAaboN7mYtNNZm6eQoqp\n\n"
                           "Note:\n"
                           "- If the amount is less than required, the verification will NOT pass.\n"
                           "- Any amount over will be considered as a donation and is non-refundable.\n\n"
                           "Once done, press 'Confirm payment' or return if you wish to cancel.",
                           reply_markup=types.InlineKeyboardMarkup().add(confirm_button))


# Обработчик нажатия на кнопку подтверждения оплаты
@dp.callback_query_handler(lambda c: c.data == "confirm_payment")
async def process_confirm_payment(callback_query: types.CallbackQuery):
    await bot.answer_callback_query(callback_query.id)
    await bot.send_message(callback_query.from_user.id, "Payment confirmed. Please provide your wallet address.")


# Обработчик для получения адреса кошелька после оплаты
@dp.message_handler(content_types=ContentType.TEXT)
async def handle_wallet_address(message: types.Message):
    # Проверяем, была ли выполнена оплата
    if message.text.strip() == 'qwerty':
        # Получение выбранной пользователем подписки из словаря
        subscription_label = user_subscriptions.get(message.from_user.id)

        # Проверяем, выбрал ли пользователь подписку
        if subscription_label:
            # Определение выбранного пользователем срока подписки
            chosen_subscription_id = [key for key, value in SUBSCRIPTION_PRICES.items() if value.label == subscription_label][0]

            # Определение срока подписки в секундах
            subscription_duration = int(chosen_subscription_id.split('_')[0])

            # Определение идентификатора транзакции
            transaction_id = '12345'

            # Проверка транзакции
            if await check_transaction(transaction_id, message.text.strip()):
                # Получение текущей даты и времени
                current_date = datetime.now()

                # Вычисление даты истечения подписки
                expiry_date = current_date + timedelta(seconds=subscription_duration)
                expiry_date_str = expiry_date.strftime("%Y-%m-%d %H:%M:%S")

                # Добавление подписки в базу данных
                add_subscription(message.from_user.id, message.from_user.username, expiry_date_str, transaction_id)

                # Отправка подтверждения о покупке
                await bot.send_message(message.chat.id, "Payment confirmed. Thank you for subscribing!")
            else:
                # Отправка сообщения об ошибке при проверке транзакции
                await bot.send_message(message.chat.id, "Payment verification failed. Please try again later.")
        else:
            # Отправка сообщения о необходимости выбора подписки
            await bot.send_message(message.chat.id, "Please reply to the message with subscription options.")
    else:
        # Проверяем, существует ли у пользователя активная подписка
        cursor.execute("SELECT user_id FROM subscriptions WHERE user_id = ? AND expiry_date > ?",
                       (message.from_user.id, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        subscription_exists = cursor.fetchone()
        if subscription_exists:
            # Отправка сообщения о наличии активной подписки
            await bot.send_message(message.chat.id, "You already have an active subscription.")
        else:
            # Отправка сообщения об ошибке при неверном кошельке
            await bot.send_message(message.chat.id, "Invalid wallet address. Please try again.")
async def check_transaction(transaction_id, wallet_address):
    # Здесь должна быть ваша логика проверки транзакции
    # В данной заглушке мы просто сравниваем номер кошелька с номером, указанным в сообщении
    expected_wallet_address = 'qwerty'
    if wallet_address == expected_wallet_address:
        return True  # Транзакция прошла успешно
    else:
        return False  # Транзакция не прошла


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(check_subscription_expiry_task())
    executor.start_polling(dp, skip_updates=False)
