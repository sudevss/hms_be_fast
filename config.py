"""
config.py - Centralized Configuration for Production & Development
Location: project root (same level as main.py)

DEPLOYMENT NOTES:
✅ YES - Deploy this file to Vercel
✅ All sensitive values come from environment variables
✅ No hardcoded secrets in this file
❌ NEVER commit .env file to Git
✅ Set environment variables in Vercel Dashboard
"""

import os
from dotenv import load_dotenv
import secrets

# Load environment variables from .env file (local development only)
# In production (Vercel), environment variables come from Vercel dashboard
load_dotenv()

# ===========================================
# ENVIRONMENT DETECTION
# ===========================================
ENVIRONMENT = os.getenv("ENVIRONMENT", "production")  # Default to production for safety
DEBUG = os.getenv("DEBUG", "False").lower() == "true"

# Detect if running on Vercel
IS_VERCEL = os.getenv("VERCEL", "").lower() == "1"
IS_PRODUCTION = ENVIRONMENT == "production" or IS_VERCEL

# ===========================================
# JWT Configuration - SINGLE SOURCE OF TRUTH
# ===========================================
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"

# Validate SECRET_KEY exists
if not SECRET_KEY:
    if IS_PRODUCTION:
        # In production, SECRET_KEY MUST be set
        raise ValueError(
            "❌ CRITICAL: SECRET_KEY environment variable is required for production! "
            "Set it in Vercel Dashboard: Settings > Environment Variables"
        )
    else:
        # In development, generate a temporary key with warning
        print("⚠️  WARNING: SECRET_KEY not found. Generating temporary key for development...")
        print("   Add SECRET_KEY to your .env file for persistent sessions!")
        SECRET_KEY = secrets.token_hex(32)

# Security validation for production
if IS_PRODUCTION:
    # Check if using a weak/default key
    WEAK_KEYS = [
        "KlgH6AzYDeZeGwD288to79I3vTHT8wp7",
        "your_secret_key_here",
        "change_me",
        "secret",
        "12345"
    ]
    
    if SECRET_KEY in WEAK_KEYS or len(SECRET_KEY) < 32:
        raise ValueError(
            "❌ CRITICAL: Weak SECRET_KEY detected in production! "
            "Generate a strong key using: python -c \"import secrets; print(secrets.token_hex(32))\""
        )
    
    print("✅ Production SECRET_KEY validated")
else:
    if SECRET_KEY in ["KlgH6AzYDeZeGwD288to79I3vTHT8wp7", "your_secret_key_here"]:
        print("⚠️  WARNING: Using default/example SECRET_KEY in development.")
        print("   Generate new key: python -c \"import secrets; print(secrets.token_hex(32))\"")

# ===========================================
# Email Configuration
# ===========================================
MAIL_USERNAME = os.getenv("MAIL_USERNAME")
MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")
MAIL_SERVER = os.getenv("MAIL_SERVER", "smtp.gmail.com")
MAIL_PORT = int(os.getenv("MAIL_PORT", "465"))

# Email validation for production
if IS_PRODUCTION and not (MAIL_USERNAME and MAIL_PASSWORD):
    print("⚠️  WARNING: Email credentials not configured in production.")
    print("   Email features will be disabled.")
elif not IS_PRODUCTION:
    # Development fallbacks
    if not MAIL_USERNAME:
        print("⚠️  Email not configured. Email features disabled in development.")

# ===========================================
# Payment Gateway Configuration
# ===========================================
RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "")

# Payment gateway validation
PAYMENTS_ENABLED = bool(RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET)

if IS_PRODUCTION and not PAYMENTS_ENABLED:
    print("⚠️  WARNING: Razorpay not configured. Payment features will be disabled.")

# ===========================================
# Token Configuration
# ===========================================
ACCESS_TOKEN_EXPIRE_HOURS = int(os.getenv("ACCESS_TOKEN_EXPIRE_HOURS", "8"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "30"))

# Validate token expiration for production
if IS_PRODUCTION and ACCESS_TOKEN_EXPIRE_HOURS > 24:
    print("⚠️  WARNING: Token expiration > 24 hours in production may pose security risk.")

# ===========================================
# Database Configuration (for future use)
# ===========================================
DATABASE_URL = os.getenv("DATABASE_URL")

if IS_PRODUCTION and not DATABASE_URL:
    print("⚠️  WARNING: DATABASE_URL not set. Ensure database is properly configured.")

# ===========================================
# CORS Configuration
# ===========================================
# In production, restrict CORS to specific origins
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")

if IS_PRODUCTION and "*" in CORS_ORIGINS:
    print("⚠️  WARNING: CORS allows all origins (*) in production!")
    print("   Set CORS_ORIGINS in environment variables to specific domains.")

# ===========================================
# Security Headers
# ===========================================
SECURE_HEADERS = IS_PRODUCTION  # Enable security headers in production

# ===========================================
# Logging Configuration
# ===========================================
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO" if IS_PRODUCTION else "DEBUG")

# ===========================================
# Application Metadata
# ===========================================
APP_NAME = "Hospital Management System"
APP_VERSION = "2.0.0"
API_PREFIX = os.getenv("API_PREFIX", "")  # Optional API prefix for deployment

# ===========================================
# Feature Flags
# ===========================================
FEATURES = {
    "email": bool(MAIL_USERNAME and MAIL_PASSWORD),
    "payments": PAYMENTS_ENABLED,
    "debug": DEBUG,
}

# ===========================================
# Startup Configuration Summary
# ===========================================
def print_config_summary():
    """Print configuration summary on startup"""
    print("=" * 60)
    print(f"🏥 {APP_NAME} v{APP_VERSION}")
    print("=" * 60)
    print(f"Environment:        {ENVIRONMENT}")
    print(f"Platform:           {'Vercel' if IS_VERCEL else 'Local/Other'}")
    print(f"Debug Mode:         {DEBUG}")
    print(f"Secret Key:         {'✅ Configured' if SECRET_KEY else '❌ Missing'}")
    print(f"Email:              {'✅ Enabled' if FEATURES['email'] else '❌ Disabled'}")
    print(f"Payments:           {'✅ Enabled' if FEATURES['payments'] else '❌ Disabled'}")
    print(f"Token Expiration:   {ACCESS_TOKEN_EXPIRE_HOURS} hours")
    print(f"CORS Origins:       {CORS_ORIGINS if len(str(CORS_ORIGINS)) < 50 else '[Multiple]'}")
    print(f"Log Level:          {LOG_LEVEL}")
    print("=" * 60)
    
    # Production security checklist
    if IS_PRODUCTION:
        print("\n🔒 PRODUCTION SECURITY CHECKLIST:")
        checks = [
            ("Strong SECRET_KEY", len(SECRET_KEY) >= 32 if SECRET_KEY else False),
            ("CORS Restricted", "*" not in CORS_ORIGINS),
            ("Debug Disabled", not DEBUG),
            ("HTTPS Only", True),  # Vercel handles this automatically
        ]
        
        for check, passed in checks:
            status = "✅" if passed else "⚠️ "
            print(f"{status} {check}")
        print("=" * 60)

# Auto-print on import
print_config_summary()

# ===========================================
# Export commonly used settings
# ===========================================
__all__ = [
    'SECRET_KEY',
    'ALGORITHM',
    'ACCESS_TOKEN_EXPIRE_HOURS',
    'REFRESH_TOKEN_EXPIRE_DAYS',
    'MAIL_USERNAME',
    'MAIL_PASSWORD',
    'MAIL_SERVER',
    'MAIL_PORT',
    'RAZORPAY_KEY_ID',
    'RAZORPAY_KEY_SECRET',
    'ENVIRONMENT',
    'DEBUG',
    'IS_PRODUCTION',
    'FEATURES',
    'CORS_ORIGINS',
]