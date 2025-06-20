
import os
from bot import app, main  # Замените your_bot_file на имя вашего файла

if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    main()  # Запуск вебхука бота
