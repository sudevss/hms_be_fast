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

from database import engine, Base, SessionLocal, get_db

from router import (
     doctors, patients, usermaster, facility,
     doctor_schedule, 
    appointment, medical_record, billing,
    medical_document, login, dashboard, new_booking,patient_diagnosis,patient_reports
)

import model

# Initialize FastAPI app
app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # ✅ Allows all origins (dev mode). In production, replace with ["https://yourfrontend.com"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Jinja2 templates directory
templates = Jinja2Templates(directory="templates")

# ❌ Removed create_all — Alembic should handle schema migrations
# model.Base.metadata.create_all(bind=engine)

# Dummy model for Razorpay Payment - if needed
class PatientPayment(BaseModel):
    id: int
    name: str
    payment_status: int
    order_id: str
    amount: int

    class Config:
        from_attributes = True  # Pydantic V2 compatible


# Razorpay Setup - SAFE fallback
RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")

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


# Include all routers
# app.include_router(auth.router)
app.include_router(doctors.router)
app.include_router(patients.router)
app.include_router(usermaster.router)
app.include_router(facility.router)

app.include_router(doctor_schedule.router)

app.include_router(appointment.router)
app.include_router(medical_record.router)
app.include_router(billing.router)
app.include_router(medical_document.router)
app.include_router(login.router)
app.include_router(dashboard.router)
app.include_router(new_booking.router)
app.include_router(patient_diagnosis.router)
app.include_router(patient_reports.router)


# Home route (API root info)
@app.get("/")
async def hello():
    return {
        "message": "This is just backend part of the HMS project. Please type '/docs' in the URL to see the API documentation (OpenAPI)."
    }


# Payment Gateway Page (HTML landing with order info)
@app.get("/payment_gateway", response_class=HTMLResponse, tags=["patients"])
async def read_item(request: Request, order_ID: str, db: Session = Depends(get_db)):
    patient = db.query(model.Patients).filter(model.Patients.order_id == order_ID).first()

    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    return templates.TemplateResponse("index.html", {
        "request": request,
        "amount": patient.amount,
        "order_id": order_ID,
        "name": patient.name
    })


# 404 Utility
def get_notfound_exception():

    raise HTTPException(status_code=404, detail="Entry not found")


