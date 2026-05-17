import os
import sys

import requests
from dotenv import load_dotenv


MESSAGE = "✅ Trading Alert AI conectado correctamente."


def main() -> int:
    load_dotenv()

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    missing = [
        name
        for name, value in (
            ("TELEGRAM_BOT_TOKEN", bot_token),
            ("TELEGRAM_CHAT_ID", chat_id),
        )
        if not value
    ]

    if missing:
        print(
            "Error: faltan variables requeridas en el archivo .env: "
            + ", ".join(missing),
            file=sys.stderr,
        )
        return 1

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": MESSAGE}

    try:
        response = requests.post(url, data=payload, timeout=10)
        response.raise_for_status()
        result = response.json()
    except requests.exceptions.RequestException:
        print(
            "Error: no se pudo enviar el mensaje a Telegram. "
            "Revisa tu token, chat_id o conexión.",
            file=sys.stderr,
        )
        return 1
    except ValueError:
        print(
            "Error: Telegram respondió con un formato inesperado.",
            file=sys.stderr,
        )
        return 1

    if not result.get("ok"):
        print(
            "Error: Telegram no confirmó el envío del mensaje.",
            file=sys.stderr,
        )
        return 1

    print("Mensaje enviado correctamente a Telegram.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
