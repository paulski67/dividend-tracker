import logging
import requests
from datetime import datetime
from pathlib import Path
from models.settings import get_health_check_config

def verify_internet_connection():

    try:

        settings = get_health_check_config()

        response = requests.get(
            settings["url"],
            timeout=settings["timeout"]
        )

        response.raise_for_status()

        logging.info(
            "Internet connection successful"
        )

        return True

    except Exception as e:

        logging.error(
            f"Internet connection failed: {e}"
        )

        return False
        
  

def get_timestamped_file(directory, base_name, extension="txt"):

    timestamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    output_dir = Path(directory)
    output_dir.mkdir(exist_ok=True)

    return (
        output_dir /
        f"{base_name}_{timestamp}.{extension}"
    )

def safe_int(value, default=0):

    if value in [None, "", "None", "N/A"]:
        return default

    try:
        return int(value)

    except Exception:
        return default    
    
def safe_float(value, default=0.0):

    if value in [None, "", "None", "N/A"]:
        return default

    try:
        return float(value)

    except Exception:
        return default
        
def safe_percent(value, default=0.0):

    value = safe_float(value, default)

    if value > 1:
        return value / 100

    return value

def safe_date(value):

    if value in [None, "", "None", "N/A"]:
        return None

    try:
        return datetime.strptime(
            value,
            "%Y-%m-%d"
        )

    except Exception:

        return None    