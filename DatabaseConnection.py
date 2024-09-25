import psycopg2
from psycopg2 import sql
from threading import Lock
from dotenv import load_dotenv

load_dotenv()

class DatabaseConnection:
    _instance = None
    _lock = Lock()
    

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(DatabaseConnection, cls).__new__(cls)
                    cls._instance.connection = cls.create_connection()
        return cls._instance

    @staticmethod
    def create_connection():
        return psycopg2.connect(
            user=os.getenv('DB_USER'),
            password=os.getenv('DB_PASSWORD'),
            host="127.0.0.1",
            port="5432",
            database=os.getenv('DB_NAME')
        )