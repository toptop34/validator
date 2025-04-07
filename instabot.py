import json
import time
import traceback
import logging
from typing import Any, Dict, List, Optional
from instagrapi import Client
from instagrapi.exceptions import ClientError, LoginRequired
from requests.exceptions import RetryError

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def load_settings() -> Optional[Dict[str, Any]]:
    try:
        with open("settings.json", "r", encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError:
        logger.error("Файл настроек не найден.")
    except json.JSONDecodeError:
        logger.error("Ошибка декодирования файла настроек.")
    except Exception as e:
        logger.error(f"Ошибка при загрузке настроек: {e}")
    return None

cl = Client()
cl.delay_range = [3, 6]  # Случайные задержки от 3 до 6 секунд

def load_cookies() -> bool:
    try:
        cl.load_settings('cookies.json')
        logger.info("Куки успешно загружены из файла")
        return True
    except FileNotFoundError:
        logger.warning("Файл cookies.json не найден.")
    except Exception as e:
        logger.warning(f"Не удалось загрузить куки: {e}")
    return False

def save_cookies() -> None:
    try:
        cl.dump_settings('cookies.json')
        logger.info("Куки успешно сохранены в файл")
    except Exception as e:
        logger.error(f"Ошибка при сохранении куков: {e}")

def login_with_credentials() -> None:
    settings = load_settings()
    if not settings:
        logger.error("Не удалось загрузить настройки для авторизации")
        raise ValueError("Settings not loaded")

    try:
        logger.info("Начинаю авторизацию с логином и паролем")
        cl.login(settings["instagram_username"], settings["instagram_password"])
        logger.info(f"Успешно авторизован как {settings['instagram_username']}")
        save_cookies()
    except ClientError as e:
        logger.error(f"Ошибка при авторизации с логином и паролем: {e}")
        raise
    except Exception as e:
        logger.error(f"Неизвестная ошибка при авторизации: {e}")
        raise

def initialize_login() -> None:
    global cl
    if load_cookies():
        try:
            logger.info("Проверяю валидность сессии с использованием куков")
            cl.get_timeline_feed()
            logger.info("Успешно авторизован с использованием куков")
        except (ClientError, LoginRequired) as e:
            logger.warning(f"Сессия с куками недействительна: {e}")
            login_with_credentials()
    else:
        login_with_credentials()

def get_all_comments(media_id: str) -> List[Any]:
    comments_data = []
    output_file = f"comments_{media_id}.json"

    logger.info(f"🚀 ЗАГРУЗКА КОММЕНТАРИЕВ ДЛЯ ПОСТА {media_id}")

    try:
        media_info = cl.media_info(media_id).model_dump()  # Исправлено на model_dump()
        comment_count = media_info.get('comment_count', 0)
        logger.info(f"ℹ Всего комментариев: {comment_count}")

        if comment_count == 0:
            logger.info("ℹ Нет комментариев для загрузки")
            return []

        csrf_token = cl.private.cookies.get("csrftoken")
        headers = {
            "X-CSRFToken": csrf_token,
            "X-IG-App-ID": "1217981644879628",
            "Referer": f"https://www.instagram.com/p/{media_info['code']}/"
        }

        loaded_count = 0
        next_max_id: Optional[str] = None
        retry_count = 0
        max_retries = 3

        while loaded_count < min(comment_count, 2000) and retry_count < max_retries:
            try:
                params = {
                    "can_support_threading": "true",
                    "permalink_enabled": "false",
                    "count": 20  # Начальный размер порции
                }

                if next_max_id:
                    params["max_id"] = next_max_id

                response = cl.private_request(
                    f"media/{media_id}/comments/",
                    params=params,
                    headers=headers
                )

                comments = response.get("comments", [])
                if not comments:
                    logger.info("ℹ Больше комментариев не найдено")
                    break

                valid_comments = [c for c in comments if isinstance(c, dict)]
                comments_data.extend(valid_comments)
                loaded_count += len(valid_comments)

                if valid_comments:
                    next_max_id = valid_comments[-1].get("pk")
                else:
                    next_max_id = None

                logger.info(f"✅ Загружено: {len(valid_comments)} | Всего: {loaded_count}/{comment_count}")

                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(comments_data, f, ensure_ascii=False, indent=2)

                current_delay = min(10, 5 + loaded_count // 100)
                logger.info(f"⏳ Пауза {current_delay} сек...")
                time.sleep(current_delay)

                retry_count = 0

            except RetryError as e:
                retry_count += 1
                error_msg = str(e)[:200]
                logger.warning(f"⚠ Ошибка ({retry_count}/{max_retries}): {error_msg}")

                if retry_count >= max_retries:
                    logger.error("⛔ Достигнуто максимальное количество попыток")
                    break

                error_delay = min(30, 10 * retry_count)
                logger.info(f"⏳ Повтор через {error_delay} сек...")
                time.sleep(error_delay)
                continue
            except ClientError as e:
                logger.error(f"⛔ Критическая ошибка: {e}")
                break

    except ClientError as e:
        logger.error(f"⛔ Критическая ошибка: {e}")
        traceback.print_exc()

    try:
        with open(output_file, 'w', encoding="utf-8") as f:
            json.dump(comments_data, f, ensure_ascii=False, indent=2)
        logger.info(f"💾 СОХРАНЕНО: {len(comments_data)} комментариев")
        logger.info(f"📂 Файл: {output_file}")
    except Exception as e:
        logger.error(f"⛔ Ошибка сохранения: {e}")

    logger.info(f"🏁 ЗАВЕРШЕНО: {len(comments_data)}/{comment_count} комментариев")

    return [c["pk"] for c in comments_data if isinstance(c, dict) and "pk" in c]

def main_loop() -> None:
    initialize_login()

    while True:
        settings = load_settings()
        if not settings:
            logger.error("Ошибка загрузки настроек. Ожидание...")
            time.sleep(10)
            continue

        logger.info("Начинаю проверку постов...")
        for post_url in settings["posts"]:
            media_id = cl.media_pk_from_url(post_url)
            get_all_comments(media_id)
            time.sleep(10)

        logger.info(f"Ожидание {settings.get('check_interval', 60)} сек...")
        time.sleep(settings.get("check_interval", 60))

if __name__ == "__main__":
    try:
        main_loop()
    except KeyboardInterrupt:
        logger.info("Бот остановлен")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        traceback.print_exc()
