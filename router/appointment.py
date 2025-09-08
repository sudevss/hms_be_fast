from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, extract, and_
from typing import List, Optional
from datetime import date, datetime, time,timezone
from pydantic import BaseModel, validator
from model import Appointment, Patients, Doctors, DoctorSchedule, DoctorBookedSlots
import pytz

from database import get_db
from  router.new_booking import update_slot_booking_status   # ✅ import the slot updater

router = APIRouter(
    prefix="/appointments",
    tags=["Appointments"]
)

# -------------------- Pydantic Models --------------------

class AppointmentCreate(BaseModel):
    PatientID: int
    DoctorID: int
    FacilityID: int
    AppointmentDate: date
    AppointmentTime: time
    Reason: str
    AppointmentMode: str
    AppointmentStatus: Optional[str] = "Scheduled"

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

    class Config:
        from_attributes = True


class AppointmentUpdate(BaseModel):
    DoctorID: Optional[int] = None
    AppointmentDate: Optional[date] = None
    AppointmentTime: Optional[time] = None
    Reason: Optional[str] = None
    AppointmentMode: Optional[str] = None
    AppointmentStatus: Optional[str] = None

    @validator('AppointmentDate', pre=True)
    def validate_date(cls, v):
        if v is None:
            return v
        try:
            # If it's a string, parse it
            if isinstance(v, str):
                # Handle ISO format dates
                if 'T' in v:
                    v = v.split('T')[0]
                return datetime.strptime(v, '%Y-%m-%d').date()
            if isinstance(v, datetime):
                return v.date()
            if isinstance(v, date):
                return v
        except Exception:
            raise ValueError("Invalid date format. Use YYYY-MM-DD")
        return v

    @validator('AppointmentTime', pre=True)
    def parse_time(cls, v):
        if v is None:
            return v
        
        # If it's already a time object, return as is
        if isinstance(v, time):
            return v.replace(second=0, microsecond=0)
            
        try:
            if isinstance(v, str):
                # Remove timezone info and parse
                v = v.rstrip('Z')
                
                # Check if this looks like an auto-generated timestamp
                # If it has microseconds or seconds, it's likely auto-generated
                if '.' in v or (v.count(':') == 2 and not v.endswith(':00')):
                    # This looks like an auto-generated timestamp
                    # Instead of parsing it, return None to signal it should be ignored
                    return None
                
                # Handle various time formats
                if 'T' in v:
                    # Extract time part from datetime string
                    time_part = v.split('T')[1] if 'T' in v else v
                else:
                    time_part = v
                
                # Parse different time formats
                if '.' in time_part:
                    # Handle microseconds - but this suggests auto-generation
                    time_part = time_part.split('.')[0]
                
                # Try parsing with different formats
                try:
                    parsed_time = datetime.strptime(time_part, '%H:%M:%S').time()
                except ValueError:
                    try:
                        parsed_time = datetime.strptime(time_part, '%H:%M').time()
                    except ValueError:
                        return None  # Invalid format, ignore
                
                return parsed_time.replace(second=0, microsecond=0)
                
            if isinstance(v, datetime):
                return v.time().replace(second=0, microsecond=0)
                
        except Exception:
            return None  # On any parsing error, return None to ignore
        
        return None

    class Config:
        from_attributes = True
        extra = "ignore"


class CheckinRequest(BaseModel):
    pass  # No additional fields needed since FacilityID and AppointmentID come from query params


class CancelRequest(BaseModel):
    reason: Optional[str] = None  # Optional cancellation reason

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
    # New fields
    name: Optional[str] = None  # Patient name
    phone: Optional[str] = None  # Patient phone number
    doctor: Optional[str] = None  # Doctor name
    time_slot: Optional[str] = None  # Formatted time slot
    paid: Optional[bool] = None  # Payment status
    consultation_fee: Optional[float] = None  # Doctor's consultation fee

    class Config:
        from_attributes = True


class CheckinResponse(BaseModel):
    AppointmentID: int
    TokenID: str
    CheckinTime: datetime
    AppointmentStatus: str
    message: str

    class Config:
        from_attributes = True


class CancelResponse(BaseModel):
    AppointmentID: int
    Cancelled: bool
    AppointmentStatus: str
    message: str

    class Config:
        from_attributes = True


class HourlyData(BaseModel):
    hour: int
    count: int


class AppointmentSummary(BaseModel):
    # totalSlots: int
    totalAppointments: int
    totalCheckin: int
    availableSlots: int
    totalWalkInPatients: int


class AppointmentDetailsResponse(BaseModel):
    hourly: List[HourlyData]
    summary: AppointmentSummary

# -------------------- Helper Functions --------------------

def get_available_dcid(db: Session, doctor_id: int, facility_id: int, appointment_date: date, appointment_time: time):
    """
    Find an available DCID from doctor_booked_slots for the given doctor, facility, date and time.
    Creates a new slot if none exists, or finds an unbooked slot.
    """
    # First check if there's an existing unbooked slot for this time
    available_slot = (
        db.query(DoctorBookedSlots)
        .filter(
            DoctorBookedSlots.Doctor_id == doctor_id,
            DoctorBookedSlots.Facility_id == facility_id,
            DoctorBookedSlots.Slot_date == appointment_date,
            DoctorBookedSlots.Start_Time <= appointment_time,
            DoctorBookedSlots.End_Time > appointment_time,
            DoctorBookedSlots.Booked_status == 'Not Booked'
        )
        .first()
    )
    
    if available_slot:
        return available_slot.DCID
    
    # If no available slot, check if doctor has schedule for this time
    weekday = appointment_date.strftime('%A')  # Get day name (Monday, Tuesday, etc.)
    
    schedule = (
        db.query(DoctorSchedule)
        .filter(
            DoctorSchedule.Doctor_id == doctor_id,
            DoctorSchedule.Facility_id == facility_id,
            DoctorSchedule.Start_Date <= appointment_date,
            DoctorSchedule.End_Date >= appointment_date,
            DoctorSchedule.WeekDay == weekday,
            DoctorSchedule.Slot_Start_Time <= appointment_time,
            DoctorSchedule.Slot_End_Time > appointment_time
        )
        .first()
    )
    
    if not schedule:
        raise HTTPException(
            status_code=400, 
            detail=f"Doctor is not available at {appointment_time} on {weekday}s"
        )
    
    # Create a new booked slot
    new_slot = DoctorBookedSlots(
        Doctor_id=doctor_id,
        Facility_id=facility_id,
        Slot_date=appointment_date,
        Start_Time=schedule.Slot_Start_Time,
        End_Time=schedule.Slot_End_Time,
        Booked_status='Not Booked'  # Will be set to 'Y' when appointment is created
    )
    
    db.add(new_slot)
    db.flush()  # Get the DCID without committing
    
    return new_slot.DCID


def validate_doctor_availability(db: Session, doctor_id: int, facility_id: int, appointment_date: date, appointment_time: time):
    """
    Validate if doctor is available at the requested time based on their schedule.
    """
    weekday = appointment_date.strftime('%A')
    
    schedule = (
        db.query(DoctorSchedule)
        .filter(
            DoctorSchedule.Doctor_id == doctor_id,
            DoctorSchedule.Facility_id == facility_id,
            DoctorSchedule.Start_Date <= appointment_date,
            DoctorSchedule.End_Date >= appointment_date,
            DoctorSchedule.WeekDay == weekday,
            DoctorSchedule.Slot_Start_Time <= appointment_time,
            DoctorSchedule.Slot_End_Time > appointment_time
        )
        .first()
    )
    
    return schedule is not None

# -------------------- CRUD Endpoints --------------------

@router.get("/", response_model=List[AppointmentResponse])
def get_all_appointments(
    facility_id: int = Query(..., alias="FacilityID"),
    date: date = Query(...),
    # starts_from: int = Query(0, ge=0),
    # max_results: int = Query(10, le=100),
    db: Session = Depends(get_db)
):
    # Modified query to include joins with Patients and Doctors tables
    results = (
        db.query(
            Appointment,
            Patients.firstname.label('patient_firstname'),
            Patients.lastname.label('patient_lastname'),
            Patients.contact_number.label('patient_phone'),
            Patients.is_paid.label('patient_paid'),
            Doctors.firstname.label('doctor_firstname'),
            Doctors.lastname.label('doctor_lastname'),
            Doctors.consultation_fee.label('doctor_consultation_fee')
        )
        .join(Patients, Appointment.PatientID == Patients.id)
        .join(Doctors, Appointment.DoctorID == Doctors.id)
        .filter(Appointment.FacilityID == facility_id)
        .filter(Appointment.AppointmentDate == date)
        .filter(Appointment.CheckinTime == None)
        # .offset(starts_from)
        # .limit(max_results)
        .all()
    )
    
    # Format the results to include the new fields
    formatted_results = []
    for appointment, patient_firstname, patient_lastname, patient_phone, patient_paid, doctor_firstname, doctor_lastname, doctor_consultation_fee in results:
        # Create appointment dict from the appointment object
        appointment_dict = {
            "AppointmentID": appointment.AppointmentID,
            "PatientID": appointment.PatientID,
            "DoctorID": appointment.DoctorID,
            "FacilityID": appointment.FacilityID,
            "DCID": appointment.DCID,
            "AppointmentDate": appointment.AppointmentDate,
            "AppointmentTime": appointment.AppointmentTime,
            "Reason": appointment.Reason,
            "AppointmentMode": appointment.AppointmentMode,
            "CheckinTime": appointment.CheckinTime,
            "Cancelled": appointment.Cancelled,
            "TokenID": appointment.TokenID,
            "AppointmentStatus": appointment.AppointmentStatus,
            # Add the new fields
            "name": f"{patient_firstname} {patient_lastname}".strip(),
            "phone": patient_phone,
            "doctor": f"{doctor_firstname} {doctor_lastname}".strip(),
            "time_slot": appointment.AppointmentTime.strftime("%H:%M") if appointment.AppointmentTime else None,
            "paid": patient_paid,
            "consultation_fee": float(doctor_consultation_fee) if doctor_consultation_fee else None
        }
        formatted_results.append(AppointmentResponse(**appointment_dict))
    
    return formatted_results


@router.get("/{appointment_id}", response_model=AppointmentResponse)
def get_appointment(
    appointment_id: int,
    facility_id: int = Query(..., alias="FacilityID"),
    db: Session = Depends(get_db)
):
    # Use the same join logic as get_all_appointments
    result = (
        db.query(
            Appointment,
            Patients.firstname.label('patient_firstname'),
            Patients.lastname.label('patient_lastname'),
            Patients.contact_number.label('patient_phone'),
            Patients.is_paid.label('patient_paid'),
            Doctors.firstname.label('doctor_firstname'),
            Doctors.lastname.label('doctor_lastname'),
            Doctors.consultation_fee.label('doctor_consultation_fee')
        )
        .join(Patients, Appointment.PatientID == Patients.id)
        .join(Doctors, Appointment.DoctorID == Doctors.id)
        .filter(
            Appointment.AppointmentID == appointment_id,
            Appointment.FacilityID == facility_id
        )
        .first()
    )
    
    if not result:
        raise HTTPException(status_code=404, detail="Appointment not found")
    
    # Unpack the result
    appointment, patient_firstname, patient_lastname, patient_phone, patient_paid, doctor_firstname, doctor_lastname, doctor_consultation_fee = result
    
    # Format the result to include the new fields
    appointment_dict = {
        "AppointmentID": appointment.AppointmentID,
        "PatientID": appointment.PatientID,
        "DoctorID": appointment.DoctorID,
        "FacilityID": appointment.FacilityID,
        "DCID": appointment.DCID,
        "AppointmentDate": appointment.AppointmentDate,
        "AppointmentTime": appointment.AppointmentTime,
        "Reason": appointment.Reason,
        "AppointmentMode": appointment.AppointmentMode,
        "CheckinTime": appointment.CheckinTime,
        "Cancelled": appointment.Cancelled,
        "TokenID": appointment.TokenID,
        "AppointmentStatus": appointment.AppointmentStatus,
        # Add the new fields
        "name": f"{patient_firstname} {patient_lastname}".strip(),
        "phone": patient_phone,
        "doctor": f"{doctor_firstname} {doctor_lastname}".strip(),
        "time_slot": appointment.AppointmentTime.strftime("%H:%M") if appointment.AppointmentTime else None,
        "paid": patient_paid,
        "consultation_fee": float(doctor_consultation_fee) if doctor_consultation_fee else None
    }
    
    return AppointmentResponse(**appointment_dict)


@router.post("/", response_model=AppointmentResponse)
def create_appointment(
    appointment: AppointmentCreate,
    db: Session = Depends(get_db)
):
    payload = appointment.dict(exclude_unset=True)

    # Set default values
    payload["Cancelled"] = False
    if "AppointmentStatus" not in payload:
        payload["AppointmentStatus"] = "Scheduled"

    # Validate doctor availability using new schedule system
    if not validate_doctor_availability(
        db, 
        payload["DoctorID"], 
        payload["FacilityID"], 
        payload["AppointmentDate"], 
        payload["AppointmentTime"]
    ):
        raise HTTPException(
            status_code=400, 
            detail="Doctor is not available at the requested time"
        )

    # Check for duplicate appointments
    exists = (
        db.query(Appointment)
        .filter(
            Appointment.PatientID == payload["PatientID"],
            Appointment.DoctorID == payload["DoctorID"],
            Appointment.AppointmentDate == payload["AppointmentDate"],
            Appointment.AppointmentTime == payload["AppointmentTime"],
            Appointment.FacilityID == payload["FacilityID"]
        )
        .first()
    )
    if exists:
        raise HTTPException(400, "Duplicate appointment exists")

    try:
        # Get or create DCID from the new booked slots system
        dcid = get_available_dcid(
            db, 
            payload["DoctorID"], 
            payload["FacilityID"], 
            payload["AppointmentDate"], 
            payload["AppointmentTime"]
        )
        payload["DCID"] = dcid

        # TokenID and CheckinTime will be generated during checkin, not during creation
        payload["TokenID"] = None
        payload["CheckinTime"] = None

        new_appt = Appointment(**payload)
        db.add(new_appt)
        
        # Mark the slot as booked
        booked_slot = db.query(DoctorBookedSlots).filter(DoctorBookedSlots.DCID == dcid).first()
        if booked_slot:
            booked_slot.Booked_status = 'Booked'
        
        db.commit()
        db.refresh(new_appt)
        
        # Fetch the created appointment with joined data (same logic as get_appointment)
        result = (
            db.query(
                Appointment,
                Patients.firstname.label('patient_firstname'),
                Patients.lastname.label('patient_lastname'),
                Patients.contact_number.label('patient_phone'),
                Patients.is_paid.label('patient_paid'),
                Doctors.firstname.label('doctor_firstname'),
                Doctors.lastname.label('doctor_lastname'),
                Doctors.consultation_fee.label('doctor_consultation_fee')
            )
            .join(Patients, Appointment.PatientID == Patients.id)
            .join(Doctors, Appointment.DoctorID == Doctors.id)
            .filter(Appointment.AppointmentID == new_appt.AppointmentID)
            .first()
        )
        
        if not result:
            raise HTTPException(status_code=500, detail="Failed to fetch created appointment")
        
        # Unpack the result
        appointment, patient_firstname, patient_lastname, patient_phone, patient_paid, doctor_firstname, doctor_lastname, doctor_consultation_fee = result
        
        # Format the result to include the new fields
        appointment_dict = {
            "AppointmentID": appointment.AppointmentID,
            "PatientID": appointment.PatientID,
            "DoctorID": appointment.DoctorID,
            "FacilityID": appointment.FacilityID,
            "DCID": appointment.DCID,
            "AppointmentDate": appointment.AppointmentDate,
            "AppointmentTime": appointment.AppointmentTime,
            "Reason": appointment.Reason,
            "AppointmentMode": appointment.AppointmentMode,
            "CheckinTime": appointment.CheckinTime,
            "Cancelled": appointment.Cancelled,
            "TokenID": appointment.TokenID,
            "AppointmentStatus": appointment.AppointmentStatus,
            # Add the new fields
            "name": f"{patient_firstname} {patient_lastname}".strip(),
            "phone": patient_phone,
            "doctor": f"{doctor_firstname} {doctor_lastname}".strip(),
            "time_slot": appointment.AppointmentTime.strftime("%H:%M") if appointment.AppointmentTime else None,
            "paid": patient_paid,
            "consultation_fee": float(doctor_consultation_fee) if doctor_consultation_fee else None
        }
        
        return AppointmentResponse(**appointment_dict)
        
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Error creating appointment: {str(e)}")
@router.post("/{appointment_id}/checkin", response_model=CheckinResponse)
def checkin_appointment(
    appointment_id: int,
    facility_id: int = Query(..., alias="FacilityID"),
    db: Session = Depends(get_db)
):
    """
    This version requires database schema change to allow TokenID uniqueness 
    per facility per day instead of global uniqueness
    """
    # Find the appointment
    appt = (
        db.query(Appointment)
        .filter(
            Appointment.AppointmentID == appointment_id,
            Appointment.FacilityID == facility_id
        )
        .first()
    )
    
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    
    # Check if already checked in
    if appt.CheckinTime is not None:
        raise HTTPException(status_code=400, detail="Appointment already checked in")
    
    # Check if appointment is cancelled
    if appt.Cancelled:
        raise HTTPException(status_code=400, detail="Cannot checkin cancelled appointment")
    
    try:
        # Generate TokenID based on appointment mode
        mode = appt.AppointmentMode.lower() if appt.AppointmentMode else ""
        prefix = "A" if mode == "a" else "W" if mode == "w" else "X"
        
        # Get current times
        utc_now = datetime.now(timezone.utc)
        local_tz = pytz.timezone('Asia/Kolkata')  # Indian Standard Time
        local_now = utc_now.astimezone(local_tz)
        
        # Use local date for token counting (this ensures tokens are consistent with user's day)
        today = local_now.date()
        
        # Count existing tokens with the same prefix checked in TODAY at THIS FACILITY
        # Since you have AppointmentDate field, we can use that for more accurate token counting
        count = (
            db.query(func.count(Appointment.AppointmentID))
            .filter(
                Appointment.FacilityID == facility_id,
                Appointment.TokenID.like(f"{prefix}%"),
                Appointment.TokenID.isnot(None),
                Appointment.AppointmentDate == today  # Use AppointmentDate from your model
            )
            .scalar() or 0
        )
        
        # Generate simple token
        token_id = f"{prefix}{count + 1}"
        
        # Handle race conditions - check against your unique constraint
        max_retries = 5
        for attempt in range(max_retries):
            test_token = f"{prefix}{count + 1 + attempt}"
            
            # Check if this token exists today at this facility (respecting your unique constraint)
            existing = (
                db.query(Appointment)
                .filter(
                    Appointment.TokenID == test_token,
                    Appointment.FacilityID == facility_id,
                    Appointment.AppointmentDate == today  # This matches your unique constraint
                )
                .first()
            )
            
            if not existing:
                token_id = test_token
                break
        
        # Store UTC time in database (for consistency across servers)
        appt.TokenID = token_id
        appt.CheckinTime = utc_now
        appt.AppointmentStatus = "Completed"
        db.commit()
        db.refresh(appt)
        
        # Return local time in response (what user expects to see)
        return CheckinResponse(
            AppointmentID=appt.AppointmentID,
            TokenID=token_id,
            CheckinTime=local_now.replace(tzinfo=None),  # Remove timezone info, keep local time
            AppointmentStatus="Completed",
            message="Patient checked in successfully"
        )
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error during checkin: {str(e)}")
@router.post("/{appointment_id}/cancel", response_model=CancelResponse)
def cancel_appointment(
    appointment_id: int,
    cancel_request: CancelRequest = CancelRequest(),
    facility_id: int = Query(..., alias="FacilityID"),
    db: Session = Depends(get_db)
):
    """
    Cancel an appointment by setting Cancelled=True and updating status.
    Also frees up the booked slot.
    """
    # Find the appointment
    appt = (
        db.query(Appointment)
        .filter(
            Appointment.AppointmentID == appointment_id,
            Appointment.FacilityID == facility_id
        )
        .first()
    )

    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")

    # Check if already cancelled
    if appt.Cancelled:
        raise HTTPException(status_code=400, detail="Appointment is already cancelled")

    # Check if already checked in
    if appt.CheckinTime is not None:
        raise HTTPException(status_code=400, detail="Cannot cancel checked-in appointment")

    try:
        # Update appointment to cancelled status
        appt.Cancelled = True
        appt.AppointmentStatus = "Cancelled"

        # Free up the booked slot
        if appt.DCID:
            success, error = update_slot_booking_status(db, appt.DCID, status="Not Booked")
            if not success:
                raise HTTPException(status_code=500, detail=f"Failed to free slot: {error}")

        # Optionally store cancellation reason if your model supports it
        # appt.CancellationReason = cancel_request.reason

        db.commit()
        db.refresh(appt)

        return CancelResponse(
            AppointmentID=appt.AppointmentID,
            Cancelled=True,
            AppointmentStatus="Cancelled",
            message="Appointment cancelled successfully"
        )

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error cancelling appointment: {str(e)}")

@router.patch("/{appointment_id}", response_model=AppointmentResponse)
def update_appointment(
    appointment_id: int,
    updated: AppointmentUpdate,
    facility_id: int = Query(..., alias="FacilityID"),
    db: Session = Depends(get_db)
):
    appt = (
        db.query(Appointment)
        .filter(
            Appointment.AppointmentID == appointment_id,
            Appointment.FacilityID == facility_id
        )
        .first()
    )
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")

    # Get the raw request data
    update_data = updated.dict(exclude_unset=True, exclude_none=True)

    # Very strict filtering - only update fields that are explicitly set with valid values
    filtered_data = {}
    current_time = datetime.now().time()
    current_date = date.today()
    
    for k, v in update_data.items():
        # Skip if value is None
        if v is None:
            continue
        
        # Skip string fields with placeholder values
        if isinstance(v, str) and (v.strip() == "" or v.lower() == "string"):
            continue
        
        # Skip integer fields with value 0 - these are likely defaults from frontend
        if isinstance(v, int) and v == 0:
            continue
        
        # Skip empty lists
        if isinstance(v, list) and len(v) == 0:
            continue
        
        # Special handling for AppointmentDate
        if k == "AppointmentDate" and isinstance(v, date):
            current_db_date = getattr(appt, k)
            # Skip if it's the same as current DB value OR if it's today's date (likely default)
            if current_db_date == v or v == current_date:
                continue
        
        # Special handling for AppointmentTime - be very strict
        if k == "AppointmentTime":
            # If the validator returned None (indicating auto-generated timestamp), skip
            if v is None:
                continue
                
            if isinstance(v, time):
                current_db_time = getattr(appt, k)
                
                # Skip if it's the same as current DB value
                current_time_normalized = current_db_time.replace(second=0, microsecond=0)
                new_time_normalized = v.replace(second=0, microsecond=0)
                if current_time_normalized == new_time_normalized:
                    continue
                
                # Skip if the time looks like it's generated automatically
                # Check if it's very close to current time (within 5 minutes) - likely auto-generated
                current_system_time = datetime.now().time()
                current_system_minutes = current_system_time.hour * 60 + current_system_time.minute
                new_time_minutes = v.hour * 60 + v.minute
                
                # If the time is within 5 minutes of current system time, it's likely auto-generated
                if abs(current_system_minutes - new_time_minutes) <= 5:
                    continue
                
                # Additional check: Skip if it's not a "round" time (like 08:30, 14:00, etc.)
                # User-set times are usually round numbers, auto-generated ones are not
                if v.minute % 5 != 0:  # Not a 5-minute interval
                    continue
            else:
                continue  # Not a time object, skip
        
        # For AppointmentMode, skip "string" or single character defaults
        if k == "AppointmentMode" and isinstance(v, str):
            if v.lower() == "string" or len(v.strip()) == 0:
                continue
        
        # For AppointmentStatus, skip "string" default
        if k == "AppointmentStatus" and isinstance(v, str):
            if v.lower() == "string":
                continue
        
        # For other fields, only update if the value is actually different from current
        current_value = getattr(appt, k, None)
        if current_value == v:
            continue
        
        filtered_data[k] = v

    if not filtered_data:
        raise HTTPException(status_code=400, detail="No valid fields provided for update")

    # Handle doctor/time/date changes - need to update DCID and slot booking
    needs_slot_update = any(k in filtered_data for k in ['DoctorID', 'AppointmentDate', 'AppointmentTime'])
    old_dcid = appt.DCID if needs_slot_update else None

    # Validate new doctor availability if doctor/time/date is being changed
    if needs_slot_update:
        new_doctor_id = filtered_data.get('DoctorID', appt.DoctorID)
        new_date = filtered_data.get('AppointmentDate', appt.AppointmentDate)
        new_time = filtered_data.get('AppointmentTime', appt.AppointmentTime)
        
        if not validate_doctor_availability(db, new_doctor_id, facility_id, new_date, new_time):
            raise HTTPException(
                status_code=400, 
                detail="Doctor is not available at the requested time"
            )
        
        # Get new DCID
        new_dcid = get_available_dcid(db, new_doctor_id, facility_id, new_date, new_time)
        filtered_data['DCID'] = new_dcid

    # Apply updates
    for field_name, new_value in filtered_data.items():
        setattr(appt, field_name, new_value)

    try:
        # Handle slot booking changes
        if needs_slot_update:
            # Free up old slot
            if old_dcid:
                old_slot = db.query(DoctorBookedSlots).filter(DoctorBookedSlots.DCID == old_dcid).first()
                if old_slot:
                    old_slot.Booked_status = 'Not Booked'
            
            # Book new slot
            new_slot = db.query(DoctorBookedSlots).filter(DoctorBookedSlots.DCID == filtered_data['DCID']).first()
            if new_slot:
                new_slot.Booked_status = 'Booked'

        db.commit()
        db.refresh(appt)
        
        # Fetch the updated appointment with joined data (same as get_appointment)
        result = (
            db.query(
                Appointment,
                Patients.firstname.label('patient_firstname'),
                Patients.lastname.label('patient_lastname'),
                Patients.contact_number.label('patient_phone'),
                Patients.is_paid.label('patient_paid'),
                Doctors.firstname.label('doctor_firstname'),
                Doctors.lastname.label('doctor_lastname'),
                Doctors.consultation_fee.label('doctor_consultation_fee')
            )
            .join(Patients, Appointment.PatientID == Patients.id)
            .join(Doctors, Appointment.DoctorID == Doctors.id)
            .filter(
                Appointment.AppointmentID == appointment_id,
                Appointment.FacilityID == facility_id
            )
            .first()
        )
        
        if not result:
            raise HTTPException(status_code=404, detail="Updated appointment not found")
        
        # Unpack the result
        appointment, patient_firstname, patient_lastname, patient_phone, patient_paid, doctor_firstname, doctor_lastname, doctor_consultation_fee = result
        
        # Format the result to include the new fields
        appointment_dict = {
            "AppointmentID": appointment.AppointmentID,
            "PatientID": appointment.PatientID,
            "DoctorID": appointment.DoctorID,
            "FacilityID": appointment.FacilityID,
            "DCID": appointment.DCID,
            "AppointmentDate": appointment.AppointmentDate,
            "AppointmentTime": appointment.AppointmentTime,
            "Reason": appointment.Reason,
            "AppointmentMode": appointment.AppointmentMode,
            "CheckinTime": appointment.CheckinTime,
            "Cancelled": appointment.Cancelled,
            "TokenID": appointment.TokenID,
            "AppointmentStatus": appointment.AppointmentStatus,
            # Add the new fields
            "name": f"{patient_firstname} {patient_lastname}".strip(),
            "phone": patient_phone,
            "doctor": f"{doctor_firstname} {doctor_lastname}".strip(),
            "time_slot": appointment.AppointmentTime.strftime("%H:%M") if appointment.AppointmentTime else None,
            "paid": patient_paid,
            "consultation_fee": float(doctor_consultation_fee) if doctor_consultation_fee else None
        }
        
        return AppointmentResponse(**appointment_dict)
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@router.delete("/{appointment_id}")
def delete_appointment(
    appointment_id: int,
    facility_id: int = Query(..., alias="FacilityID"),
    db: Session = Depends(get_db)
):
    appt = (
        db.query(Appointment)
        .filter(
            Appointment.AppointmentID == appointment_id,
            Appointment.FacilityID == facility_id
        )
        .first()
    )
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    
    try:
        # Free up the booked slot before deleting
        if appt.DCID:
            booked_slot = db.query(DoctorBookedSlots).filter(DoctorBookedSlots.DCID == appt.DCID).first()
            if booked_slot:
                booked_slot.Booked_status = 'Not Booked'  # Changed from 'N' to 'Not Booked'
        
        db.delete(appt)
        db.commit()
        return {"detail": "Deleted successfully"}
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error deleting appointment: {str(e)}")


# -------------------- Additional Endpoints for New Schedule System --------------------

# @router.get("/available-slots/")
# def get_available_slots(
#     doctor_id: int = Query(...),
#     facility_id: int = Query(..., alias="FacilityID"),
#     date: date = Query(...),
#     db: Session = Depends(get_db)
# ):
#     """
#     Get available time slots for a doctor on a specific date.
#     """
#     weekday = date.strftime('%A')
    
#     # Get doctor's schedule for the day
#     schedules = (
#         db.query(DoctorSchedule)
#         .filter(
#             DoctorSchedule.Doctor_id == doctor_id,
#             DoctorSchedule.Facility_id == facility_id,
#             DoctorSchedule.Start_Date <= date,
#             DoctorSchedule.End_Date >= date,
#             DoctorSchedule.WeekDay == weekday
#         )
#         .all()
#     )
    
#     if not schedules:
#         return {"available_slots": [], "message": f"Doctor is not scheduled on {weekday}s"}
    
#     # Get booked slots for the day
#     booked_slots = (
#         db.query(DoctorBookedSlots)
#         .filter(
#             DoctorBookedSlots.Doctor_id == doctor_id,
#             DoctorBookedSlots.Facility_id == facility_id,
#             DoctorBookedSlots.Slot_date == date,
#             DoctorBookedSlots.Booked_status == 'Y'
#         )
#         .all()
#     )
    
#     available_slots = []
#     for schedule in schedules:
#         # Check if this time slot is booked
#         is_booked = any(
#             slot.Start_Time <= schedule.Slot_Start_Time < slot.End_Time
#             for slot in booked_slots
#         )
        
#         if not is_booked:
#             available_slots.append({
#                 "window_num": schedule.Window_Num,
#                 "start_time": schedule.Slot_Start_Time.strftime("%H:%M"),
#                 "end_time": schedule.Slot_End_Time.strftime("%H:%M"),
#                 "time_slot": f"{schedule.Slot_Start_Time.strftime('%H:%M')} - {schedule.Slot_End_Time.strftime('%H:%M')}"
#             })
    
#     return {
#         "available_slots": available_slots,
#         "total_slots": len(schedules),
#         "available_count": len(available_slots),
#         "booked_count": len(booked_slots)
#     }


@router.get("/doctor-schedule/")
def get_doctor_schedule(
    doctor_id: int = Query(...),
    facility_id: int = Query(..., alias="FacilityID"),
    start_date: date = Query(...),
    end_date: date = Query(...),
    db: Session = Depends(get_db)
):
    """
    Get doctor's schedule for a date range.
    """
    schedules = (
        db.query(DoctorSchedule)
        .filter(
            DoctorSchedule.Doctor_id == doctor_id,
            DoctorSchedule.Facility_id == facility_id,
            DoctorSchedule.Start_Date <= end_date,
            DoctorSchedule.End_Date >= start_date
        )
        .all()
    )
    
    schedule_data = []
    for schedule in schedules:
        schedule_data.append({
            "weekday": schedule.WeekDay,
            "window_num": schedule.Window_Num,
            "start_time": schedule.Slot_Start_Time.strftime("%H:%M"),
            "end_time": schedule.Slot_End_Time.strftime("%H:%M"),
            "schedule_period": {
                "start_date": schedule.Start_Date.strftime("%Y-%m-%d"),
                "end_date": schedule.End_Date.strftime("%Y-%m-%d")
            }
        })
    
    return {
        "doctor_id": doctor_id,
        "facility_id": facility_id,
        "schedules": schedule_data
    }