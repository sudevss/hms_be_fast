from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import List, Optional
from datetime import date, datetime, time
from pydantic import BaseModel, validator
import re

# Import your existing modules
from database import get_db
import model

router = APIRouter(
    prefix="/new_booking",
    tags=["new_booking"]
)

# -------------------- Pydantic Models --------------------

class PatientInfo(BaseModel):
    firstname: str
    lastname: str
    age: Optional[int] = None
    dob: Optional[date] = None
    contact_number: str  # This will be the primary lookup field
    address: Optional[str] = None
    gender: Optional[str] = None
    email_id: Optional[str] = None
    disease: Optional[str] = None
    ABDM_ABHA_id: Optional[str] = None

    @validator('contact_number')
    def validate_phone(cls, v):
        if not v:
            raise ValueError("Contact number is required")
        # Remove spaces and special characters
        phone = re.sub(r'[^\d]', '', v)
        # Check if it's a valid Indian phone number (10 digits)
        if len(phone) != 10 or not phone.isdigit():
            raise ValueError("Contact number must be a valid 10-digit number")
        return phone

    @validator('email_id')
    def validate_email(cls, v):
        if v and '@' not in v:
            raise ValueError("Invalid email format")
        return v

    class Config:
        from_attributes = True


class DashboardAppointmentCreate(BaseModel):
    patient_info: PatientInfo
    DoctorID: int
    FacilityID: int
    DCID: int
    AppointmentDate: date
    AppointmentTime: time
    Reason: str
    AppointmentMode: str = "A"  # Default to Appointment mode
    room_id: Optional[int] = 1  # Default room

    @validator('AppointmentTime', pre=True)
    def parse_time(cls, v):
        if v is None:
            raise ValueError("AppointmentTime is required")
        try:
            if isinstance(v, str):
                v = v.rstrip('Z')
                return datetime.fromisoformat(f"2000-01-01T{v}").time().replace(second=0, microsecond=0)
            if isinstance(v, datetime):
                return v.time().replace(second=0, microsecond=0)
            if isinstance(v, time):
                return v.replace(second=0, microsecond=0)
        except Exception:
            raise ValueError("Invalid format for AppointmentTime")
        raise ValueError("Invalid format for AppointmentTime")

    @validator('AppointmentDate')
    def validate_appointment_date(cls, v):
        if v < date.today():
            raise ValueError("Appointment date cannot be in the past")
        return v

    class Config:
        from_attributes = True


class AppointmentResponse(BaseModel):
    AppointmentID: int
    PatientID: int
    DoctorID: int
    FacilityID: int
    DCID: int
    AppointmentDate: date
    AppointmentTime: time
    Reason: str
    AppointmentMode: str
    CheckinTime: Optional[datetime] = None
    Cancelled: Optional[bool] = None
    TokenID: Optional[str] = None
    AppointmentStatus: Optional[str] = None

    class Config:
        from_attributes = True


class DashboardAppointmentResponse(BaseModel):
    appointment: AppointmentResponse
    patient: dict
    is_new_patient: bool
    message: str

    class Config:
        from_attributes = True


# Updated models for multiple patients lookup
class PatientDetails(BaseModel):
    id: int
    name: str
    firstname: str
    lastname: str
    contact_number: str
    age: Optional[int] = None
    dob: Optional[date] = None
    address: Optional[str] = None
    gender: Optional[str] = None
    email_id: Optional[str] = None
    disease: Optional[str] = None
    ABDM_ABHA_id: Optional[str] = None
    facility_id: int
    recent_appointments: List[dict] = []

    class Config:
        from_attributes = True


class PatientLookupResponse(BaseModel):
    exists: bool
    total_patients: int
    patients: List[PatientDetails] = []
    message: str

    class Config:
        from_attributes = True


class QuickAppointmentCreate(BaseModel):
    PatientID: int
    DoctorID: int
    FacilityID: int
    DCID: int
    AppointmentDate: date
    AppointmentTime: time
    Reason: str
    AppointmentMode: str = "A"  # Default to Appointment mode

    @validator('PatientID')
    def validate_patient_id(cls, v):
        if not v or v <= 0:
            raise ValueError("Valid PatientID is required")
        return v

    @validator('AppointmentTime', pre=True)
    def parse_time(cls, v):
        if v is None:
            raise ValueError("AppointmentTime is required")
        try:
            if isinstance(v, str):
                v = v.rstrip('Z')
                return datetime.fromisoformat(f"2000-01-01T{v}").time().replace(second=0, microsecond=0)
            if isinstance(v, datetime):
                return v.time().replace(second=0, microsecond=0)
            if isinstance(v, time):
                return v.replace(second=0, microsecond=0)
        except Exception:
            raise ValueError("Invalid format for AppointmentTime")
        raise ValueError("Invalid format for AppointmentTime")

    @validator('AppointmentDate')
    def validate_appointment_date(cls, v):
        if v < date.today():
            raise ValueError("Appointment date cannot be in the past")
        return v

    class Config:
        from_attributes = True


# -------------------- Dashboard Endpoints --------------------

@router.post("/book", response_model=DashboardAppointmentResponse)
def dashboard_book_appointment(
    booking_data: DashboardAppointmentCreate,
    db: Session = Depends(get_db)
):
    """
    Dashboard API: Books appointment by phone number lookup
    - If patient exists: fetch details and book appointment
    - If patient doesn't exist: create patient and book appointment
    """
    try:
        phone_number = booking_data.patient_info.contact_number
        facility_id = booking_data.FacilityID
        
        # Step 1: Check if patient exists by phone number and facility
        existing_patient = (
            db.query(model.Patients)
            .filter(
                model.Patients.contact_number == phone_number,
                model.Patients.FacilityID == facility_id
            )
            .first()
        )
        
        is_new_patient = False
        patient_id = None
        
        if existing_patient:
            # Patient exists - use existing patient
            patient_id = existing_patient.id
            patient_dict = {
                "id": existing_patient.id,
                "name": f"{existing_patient.firstname} {existing_patient.lastname}",
                "contact_number": existing_patient.contact_number,
                "age": existing_patient.age,
                "address": existing_patient.address,
                "gender": existing_patient.gender,
                "email_id": getattr(existing_patient, 'email_id', None),
                "disease": getattr(existing_patient, 'disease', None),
                "ABDM_ABHA_id": getattr(existing_patient, 'ABDM_ABHA_id', None)
            }
        else:
            # Patient doesn't exist - create new patient
            is_new_patient = True
            
            # Validate required fields for new patient
            if not booking_data.patient_info.firstname:
                raise HTTPException(400, "First name is required for new patient")
            if not booking_data.patient_info.lastname:
                raise HTTPException(400, "Last name is required for new patient")
            
            # Set default values for optional fields
            patient_age = booking_data.patient_info.age or 0
            patient_dob = booking_data.patient_info.dob or date.today()
            patient_address = booking_data.patient_info.address or "Not provided"
            patient_gender = booking_data.patient_info.gender or "Not specified"
            patient_email = booking_data.patient_info.email_id or f"{phone_number}@temp.com"
            patient_disease = booking_data.patient_info.disease or "General consultation"
            
            # Create new patient
            new_patient = model.Patients(
                firstname=booking_data.patient_info.firstname,
                lastname=booking_data.patient_info.lastname,
                age=patient_age,
                dob=patient_dob,
                contact_number=phone_number,
                address=patient_address,
                gender=patient_gender,
                email_id=patient_email,
                disease=patient_disease,
                room_id=booking_data.room_id,
                payment_status=0,  # Default to unpaid
                ABDM_ABHA_id=booking_data.patient_info.ABDM_ABHA_id,
                FacilityID=facility_id
            )
            
            db.add(new_patient)
            db.flush()  # Get the ID without committing
            patient_id = new_patient.id
            
            patient_dict = {
                "id": new_patient.id,
                "name": f"{new_patient.firstname} {new_patient.lastname}",
                "contact_number": new_patient.contact_number,
                "age": new_patient.age,
                "address": new_patient.address,
                "gender": new_patient.gender,
                "email_id": new_patient.email_id,
                "disease": new_patient.disease,
                "ABDM_ABHA_id": new_patient.ABDM_ABHA_id
            }
        
        # Step 2: Verify doctor exists
        doctor = db.query(model.Doctors).filter(model.Doctors.id == booking_data.DoctorID).first()
        if not doctor:
            raise HTTPException(404, "Doctor not found")
        
        # Step 3: Check for duplicate appointments
        existing_appointment = (
            db.query(model.Appointment)
            .filter(
                model.Appointment.PatientID == patient_id,
                model.Appointment.DoctorID == booking_data.DoctorID,
                model.Appointment.AppointmentDate == booking_data.AppointmentDate,
                model.Appointment.AppointmentTime == booking_data.AppointmentTime,
                model.Appointment.FacilityID == facility_id,
                model.Appointment.Cancelled == False
            )
            .first()
        )
        
        if existing_appointment:
            raise HTTPException(400, "Duplicate appointment already exists for this patient at the same time")
        
        # Step 4: Create appointment
        appointment_data = {
            "PatientID": patient_id,
            "DoctorID": booking_data.DoctorID,
            "FacilityID": facility_id,
            "DCID": booking_data.DCID,
            "AppointmentDate": booking_data.AppointmentDate,
            "AppointmentTime": booking_data.AppointmentTime,
            "Reason": booking_data.Reason,
            "AppointmentMode": booking_data.AppointmentMode,
            "AppointmentStatus": "Scheduled",
            "Cancelled": False,
            "TokenID": None,
            "CheckinTime": None
        }
        
        new_appointment = model.Appointment(**appointment_data)
        db.add(new_appointment)
        db.commit()
        db.refresh(new_appointment)
        
        # Step 5: Prepare response
        appointment_response = AppointmentResponse(
            AppointmentID=new_appointment.AppointmentID,
            PatientID=new_appointment.PatientID,
            DoctorID=new_appointment.DoctorID,
            FacilityID=new_appointment.FacilityID,
            DCID=new_appointment.DCID,
            AppointmentDate=new_appointment.AppointmentDate,
            AppointmentTime=new_appointment.AppointmentTime,
            Reason=new_appointment.Reason,
            AppointmentMode=new_appointment.AppointmentMode,
            CheckinTime=new_appointment.CheckinTime,
            Cancelled=new_appointment.Cancelled,
            TokenID=new_appointment.TokenID,
            AppointmentStatus=new_appointment.AppointmentStatus
        )
        
        success_message = (
            f"New patient created and appointment booked successfully" 
            if is_new_patient 
            else f"Appointment booked successfully for existing patient"
        )
        
        return DashboardAppointmentResponse(
            appointment=appointment_response,
            patient=patient_dict,
            is_new_patient=is_new_patient,
            message=success_message
        )
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Error processing dashboard booking: {str(e)}")

@router.get("/lookup", response_model=PatientLookupResponse)
def dashboard_patient_lookup(
    phone_number: str = Query(..., description="Patient phone number"),
    facility_id: Optional[int] = Query(None, alias="FacilityID", description="Filter by specific facility (optional)"),
    db: Session = Depends(get_db)
):
    """
    Lookup ALL patients registered with the same phone number
    Can optionally filter by facility_id, or search across all facilities
    Returns comprehensive patient information and recent appointment history for each patient
    """
    try:
        # Clean phone number
        clean_phone = re.sub(r'[^\d]', '', phone_number)
        if len(clean_phone) != 10:
            raise HTTPException(400, "Invalid phone number format. Must be 10 digits.")
        
        # Build base query
        query = db.query(model.Patients).filter(
            model.Patients.contact_number == clean_phone
        )
        
        # Optional facility filter
        if facility_id:
            query = query.filter(model.Patients.FacilityID == facility_id)
        
        # Fetch patients
        patients = query.order_by(
            model.Patients.FacilityID,
            model.Patients.firstname,
            model.Patients.lastname
        ).all()
        
        if not patients:
            msg = f"No patients found with phone number {clean_phone}"
            if facility_id:
                msg += f" in facility {facility_id}"
            msg += ". New patient will be created when booking."
            return PatientLookupResponse(
                exists=False,
                total_patients=0,
                patients=[],
                message=msg
            )
        
        # Gather details & recent history
        patient_details_list = []
        for patient in patients:
            # Recent appointments
            recent_appointments = (
                db.query(model.Appointment)
                .filter(
                    model.Appointment.PatientID == patient.id,
                    model.Appointment.Cancelled == False
                )
                .order_by(model.Appointment.AppointmentDate.desc())
                .limit(5)
                .all()
            )
            
            appointment_history = []
            for apt in recent_appointments:
                # Doctor lookup (Doctors.id is PK)
                doctor = (
                    db.query(model.Doctors)
                      .filter(model.Doctors.id == apt.DoctorID)
                      .first()
                )
                doctor_name = (
                    f"Dr. {doctor.firstname} {doctor.lastname}"
                    if doctor else
                    "Unknown Doctor"
                )
                
                # Facility lookup (Facility.FacilityID is PK)
                facility = (
                    db.query(model.Facility)
                      .filter(model.Facility.FacilityID == apt.FacilityID)
                      .first()
                )
                facility_name = (
                    facility.FacilityName
                    if facility else
                    f"Facility {apt.FacilityID}"
                )
                
                appointment_history.append({
                    "appointment_id": apt.AppointmentID,
                    "date": apt.AppointmentDate.isoformat(),
                    "time": apt.AppointmentTime.strftime("%H:%M"),
                    "doctor": doctor_name,
                    "facility": facility_name,
                    "reason": apt.Reason,
                    "status": apt.AppointmentStatus or "Scheduled",
                    "mode": apt.AppointmentMode
                })
            
            # Build patient detail
            patient_details_list.append(PatientDetails(
                id=patient.id,
                name=f"{patient.firstname} {patient.lastname}",
                firstname=patient.firstname,
                lastname=patient.lastname,
                contact_number=patient.contact_number,
                age=patient.age,
                dob=patient.dob,
                address=patient.address,
                gender=patient.gender,
                email_id=getattr(patient, 'email_id', None),
                disease=getattr(patient, 'disease', None),
                ABDM_ABHA_id=getattr(patient, 'ABDM_ABHA_id', None),
                facility_id=patient.FacilityID,
                recent_appointments=appointment_history
            ))
        
        # Summary message
        total = len(patients)
        if total == 1:
            message = f"Found 1 patient with phone number {clean_phone}"
        else:
            message = f"Found {total} patients with phone number {clean_phone}"
        
        if facility_id:
            message += f" in facility {facility_id}"
        else:
            # Multi-facility breakdown
            counts = {}
            for p in patients:
                counts[p.FacilityID] = counts.get(p.FacilityID, 0) + 1
            if len(counts) > 1:
                parts = [f"{cnt} in facility {fid}" for fid, cnt in counts.items()]
                message += f" across facilities ({', '.join(parts)})"
        
        message += ". Select a patient to book appointment or create new patient."
        
        return PatientLookupResponse(
            exists=True,
            total_patients=total,
            patients=patient_details_list,
            message=message
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Error looking up patients: {str(e)}")


@router.post("/book-existing", response_model=DashboardAppointmentResponse)
def book_appointment_for_existing_patient(
    booking_data: QuickAppointmentCreate,
    db: Session = Depends(get_db)
):
    """
    Quick booking for existing patients using PatientID
    Automatically fetches patient information and books appointment
    """
    try:
        patient_id = booking_data.PatientID
        facility_id = booking_data.FacilityID
        
        # Step 1: Find existing patient by PatientID
        existing_patient = (
            db.query(model.Patients)
            .filter(
                model.Patients.id == patient_id,
                model.Patients.FacilityID == facility_id
            )
            .first()
        )
        
        if not existing_patient:
            raise HTTPException(404, f"Patient with ID {patient_id} not found in facility {facility_id}")
        
        # Prepare patient info for response
        patient_dict = {
            "id": existing_patient.id,
            "name": f"{existing_patient.firstname} {existing_patient.lastname}",
            "contact_number": existing_patient.contact_number,
            "age": existing_patient.age,
            "address": existing_patient.address,
            "gender": existing_patient.gender,
            "email_id": getattr(existing_patient, 'email_id', None),
            "disease": getattr(existing_patient, 'disease', None),
            "ABDM_ABHA_id": getattr(existing_patient, 'ABDM_ABHA_id', None)
        }
        
        # Step 2: Verify doctor exists
        doctor = db.query(model.Doctors).filter(model.Doctors.id == booking_data.DoctorID).first()
        if not doctor:
            raise HTTPException(404, "Doctor not found")
        
        # Step 3: Check for duplicate appointments
        existing_appointment = (
            db.query(model.Appointment)
            .filter(
                model.Appointment.PatientID == patient_id,
                model.Appointment.DoctorID == booking_data.DoctorID,
                model.Appointment.AppointmentDate == booking_data.AppointmentDate,
                model.Appointment.AppointmentTime == booking_data.AppointmentTime,
                model.Appointment.FacilityID == facility_id,
                model.Appointment.Cancelled == False
            )
            .first()
        )
        
        if existing_appointment:
            raise HTTPException(400, "Duplicate appointment already exists for this patient at the same time")
        
        # Step 4: Create appointment
        appointment_data = {
            "PatientID": patient_id,
            "DoctorID": booking_data.DoctorID,
            "FacilityID": facility_id,
            "DCID": booking_data.DCID,
            "AppointmentDate": booking_data.AppointmentDate,
            "AppointmentTime": booking_data.AppointmentTime,
            "Reason": booking_data.Reason,
            "AppointmentMode": booking_data.AppointmentMode,
            "AppointmentStatus": "Scheduled",
            "Cancelled": False,
            "TokenID": None,
            "CheckinTime": None
        }
        
        new_appointment = model.Appointment(**appointment_data)
        db.add(new_appointment)
        db.commit()
        db.refresh(new_appointment)
        
        # Step 5: Prepare response
        appointment_response = AppointmentResponse(
            AppointmentID=new_appointment.AppointmentID,
            PatientID=new_appointment.PatientID,
            DoctorID=new_appointment.DoctorID,
            FacilityID=new_appointment.FacilityID,
            DCID=new_appointment.DCID,
            AppointmentDate=new_appointment.AppointmentDate,
            AppointmentTime=new_appointment.AppointmentTime,
            Reason=new_appointment.Reason,
            AppointmentMode=new_appointment.AppointmentMode,
            CheckinTime=new_appointment.CheckinTime,
            Cancelled=new_appointment.Cancelled,
            TokenID=new_appointment.TokenID,
            AppointmentStatus=new_appointment.AppointmentStatus
        )
        
        return DashboardAppointmentResponse(
            appointment=appointment_response,
            patient=patient_dict,
            is_new_patient=False,
            message=f"Appointment booked successfully for {patient_dict['name']}"
        )
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Error processing quick booking: {str(e)}")