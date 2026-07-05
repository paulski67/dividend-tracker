from pymongo import MongoClient
import configparser


config = configparser.ConfigParser()
config.read("config/config.ini")

MONGO_URI = config["mongo"]["host"]

DATABASE_NAME = "dividend_tracker"

client = MongoClient(MONGO_URI)

db = client[DATABASE_NAME]

def get_mongo_client():

    return client
    
def get_collection(collection_name):
    """
    Return Mongo collection reference.
    """

    return db[collection_name]