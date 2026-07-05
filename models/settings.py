from pymongo import MongoClient
import configparser

config = configparser.ConfigParser()
config.read("config/config.ini")   

def get_health_check_config():

    return {
        "url": config.get(
            "health_checks",
            "INTERNET_TEST_URL"
        ),
        "timeout": config.getint(
            "health_checks",
            "REQUEST_TIMEOUT"
        )
    }

def get_api_key():
    return config["api_key"]["alpha_advantage"]

def get_max_payout_ratio():

    return float(
        config["thresholds"][
            "max_payout_ratio"
        ]
    )
    
def get_max_beta():

    return float(
        config["thresholds"][
            "max_beta"
        ]
    )    