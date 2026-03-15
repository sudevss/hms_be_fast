from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session
from dotenv import load_dotenv
import os

# Load environment variables from .env file
load_dotenv()

# Import config (this will auto-print configuration summary)
import config

from database import engine, Base, SessionLocal, get_db
from router import (
    doctors, patients, usermaster, facility,
    doctor_schedule, 
    appointment, medical_record, billing,
    medical_document, login, dashboard, new_booking,
    patient_diagnosis,templates, patient_reports,
    admin,lab_result
)
import model

# Initialize FastAPI app
app = FastAPI(
    title="Hospital Management System API",
    description="Comprehensive HMS Backend with Admin Management",
    version="2.0.0"
)

# Add CORS middleware with config values
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Jinja2 templates directory
jinja_templates = Jinja2Templates(directory="templatess")

# Dummy model for Razorpay Payment - if needed
class PatientPayment(BaseModel):
    id: int
    name: str
    payment_status: int
    order_id: str
    amount: int
    
    class Config:
        from_attributes = True

# Razorpay Setup - use config values
RAZORPAY_KEY_ID = config.RAZORPAY_KEY_ID
RAZORPAY_KEY_SECRET = config.RAZORPAY_KEY_SECRET

try:
    import razorpay
    if RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET:
        razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
        print("✅ Razorpay configured")
    else:
        razorpay_client = None
        print("⚠ Razorpay keys not configured. Payments disabled.")
except Exception as e:
    razorpay_client = None
    print(f"❌ Razorpay setup failed: {str(e)}")

# ============================================
# INCLUDE ALL ROUTERS
# ============================================
# Admin router FIRST (for admin management)
app.include_router(admin.router)

# Authentication & Core
app.include_router(login.router)
app.include_router(dashboard.router)

# Entity Management
app.include_router(doctors.router)
app.include_router(patients.router)
app.include_router(usermaster.router)
app.include_router(facility.router)
app.include_router(lab_results.router)

# Medical Operations
app.include_router(doctor_schedule.router)
app.include_router(appointment.router)
app.include_router(new_booking.router)
app.include_router(medical_record.router)
app.include_router(patient_diagnosis.router)
app.include_router(patient_reports.router)
app.include_router(medical_document.router)
app.include_router(templates.router)

# Billing
app.include_router(billing.router)

# ============================================
# ROOT ENDPOINTS
# ============================================
@app.get("/")
async def hello():
    return {
        "message": "Hospital Management System API",
        "version": config.APP_VERSION,
        "environment": config.ENVIRONMENT,
        "documentation": "/docs",
        "admin_setup": "/admin/initial-setup (for first-time setup)",
        "admin_login": "/admin/login",
        "features": {
            "email": config.FEATURES["email"],
            "payments": config.FEATURES["payments"],
        },
        "endpoints": {
            "api_docs": "/docs",
            "openapi_schema": "/openapi.json",
            "admin_management": "/admin/*"
        }
    }

@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring"""
    return {
        "status": "healthy",
        "environment": config.ENVIRONMENT,
        "debug": config.DEBUG,
        "version": config.APP_VERSION,
        "features": config.FEATURES
    }

# ============================================
# PAYMENT GATEWAY
# ============================================
@app.get("/payment_gateway", response_class=HTMLResponse, tags=["payments"])
async def read_item(request: Request, order_ID: str, db: Session = Depends(get_db)):
    """Payment Gateway Page (HTML landing with order info)"""
    patient = db.query(model.Patients).filter(model.Patients.order_id == order_ID).first()
    
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    
    return jinja_templates.TemplateResponse("index.html", {
        "request": request,
        "amount": patient.amount,
        "order_id": order_ID,
        "name": patient.name
    })

# ============================================
# UTILITY FUNCTIONS
# ============================================
def get_notfound_exception():
    """Utility to raise 404 exception"""
    raise HTTPException(status_code=404, detail="Entry not found")

# ============================================
# STARTUP EVENT
# ============================================
@app.on_event("startup")
async def startup_event():
    """Run on application startup"""
    print("=" * 50)
    print("🏥 Hospital Management System Starting...")
    print("=" * 50)
    print(f"Environment: {config.ENVIRONMENT}")
    print(f"Debug Mode: {config.DEBUG}")
    print(f"Version: {config.APP_VERSION}")
    print(f"Admin Endpoints Available: /admin/*")
    print("=" * 50)

@app.on_event("shutdown")
async def shutdown_event():
    """Run on application shutdown"""
    print("🛑 Hospital Management System Shutting Down...")
