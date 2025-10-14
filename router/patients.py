from typing import List, Optional
from datetime import timedelta, datetime, date
from pytz import timezone
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload
from fastapi import FastAPI, Depends, HTTPException, APIRouter, Request, Query, BackgroundTasks
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

# Import authentication middleware
from auth_middleware import get_current_user, require_same_facility, CurrentUser

import model
from database import Base, engine, SessionLocal
from .doctors import doctor_response

# email
from fastapi_mail import ConnectionConfig, FastMail, MessageSchema, MessageType
from pydantic import EmailStr
from starlette.responses import JSONResponse
import razorpay
from dotenv import dotenv_values
import os
import asyncio
from functools import lru_cache

# Load from environment variables
RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "")

# Email configuration
MAIL_USERNAME = os.getenv("MAIL_USERNAME", "divyanshnumb@gmail.com")
MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "jbomvyfqjcxtixrz")
MAIL_SERVER = os.getenv("MAIL_SERVER", "smtp.gmail.com")
MAIL_PORT = int(os.getenv("MAIL_PORT", "465"))

# Warn if using default credentials
if MAIL_PASSWORD == "jbomvyfqjcxtixrz":
    print("⚠️  WARNING: Using default email credentials. Set MAIL_USERNAME and MAIL_PASSWORD environment variables!")

class EmailSchema(BaseModel):
    email: List[EmailStr]

class PatientUpdateSchema(BaseModel):
    firstname: Optional[str] = None
    lastname: Optional[str] = None
    age: Optional[int] = None
    dob: Optional[date] = None
    contact_number: Optional[str] = None
    address: Optional[str] = None
    gender: Optional[str] = None
    disease: Optional[str] = None
    room_id: Optional[int] = None
    ABDM_ABHA_id: Optional[str] = None
    facility_id: Optional[int] = None
    email: Optional[str] = None

# Cache configuration for better performance
@lru_cache()
def get_mail_config():
    return ConnectionConfig(
        MAIL_USERNAME=MAIL_USERNAME,
        MAIL_PASSWORD=MAIL_PASSWORD,
        MAIL_PORT=MAIL_PORT,
        MAIL_SERVER=MAIL_SERVER,
        MAIL_STARTTLS=False,
        MAIL_SSL_TLS=True,
        USE_CREDENTIALS=True,
        VALIDATE_CERTS=True
    )

model.Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

router = APIRouter(
    prefix="/patients",
    responses={404: {"description": "Not found"}}
)

class ui_patient(BaseModel):
    firstname: str
    lastname: str
    age: int
    dob: date
    contact_number: str
    address: str
    gender: str
    ABDM_ABHA_id: Optional[str] = None
    email_id: str
    disease: str
    room_id: int
    facility_id: int
   

class patient_response(BaseModel):
    id: int
    name: str
    contact_number: str
    age: int
    address: str
    ABDM_ABHA_id: Optional[str] = None
    gender: str

    class Config:
        orm_mode = True

class patient_payment(BaseModel):
    id: int
    name: str
    order_id: Optional[str] = None
    amount: Optional[int] = None

    class Config:
        orm_mode = True

class doctor_simple(BaseModel):
    id: int
    name: str
    specialization: Optional[str] = None
    experience: Optional[int] = None

class CreateOrder(BaseModel):
    amount: int
    currency: str = "INR"

class VerifyOrder(BaseModel):
    order_id: str

@router.get("/", tags=["patients"])
async def get_all_patients(
    current_user: CurrentUser = Depends(get_current_user),
    facility_id: int = Query(..., description="Facility ID to filter patients"), 
    db: Session = Depends(get_db)
):
    try:
        # Verify user has access to this facility
        if not current_user.is_super_admin() and current_user.facility_id != facility_id:
            raise HTTPException(
                status_code=403, 
                detail="Access denied. You can only access patients from your facility."
            )
        
        # Get all patients for the facility
        patients = db.query(model.Patients).filter(
            model.Patients.facility_id == facility_id
        ).all()
        
        result = []
        for patient in patients:
            # Get the most recent checked-in appointment
            latest_appointment = db.query(model.Appointment).join(
                model.Doctors, model.Appointment.doctor_id == model.Doctors.id
            ).filter(
                model.Appointment.patient_id == patient.id,
                model.Appointment.CheckinTime.isnot(None),
                model.Appointment.Cancelled == False
            ).order_by(
                model.Appointment.AppointmentDate.desc(),
                model.Appointment.AppointmentTime.desc()
            ).first()
            
            # Get doctor name and visit date if appointment exists
            doctor_name = None
            last_visited_date = None
            if latest_appointment:
                doctor = db.query(model.Doctors).filter(
                    model.Doctors.id == latest_appointment.doctor_id
                ).first()
                if doctor:
                    doctor_name = f"Dr. {doctor.firstname} {doctor.lastname}"
                    last_visited_date = latest_appointment.AppointmentDate
            
            patient_dict = {
                "id": patient.id,
                "firstname": patient.firstname,
                "lastname": patient.lastname,
                "name": f"{patient.firstname} {patient.lastname}",
                "age": patient.age,
                "dob": patient.dob,
                "contact_number": patient.contact_number,
                "address": patient.address,
                "gender": patient.gender,
                "disease": patient.disease,
                "room_id": patient.room_id,
                "email_id": patient.email_id,
                "ABDM_ABHA_id": getattr(patient, 'ABDM_ABHA_id', None),
                "facility_id": patient.facility_id,
                "doctor_visited": doctor_name,
                "last_visited_date": last_visited_date
            }
            result.append(patient_dict)
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@router.get("/{patient_id}", tags=["patients"])
async def get_patient_byid(
    patient_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    facility_id: int = Query(..., description="Facility ID"), 
    db: Session = Depends(get_db)
):
    try:
        # Verify user has access to this facility
        if not current_user.is_super_admin() and current_user.facility_id != facility_id:
            raise HTTPException(
                status_code=403, 
                detail="Access denied. You can only access patients from your facility."
            )
        
        patient = db.query(model.Patients).filter(
            model.Patients.id == patient_id,
            model.Patients.facility_id == facility_id
        ).first()
        
        if not patient:
            raise get_notfound_exception()

        # Get the most recent checked-in appointment
        latest_appointment = db.query(model.Appointment).join(
            model.Doctors, model.Appointment.doctor_id == model.Doctors.id
        ).filter(
            model.Appointment.patient_id == patient.id,
            model.Appointment.CheckinTime.isnot(None),
            model.Appointment.Cancelled == False
        ).order_by(
            model.Appointment.AppointmentDate.desc(),
            model.Appointment.AppointmentTime.desc()
        ).first()
        
        # Get doctor name and visit date if appointment exists
        doctor_name = None
        last_visited_date = None
        if latest_appointment:
            doctor = db.query(model.Doctors).filter(
                model.Doctors.id == latest_appointment.doctor_id
            ).first()
            if doctor:
                doctor_name = f"Dr. {doctor.firstname} {doctor.lastname}"
                last_visited_date = latest_appointment.AppointmentDate

        patient_response = {
            "id": patient.id,
            "firstname": patient.firstname,
            "lastname": patient.lastname,
            "name": f"{patient.firstname} {patient.lastname}",
            "age": patient.age,
            "dob": patient.dob,
            "contact_number": patient.contact_number,
            "address": patient.address,
            "gender": patient.gender,
            "disease": patient.disease,
            "room_id": patient.room_id,
            "email_id": patient.email_id,
            "ABDM_ABHA_id": getattr(patient, 'ABDM_ABHA_id', None),
            "facility_id": patient.facility_id,
            "doctor_visited": doctor_name,
            "last_visited_date": last_visited_date
        }

        return patient_response
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

async def send_mail_background(email_list: List[str], name: str, room_no: int):
    """Background task for sending emails to avoid blocking the main thread"""
    try:
        appointment_time = datetime.utcnow() + timedelta(hours=7, minutes=30)

        html = f"""
        <p>Dear {name},</p>
        <p>We are delighted to confirm your upcoming appointment at Midland Hospital. 
        Your health and well-being are of utmost importance to us, and we appreciate the opportunity
        to provide you with exceptional care. Please review the details of your appointment below:</p>
        
        <h3>Appointment Details:</h3>
        <ul>
            <li><strong>Patient Name:</strong> {name}</li>
            <li><strong>Appointment Date:</strong> {datetime.now(timezone("Asia/Kolkata")).strftime('%Y-%m-%d')}</li>
            <li><strong>Appointment Time:</strong> {appointment_time.strftime('%H:%M')}</li>
            <li><strong>Room Number:</strong> {room_no}</li>
        </ul>

        <p>Please ensure that you arrive at least 15 minutes before your scheduled appointment time to 
        complete any necessary paperwork and check-in procedures. If you anticipate any delays or if you 
        are unable to keep the appointment, kindly notify us at your earliest convenience so that we may 
        accommodate other patients who may be in need of our services.</p>

        <p>We look forward to seeing you. Thank you once again for choosing us for your healthcare needs.</p>

        <p>Best regards,<br><b>MIDLAND HOSPITAL</b><br>(8299821096)</p>
        """

        message = MessageSchema(
            subject=f"Confirmation of Appointment Details - {name}",
            recipients=email_list,
            body=html,
            subtype=MessageType.html
        )

        fm = FastMail(get_mail_config())

        try:
            await asyncio.wait_for(fm.send_message(message), timeout=15)
            print(f"✅ Email sent successfully to {email_list}")
        except asyncio.TimeoutError:
            print("❌ Email sending timed out")
        except Exception as e:
            print(f"❌ Email sending failed inside try block: {str(e)}")

    except Exception as e:
        print(f"❌ Email sending outer failure: {str(e)}")


@router.post("/", tags=["patients"])
async def add_new_patient(
    patient: ui_patient,
    current_user: CurrentUser = Depends(get_current_user),
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db)
):
    try:
        # Verify user has access to this facility
        if not current_user.is_super_admin() and current_user.facility_id != patient.facility_id:
            raise HTTPException(
                status_code=403, 
                detail="Access denied. You can only add patients to your facility."
            )
        
        patient_model = model.Patients(
            firstname=patient.firstname,
            lastname=patient.lastname,
            age=patient.age,
            dob=patient.dob,
            contact_number=patient.contact_number,
            address=patient.address,
            gender=patient.gender,
            disease=patient.disease,
            room_id=patient.room_id,
            email_id=patient.email_id,
            ABDM_ABHA_id=patient.ABDM_ABHA_id,
            facility_id=patient.facility_id
        )

        db.add(patient_model)
        db.commit()
        db.refresh(patient_model)
        
        # Add email sending as background task to avoid blocking
        full_name = f"{patient.firstname} {patient.lastname}"
        if background_tasks:
            background_tasks.add_task(send_mail_background, [patient.email_id], full_name, patient.room_id)
        
        return successful_response(201)
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@router.api_route("/{patient_id}", methods=["PATCH"], tags=["patients"])
async def update_patient(
    patient_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    facility_id: int = Query(..., description="Facility ID"),
    patient: PatientUpdateSchema = None, 
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db)
):
    try:
        # Verify user has access to this facility
        if not current_user.is_super_admin() and current_user.facility_id != facility_id:
            raise HTTPException(
                status_code=403, 
                detail="Access denied. You can only update patients from your facility."
            )
        
        existing_patient = db.query(model.Patients).filter(
            model.Patients.id == patient_id,
            model.Patients.facility_id == facility_id
        ).first()
        
        if not existing_patient:
            raise get_notfound_exception()
        
        # Get only the fields that were explicitly set in the request
        update_data = patient.dict(exclude_unset=True, exclude_none=True) if patient else {}
        filtered_data = {}
        
        # Define invalid values to skip
        invalid_strings = {"", "string", "example@email.com", "test@test.com", "user@example.com"}
        current_date = date.today()
        
        for k, v in update_data.items():
            if v is None:
                continue
                
            # Skip invalid string values
            if isinstance(v, str) and (v.strip().lower() in invalid_strings or v.strip() == ""):
                continue
                
            # Skip zero integers for non-critical fields
            if isinstance(v, int) and v == 0 and k not in ['last_visited_doctor_id']:
                continue
            
            # Special handling for DOB field to prevent unwanted updates
            if k == "dob" and isinstance(v, date):
                current_db_dob = getattr(existing_patient, 'dob', None)
                
                if (current_db_dob != v and 
                    v != current_date and
                    v.year > 1900 and
                    v < current_date):
                    filtered_data[k] = v
                continue
            
            # Special handling for last_visited_date
            if k == "last_visited_date" and isinstance(v, date):
                current_db_date = getattr(existing_patient, 'last_visited_date', None)
                if current_db_date != v and v <= current_date:
                    filtered_data[k] = v
                continue
            
            # Special handling for last_visited_doctor_id
            if k == "last_visited_doctor_id" and isinstance(v, int):
                # Verify doctor exists
                doctor = db.query(model.Doctors).filter(model.Doctors.id == v).first()
                if doctor:
                    current_doctor_id = getattr(existing_patient, 'last_visited_doctor_id', None)
                    if current_doctor_id != v:
                        filtered_data[k] = v
                        # Auto-update last_visited_date to today if not already set
                        if 'last_visited_date' not in filtered_data:
                            filtered_data['last_visited_date'] = current_date
                continue
            
            # For other date fields, similar validation
            if isinstance(v, date) and k not in ["dob", "last_visited_date"]:
                current_db_value = getattr(existing_patient, k, None)
                if current_db_value != v:
                    filtered_data[k] = v
                continue
                
            # For all other fields, only update if value differs from current
            current_value = getattr(existing_patient, k, None)
            if current_value != v:
                filtered_data[k] = v
        
        # Handle email updates
        send_email = False
        if 'email' in filtered_data and filtered_data['email']:
            new_email = filtered_data['email']
            # Validate email format
            if "@" in new_email and new_email.lower() not in invalid_strings:
                current_email = getattr(existing_patient, 'email_id', None)
                if current_email != new_email:
                    existing_patient.email_id = new_email
                    send_email = True
                    del filtered_data['email']
        
        if not filtered_data and not send_email:
            raise HTTPException(status_code=400, detail="No valid fields provided for update")
        
        # Update patient fields efficiently
        for key, value in filtered_data.items():
            if hasattr(existing_patient, key):
                setattr(existing_patient, key, value)

        db.commit()
        db.refresh(existing_patient)
        
        # Send email in background if needed
        if send_email and background_tasks:
            full_name = f"{existing_patient.firstname} {existing_patient.lastname}"
            background_tasks.add_task(send_mail_background, [existing_patient.email_id], full_name, existing_patient.room_id)
        
        return successful_response(200)
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@router.delete("/", tags=["patients"])
async def delete_patient_details(
    current_user: CurrentUser = Depends(get_current_user),
    patient_id: int = Query(..., description="Patient ID"),
    facility_id: int = Query(..., description="Facility ID"),
    db: Session = Depends(get_db)
):
    try:
        # Verify user has access to this facility
        if not current_user.is_super_admin() and current_user.facility_id != facility_id:
            raise HTTPException(
                status_code=403, 
                detail="Access denied. You can only delete patients from your facility."
            )
        
        # Single query to check existence and delete
        deleted_count = db.query(model.Patients).filter(
            model.Patients.id == patient_id,
            model.Patients.facility_id == facility_id
            
        ).delete()
        
        if deleted_count == 0:
            raise get_notfound_exception()

        db.commit()
        return successful_response(201)
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

def get_user_exception():
    raise HTTPException(status_code=401, detail="Authentication failed")

def get_notfound_exception():
    raise HTTPException(status_code=404, detail="Entry not found")

def successful_response(status_code):
    return {
        "status_response": status_code,
        "details": "Successful"
    }

# Initialize Razorpay client with caching
@lru_cache()
def get_razorpay_client():
    try:
        if RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET:
            return razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
        else:
            print("⚠️  Razorpay keys not configured")
            return None
    except Exception as e:
        print(f"❌ Razorpay client initialization failed: {str(e)}")
        return None

@router.post("/create_order", response_model=patient_payment, tags=["patients"])
async def create_order(
    input: CreateOrder, 
    id: int,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        client = get_razorpay_client()
        if not client:
            raise HTTPException(status_code=500, detail="Payment service not available")
        
        patient = db.query(model.Patients).filter(model.Patients.id == id).first()
        if not patient:
            raise HTTPException(status_code=404, detail="Patient not found")
        
        # Verify user has access to this patient's facility
        if not current_user.is_super_admin() and current_user.facility_id != patient.facility_id:
            raise HTTPException(
                status_code=403, 
                detail="Access denied. You can only create orders for patients from your facility."
            )

        payment = client.order.create({
            'amount': input.amount * 100, 
            'currency': input.currency, 
            'payment_capture': '1'
        })

        patient.order_id = payment.get("id")
        patient.amount = payment.get("amount")

        db.commit()
        
        return {
            "id": patient.id,
            "name": f"{patient.firstname} {patient.lastname}",
            "order_id": patient.order_id,
            "amount": patient.amount
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@router.get("/verify_order/{input}", tags=["patients"])
async def verify_order(
    input: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        client = get_razorpay_client()
        if not client:
            raise HTTPException(status_code=500, detail="Payment service not available")
        
        order = client.order.fetch(input)

        if order['status'] == 'paid':
            return JSONResponse(status_code=200, content={'message': 'Payment successful'})
        else:
            return JSONResponse(status_code=400, content={'message': 'Payment failed'})
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse(status_code=500, content={'message': f'Internal server error: {str(e)}'})