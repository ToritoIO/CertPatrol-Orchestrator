"""
Configuration settings for CertPatrol Orchestrator
"""
import os

# Base directory
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Database
DATABASE_PATH = os.path.join(BASE_DIR, "certpatrol_manager.db")

# CertPatrol command (installed via pip)
CERTPATROL_CMD = "certpatrol"

# Flask settings
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")
HOST = os.environ.get("MANAGER_HOST", "127.0.0.1")
PORT = int(os.environ.get("MANAGER_PORT", 8080))  # Changed from 5000 (conflicts with AirPlay on macOS)
DEBUG = os.environ.get("MANAGER_DEBUG", "False").lower() == "true"

# Process management
MAX_CONCURRENT_SEARCHES = int(os.environ.get("MAX_CONCURRENT_SEARCHES", 20))

