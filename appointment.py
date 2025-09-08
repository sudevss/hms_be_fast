from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, extract
from typing import List, Optional
from datetime import date, datetime, time,timezone
from pydantic import BaseModel, validator
import pytz

from database import get_db
from model import Appointment, DoctorCalendar

router = APIRouter(
    prefix="/appointments",
    tags=["Appointments"]
)

# -------------------- Pydantic Models --------------------

class AppointmentCreate(BaseModel):
    PatientID: int
    DoctorID: int
    FacilityID: int
    DCID: int
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
    DCID: Optional[int] = None
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

# -------------------- CRUD Endpoints --------------------

@router.get("/", response_model=List[AppointmentResponse])
def get_all_appointments(
    facility_id: int = Query(..., alias="FacilityID"),
    skip: int = Query(0, ge=0),
    limit: int = Query(10, le=100),
    db: Session = Depends(get_db)
):
    return (
        db.query(Appointment)
        .filter(Appointment.FacilityID == facility_id)
        .offset(skip)
        .limit(limit)
        .all()
    )


@router.get("/{appointment_id}", response_model=AppointmentResponse)
def get_appointment(
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
    return appt


# @router.post("/", response_model=AppointmentResponse)
# def create_appointment(
#     appointment: AppointmentCreate,
#     db: Session = Depends(get_db)
# ):
#     payload = appointment.dict(exclude_unset=True)

#     # Set default values
#     payload["Cancelled"] = False
#     if "AppointmentStatus" not in payload:
#         payload["AppointmentStatus"] = "Scheduled"

#     # Check for duplicate appointments
#     exists = (
#         db.query(Appointment)
#         .filter(
#             Appointment.PatientID == payload["PatientID"],
#             Appointment.DoctorID == payload["DoctorID"],
#             Appointment.AppointmentDate == payload["AppointmentDate"],
#             Appointment.AppointmentTime == payload["AppointmentTime"],
#             Appointment.FacilityID == payload["FacilityID"]
#         )
#         .first()
#     )
#     if exists:
#         raise HTTPException(400, "Duplicate appointment exists")

#     # TokenID and CheckinTime will be generated during checkin, not during creation
#     payload["TokenID"] = None
#     payload["CheckinTime"] = None

#     try:
#         new_appt = Appointment(**payload)
#         db.add(new_appt)
#         db.commit()
#         db.refresh(new_appt)
#         return new_appt
#     except Exception as e:
#         db.rollback()
#         raise HTTPException(500, f"Error creating appointment: {str(e)}")


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
        # Convert today back to UTC for database comparison
        today_utc_start = local_tz.localize(datetime.combine(today, datetime.min.time())).astimezone(timezone.utc)
        today_utc_end = local_tz.localize(datetime.combine(today, datetime.max.time())).astimezone(timezone.utc)
        
        count = (
            db.query(func.count(Appointment.AppointmentID))
            .filter(
                Appointment.FacilityID == facility_id,
                Appointment.TokenID.like(f"{prefix}%"),
                Appointment.TokenID.isnot(None),
                Appointment.CheckinTime >= today_utc_start,
                Appointment.CheckinTime <= today_utc_end
            )
            .scalar() or 0
        )
        
        # Generate simple token
        token_id = f"{prefix}{count + 1}"
        
        # Handle race conditions
        max_retries = 5
        for attempt in range(max_retries):
            test_token = f"{prefix}{count + 1 + attempt}"
            
            # Check if this token exists today at this facility
            existing = (
                db.query(Appointment)
                .filter(
                    Appointment.TokenID == test_token,
                    Appointment.FacilityID == facility_id,
                    Appointment.CheckinTime >= today_utc_start,
                    Appointment.CheckinTime <= today_utc_end
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
    Cancel an appointment by setting Cancelled=True and updating status
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

    # Apply updates
    for field_name, new_value in filtered_data.items():
        setattr(appt, field_name, new_value)

    try:
        db.commit()
        db.refresh(appt)
        return appt
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
    db.delete(appt)
    db.commit()

    return {"detail": "Deleted successfully"}



