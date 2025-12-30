
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, extract, and_
from typing import List, Optional, Dict, Tuple
from datetime import date, datetime, time, timezone, timedelta
from pydantic import BaseModel, validator
from model import Appointment, Patients, Doctors, DoctorSchedule, DoctorBookedSlots, PatientDiagnosis, HMSParams
import pytz
import logging

from database import get_db
from router.new_booking import update_slot_booking_status
from auth_middleware import get_current_user, require_roles, CurrentUser

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/appointments",
    tags=["Appointments"]
)

# ==================== TOKEN GENERATION FUNCTIONS ====================

def get_walkin_reserve_ratio(db: Session, facility_id: int) -> float:
    """Get WALKIN_RESERVE_RATIO from HMS_PARAMS table. Returns default value of 0.4 (40%) if not found."""
    try:
        param = db.query(HMSParams).filter(
            HMSParams.facility_id == facility_id,
            HMSParams.param_name == 'WALKIN_RESERVE_RATIO'
        ).first()
        
        if param:
            ratio = float(param.param_value)
            if 0 <= ratio <= 1:
                logger.info(f"Retrieved WALKIN_RESERVE_RATIO: {ratio} for facility {facility_id}")
                return ratio
            else:
                logger.warning(f"Invalid WALKIN_RESERVE_RATIO value: {ratio}. Using default 0.4")
                return 0.4
        else:
            logger.info(f"WALKIN_RESERVE_RATIO not found for facility {facility_id}. Using default 0.4")
            return 0.4
    except Exception as e:
        logger.error(f"Error retrieving WALKIN_RESERVE_RATIO: {str(e)}. Using default 0.4")
        return 0.4


def get_hourly_slots_for_date(db: Session, facility_id: int, target_date: date) -> List[Dict]:
    """Get all hourly slots for a specific date by aggregating doctor schedules."""
    weekday = target_date.strftime('%A')
    schedules = db.query(DoctorSchedule).filter(
        DoctorSchedule.facility_id == facility_id,
        DoctorSchedule.start_date <= target_date,
        DoctorSchedule.end_date >= target_date,
        DoctorSchedule.week_day == weekday,
        DoctorSchedule.availability_flag == 'A'
    ).all()
    
    if not schedules:
        return []
    
    hourly_slots = {}
    for schedule in schedules:
        start_hour = schedule.slot_start_time.hour
        end_hour = schedule.slot_end_time.hour
        if schedule.slot_end_time.minute == 0 and end_hour > 0:
            end_hour -= 1
        
        current_hour = start_hour
        while current_hour <= end_hour:
            if current_hour not in hourly_slots:
                hourly_slots[current_hour] = {
                    'hour': current_hour,
                    'start_time': time(current_hour, 0),
                    'end_time': time(current_hour + 1, 0) if current_hour < 23 else time(23, 59),
                    'total_slots': 0
                }
            
            if schedule.total_slots:
                schedule_start_minutes = schedule.slot_start_time.hour * 60 + schedule.slot_start_time.minute
                schedule_end_minutes = schedule.slot_end_time.hour * 60 + schedule.slot_end_time.minute
                schedule_duration = schedule_end_minutes - schedule_start_minutes
                
                if schedule_duration > 0:
                    hour_start_minutes = current_hour * 60
                    hour_end_minutes = (current_hour + 1) * 60
                    overlap_start = max(schedule_start_minutes, hour_start_minutes)
                    overlap_end = min(schedule_end_minutes, hour_end_minutes)
                    overlap_duration = overlap_end - overlap_start
                    hour_slots = int((schedule.total_slots * overlap_duration) / schedule_duration)
                    hourly_slots[current_hour]['total_slots'] += hour_slots
            else:
                slot_duration = schedule.slot_duration_minutes or 15
                slots_per_hour = 60 // slot_duration
                hourly_slots[current_hour]['total_slots'] += slots_per_hour
            
            current_hour += 1
    
    return sorted(hourly_slots.values(), key=lambda x: x['hour'])


def generate_daily_token_table(db: Session, facility_id: int, target_date: date) -> List[Dict]:
    """Generate a token table for the day based on hourly slots and walk-in reserve ratio."""
    walkin_reserve_ratio = get_walkin_reserve_ratio(db, facility_id)
    hourly_slots = get_hourly_slots_for_date(db, facility_id, target_date)
    
    if not hourly_slots:
        logger.warning(f"No hourly slots found for facility {facility_id} on {target_date}")
        return []
    
    token_table = []
    appointment_start = 1
    walkin_start = 1  # This will be updated to continue from appointment tokens
    
    for slot in hourly_slots:
        total_slots = slot['total_slots']
        walkin_tokens = int(total_slots * walkin_reserve_ratio)
        appointment_tokens = total_slots - walkin_tokens
        appointment_end = appointment_start + appointment_tokens - 1
        
        # Walk-in tokens should continue from where appointment tokens end
        walkin_start = appointment_end + 1
        walkin_end = walkin_start + walkin_tokens - 1
        
        token_table.append({
            "slot": f"{slot['start_time'].strftime('%H:%M')} to {slot['end_time'].strftime('%H:%M')}",
            "hour": slot['hour'],
            "start_time": slot['start_time'],
            "end_time": slot['end_time'],
            "total_slots": total_slots,
            "appointment_tokens": appointment_tokens,
            "walkin_tokens": walkin_tokens,
            "appointment_from": appointment_start,
            "appointment_to": appointment_end,
            "walkin_from": walkin_start,
            "walkin_to": walkin_end,
        })
        
        # Next slot's appointment tokens should start after current slot's walk-in tokens
        appointment_start = walkin_end + 1
    
    logger.info(f"Generated token table with {len(token_table)} hourly slots for {target_date}")
    return token_table


def get_next_token_number(db: Session, facility_id: int, appointment_time: time, 
                          appointment_date: date, token_type: str) -> Tuple[str, str]:
    """
    Get the next available token number for a specific time slot.
    
    Walk-in Logic: Assign to the specific hour's walk-in token range ONLY
    Appointment Logic: Assign to the specific hour's appointment token range first,
                       then fill unused tokens from earlier slots if current hour is full
    """
    token_table = generate_daily_token_table(db, facility_id, appointment_date)
    if not token_table:
        raise ValueError(f"No token slots available for {appointment_date}")
    
    appointment_hour = appointment_time.hour
    slot_info = next((slot for slot in token_table if slot['hour'] == appointment_hour), None)
    if not slot_info:
        raise ValueError(f"No token slot found for time {appointment_time}")
    
    # Get all existing tokens for the day
    existing_tokens = db.query(Appointment.TokenID).filter(
        Appointment.facility_id == facility_id,
        Appointment.AppointmentDate == appointment_date,
        Appointment.TokenID.isnot(None)
    ).all()
    
    used_token_numbers = set()
    for (token_id,) in existing_tokens:
        if token_id and len(token_id) > 1:
            try:
                used_token_numbers.add(int(token_id[1:]))
            except ValueError:
                continue
    
    # WALK-IN LOGIC: Assign to specific hour's walk-in range ONLY
    if token_type.lower() in ['walkin', 'w']:
        prefix = "W"
        from_token = slot_info['walkin_from']
        to_token = slot_info['walkin_to']
        
        # Try to find available token in THIS hour's walk-in range only
        for token_num in range(from_token, to_token + 1):
            if token_num not in used_token_numbers:
                return f"{prefix}{token_num:03d}", slot_info['slot']
        
        # If this hour's walk-in tokens are full, raise error
        raise ValueError(f"No available walk-in tokens for time slot {slot_info['slot']}. All walk-in slots for this hour are booked.")
    
    # APPOINTMENT LOGIC: Try current hour first, then fill from earliest unused
    else:
        prefix = "A"
        from_token = slot_info['appointment_from']
        to_token = slot_info['appointment_to']
        
        # STEP 1: Try to assign token from the CURRENT HOUR's appointment range first
        for token_num in range(from_token, to_token + 1):
            if token_num not in used_token_numbers:
                return f"{prefix}{token_num:03d}", slot_info['slot']
        
        # STEP 2: If current hour is full, fill unused tokens from EARLIER slots
        current_slot_index = token_table.index(slot_info)
        for earlier_slot in token_table[:current_slot_index]:
            earlier_from = earlier_slot['appointment_from']
            earlier_to = earlier_slot['appointment_to']
            
            for token_num in range(earlier_from, earlier_to + 1):
                if token_num not in used_token_numbers:
                    # Return token from earlier slot, but keep the actual appointment time slot info
                    return f"{prefix}{token_num:03d}", slot_info['slot']
        
        # STEP 3: If earlier slots are also full, check LATER slots
        for later_slot in token_table[current_slot_index + 1:]:
            later_from = later_slot['appointment_from']
            later_to = later_slot['appointment_to']
            
            for token_num in range(later_from, later_to + 1):
                if token_num not in used_token_numbers:
                    return f"{prefix}{token_num:03d}", slot_info['slot']
        
        # If all appointment tokens are used across all slots
        raise ValueError(f"No available appointment tokens for {appointment_date}")


def validate_token_availability(db: Session, facility_id: int, appointment_time: time,
                               appointment_date: date, token_type: str) -> bool:
    """Check if tokens are available for the specified time slot."""
    try:
        get_next_token_number(db, facility_id, appointment_time, appointment_date, token_type)
        return True
    except ValueError:
        return False


def get_token_statistics(db: Session, facility_id: int, target_date: date) -> Dict:
    """Get token usage statistics for a specific date."""
    token_table = generate_daily_token_table(db, facility_id, target_date)
    
    if not token_table:
        return {
            "date": str(target_date),
            "total_appointment_tokens": 0,
            "total_walkin_tokens": 0,
            "used_appointment_tokens": 0,
            "used_walkin_tokens": 0,
            "available_appointment_tokens": 0,
            "available_walkin_tokens": 0,
            "hourly_breakdown": []
        }
    
    appointments = db.query(Appointment).filter(
        Appointment.facility_id == facility_id,
        Appointment.AppointmentDate == target_date,
        Appointment.TokenID.isnot(None)
    ).all()
    
    used_appointment_tokens = sum(1 for a in appointments if a.TokenID and a.TokenID.startswith('A'))
    used_walkin_tokens = sum(1 for a in appointments if a.TokenID and a.TokenID.startswith('W'))
    total_appointment_tokens = sum(slot['appointment_tokens'] for slot in token_table)
    total_walkin_tokens = sum(slot['walkin_tokens'] for slot in token_table)
    
    return {
        "date": str(target_date),
        "total_appointment_tokens": total_appointment_tokens,
        "total_walkin_tokens": total_walkin_tokens,
        "used_appointment_tokens": used_appointment_tokens,
        "used_walkin_tokens": used_walkin_tokens,
        "available_appointment_tokens": total_appointment_tokens - used_appointment_tokens,
        "available_walkin_tokens": total_walkin_tokens - used_walkin_tokens,
        "hourly_breakdown": token_table
    }

# ==================== PYDANTIC MODELS ====================

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
                time_part = v.split('T')[1] if 'T' in v else v
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

# ==================== HELPER FUNCTIONS ====================

def get_effective_facility_id(current_user: CurrentUser, facility_id: Optional[int]) -> int:
    """Determine the effective facility_id based on user role"""
    if current_user.is_super_admin():
        if facility_id is None:
            raise HTTPException(status_code=400, detail="facility_id is required")
        return facility_id
    else:
        return current_user.facility_id


def get_available_dcid(db: Session, doctor_id: int, facility_id: int, appointment_date: date, appointment_time: time):
    """Find an available DCID from doctor_booked_slots"""
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
    """Validate if doctor is available at the requested time"""
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

# ==================== TOKEN ENDPOINTS ====================

@router.get("/tokens/statistics", response_model=Dict)
def get_daily_token_statistics(
    date: date = Query(...),
    facility_id: Optional[int] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get token usage statistics for a specific date."""
    effective_facility_id = get_effective_facility_id(current_user, facility_id)
    statistics = get_token_statistics(db, effective_facility_id, date)
    return statistics


@router.get("/tokens/table", response_model=Dict)
def get_token_table(
    date: date = Query(...),
    facility_id: Optional[int] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get the token table for a specific date."""
    effective_facility_id = get_effective_facility_id(current_user, facility_id)
    token_table = generate_daily_token_table(db, effective_facility_id, date)
    return {
        "date": str(date),
        "facility_id": effective_facility_id,
        "token_table": token_table
    }

# ==================== CRUD ENDPOINTS ====================

@router.get("/", response_model=List[AppointmentResponse])
def get_all_appointments(
    facility_id: Optional[int] = Query(None),
    date: date = Query(...),
    end_date: Optional[date] = Query(None),
    patient_id: Optional[int] = Query(None),
    appointment_status: Optional[str] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    effective_facility_id = get_effective_facility_id(current_user, facility_id)
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
        .filter(Appointment.facility_id == effective_facility_id)
    )
    
    if end_date:
        query = query.filter(Appointment.AppointmentDate >= date, Appointment.AppointmentDate <= end_date)
    else:
        query = query.filter(Appointment.AppointmentDate == date)
    
    if patient_id:
        query = query.filter(Appointment.patient_id == patient_id)
    
    if appointment_status:
        status_lower = appointment_status.lower()
        if status_lower == "scheduled":
            query = query.filter(Appointment.AppointmentStatus == "Scheduled", Appointment.CheckinTime == None, Appointment.Cancelled == False)
        elif status_lower == "waiting":
            query = query.filter(Appointment.AppointmentStatus == "Waiting", Appointment.CheckinTime != None, Appointment.Cancelled == False)
        elif status_lower == "completed":
            query = query.filter(Appointment.AppointmentStatus == "Completed", Appointment.CheckinTime != None, Appointment.Cancelled == False)
        elif status_lower == "cancelled":
            query = query.filter(Appointment.AppointmentStatus == "Cancelled", Appointment.Cancelled == True)
        else:
            query = query.filter(Appointment.AppointmentStatus == appointment_status)
    else:
        query = query.filter(Appointment.AppointmentStatus == "Scheduled", Appointment.CheckinTime == None, Appointment.Cancelled == False)
    
    query = query.order_by(Appointment.AppointmentDate.desc(), Appointment.AppointmentTime.desc())
    results = query.all()
    
    formatted_results = []
    for appointment, patient_firstname, patient_lastname, patient_phone, doctor_firstname, doctor_lastname, doctor_consultation_fee, diagnosis_id in results:
        appointment_mode_display = appointment.AppointmentMode
        if appointment.AppointmentMode and appointment.AppointmentMode.lower() == 'a':
            appointment_mode_display = 'appointment'
        elif appointment.AppointmentMode and appointment.AppointmentMode.lower() == 'w':
            appointment_mode_display = 'walkin'
        
        formatted_results.append(AppointmentResponse(**{
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
        }))
    
    return formatted_results


@router.get("/{appointment_id}", response_model=AppointmentResponse)
def get_appointment(
    appointment_id: int,
    facility_id: Optional[int] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    effective_facility_id = get_effective_facility_id(current_user, facility_id)
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
        .filter(Appointment.appointment_id == appointment_id, Appointment.facility_id == effective_facility_id)
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
    
    return AppointmentResponse(**{
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
    })


@router.post("/", response_model=AppointmentResponse)
def create_appointment(
    appointment: AppointmentCreate,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not current_user.is_super_admin():
        appointment.facility_id = current_user.facility_id
    
    effective_facility_id = appointment.facility_id
    payload = appointment.dict(exclude_unset=True)
    payload["facility_id"] = effective_facility_id
    payload["Cancelled"] = False
    if "AppointmentStatus" not in payload:
        payload["AppointmentStatus"] = "Scheduled"

    if not validate_doctor_availability(db, payload["doctor_id"], effective_facility_id, payload["appointment_date"], payload["appointment_time"]):
        raise HTTPException(status_code=400, detail="Doctor is not available at the requested time")

    # Validate token availability
    token_type = payload.get("appointment_mode", "a").lower()
    token_type_name = "appointment" if token_type == "a" else "walkin"
    if not validate_token_availability(db, effective_facility_id, payload["appointment_time"], payload["appointment_date"], token_type_name):
        raise HTTPException(status_code=400, detail=f"No {token_type_name} tokens available for the selected time slot")

    exists = (
        db.query(Appointment)
        .filter(
            Appointment.patient_id == payload["patient_id"],
            Appointment.doctor_id == payload["doctor_id"],
            Appointment.AppointmentDate == payload["appointment_date"],
            Appointment.AppointmentTime == payload["appointment_time"],
            Appointment.facility_id == effective_facility_id
        )
        .first()
    )
    if exists:
        raise HTTPException(400, "Duplicate appointment exists")

    try:
        dcid = get_available_dcid(db, payload["doctor_id"], effective_facility_id, payload["appointment_date"], payload["appointment_time"])
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
        
        return AppointmentResponse(**{
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
        })
        
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Error creating appointment: {str(e)}")


@router.post("/{appointment_id}/checkin", response_model=CheckinResponse)
def checkin_appointment(
    appointment_id: int,
    facility_id: Optional[int] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    effective_facility_id = get_effective_facility_id(current_user, facility_id)
    appt = (
        db.query(Appointment)
        .filter(Appointment.appointment_id == appointment_id, Appointment.facility_id == effective_facility_id)
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
        token_type = "appointment" if mode == "a" else "walkin" if mode == "w" else "appointment"
        
        # Generate token using the new logic
        token_id, slot_info = get_next_token_number(db, effective_facility_id, appt.AppointmentTime, appt.AppointmentDate, token_type)
        
        utc_now = datetime.now(timezone.utc)
        local_tz = pytz.timezone('Asia/Kolkata')
        local_now = utc_now.astimezone(local_tz)
        
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
            message=f"Patient checked in successfully with token {token_id} for slot {slot_info}"
        )
        
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error during checkin: {str(e)}")


@router.post("/{appointment_id}/cancel", response_model=CancelResponse)
def cancel_appointment(
    appointment_id: int,
    cancel_request: CancelRequest = CancelRequest(),
    facility_id: Optional[int] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    effective_facility_id = get_effective_facility_id(current_user, facility_id)
    appt = (
        db.query(Appointment)
        .filter(Appointment.appointment_id == appointment_id, Appointment.facility_id == effective_facility_id)
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
    facility_id: Optional[int] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    effective_facility_id = get_effective_facility_id(current_user, facility_id)
    appt = (
        db.query(Appointment)
        .filter(Appointment.appointment_id == appointment_id, Appointment.facility_id == effective_facility_id)
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
        if payment_request.payment_comments is not None:
            appt.payment_comments = payment_request.payment_comments

        appt.payment_status = payment_request.payment_status
        message = "Payment processed successfully" if payment_request.payment_status else "Payment marked as pending"

        db.commit()
        db.refresh(appt)

        return PaymentResponse(
            appointment_id=appt.appointment_id,
            payment_status=payment_request.payment_status,
            payment_method=payment_request.payment_method,
            payment_comments=appt.payment_comments,
            appointment_status=appt.AppointmentStatus,
            message=message
        )

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error updating payment status: {str(e)}")


@router.post("/{appointment_id}/complete", response_model=CompleteResponse)
def complete_appointment(
    appointment_id: int,
    facility_id: Optional[int] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    effective_facility_id = get_effective_facility_id(current_user, facility_id)
    appt = (
        db.query(Appointment)
        .filter(Appointment.appointment_id == appointment_id, Appointment.facility_id == effective_facility_id)
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
    facility_id: Optional[int] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    effective_facility_id = get_effective_facility_id(current_user, facility_id)
    appt = (
        db.query(Appointment)
        .filter(Appointment.appointment_id == appointment_id, Appointment.facility_id == effective_facility_id)
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
        
        if not validate_doctor_availability(db, new_doctor_id, effective_facility_id, new_date, new_time):
            raise HTTPException(status_code=400, detail="Doctor is not available at the requested time")
        
        new_dcid = get_available_dcid(db, new_doctor_id, effective_facility_id, new_date, new_time)
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
            .filter(Appointment.appointment_id == appointment_id, Appointment.facility_id == effective_facility_id)
            .first()
        )
        
        if not result:
            raise HTTPException(status_code=404, detail="Updated appointment not found")
        
        appointment, patient_firstname, patient_lastname, patient_phone, doctor_firstname, doctor_lastname, doctor_consultation_fee, diagnosis_id = result
        
        return AppointmentResponse(**{
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
        })
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@router.delete("/{appointment_id}")
def delete_appointment(
    appointment_id: int,
    facility_id: Optional[int] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    effective_facility_id = get_effective_facility_id(current_user, facility_id)
    appt = (
        db.query(Appointment)
        .filter(Appointment.appointment_id == appointment_id, Appointment.facility_id == effective_facility_id)
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
    facility_id: Optional[int] = Query(None),
    start_date: date = Query(...),
    end_date: date = Query(...),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    effective_facility_id = get_effective_facility_id(current_user, facility_id)
    schedules = (
        db.query(DoctorSchedule)
        .filter(
            DoctorSchedule.doctor_id == doctor_id,
            DoctorSchedule.facility_id == effective_facility_id,
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
    facility_id: Optional[int] = Query(None, description="Facility ID"),
    limit: Optional[int] = Query(None, description="Limit number of visits (optional)"),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    effective_facility_id = get_effective_facility_id(current_user, facility_id)
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
        .filter(Patients.id == patient_id, Appointment.facility_id == effective_facility_id)
        .order_by(Appointment.AppointmentDate.desc(), Appointment.AppointmentTime.desc())
    )
    
    if limit:
        query = query.limit(limit)
    
    results = query.all()
    
    if not results:
        raise HTTPException(status_code=404, detail=f"No visits found for patient ID {patient_id} in facility {facility_id}")
    
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
        
        visits.append(PatientVisitReportResponse(**{
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
        }))
    
    return PatientVisitReportsListResponse(**{
        "patient_id": patient_id,
        "facility_id": facility_id,
        "patient_name": patient_name,
        "total_visits": len(visits),
        "paid_visits": paid_count,
        "unpaid_visits": unpaid_count,
        "visits": visits
    })


@router.get("/patient/{patient_id}", response_model=List[AppointmentResponse])
def get_patient_appointments(
    patient_id: int,
    facility_id: Optional[int] = Query(None),
    appointment_status: Optional[str] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    effective_facility_id = get_effective_facility_id(current_user, facility_id)
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
        .filter(Appointment.patient_id == patient_id, Appointment.facility_id == effective_facility_id)
    )
    
    if appointment_status:
        status_lower = appointment_status.lower()
        if status_lower == "scheduled":
            query = query.filter(Appointment.AppointmentStatus == "Scheduled", Appointment.CheckinTime == None, Appointment.Cancelled == False)
        elif status_lower == "waiting":
            query = query.filter(Appointment.AppointmentStatus == "Waiting", Appointment.CheckinTime != None, Appointment.Cancelled == False)
        elif status_lower == "completed":
            query = query.filter(Appointment.AppointmentStatus == "Completed", Appointment.CheckinTime != None, Appointment.Cancelled == False)
        elif status_lower == "cancelled":
            query = query.filter(Appointment.AppointmentStatus == "Cancelled", Appointment.Cancelled == True)
        else:
            query = query.filter(Appointment.AppointmentStatus == appointment_status)
    
    query = query.order_by(Appointment.AppointmentDate.desc(), Appointment.AppointmentTime.desc())
    results = query.all()
    
    if not results:
        raise HTTPException(status_code=404, detail=f"No appointments found for patient ID {patient_id} in facility {facility_id}")
    
    formatted_results = []
    for appointment, patient_firstname, patient_lastname, patient_phone, doctor_firstname, doctor_lastname, doctor_consultation_fee, diagnosis_id in results:
        appointment_mode_display = appointment.AppointmentMode
        if appointment.AppointmentMode and appointment.AppointmentMode.lower() == 'a':
            appointment_mode_display = 'appointment'
        elif appointment.AppointmentMode and appointment.AppointmentMode.lower() == 'w':
            appointment_mode_display = 'walkin'
        
        formatted_results.append(AppointmentResponse(**{
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
        }))
    
    return formatted_results