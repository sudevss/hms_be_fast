from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, extract, and_
from typing import List, Optional
from datetime import date, datetime, time, timezone
from pydantic import BaseModel, validator
from model import Appointment, Patients, Doctors, DoctorSchedule, DoctorBookedSlots, PatientDiagnosis
import pytz

from database import get_db
from router.new_booking import update_slot_booking_status
from auth_middleware import get_current_user, require_roles, CurrentUser

router = APIRouter(
    prefix="/appointments",
    tags=["Appointments"]
)

# -------------------- Pydantic Models --------------------

class AppointmentCreate(BaseModel):
    patient_id: int
    doctor_id: int
    facility_id: int
    appointment_date: date
    appointment_time: time
    reason: str
    appointment_mode: str
    appointment_status: Optional[str] = "Scheduled"

    @validator('appointment_time', pre=True)
    def parse_time(cls, v):
        if v is None:
            raise ValueError("appointment_time is required")
        try:
            if isinstance(v, str):
                v = v.rstrip('Z')
                return datetime.fromisoformat(f"2000-01-01T{v}").time().replace(second=0, microsecond=0)
            if isinstance(v, datetime):
                return v.time().replace(second=0, microsecond=0)
            if isinstance(v, time):
                return v.replace(second=0, microsecond=0)
        except Exception:
            raise ValueError("Invalid format for appointment_time")
        raise ValueError("Invalid format for appointment_time")

    class Config:
        from_attributes = True


class AppointmentUpdate(BaseModel):
    doctor_id: Optional[int] = None
    appointment_date: Optional[date] = None
    appointment_time: Optional[time] = None
    reason: Optional[str] = None
    appointment_mode: Optional[str] = None
    appointment_status: Optional[str] = None

    @validator('appointment_date', pre=True)
    def validate_date(cls, v):
        if v is None:
            return v
        try:
            if isinstance(v, str):
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

    @validator('appointment_time', pre=True)
    def parse_time(cls, v):
        if v is None:
            return v
        
        if isinstance(v, time):
            return v.replace(second=0, microsecond=0)
            
        try:
            if isinstance(v, str):
                v = v.rstrip('Z')
                
                if '.' in v or (v.count(':') == 2 and not v.endswith(':00')):
                    return None
                
                if 'T' in v:
                    time_part = v.split('T')[1] if 'T' in v else v
                else:
                    time_part = v
                
                if '.' in time_part:
                    time_part = time_part.split('.')[0]
                
                try:
                    parsed_time = datetime.strptime(time_part, '%H:%M:%S').time()
                except ValueError:
                    try:
                        parsed_time = datetime.strptime(time_part, '%H:%M').time()
                    except ValueError:
                        return None
                
                return parsed_time.replace(second=0, microsecond=0)
                
            if isinstance(v, datetime):
                return v.time().replace(second=0, microsecond=0)
                
        except Exception:
            return None
        
        return None

    class Config:
        from_attributes = True
        extra = "ignore"


class CheckinRequest(BaseModel):
    pass


class CancelRequest(BaseModel):
    reason: Optional[str] = None

    class Config:
        from_attributes = True


class PaymentRequest(BaseModel):
    payment_status: bool = False
    payment_method: Optional[str] = None
    payment_comments: Optional[str] = None

    class Config:
        from_attributes = True


class CompleteRequest(BaseModel):
    pass


class AppointmentResponse(BaseModel):
    appointment_id: int
    patient_id: int
    doctor_id: int
    facility_id: int
    dcid: int
    appointment_date: date
    appointment_time: time
    reason: str
    appointment_mode: str
    checkin_time: Optional[datetime] = None
    cancelled: Optional[bool] = None
    token_id: Optional[str] = None
    appointment_status: Optional[str] = None
    name: Optional[str] = None
    phone: Optional[str] = None
    doctor: Optional[str] = None
    time_slot: Optional[str] = None
    paid: Optional[bool] = None
    consultation_fee: Optional[float] = None
    payment_method: Optional[str] = None
    payment_comments: Optional[str] = None
    diagnosis_id: Optional[int] = None

    class Config:
        from_attributes = True


class CheckinResponse(BaseModel):
    appointment_id: int
    token_id: str
    checkin_time: datetime
    appointment_status: str
    message: str

    class Config:
        from_attributes = True


class CancelResponse(BaseModel):
    appointment_id: int
    cancelled: bool
    appointment_status: str
    message: str

    class Config:
        from_attributes = True


class PaymentResponse(BaseModel):
    appointment_id: int
    payment_status: bool
    payment_method: Optional[str]
    payment_comments: Optional[str]
    appointment_status: str
    message: str

    class Config:
        from_attributes = True


class CompleteResponse(BaseModel):
    appointment_id: int
    appointment_status: str
    message: str

    class Config:
        from_attributes = True


class HourlyData(BaseModel):
    hour: int
    count: int


class AppointmentSummary(BaseModel):
    totalAppointments: int
    totalCheckin: int
    availableSlots: int
    totalWalkInPatients: int


class AppointmentDetailsResponse(BaseModel):
    hourly: List[HourlyData]
    summary: AppointmentSummary

class PatientVisitReportResponse(BaseModel):
    appointment_id: int
    patient_id: int
    doctor_id: int
    facility_id: int
    dcid: Optional[int] = None
    appointment_date: date
    appointment_time: time
    reason: Optional[str] = None
    appointment_mode: Optional[str] = None
    checkin_time: Optional[datetime] = None
    cancelled: Optional[bool] = False
    token_id: Optional[str] = None
    appointment_status: Optional[str] = None
    name: str
    phone: str
    doctor: str
    time_slot: Optional[str] = None
    paid: bool
    consultation_fee: Optional[float] = None
    payment_method: Optional[str] = None
    
    class Config:
        from_attributes = True

class PatientVisitReportsListResponse(BaseModel):
    patient_id: int
    facility_id: int
    patient_name: str
    total_visits: int
    paid_visits: int
    unpaid_visits: int
    visits: List[PatientVisitReportResponse]
    
    class Config:
        from_attributes = True

# -------------------- Helper Functions --------------------

def get_available_dcid(db: Session, doctor_id: int, facility_id: int, appointment_date: date, appointment_time: time):
    """
    Find an available DCID from doctor_booked_slots for the given doctor, facility, date and time.
    Creates a new slot if none exists, or finds an unbooked slot.
    """
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
    
    weekday = appointment_date.strftime('%A')
    
    schedule = (
        db.query(DoctorSchedule)
        .filter(
            DoctorSchedule.doctor_id == doctor_id,
            DoctorSchedule.facility_id == facility_id,
            DoctorSchedule.start_date <= appointment_date,
            DoctorSchedule.end_date >= appointment_date,
            DoctorSchedule.week_day == weekday,
            DoctorSchedule.slot_start_time <= appointment_time,
            DoctorSchedule.slot_end_time > appointment_time
        )
        .first()
    )
    
    if not schedule:
        raise HTTPException(
            status_code=400, 
            detail=f"Doctor is not available at {appointment_time} on {weekday}s"
        )
    
    new_slot = DoctorBookedSlots(
        Doctor_id=doctor_id,
        Facility_id=facility_id,
        Slot_date=appointment_date,
        Start_Time=schedule.slot_start_time,
        End_Time=schedule.slot_end_time,
        Booked_status='Not Booked'
    )
    
    db.add(new_slot)
    db.flush()
    
    return new_slot.DCID


def validate_doctor_availability(db: Session, doctor_id: int, facility_id: int, appointment_date: date, appointment_time: time):
    """
    Validate if doctor is available at the requested time based on their schedule.
    """
    weekday = appointment_date.strftime('%A')
    
    schedule = (
        db.query(DoctorSchedule)
        .filter(
            DoctorSchedule.doctor_id == doctor_id,
            DoctorSchedule.facility_id == facility_id,
            DoctorSchedule.start_date <= appointment_date,
            DoctorSchedule.end_date >= appointment_date,
            DoctorSchedule.week_day == weekday,
            DoctorSchedule.slot_start_time <= appointment_time,
            DoctorSchedule.slot_end_time > appointment_time
        )
        .first()
    )
    
    return schedule is not None

# -------------------- CRUD Endpoints --------------------

@router.get("/", response_model=List[AppointmentResponse])
def get_all_appointments(
    facility_id: int = Query(...),
    date: date = Query(...),
    end_date: Optional[date] = Query(None),
    patient_id: Optional[int] = Query(None),
    appointment_status: Optional[str] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Verify user belongs to the requested facility
    if current_user.facility_id != facility_id and current_user.facility_id != 0:
        raise HTTPException(status_code=403, detail="Access denied. You can only access your facility's data.")
    
    query = (
        db.query(
            Appointment,
            Patients.firstname.label('patient_firstname'),
            Patients.lastname.label('patient_lastname'),
            Patients.contact_number.label('patient_phone'),
            Doctors.firstname.label('doctor_firstname'),
            Doctors.lastname.label('doctor_lastname'),
            Doctors.consultation_fee.label('doctor_consultation_fee'),
            PatientDiagnosis.diagnosis_id.label('diagnosis_id')
        )
        .join(Patients, Appointment.patient_id == Patients.id)
        .join(Doctors, Appointment.doctor_id == Doctors.id)
        .outerjoin(PatientDiagnosis, Appointment.appointment_id == PatientDiagnosis.appointment_id)
        .filter(Appointment.facility_id == facility_id)
    )
    
    # Apply date filtering
    if end_date:
        # Date range filter
        query = query.filter(
            Appointment.AppointmentDate >= date,
            Appointment.AppointmentDate <= end_date
        )
    else:
        # Single date filter
        query = query.filter(Appointment.AppointmentDate == date)
    
    # Apply patient filter if provided
    if patient_id:
        query = query.filter(Appointment.patient_id == patient_id)
    
    if appointment_status:
        status_lower = appointment_status.lower()
        
        if status_lower == "scheduled":
            query = query.filter(
                Appointment.AppointmentStatus == "Scheduled",
                Appointment.CheckinTime == None,
                Appointment.Cancelled == False
            )
        elif status_lower == "waiting":
            query = query.filter(
                Appointment.AppointmentStatus == "Waiting",
                Appointment.CheckinTime != None,
                Appointment.Cancelled == False
            )
        elif status_lower == "completed":
            query = query.filter(
                Appointment.AppointmentStatus == "Completed",
                Appointment.CheckinTime != None,
                Appointment.Cancelled == False
            )
        elif status_lower == "cancelled":
            query = query.filter(
                Appointment.AppointmentStatus == "Cancelled",
                Appointment.Cancelled == True
            )
        else:
            query = query.filter(Appointment.AppointmentStatus == appointment_status)
    else:
        query = query.filter(
            Appointment.AppointmentStatus == "Scheduled",
            Appointment.CheckinTime == None,
            Appointment.Cancelled == False
        )
    
    # Order by most recent appointments first
    query = query.order_by(
        Appointment.AppointmentDate.desc(),
        Appointment.AppointmentTime.desc()
    )
    
    results = query.all()
    
    formatted_results = []
    for appointment, patient_firstname, patient_lastname, patient_phone, doctor_firstname, doctor_lastname, doctor_consultation_fee, diagnosis_id in results:
        appointment_mode_display = appointment.AppointmentMode
        if appointment.AppointmentMode and appointment.AppointmentMode.lower() == 'a':
            appointment_mode_display = 'appointment'
        elif appointment.AppointmentMode and appointment.AppointmentMode.lower() == 'w':
            appointment_mode_display = 'walkin'
        
        appointment_dict = {
            "appointment_id": appointment.appointment_id,
            "patient_id": appointment.patient_id,
            "doctor_id": appointment.doctor_id,
            "facility_id": appointment.facility_id,
            "dcid": appointment.DCID,
            "appointment_date": appointment.AppointmentDate,
            "appointment_time": appointment.AppointmentTime,
            "reason": appointment.Reason,
            "appointment_mode": appointment_mode_display,
            "checkin_time": appointment.CheckinTime,
            "cancelled": appointment.Cancelled,
            "token_id": appointment.TokenID,
            "appointment_status": appointment.AppointmentStatus,
            "name": f"{patient_firstname} {patient_lastname}".strip(),
            "phone": patient_phone,
            "doctor": f"{doctor_firstname} {doctor_lastname}".strip(),
            "time_slot": appointment.AppointmentTime.strftime("%H:%M") if appointment.AppointmentTime else None,
            "paid": True if appointment.payment_status == 1 else False,
            "consultation_fee": float(doctor_consultation_fee) if doctor_consultation_fee else None,
            "payment_method": appointment.payment_method,
            "payment_comments": appointment.payment_comments,
            "diagnosis_id": diagnosis_id
        }
        formatted_results.append(AppointmentResponse(**appointment_dict))
    
    return formatted_results


@router.get("/{appointment_id}", response_model=AppointmentResponse)
def get_appointment(
    appointment_id: int,
    facility_id: int = Query(...),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Verify user belongs to the requested facility
    if current_user.facility_id != facility_id and current_user.facility_id != 0:
        raise HTTPException(status_code=403, detail="Access denied. You can only access your facility's data.")
    
    result = (
        db.query(
            Appointment,
            Patients.firstname.label('patient_firstname'),
            Patients.lastname.label('patient_lastname'),
            Patients.contact_number.label('patient_phone'),
            Doctors.firstname.label('doctor_firstname'),
            Doctors.lastname.label('doctor_lastname'),
            Doctors.consultation_fee.label('doctor_consultation_fee'),
            PatientDiagnosis.diagnosis_id.label('diagnosis_id')
        )
        .join(Patients, Appointment.patient_id == Patients.id)
        .join(Doctors, Appointment.doctor_id == Doctors.id)
        .outerjoin(PatientDiagnosis, Appointment.appointment_id == PatientDiagnosis.appointment_id)
        .filter(
            Appointment.appointment_id == appointment_id,
            Appointment.facility_id == facility_id
        )
        .first()
    )
    
    if not result:
        raise HTTPException(status_code=404, detail="Appointment not found")
    
    appointment, patient_firstname, patient_lastname, patient_phone, doctor_firstname, doctor_lastname, doctor_consultation_fee, diagnosis_id = result
    
    appointment_mode_display = appointment.AppointmentMode
    if appointment.AppointmentMode and appointment.AppointmentMode.lower() == 'a':
        appointment_mode_display = 'appointment'
    elif appointment.AppointmentMode and appointment.AppointmentMode.lower() == 'w':
        appointment_mode_display = 'walkin'
    
    appointment_dict = {
        "appointment_id": appointment.appointment_id,
        "patient_id": appointment.patient_id,
        "doctor_id": appointment.doctor_id,
        "facility_id": appointment.facility_id,
        "dcid": appointment.DCID,
        "appointment_date": appointment.AppointmentDate,
        "appointment_time": appointment.AppointmentTime,
        "reason": appointment.Reason,
        "appointment_mode": appointment_mode_display,
        "checkin_time": appointment.CheckinTime,
        "cancelled": appointment.Cancelled,
        "token_id": appointment.TokenID,
        "appointment_status": appointment.AppointmentStatus,
        "name": f"{patient_firstname} {patient_lastname}".strip(),
        "phone": patient_phone,
        "doctor": f"{doctor_firstname} {doctor_lastname}".strip(),
        "time_slot": appointment.AppointmentTime.strftime("%H:%M") if appointment.AppointmentTime else None,
        "paid": True if appointment.payment_status == 1 else False,
        "consultation_fee": float(doctor_consultation_fee) if doctor_consultation_fee else None,
        "payment_method": appointment.payment_method,
        "payment_comments": appointment.payment_comments,
        "diagnosis_id": diagnosis_id
    }
    
    return AppointmentResponse(**appointment_dict)


@router.post("/", response_model=AppointmentResponse)
def create_appointment(
    appointment: AppointmentCreate,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Verify user belongs to the requested facility
    if current_user.facility_id != appointment.facility_id and current_user.facility_id != 0:
        raise HTTPException(status_code=403, detail="Access denied. You can only access your facility's data.")
    
    payload = appointment.dict(exclude_unset=True)

    payload["Cancelled"] = False
    if "AppointmentStatus" not in payload:
        payload["AppointmentStatus"] = "Scheduled"

    if not validate_doctor_availability(
        db, 
        payload["doctor_id"], 
        payload["facility_id"], 
        payload["appointment_date"], 
        payload["appointment_time"]
    ):
        raise HTTPException(
            status_code=400, 
            detail="Doctor is not available at the requested time"
        )

    exists = (
        db.query(Appointment)
        .filter(
            Appointment.patient_id == payload["patient_id"],
            Appointment.doctor_id == payload["doctor_id"],
            Appointment.AppointmentDate == payload["appointment_date"],
            Appointment.AppointmentTime == payload["appointment_time"],
            Appointment.facility_id == payload["facility_id"]
        )
        .first()
    )
    if exists:
        raise HTTPException(400, "Duplicate appointment exists")

    try:
        dcid = get_available_dcid(
            db, 
            payload["doctor_id"], 
            payload["facility_id"], 
            payload["appointment_date"], 
            payload["appointment_time"]
        )
        payload["DCID"] = dcid

        payload["TokenID"] = None
        payload["CheckinTime"] = None

        new_appt = Appointment(**payload)
        db.add(new_appt)
        
        booked_slot = db.query(DoctorBookedSlots).filter(DoctorBookedSlots.DCID == dcid).first()
        if booked_slot:
            booked_slot.Booked_status = 'Booked'
        
        db.commit()
        db.refresh(new_appt)
        
        result = (
            db.query(
                Appointment,
                Patients.firstname.label('patient_firstname'),
                Patients.lastname.label('patient_lastname'),
                Patients.contact_number.label('patient_phone'),
                Doctors.firstname.label('doctor_firstname'),
                Doctors.lastname.label('doctor_lastname'),
                Doctors.consultation_fee.label('doctor_consultation_fee'),
                PatientDiagnosis.diagnosis_id.label('diagnosis_id')
            )
            .join(Patients, Appointment.patient_id == Patients.id)
            .join(Doctors, Appointment.doctor_id == Doctors.id)
            .outerjoin(PatientDiagnosis, Appointment.appointment_id == PatientDiagnosis.appointment_id)
            .filter(Appointment.appointment_id == new_appt.appointment_id)
            .first()
        )
        
        if not result:
            raise HTTPException(status_code=500, detail="Failed to fetch created appointment")
        
        appointment, patient_firstname, patient_lastname, patient_phone, doctor_firstname, doctor_lastname, doctor_consultation_fee, diagnosis_id = result
        
        appointment_dict = {
            "appointment_id": appointment.appointment_id,
            "patient_id": appointment.patient_id,
            "doctor_id": appointment.doctor_id,
            "facility_id": appointment.facility_id,
            "dcid": appointment.DCID,
            "appointment_date": appointment.AppointmentDate,
            "appointment_time": appointment.AppointmentTime,
            "reason": appointment.Reason,
            "appointment_mode": appointment.AppointmentMode,
            "checkin_time": appointment.CheckinTime,
            "cancelled": appointment.Cancelled,
            "token_id": appointment.TokenID,
            "appointment_status": appointment.AppointmentStatus,
            "name": f"{patient_firstname} {patient_lastname}".strip(),
            "phone": patient_phone,
            "doctor": f"{doctor_firstname} {doctor_lastname}".strip(),
            "time_slot": appointment.AppointmentTime.strftime("%H:%M") if appointment.AppointmentTime else None,
            "paid": True if appointment.payment_status == 1 else False,
            "consultation_fee": float(doctor_consultation_fee) if doctor_consultation_fee else None,
            "payment_comments": appointment.payment_comments,
            "diagnosis_id": diagnosis_id
        }
        
        return AppointmentResponse(**appointment_dict)
        
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Error creating appointment: {str(e)}")


@router.post("/{appointment_id}/checkin", response_model=CheckinResponse)
def checkin_appointment(
    appointment_id: int,
    facility_id: int = Query(...),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Verify user belongs to the requested facility
    if current_user.facility_id != facility_id and current_user.facility_id != 0:
        raise HTTPException(status_code=403, detail="Access denied. You can only access your facility's data.")
    
    appt = (
        db.query(Appointment)
        .filter(
            Appointment.appointment_id == appointment_id,
            Appointment.facility_id == facility_id
        )
        .first()
    )
    
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    
    if appt.CheckinTime is not None:
        raise HTTPException(status_code=400, detail="Appointment already checked in")
    
    if appt.Cancelled:
        raise HTTPException(status_code=400, detail="Cannot checkin cancelled appointment")
    
    try:
        mode = appt.AppointmentMode.lower() if appt.AppointmentMode else ""
        prefix = "A" if mode == "a" else "W" if mode == "w" else "X"
        
        utc_now = datetime.now(timezone.utc)
        local_tz = pytz.timezone('Asia/Kolkata')
        local_now = utc_now.astimezone(local_tz)
        
        today = local_now.date()
        
        count = (
            db.query(func.count(Appointment.appointment_id))
            .filter(
                Appointment.facility_id == facility_id,
                Appointment.TokenID.like(f"{prefix}%"),
                Appointment.TokenID.isnot(None),
                Appointment.AppointmentDate == today
            )
            .scalar() or 0
        )
        
        token_id = f"{prefix}{count + 1}"
        
        max_retries = 5
        for attempt in range(max_retries):
            test_token = f"{prefix}{count + 1 + attempt}"
            
            existing = (
                db.query(Appointment)
                .filter(
                    Appointment.TokenID == test_token,
                    Appointment.facility_id == facility_id,
                    Appointment.AppointmentDate == today
                )
                .first()
            )
            
            if not existing:
                token_id = test_token
                break
        
        appt.TokenID = token_id
        appt.CheckinTime = utc_now
        appt.AppointmentStatus = "Waiting"
        db.commit()
        db.refresh(appt)
        
        return CheckinResponse(
            appointment_id=appt.appointment_id,
            token_id=token_id,
            checkin_time=local_now.replace(tzinfo=None),
            appointment_status="Waiting",
            message="Patient checked in successfully"
        )
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error during checkin: {str(e)}")


@router.post("/{appointment_id}/cancel", response_model=CancelResponse)
def cancel_appointment(
    appointment_id: int,
    cancel_request: CancelRequest = CancelRequest(),
    facility_id: int = Query(...),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Verify user belongs to the requested facility
    if current_user.facility_id != facility_id and current_user.facility_id != 0:
        raise HTTPException(status_code=403, detail="Access denied. You can only access your facility's data.")
    
    appt = (
        db.query(Appointment)
        .filter(
            Appointment.appointment_id == appointment_id,
            Appointment.facility_id == facility_id
        )
        .first()
    )

    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")

    if appt.Cancelled:
        raise HTTPException(status_code=400, detail="Appointment is already cancelled")

    if appt.CheckinTime is not None:
        raise HTTPException(status_code=400, detail="Cannot cancel checked-in appointment")

    try:
        appt.Cancelled = True
        appt.AppointmentStatus = "Cancelled"

        if appt.DCID:
            success, error = update_slot_booking_status(db, appt.DCID, status="Not Booked")
            if not success:
                raise HTTPException(status_code=500, detail=f"Failed to free slot: {error}")

        db.commit()
        db.refresh(appt)

        return CancelResponse(
            appointment_id=appt.appointment_id,
            cancelled=True,
            appointment_status="Cancelled",
            message="Appointment cancelled successfully"
        )

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error cancelling appointment: {str(e)}")

@router.post("/{appointment_id}/payment", response_model=PaymentResponse)
def update_payment_status(
    appointment_id: int,
    payment_request: PaymentRequest,
    facility_id: int = Query(...),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Verify user belongs to the requested facility
    if current_user.facility_id != facility_id and current_user.facility_id != 0:
        raise HTTPException(status_code=403, detail="Access denied. You can only access your facility's data.")
    
    appt = (
        db.query(Appointment)
        .filter(
            Appointment.appointment_id == appointment_id,
            Appointment.facility_id == facility_id
        )
        .first()
    )
    
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    
    if appt.CheckinTime is None:
        raise HTTPException(status_code=400, detail="Patient must be checked in before payment")
    
    if appt.Cancelled:
        raise HTTPException(status_code=400, detail="Cannot process payment for cancelled appointment")

    try:
        patient = db.query(Patients).filter(Patients.id == appt.patient_id).first()
        if patient:
            patient.is_paid = payment_request.payment_status

        if payment_request.payment_method:
            appt.payment_method = payment_request.payment_method
        
        # Add payment comments - handle both adding and clearing
        if payment_request.payment_comments is not None:
            appt.payment_comments = payment_request.payment_comments

        appt.payment_status = payment_request.payment_status
        
        if payment_request.payment_status:
            message = "Payment processed successfully"
        else:
            message = "Payment marked as pending"

        db.commit()
        db.refresh(appt)

        return PaymentResponse(
            appointment_id=appt.appointment_id,
            payment_status=payment_request.payment_status,
            payment_method=payment_request.payment_method,
            payment_comments=appt.payment_comments,  # Return the saved comment
            appointment_status=appt.AppointmentStatus,
            message=message
        )

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error updating payment status: {str(e)}")


@router.post("/{appointment_id}/complete", response_model=CompleteResponse)
def complete_appointment(
    appointment_id: int,
    facility_id: int = Query(...),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Verify user belongs to the requested facility
    if current_user.facility_id != facility_id and current_user.facility_id != 0:
        raise HTTPException(status_code=403, detail="Access denied. You can only access your facility's data.")
    
    appt = (
        db.query(Appointment)
        .filter(
            Appointment.appointment_id == appointment_id,
            Appointment.facility_id == facility_id
        )
        .first()
    )
    
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    
    if appt.Cancelled:
        raise HTTPException(status_code=400, detail="Cannot complete cancelled appointment")
    
    if appt.AppointmentStatus == "Completed":
        raise HTTPException(status_code=400, detail="Appointment is already completed")

    try:
        appt.AppointmentStatus = "Completed"

        db.commit()
        db.refresh(appt)

        return CompleteResponse(
            appointment_id=appt.appointment_id,
            appointment_status="Completed",
            message="Appointment completed successfully"
        )

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error completing appointment: {str(e)}")


@router.patch("/{appointment_id}", response_model=AppointmentResponse)
def update_appointment(
    appointment_id: int,
    updated: AppointmentUpdate,
    facility_id: int = Query(...),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Verify user belongs to the requested facility
    if current_user.facility_id != facility_id and current_user.facility_id != 0:
        raise HTTPException(status_code=403, detail="Access denied. You can only access your facility's data.")
    
    appt = (
        db.query(Appointment)
        .filter(
            Appointment.appointment_id == appointment_id,
            Appointment.facility_id == facility_id
        )
        .first()
    )
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")

    update_data = updated.dict(exclude_unset=True, exclude_none=True)

    filtered_data = {}
    current_time = datetime.now().time()
    current_date = date.today()
    
    for k, v in update_data.items():
        if v is None:
            continue
        
        if isinstance(v, str) and (v.strip() == "" or v.lower() == "string"):
            continue
        
        if isinstance(v, int) and v == 0:
            continue
        
        if isinstance(v, list) and len(v) == 0:
            continue
        
        if k == "appointment_date" and isinstance(v, date):
            current_db_date = getattr(appt, k)
            if current_db_date == v or v == current_date:
                continue
        
        if k == "appointment_time":
            if v is None:
                continue
                
            if isinstance(v, time):
                current_db_time = getattr(appt, k)
                
                current_time_normalized = current_db_time.replace(second=0, microsecond=0)
                new_time_normalized = v.replace(second=0, microsecond=0)
                if current_time_normalized == new_time_normalized:
                    continue
                
                current_system_time = datetime.now().time()
                current_system_minutes = current_system_time.hour * 60 + current_system_time.minute
                new_time_minutes = v.hour * 60 + v.minute
                
                if abs(current_system_minutes - new_time_minutes) <= 5:
                    continue
                
                if v.minute % 5 != 0:
                    continue
            else:
                continue
        
        if k == "appointment_mode" and isinstance(v, str):
            if v.lower() == "string" or len(v.strip()) == 0:
                continue
        
        if k == "appointment_status" and isinstance(v, str):
            if v.lower() == "string":
                continue
        
        current_value = getattr(appt, k, None)
        if current_value == v:
            continue
        
        filtered_data[k] = v

    if not filtered_data:
        raise HTTPException(status_code=400, detail="No valid fields provided for update")

    needs_slot_update = any(k in filtered_data for k in ['doctor_id', 'appointment_date', 'appointment_time'])
    old_dcid = appt.DCID if needs_slot_update else None

    if needs_slot_update:
        new_doctor_id = filtered_data.get('doctor_id', appt.doctor_id)
        new_date = filtered_data.get('appointment_date', appt.AppointmentDate)
        new_time = filtered_data.get('appointment_time', appt.AppointmentTime)
        
        if not validate_doctor_availability(db, new_doctor_id, facility_id, new_date, new_time):
            raise HTTPException(
                status_code=400, 
                detail="Doctor is not available at the requested time"
            )
        
        new_dcid = get_available_dcid(db, new_doctor_id, facility_id, new_date, new_time)
        filtered_data['DCID'] = new_dcid

    for field_name, new_value in filtered_data.items():
        setattr(appt, field_name, new_value)

    try:
        if needs_slot_update:
            if old_dcid:
                old_slot = db.query(DoctorBookedSlots).filter(DoctorBookedSlots.DCID == old_dcid).first()
                if old_slot:
                    old_slot.Booked_status = 'Not Booked'
            
            new_slot = db.query(DoctorBookedSlots).filter(DoctorBookedSlots.DCID == filtered_data['DCID']).first()
            if new_slot:
                new_slot.Booked_status = 'Booked'

        db.commit()
        db.refresh(appt)
        
        result = (
            db.query(
                Appointment,
                Patients.firstname.label('patient_firstname'),
                Patients.lastname.label('patient_lastname'),
                Patients.contact_number.label('patient_phone'),
                Doctors.firstname.label('doctor_firstname'),
                Doctors.lastname.label('doctor_lastname'),
                Doctors.consultation_fee.label('doctor_consultation_fee'),
                PatientDiagnosis.diagnosis_id.label('diagnosis_id')
            )
            .join(Patients, Appointment.patient_id == Patients.id)
            .join(Doctors, Appointment.doctor_id == Doctors.id)
            .outerjoin(PatientDiagnosis, Appointment.appointment_id == PatientDiagnosis.appointment_id)
            .filter(
                Appointment.appointment_id == appointment_id,
                Appointment.facility_id == facility_id
            )
            .first()
        )
        
        if not result:
            raise HTTPException(status_code=404, detail="Updated appointment not found")
        
        appointment, patient_firstname, patient_lastname, patient_phone, doctor_firstname, doctor_lastname, doctor_consultation_fee, diagnosis_id = result
        
        appointment_dict = {
            "appointment_id": appointment.appointment_id,
            "patient_id": appointment.patient_id,
            "doctor_id": appointment.doctor_id,
            "facility_id": appointment.facility_id,
            "dcid": appointment.DCID,
            "appointment_date": appointment.AppointmentDate,
            "appointment_time": appointment.AppointmentTime,
            "reason": appointment.Reason,
            "appointment_mode": appointment.AppointmentMode,
            "checkin_time": appointment.CheckinTime,
            "cancelled": appointment.Cancelled,
            "token_id": appointment.TokenID,
            "appointment_status": appointment.AppointmentStatus,
            "name": f"{patient_firstname} {patient_lastname}".strip(),
            "phone": patient_phone,
            "doctor": f"{doctor_firstname} {doctor_lastname}".strip(),
            "time_slot": appointment.AppointmentTime.strftime("%H:%M") if appointment.AppointmentTime else None,
            "paid": True if appointment.payment_status == 1 else False,
            "consultation_fee": float(doctor_consultation_fee) if doctor_consultation_fee else None,
            "payment_comments": appointment.payment_comments,
            "diagnosis_id": diagnosis_id
        }
        
        return AppointmentResponse(**appointment_dict)
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@router.delete("/{appointment_id}")
def delete_appointment(
    appointment_id: int,
    facility_id: int = Query(...),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Verify user belongs to the requested facility
    if current_user.facility_id != facility_id and current_user.facility_id != 0:
        raise HTTPException(status_code=403, detail="Access denied. You can only access your facility's data.")
    
    appt = (
        db.query(Appointment)
        .filter(
            Appointment.appointment_id == appointment_id,
            Appointment.facility_id == facility_id
        )
        .first()
    )
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    
    try:
        if appt.DCID:
            booked_slot = db.query(DoctorBookedSlots).filter(DoctorBookedSlots.DCID == appt.DCID).first()
            if booked_slot:
                booked_slot.Booked_status = 'Not Booked'
        
        db.delete(appt)
        db.commit()
        return {"detail": "Deleted successfully"}
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error deleting appointment: {str(e)}")


@router.get("/doctor-schedule/")
def get_doctor_schedule(
    doctor_id: int = Query(...),
    facility_id: int = Query(...),
    start_date: date = Query(...),
    end_date: date = Query(...),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Verify user belongs to the requested facility
    if current_user.facility_id != facility_id and current_user.facility_id != 0:
        raise HTTPException(status_code=403, detail="Access denied. You can only access your facility's data.")
    
    schedules = (
        db.query(DoctorSchedule)
        .filter(
            DoctorSchedule.doctor_id == doctor_id,
            DoctorSchedule.facility_id == facility_id,
            DoctorSchedule.start_date <= end_date,
            DoctorSchedule.end_date >= start_date
        )
        .all()
    )
    
    schedule_data = []
    for schedule in schedules:
        schedule_data.append({
            "weekday": schedule.week_day,
            "window_num": schedule.window_num,
            "start_time": schedule.slot_start_time.strftime("%H:%M"),
            "end_time": schedule.slot_end_time.strftime("%H:%M"),
            "schedule_period": {
                "start_date": schedule.start_date.strftime("%Y-%m-%d"),
                "end_date": schedule.end_date.strftime("%Y-%m-%d")
            }
        })
    
    return {
        "doctor_id": doctor_id,
        "facility_id": facility_id,
        "schedules": schedule_data
    }


@router.get("/patient/visit-reports", response_model=PatientVisitReportsListResponse)
def get_patient_payment_reports(
    patient_id: int = Query(..., description="Patient ID"),
    facility_id: int = Query(..., description="Facility ID"),
    limit: Optional[int] = Query(None, description="Limit number of visits (optional)"),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Verify user belongs to the requested facility
    if current_user.facility_id != facility_id and current_user.facility_id != 0:
        raise HTTPException(status_code=403, detail="Access denied. You can only access your facility's data.")
    
    query = (
        db.query(
            Appointment,
            Patients.firstname.label('patient_firstname'),
            Patients.lastname.label('patient_lastname'),
            Patients.contact_number.label('patient_phone'),
            Doctors.firstname.label('doctor_firstname'),
            Doctors.lastname.label('doctor_lastname'),
            Doctors.consultation_fee.label('doctor_consultation_fee')
        )
        .join(Patients, Appointment.patient_id == Patients.id)
        .join(Doctors, Appointment.doctor_id == Doctors.id)
        .filter(
            Patients.id == patient_id,
            Appointment.facility_id == facility_id
        )
        .order_by(Appointment.AppointmentDate.desc(), Appointment.AppointmentTime.desc())
    )
    
    if limit:
        query = query.limit(limit)
    
    results = query.all()
    
    if not results:
        raise HTTPException(
            status_code=404, 
            detail=f"No visits found for patient ID {patient_id} in facility {facility_id}"
        )
    
    visits = []
    patient_name = ""
    paid_count = 0
    unpaid_count = 0
    
    for result in results:
        appointment, patient_firstname, patient_lastname, patient_phone, doctor_firstname, doctor_lastname, doctor_consultation_fee = result
        
        if not patient_name:
            patient_name = f"{patient_firstname} {patient_lastname}".strip()
        
        appointment_mode_display = appointment.AppointmentMode
        if appointment.AppointmentMode and appointment.AppointmentMode.lower() == 'a':
            appointment_mode_display = 'appointment'
        elif appointment.AppointmentMode and appointment.AppointmentMode.lower() == 'w':
            appointment_mode_display = 'walkin'
        
        is_paid = True if appointment.payment_status == 1 else False
        if is_paid:
            paid_count += 1
        else:
            unpaid_count += 1
        
        visit_data = {
            "appointment_id": appointment.appointment_id,
            "patient_id": appointment.patient_id,
            "doctor_id": appointment.doctor_id,
            "facility_id": appointment.facility_id,
            "dcid": appointment.DCID,
            "appointment_date": appointment.AppointmentDate,
            "appointment_time": appointment.AppointmentTime,
            "reason": appointment.Reason,
            "appointment_mode": appointment_mode_display,
            "checkin_time": appointment.CheckinTime,
            "cancelled": appointment.Cancelled,
            "token_id": appointment.TokenID,
            "appointment_status": appointment.AppointmentStatus,
            "name": f"{patient_firstname} {patient_lastname}".strip(),
            "phone": patient_phone,
            "doctor": f"{doctor_firstname} {doctor_lastname}".strip(),
            "time_slot": appointment.AppointmentTime.strftime("%H:%M") if appointment.AppointmentTime else None,
            "paid": is_paid,
            "consultation_fee": float(doctor_consultation_fee) if doctor_consultation_fee else None,
            "payment_method": appointment.payment_method
        }
        
        visits.append(PatientVisitReportResponse(**visit_data))
    
    response_data = {
        "patient_id": patient_id,
        "facility_id": facility_id,
        "patient_name": patient_name,
        "total_visits": len(visits),
        "paid_visits": paid_count,
        "unpaid_visits": unpaid_count,
        "visits": visits
    }
    
    return PatientVisitReportsListResponse(**response_data)


@router.get("/patient/{patient_id}", response_model=List[AppointmentResponse])
def get_patient_appointments(
    patient_id: int,
    facility_id: int = Query(...),
    appointment_status: Optional[str] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Verify user belongs to the requested facility
    if current_user.facility_id != facility_id and current_user.facility_id != 0:
        raise HTTPException(status_code=403, detail="Access denied. You can only access your facility's data.")
    
    query = (
        db.query(
            Appointment,
            Patients.firstname.label('patient_firstname'),
            Patients.lastname.label('patient_lastname'),
            Patients.contact_number.label('patient_phone'),
            Doctors.firstname.label('doctor_firstname'),
            Doctors.lastname.label('doctor_lastname'),
            Doctors.consultation_fee.label('doctor_consultation_fee'),
            PatientDiagnosis.diagnosis_id.label('diagnosis_id')
        )
        .join(Patients, Appointment.patient_id == Patients.id)
        .join(Doctors, Appointment.doctor_id == Doctors.id)
        .outerjoin(PatientDiagnosis, Appointment.appointment_id == PatientDiagnosis.appointment_id)
        .filter(
            Appointment.patient_id == patient_id,
            Appointment.facility_id == facility_id
        )
    )
    
    if appointment_status:
        status_lower = appointment_status.lower()
        
        if status_lower == "scheduled":
            query = query.filter(
                Appointment.AppointmentStatus == "Scheduled",
                Appointment.CheckinTime == None,
                Appointment.Cancelled == False
            )
        elif status_lower == "waiting":
            query = query.filter(
                Appointment.AppointmentStatus == "Waiting",
                Appointment.CheckinTime != None,
                Appointment.Cancelled == False
            )
        elif status_lower == "completed":
            query = query.filter(
                Appointment.AppointmentStatus == "Completed",
                Appointment.CheckinTime != None,
                Appointment.Cancelled == False
            )
        elif status_lower == "cancelled":
            query = query.filter(
                Appointment.AppointmentStatus == "Cancelled",
                Appointment.Cancelled == True
            )
        else:
            query = query.filter(Appointment.AppointmentStatus == appointment_status)
    
    query = query.order_by(Appointment.AppointmentDate.desc(), Appointment.AppointmentTime.desc())
    
    results = query.all()
    
    if not results:
        raise HTTPException(
            status_code=404, 
            detail=f"No appointments found for patient ID {patient_id} in facility {facility_id}"
        )
    
    formatted_results = []
    for appointment, patient_firstname, patient_lastname, patient_phone, doctor_firstname, doctor_lastname, doctor_consultation_fee, diagnosis_id in results:
        appointment_mode_display = appointment.AppointmentMode
        if appointment.AppointmentMode and appointment.AppointmentMode.lower() == 'a':
            appointment_mode_display = 'appointment'
        elif appointment.AppointmentMode and appointment.AppointmentMode.lower() == 'w':
            appointment_mode_display = 'walkin'
        
        appointment_dict = {
            "appointment_id": appointment.appointment_id,
            "patient_id": appointment.patient_id,
            "doctor_id": appointment.doctor_id,
            "facility_id": appointment.facility_id,
            "dcid": appointment.DCID,
            "appointment_date": appointment.AppointmentDate,
            "appointment_time": appointment.AppointmentTime,
            "reason": appointment.Reason,
            "appointment_mode": appointment_mode_display,
            "checkin_time": appointment.CheckinTime,
            "cancelled": appointment.Cancelled,
            "token_id": appointment.TokenID,
            "appointment_status": appointment.AppointmentStatus,
            "name": f"{patient_firstname} {patient_lastname}".strip(),
            "phone": patient_phone,
            "doctor": f"{doctor_firstname} {doctor_lastname}".strip(),
            "time_slot": appointment.AppointmentTime.strftime("%H:%M") if appointment.AppointmentTime else None,
            "paid": True if appointment.payment_status == 1 else False,
            "consultation_fee": float(doctor_consultation_fee) if doctor_consultation_fee else None,
            "payment_method": appointment.payment_method,
            "payment_comments": appointment.payment_comments,
            "diagnosis_id": diagnosis_id
        }
        formatted_results.append(AppointmentResponse(**appointment_dict))
    
    return formatted_results