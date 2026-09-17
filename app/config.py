from dotenv import load_dotenv
import os

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")