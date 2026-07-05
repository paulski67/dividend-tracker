import logging
from utilities.logger import setup_logger

from models.mongo import get_mongo_client
from logging.handlers import (
    TimedRotatingFileHandler
)

setup_logger()

def check_api_response(data):

    message = data.get("Note") or data.get("Information")

    if not message:
        return "OK"

    logging.warning(f"API MESSAGE: {message}")

    lower_message = message.lower()

    if (
        "rate limit" in lower_message
        or "call frequency" in lower_message
        or "higher api call frequency" in lower_message
        or "too many requests" in lower_message
    ):

        logging.error("API LIMIT REACHED")
        return "LIMIT_REACHED"

    return "API_MESSAGE"
    
def verify_database_connection():
    
    client = get_mongo_client()
    
    try:

        client.admin.command("ping")

        logging.info(
            "MongoDB connection successful"
        )

        return True

    except Exception as e:

        logging.error(
            "MongoDB connection failed"
        )

        logging.error(e)

        return False