from __future__ import annotations

import logging
import sys

from telegram import Update

from bot.app import build_application
from bot.config import load_settings

logging.basicConfig(
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def main() -> None:
    try:
        settings = load_settings()
    except RuntimeError as exc:
        logger.error("%s", exc)
        sys.exit(1)

    app = build_application(settings)
    logger.info("Bot iniciado; polling a cada %s s", settings.poll_interval_seconds)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
