import os
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)
from flask import Flask, Response

# Конфигурация
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")
PRODUCTS_CHANNEL = "@ShopProductsgg"
ORDERS_CHANNEL = "@ShopOrdersgg"
PRODUCTS_FILE = "products.json"
ADMINS_FILE = "admins.json"
PHOTO, DESCRIPTION, PRICE, EMPLOYEE_ID, EMPLOYEE_ROLE, DELETE_PRODUCT, DELETE_EMPLOYEE = range(7)

# Flask для обработки пинга
app = Flask(__name__)

# Валидация JSON
def validate_products(products):
    if not isinstance(products, list):
        return False
    required_fields = ["id", "name", "price", "description"]
    for product in products:
        if not all(field in product for field in required_fields):
            return False
        if not isinstance(product["id"], str) or not isinstance(product["name"], str):
            return False
        try:
            float(product["price"])
        except (ValueError, TypeError):
            return False
    return True

def validate_admins(admins):
    if not isinstance(admins, dict) or "admins" not in admins:
        return False
    admins_list = admins["admins"]
    if not isinstance(admins_list, list):
        return False
    required_fields = ["user_id", "role", "permissions"]
    for admin in admins_list:
        if not all(field in admin for field in required_fields):
            return False
        if not isinstance(admin["user_id"], (int, str)) or not isinstance(admin["role"], str):
            return False
        if not isinstance(admin["permissions"], list):
            return False
    return True

# Работа с JSON
def load_products():
    try:
        with open(PRODUCTS_FILE, "r") as f:
            products = json.load(f)
            if not validate_products(products):
                print("Invalid products.json, creating empty")
                products = []
                save_products(products)
            return products
    except (FileNotFoundError, json.JSONDecodeError):
        products = []
        save_products(products)
        return products

def save_products(products):
    with open(PRODUCTS_FILE, "w") as f:
        json.dump(products, f, indent=2)

def load_admins():
    try:
        with open(ADMINS_FILE, "r") as f:
            admins = json.load(f)
            if not validate_admins(admins):
                print("Invalid admins.json, creating default")
                admins = [{"user_id": 7652639453, "role": "admin", "permissions": ["all"]}]
                save_admins(admins)
            return admins["admins"]
    except (FileNotFoundError, json.JSONDecodeError):
        admins = [{"user_id": 7652639453, "role": "admin", "permissions": ["all"]}]
        save_admins(admins)
        return admins

def save_admins(admins):
    with open(ADMINS_FILE, "w") as f:
        json.dump({"admins": admins}, f, indent=2)

async def send_json_files(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    for file_path in [PRODUCTS_FILE, ADMINS_FILE]:
        if os.path.exists(file_path):
            with open(file_path, "rb") as f:
                await context.bot.send_document(
                    chat_id=user_id,
                    document=f,
                    filename=os.path.basename(file_path)
                )

async def sync_products_with_channel(context: ContextTypes.DEFAULT_TYPE):
    products = load_products()
    for product in products:
        if "message_id" not in product or not product["message_id"]:
            text = f"<b>Название:</b> {product['name']}\n<b>Цена:</b> {product['price']} руб.\n<b>Описание:</b> {product['description']}"
            keyboard = [[InlineKeyboardButton("Заказать", callback_data=f"order_{product['id']}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            if product.get("photo_id"):
                message = await context.bot.send_photo(
                    chat_id=PRODUCTS_CHANNEL,
                    photo=product["photo_id"],
                    caption=text,
                    reply_markup=reply_markup,
                    parse_mode="HTML"
                )
            else:
                message = await context.bot.send_message(
                    chat_id=PRODUCTS_CHANNEL,
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode="HTML"
                )
            product["message_id"] = message.message_id
    save_products(products)

# Проверка прав
def check_permission(user_id, required_permission):
    admins = load_admins()
    for admin in admins:
        if admin["user_id"] == user_id:
            return required_permission in admin["permissions"] or "all" in admin["permissions"]
    return False

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Заказ", callback_data="role_order")],
        [InlineKeyboardButton("Админ", callback_data="role_admin")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Добро пожаловать! Выберите роль:", reply_markup=reply_markup)

# Команда /upload_json
async def upload_json(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not check_permission(user_id, "all"):
        await update.message.reply_text("Только админ может загружать JSON!")
        return
    if not update.message.document:
        await update.message.reply_text("Отправьте JSON-файл (products.json или admins.json):")
        return
    file = await update.message.document.get_file()
    file_name = update.message.document.file_name
    if file_name not in ["products.json", "admins.json"]:
        await update.message.reply_text("Неверный файл! Отправьте products.json или admins.json.")
        return
    file_path = f"temp_{file_name}"
    await file.download_to_drive(file_path)
    try:
        with open(file_path, "r") as f:
            data = json.load(f)
        if file_name == "products.json" and validate_products(data):
            save_products(data)
            await sync_products_with_channel(context)
            await send_json_files(update, context, user_id)
            await update.message.reply_text("products.json загружен и синхронизирован!")
        elif file_name == "admins.json" and validate_admins(data):
            save_admins(data["admins"])
            await send_json_files(update, context, user_id)
            await update.message.reply_text("admins.json загружен!")
        else:
            await update.message.reply_text("Некорректная структура JSON!")
    except (json.JSONDecodeError, Exception) as e:
        await update.message.reply_text(f"Ошибка: {str(e)}")
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)

# Обработчик кнопок
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if data == "role_order":
        if not check_permission(user_id, "orders"):
            await query.message.reply_text("Нет доступа к заказам!")
            return
        await query.message.reply_text("Выберите заказ для обработки (в разработке).")

    elif data == "role_admin":
        if not check_permission(user_id, "all"):
            await query.message.reply_text("Только админ может управлять магазином!")
            return
        keyboard = [
            [InlineKeyboardButton("Добавить товар", callback_data="add_product")],
            [InlineKeyboardButton("Удалить товар", callback_data="delete_product")],
            [InlineKeyboardButton("Добавить сотрудника", callback_data="add_employee")],
            [InlineKeyboardButton("Удалить сотрудника", callback_data="remove_employee")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text("Меню админа:", reply_markup=reply_markup)

    elif data == "add_product":
        await query.message.reply_text("Отправьте фото товара (или напишите 'без фото'):")
        return PHOTO

    elif data == "delete_product":
        products = load_products()
        if not products:
            await query.message.reply_text("Товаров нет!")
            return ConversationHandler.END
        keyboard = [[InlineKeyboardButton(p["name"], callback_data=f"del_product_{p['id']}")] for p in products]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text("Выберите товар для удаления:", reply_markup=reply_markup)
        return DELETE_PRODUCT

    elif data == "add_employee":
        await query.message.reply_text("Введите Telegram ID или @username:")
        return EMPLOYEE_ID

    elif data == "remove_employee":
        admins = load_admins()
        if len(admins) <= 1:
            await query.message.reply_text("Нельзя удалить последнего админа!")
            return ConversationHandler.END
        keyboard = [[InlineKeyboardButton(str(a["user_id"]), callback_data=f"del_employee_{a['user_id']}")] for a in admins]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text("Выберите сотрудника для удаления:", reply_markup=reply_markup)
        return DELETE_EMPLOYEE

    elif data.startswith("order_"):
        product_id = data.split("_")[1]
        products = load_products()
        product = next((p for p in products if p["id"] == product_id), None)
        if not product:
            await query.message.reply_text("Товар не найден!")
            return
        text = f"<b>Название:</b> {product['name']}\n<b>Цена:</b> {product['price']} руб.\n<b>Описание:</b> {product['description']}"
        if product.get("photo_id"):
            await context.bot.send_photo(chat_id=user_id, photo=product["photo_id"], caption=text, parse_mode="HTML")
        else:
            await context.bot.send_message(chat_id=user_id, text=text, parse_mode="HTML")

        # Генерация уникального ID заказа
        order_id = len(load_products()) + 1
        username = query.from_user.username or "неизвестен"
        order_text = f"Заказ #{order_id} | Товар: {product['name']} | Клиент: @{username} | Статус: Новый"
        order_message = await context.bot.send_message(chat_id=ORDERS_CHANNEL, text=order_text)

        # Сохранение информации о заказе
        if "orders" not in context.bot_data:
            context.bot_data["orders"] = {}
        context.bot_data["orders"][order_id] = {
            "message_id": order_message.message_id,
            "buyer_id": query.from_user.id,
            "product_name": product['name'],
            "product_price": product['price'],
            "username": username
        }

        admins = load_admins()
        for admin in admins:
            notify_text = f"Новый заказ #{order_id}: Товар: {product['name']}, Цена: {product['price']} руб., Клиент: @{username}"
            keyboard = [
                [InlineKeyboardButton("Взять в обработку", callback_data=f"status_processing_{order_id}")],
                [InlineKeyboardButton("Отметить как продан", callback_data=f"status_sold_{order_id}")],
                [InlineKeyboardButton("Связаться с клиентом", url=f"tg://user?id={query.from_user.id}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await context.bot.send_message(
                chat_id=admin["user_id"],
                text=notify_text,
                reply_markup=reply_markup,
                parse_mode="HTML"
            )
        await query.message.reply_text("Заказ оформлен! С вами свяжутся.")

    elif data.startswith("status_processing_"):
        order_id = int(data.split("_")[2])
        if not check_permission(user_id, "orders") and not check_permission(user_id, "all"):
            await query.message.reply_text("Нет прав для изменения статуса!")
            return

        if "orders" in context.bot_data and order_id in context.bot_data["orders"]:
            order_info = context.bot_data["orders"][order_id]
            message_id = order_info["message_id"]
            buyer_id = order_info["buyer_id"]
            product_name = order_info["product_name"]
            username = order_info["username"]

            order_text = f"Заказ #{order_id} | Товар: {product_name} | Клиент: @{username} | Статус: В обработке"
            try:
                await context.bot.edit_message_text(
                    chat_id=ORDERS_CHANNEL,
                    message_id=message_id,
                    text=order_text
                )
            except Exception as e:
                print(f"Ошибка обновления сообщения: {e}")

            # Уведомление клиента
            try:
                await context.bot.send_message(
                    chat_id=buyer_id,
                    text=f"Ваш заказ #{order_id} в обработке!"
                )
            except Exception as e:
                print(f"Ошибка отправки уведомления клиенту: {e}")

            await query.message.reply_text(f"Заказ #{order_id} взят в обработку!")
        else:
            await query.message.reply_text("Заказ не найден!")

    elif data.startswith("status_sold_"):
        order_id = int(data.split("_")[2])
        if not check_permission(user_id, "orders") and not check_permission(user_id, "all"):
            await query.message.reply_text("Нет прав для изменения статуса!")
            return

        if "orders" in context.bot_data and order_id in context.bot_data["orders"]:
            order_info = context.bot_data["orders"][order_id]
            message_id = order_info["message_id"]
            buyer_id = order_info["buyer_id"]
            product_name = order_info["product_name"]
            username = order_info["username"]

            order_text = f"Заказ #{order_id} | Товар: {product_name} | Клиент: @{username} | Статус: Продан"
            try:
                await context.bot.edit_message_text(
                    chat_id=ORDERS_CHANNEL,
                    message_id=message_id,
                    text=order_text
                )
            except Exception as e:
                print(f"Ошибка обновления сообщения: {e}")

            # Уведомление клиента
            try:
                await context.bot.send_message(
                    chat_id=buyer_id,
                    text=f"Ваш заказ #{order_id} продан! Спасибо за покупку!"
                )
            except Exception as e:
                print(f"Ошибка отправки уведомления клиенту: {e}")

            await query.message.reply_text(f"Заказ #{order_id} отмечен как продан!")
        else:
            await query.message.reply_text("Заказ не найден!")

    elif data.startswith("publish_"):
        product_id = data.split("_")[1]
        product = context.user_data.get("product")
        if not product or product["id"] != product_id:
            await query.message.reply_text("Ошибка, товар не найден!")
            return
        text = f"<b>Название:</b> {product['name']}\n<b>Цена:</b> {product['price']} руб.\n<b>Описание:</b> {product['description']}"
        keyboard = [[InlineKeyboardButton("Заказать", callback_data=f"order_{product_id}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        if product["photo_id"]:
            message = await context.bot.send_photo(
                chat_id=PRODUCTS_CHANNEL,
                photo=product["photo_id"],
                caption=text,
                reply_markup=reply_markup,
                parse_mode="HTML"
            )
        else:
            message = await context.bot.send_message(
                chat_id=PRODUCTS_CHANNEL,
                text=text,
                reply_markup=reply_markup,
                parse_mode="HTML"
            )
        product["message_id"] = message.message_id
        products = load_products()
        products.append(product)
        save_products(products)
        await send_json_files(query, context, user_id)
        await query.message.reply_text("Товар опубликован в @ShopProductsgg!")
        context.user_data.clear()

    elif data.startswith("del_product_"):
        product_id = data.split("_")[2]
        products = load_products()
        product = next((p for p in products if p["id"] == product_id), None)
        if not product:
            await query.message.reply_text("Товар не найден!")
            return ConversationHandler.END
        try:
            if product.get("message_id"):
                await context.bot.delete_message(chat_id=PRODUCTS_CHANNEL, message_id=product["message_id"])
        except Exception as e:
            print(f"Ошибка удаления сообщения: {e}")
        products = [p for p in products if p["id"] != product_id]
        save_products(products)
        await send_json_files(query, context, user_id)
        await query.message.reply_text(f"Товар {product['name']} удалён!")
        return ConversationHandler.END

    elif data.startswith("del_employee_"):
        employee_id = data.split("_")[2]
        admins = load_admins()
        if len(admins) <= 1:
            await query.message.reply_text("Нельзя удалить последнего админа!")
            return ConversationHandler.END
        # Конвертируем в строку для корректного сравнения
        try:
            employee_id_int = int(employee_id)
            admins = [a for a in admins if a["user_id"] != employee_id_int and str(a["user_id"]) != employee_id]
        except ValueError:
            admins = [a for a in admins if str(a["user_id"]) != employee_id]
        save_admins(admins)
        await send_json_files(query, context, user_id)
        await query.message.reply_text(f"Сотрудник {employee_id} удалён!")
        return ConversationHandler.END

# Обработчик добавления товара
async def add_product_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not check_permission(user_id, "all"):
        await update.message.reply_text("Только админ может добавлять товары!")
        return ConversationHandler.END
    if update.message.text and update.message.text.lower() == "без фото":
        context.user_data["photo_id"] = None
    elif update.message.photo:
        context.user_data["photo_id"] = update.message.photo[-1].file_id
    else:
        await update.message.reply_text("Отправьте фото или напишите 'без фото':")
        return PHOTO
    await update.message.reply_text("Введите описание товара:")
    return DESCRIPTION

async def add_product_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["description"] = update.message.text
    await update.message.reply_text("Введите цену товара (в рублях):")
    return PRICE

async def add_product_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    try:
        price = float(update.message.text)
        context.user_data["price"] = price
    except ValueError:
        await update.message.reply_text("Введите корректную цену (число):")
        return PRICE
    products = load_products()
    product_id = f"{len(products) + 1:03d}"
    name = "Товар #" + product_id
    description = context.user_data["description"]
    photo_id = context.user_data.get("photo_id")
    text = f"<b>Название:</b> {name}\n<b>Цена:</b> {price} руб.\n<b>Описание:</b> {description}"
    keyboard = [
        [InlineKeyboardButton("Опубликовать", callback_data=f"publish_{product_id}")],
        [InlineKeyboardButton("Редактировать", callback_data="add_product")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    if photo_id:
        await context.bot.send_photo(
            chat_id=user_id,
            photo=photo_id,
            caption=text,
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
    else:
        await context.bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
    context.user_data["product"] = {
        "id": product_id,
        "name": name,
        "price": price,
        "description": description,
        "photo_id": photo_id
    }
    return ConversationHandler.END

# Обработчик добавления сотрудника
async def add_employee_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not check_permission(user_id, "all"):
        await update.message.reply_text("Только админ может добавлять сотрудников!")
        return ConversationHandler.END
    text = update.message.text
    if text.startswith("@"):
        context.user_data["employee_id"] = text
    else:
        try:
            context.user_data["employee_id"] = int(text)
        except ValueError:
            await update.message.reply_text("Введите корректный ID или @username:")
            return EMPLOYEE_ID
    keyboard = [
        [InlineKeyboardButton("Админ", callback_data="role_admin_employee")],
        [InlineKeyboardButton("Продавец", callback_data="role_seller_employee")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Выберите роль сотрудника:", reply_markup=reply_markup)
    return EMPLOYEE_ROLE

async def add_employee_role(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    role = "admin" if query.data == "role_admin_employee" else "seller"
    employee_id = context.user_data["employee_id"]
    permissions = ["all"] if role == "admin" else ["orders"]
    admins = load_admins()

    # Проверяем, не добавлен ли уже такой сотрудник
    for admin in admins:
        if admin["user_id"] == employee_id or str(admin["user_id"]) == str(employee_id):
            await query.message.reply_text("Этот сотрудник уже добавлен!")
            return ConversationHandler.END

    admins.append({"user_id": employee_id, "role": role, "permissions": permissions})
    save_admins(admins)
    await send_json_files(query, context, query.from_user.id)
    await query.message.reply_text(f"Добавлен сотрудник {employee_id} с ролью {role}!")
    return ConversationHandler.END

def main():
    """Запуск бота с вебхуком"""
    application = Application.builder().token(BOT_TOKEN).build()

    # Настройка хендлеров
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("upload_json", upload_json))

    # ConversationHandler для добавления товара
    product_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(button, pattern="^add_product$")],
        states={
            PHOTO: [MessageHandler(filters.PHOTO | filters.TEXT, add_product_photo)],
            DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_product_description)],
            PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_product_price)],
        },
        fallbacks=[CommandHandler("start", start)],
    )
    application.add_handler(product_conv)

    # ConversationHandler для добавления сотрудника
    employee_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(button, pattern="^add_employee$")],
        states={
            EMPLOYEE_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_employee_id)],
            EMPLOYEE_ROLE: [CallbackQueryHandler(add_employee_role, pattern="^role_(admin|seller)_employee$")],
        },
        fallbacks=[CommandHandler("start", start)],
    )
    application.add_handler(employee_conv)

    # ConversationHandler для удаления
    delete_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(button, pattern="^delete_product$"),
            CallbackQueryHandler(button, pattern="^remove_employee$")
        ],
        states={
            DELETE_PRODUCT: [CallbackQueryHandler(button, pattern="^del_product_")],
            DELETE_EMPLOYEE: [CallbackQueryHandler(button, pattern="^del_employee_")]
        },
        fallbacks=[CommandHandler("start", start)],
    )
    application.add_handler(delete_conv)

    # Остальные CallbackQueryHandler
    application.add_handler(CallbackQueryHandler(button))

    # Настройка вебхука
    port = int(os.getenv("PORT", 10000))
    webhook_url = f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME')}/webhook" if os.getenv("RENDER_EXTERNAL_HOSTNAME") else "https://your-render-url.onrender.com/webhook"
    application.run_webhook(listen="0.0.0.0", port=port, url_path="/webhook", webhook_url=webhook_url)

# Эндпоинт для проверки аптайма (пинг от UptimeRobot)
@app.route('/ping', methods=['GET'])
def ping():
    return Response("OK", status=200)
