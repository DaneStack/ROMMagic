import os
from dotenv import load_dotenv

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '.env'))

from datetime import timedelta

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'default_secret')
    PERMANENT_SESSION_LIFETIME = timedelta(days=30)
    
    DB_USER = os.environ.get('DB_USER', 'root')
    DB_PASS = os.environ.get('DB_PASS', '')
    DB_HOST = os.environ.get('DB_HOST', '127.0.0.1')
    DB_NAME = os.environ.get('DB_NAME', 'rommagic')
    
    # Use pymysql driver
    SQLALCHEMY_DATABASE_URI = f"mysql+pymysql://{DB_USER}:{DB_PASS}@{DB_HOST}/{DB_NAME}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    ROM_UPLOAD_PATH = os.environ.get('ROM_UPLOAD_PATH', os.path.join(basedir, 'ROMs'))
    THEGAMESDB_API_KEY = os.environ.get('THEGAMESDB_API_KEY')
    SCREENSCRAPER_DEV_ID = os.environ.get('SCREENSCRAPER_DEV_ID')
    SCREENSCRAPER_DEV_PASSWORD = os.environ.get('SCREENSCRAPER_DEV_PASSWORD')
    SCREENSCRAPER_SOFTNAME = os.environ.get('SCREENSCRAPER_SOFTNAME', 'rommagic')
    SCREENSCRAPER_USER = os.environ.get('SCREENSCRAPER_USER')
    SCREENSCRAPER_PASSWORD = os.environ.get('SCREENSCRAPER_PASSWORD')
    MIGRATION_SECRET_KEY = os.environ.get('MIGRATION_SECRET_KEY', 'dev_migration_key')
    TIMEZONE = os.environ.get('TIMEZONE', os.environ.get('TZ', 'Europe/Budapest'))

    
    # Allow uploads up to 100 GB to prevent 413 Payload Too Large errors for large ROMs (like Switch)
    MAX_CONTENT_LENGTH = 100 * 1024 * 1024 * 1024
