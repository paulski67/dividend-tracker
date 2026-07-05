from pymongo import MongoClient
import sys
import requests
import time
import logging
import psutil

from utilities.logger import setup_logger
from models.mongo import get_mongo_client
from models.mongo import get_collection
from models.settings import get_api_key
from models.api_utils import verify_database_connection
from models.utils import verify_internet_connection

# =========================================================
# Logging
# =========================================================

setup_logger()
   
logging.info("Starting health check:")   

def run_health_checks():
    # Check Mongo DB is up
    if not verify_database_connection():
        logging.error("Connection to the Mongo DB failed!")
        logging.error("Exiting with error code 1")
        sys.exit(1)
        
    info = get_mongo_client().server_info()

    logging.info(
        f"MongoDB Version: {info['version']}"
    )

    # Check Internet connection
    if not verify_internet_connection():
        logging.error("No internet connection!")
        logging.error("Exiting with error code 2")
        sys.exit(2)      

def report_memory():
    mem = psutil.virtual_memory()

    available_gb = (
        mem.available / (1024 ** 3)
    )

    logging.info(
        f"RAM Used: {mem.percent}%"
    )

    logging.info(
        f"Available RAM: "
        f"{available_gb:.2f} GB"
    )


    if mem.percent > 90 or available_gb < 0.25:

        logging.warning(
            f"LOW MEMORY: "
            f"{available_gb:.2f} GB available"
        )

        return False

def report_top_memory_consumers():

    processes = []

    for proc in psutil.process_iter(
        ['pid', 'name', 'memory_info']
    ):

        try:

            mb = proc.info[
                'memory_info'
            ].rss / 1024 / 1024

            processes.append(
                (
                    mb,
                    proc.info['name']
                )
            )

        except:
            pass

    for mb, name in sorted(
        processes,
        reverse=True
    )[:10]:

        logging.info(
            f"{name}: {mb:.0f} MB"
        )

#### start
run_health_checks()
report_memory()

logging.info("Health checks complete")
sys.exit(0)