from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, func, or_, extract
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime, date, time, timedelta
from database import get_db
import model

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

# Schemas
class HourlyAppointmentData(BaseModel):
    hour: int
    scheduled: int
    checkedIn: int
    completed: int
    cancelled: int
    walkIns: int

class AppointmentStatusBreakdown(BaseModel):
    scheduled: int
    checkedIn: int
    completed: int
    cancelled: int
    noShow: int

class AppointmentModeBreakdown(BaseModel):
    online: int
    walkIn: int
    phone: int
    other: int

class CapacityMetrics(BaseModel):
    totalSlots: int
    bookedSlots: int
    availableSlots: int
    utilizationRate: float
    overbookingCount: int

class AppointmentDetailsResponse(BaseModel):
    date: date
    facilityId: int
    hourlyBreakdown: List[HourlyAppointmentData]
    statusBreakdown: AppointmentStatusBreakdown
    modeBreakdown: AppointmentModeBreakdown
    capacity: CapacityMetrics
    totalPatients: int
    peakHour: Optional[int] = None

class HourlyData(BaseModel):
    hour: int
    count: int

class AppointmentSummary(BaseModel):
    totalAppointments: int
    totalCheckin: int
    availableSlots: int
    totalWalkInPatients: int

class AppointmentDetailsResponse_Original(BaseModel):
    hourly: List[HourlyData]
    summary: AppointmentSummary

class SlotDetail(BaseModel):
    slot_time: str
    is_booked: bool
    appointment_id: Optional[int] = None
    patient_name: Optional[str] = None
    class Config:
        from_attributes = True

class DoctorSlotInfo(BaseModel):
    doctor_id: int
    doctor_first_name: str  # Changed to first name
    doctor_last_name: str   # Changed to last name
    specialization: str
    available_slots: List[SlotDetail] = []
    free_slots: List[SlotDetail] = []
    total_available_slots: int = 0
    total_free_slots: int = 0
    is_on_leave: bool = False
    class Config:
        from_attributes = True

class DashboardResponse(BaseModel):
    facility_id: int
    date: str
    day_of_week: str
    doctors: List[DoctorSlotInfo] = []
    summary: dict = {}
    class Config:
        schema_extra = {
            "example": {
                "facility_id": 1, "date": "2025-07-26", "day_of_week": "Saturday",
                "doctors": [{
                    "doctor_id": 1, "doctor_first_name": "John", "doctor_last_name": "Smith", 
                    "specialization": "Cardiology",
                    "available_slots": [{"slot_time": "09:00-09:30", "slot_id": 1, "total_appointments": 3, 
                                        "booked_appointments": 1, "available_appointments": 2, "is_available": True}],
                    "free_slots": [{"slot_time": "09:00-09:30", "slot_id": 1, "total_appointments": 3, 
                                    "booked_appointments": 0, "available_appointments": 3, "is_available": True}],
                    "total_available_slots": 8, "total_free_slots": 6, "is_on_leave": False
                }],
                "summary": {"total_doctors": 1, "doctors_available": 1, "doctors_on_leave": 0, 
                            "total_available_slots": 8, "total_free_slots": 6, "total_booked_slots": 2}
            }
        }

class PatientCheckinInfo(BaseModel):
    appointment_id: int
    patient_id: int
    patient_name: str
    patient_contact: str
    patient_email: str
    patient_age: Optional[int] = None
    patient_gender: Optional[str] = None
    doctor_id: int
    doctor_first_name: str  # Changed to first name
    doctor_last_name: str   # Changed to last name
    doctor_specialization: str
    appointment_date: str
    appointment_time: str
    scheduled_datetime: str
    reason: str
    appointment_mode: str
    appointment_status: str
    token_id: Optional[str] = None
    checkin_time: Optional[str] = None
    checkin_status: str
    cancelled: bool = False
    class Config:
        from_attributes = True

class CheckinSummary(BaseModel):
    total_appointments: int = 0
    checked_in: int = 0
    not_checked_in: int = 0
    cancelled: int = 0

class CheckinResponse(BaseModel):
    facility_id: int
    date: str
    day_of_week: str
    appointments: List[PatientCheckinInfo] = []
    summary: CheckinSummary
    class Config:
        schema_extra = {
            "example": {
                "facility_id": 1, "date": "2025-07-26", "day_of_week": "Saturday",
                "appointments": [{
                    "appointment_id": 1, "patient_id": 1, "patient_name": "John Doe", 
                    "patient_contact": "+91-9876543210", "patient_email": "john.doe@email.com",
                    "patient_age": 35, "patient_gender": "M", "doctor_id": 1, 
                    "doctor_first_name": "John", "doctor_last_name": "Smith", 
                    "doctor_specialization": "Cardiology",
                    "appointment_date": "2025-07-26", "appointment_time": "09:30", 
                    "scheduled_datetime": "2025-07-26 09:30", "reason": "Regular checkup",
                    "appointment_mode": "In-Person", "appointment_status": "Scheduled", 
                    "token_id": "T001", "checkin_time": "2025-07-26 09:25",
                    "checkin_status": "Checked In", "cancelled": False
                }],
                "summary": {"total_appointments": 10, "checked_in": 7, "not_checked_in": 2, "cancelled": 1}
            }
        }

# New schemas for appointment booking
class AppointmentBookingRequest(BaseModel):
    facility_id: int
    doctor_id: int
    patient_id: int
    appointment_date: date
    appointment_time: time
    reason: str
    appointment_mode: str = "In-Person"

class AppointmentBookingResponse(BaseModel):
    message: str
    appointment_id: int
    patient_name: str
    doctor_name: str
    appointment_date: str
    appointment_time: str

# Helper functions
def get_day_of_week(date_obj: date) -> str:
    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    return days[date_obj.weekday()]

def format_time_slot(start_time: time, end_time: time) -> str:
    return f"{start_time.strftime('%H:%M')}-{end_time.strftime('%H:%M')}"

def calculate_total_facility_slots(db: Session, facility_id: int, target_date: date) -> int:
    day_of_week = get_day_of_week(target_date)
    
    calendar_slots = db.query(func.count(model.DoctorCalendar.SlotID)).filter(
        and_(
            model.DoctorCalendar.FacilityID == facility_id,
            model.DoctorCalendar.Date == target_date,
            or_(model.DoctorCalendar.SlotLeave != '1', model.DoctorCalendar.SlotLeave != 'Y', model.DoctorCalendar.SlotLeave.is_(None)),
            or_(model.DoctorCalendar.FullDayLeave != '1', model.DoctorCalendar.FullDayLeave != 'Y', model.DoctorCalendar.FullDayLeave.is_(None))
        )
    ).scalar() or 0
    
    if calendar_slots > 0:
        return calendar_slots
    
    doctors_with_schedule = db.query(model.Doctors).join(
        model.DoctorSchedule, model.Doctors.id == model.DoctorSchedule.DoctorID
    ).filter(
        and_(model.Doctors.FacilityID == facility_id, func.lower(model.DoctorSchedule.DayOfWeek) == day_of_week.lower())
    ).all()
    
    total_slots = 0
    for doctor in doctors_with_schedule:
        schedule = db.query(model.DoctorSchedule).filter(
            and_(model.DoctorSchedule.DoctorID == doctor.id, func.lower(model.DoctorSchedule.DayOfWeek) == day_of_week.lower())
        ).first()
        
        if not schedule:
            continue
            
        try:
            schedule_start = datetime.strptime(schedule.StartTime, '%H:%M').time()
            schedule_end = datetime.strptime(schedule.EndTime, '%H:%M').time()
        except ValueError:
            try:
                schedule_start = datetime.strptime(schedule.StartTime, '%H:%M:%S').time()
                schedule_end = datetime.strptime(schedule.EndTime, '%H:%M:%S').time()
            except ValueError:
                continue
        
        available_slots = db.query(model.SlotLookup).filter(
            and_(
                model.SlotLookup.FacilityID == facility_id,
                model.SlotLookup.SlotStartTime >= schedule_start,
                model.SlotLookup.SlotStartTime < schedule_end,
                or_(model.SlotLookup.SlotSize == "15", model.SlotLookup.SlotSize == "30", model.SlotLookup.SlotSize == 15, model.SlotLookup.SlotSize == 30)
            )
        ).count()
        
        total_slots += available_slots
    
    return total_slots

# New helper function to check slot availability
def is_slot_available(db: Session, facility_id: int, doctor_id: int, 
                     appointment_date: date, appointment_time: time) -> bool:
    """
    Check if a time slot is available for booking
    Returns True if available, False if already booked
    """
    # Check for existing appointments in the same slot
    existing = db.query(model.Appointment).filter(
        model.Appointment.FacilityID == facility_id,
        model.Appointment.DoctorID == doctor_id,
        model.Appointment.AppointmentDate == appointment_date,
        model.Appointment.AppointmentTime == appointment_time,
        model.Appointment.Cancelled == False  # Only consider active appointments
    ).first()

    return existing is None

@router.get("/details", response_model=AppointmentDetailsResponse_Original)
def get_appointment_details(FacilityID: int = Query(...), date: date = Query(...), db: Session = Depends(get_db)):
    raw = (
        db.query(extract("hour", model.Appointment.AppointmentTime).label("hour"), func.count(model.Appointment.AppointmentID).label("count"))
        .filter(model.Appointment.FacilityID == FacilityID, model.Appointment.AppointmentDate == date)
        .group_by("hour").order_by("hour").all()
    )
    
    hourly_dict = {int(r.hour): r.count for r in raw}
    hourly = [HourlyData(hour=hour, count=hourly_dict.get(hour, 0)) for hour in range(9, 22)]

    total_facility_slots = calculate_available_slots_like_doctor_details(db, FacilityID, date)

    total_appointments = (
        db.query(func.count(model.Appointment.AppointmentID))
        .filter(model.Appointment.FacilityID == FacilityID, model.Appointment.AppointmentDate == date)
        .scalar() or 0
    )

    total_checkin = (
        db.query(func.count(model.Appointment.AppointmentID))
        .filter(model.Appointment.FacilityID == FacilityID, model.Appointment.AppointmentDate == date, model.Appointment.CheckinTime.isnot(None))
        .scalar() or 0
    )

    total_walkins = (
        db.query(func.count(model.Appointment.AppointmentID))
        .filter(model.Appointment.FacilityID == FacilityID, model.Appointment.AppointmentDate == date, model.Appointment.AppointmentMode.ilike("w%"))
        .scalar() or 0
    )

    summary = AppointmentSummary(
        totalAppointments=total_appointments,
        totalCheckin=total_checkin,
        availableSlots=total_facility_slots,
        totalWalkInPatients=total_walkins
    )

    return AppointmentDetailsResponse_Original(hourly=hourly, summary=summary)

def calculate_available_slots_like_doctor_details(db: Session, facility_id: int, target_date: date) -> int:
    try:
        day_of_week = get_day_of_week(target_date)
        doctors = db.query(model.Doctors).filter(model.Doctors.FacilityID == facility_id).options(joinedload(model.Doctors.schedules)).all()
        
        if not doctors:
            return 0
        
        total_available_slots = 0
        
        for doctor in doctors:
            doctor_schedule = None
            for schedule in doctor.schedules:
                if schedule.DayOfWeek.lower() == day_of_week.lower():
                    doctor_schedule = schedule
                    break
            
            if not doctor_schedule:
                continue
            
            calendar_entries = db.query(model.DoctorCalendar).filter(
                and_(model.DoctorCalendar.DoctorID == doctor.id, model.DoctorCalendar.Date == target_date, model.DoctorCalendar.FacilityID == facility_id)
            ).options(joinedload(model.DoctorCalendar.slot)).all()
            
            is_on_full_leave = any(entry.FullDayLeave == '1' or entry.FullDayLeave == 'Y' for entry in calendar_entries)
            
            if is_on_full_leave:
                continue
            
            if not calendar_entries:
                slots = db.query(model.SlotLookup).filter(
                    and_(model.SlotLookup.FacilityID == facility_id, model.SlotLookup.SlotSize == "30")
                ).all()
                
                try:
                    schedule_start = datetime.strptime(doctor_schedule.StartTime, '%H:%M').time()
                    schedule_end = datetime.strptime(doctor_schedule.EndTime, '%H:%M').time()
                except ValueError:
                    try:
                        schedule_start = datetime.strptime(doctor_schedule.StartTime, '%H:%M:%S').time()
                        schedule_end = datetime.strptime(doctor_schedule.EndTime, '%H:%M:%S').time()
                    except ValueError:
                        continue
                
                available_slots_for_doctor = [slot for slot in slots if schedule_start <= slot.SlotStartTime < schedule_end]
                calendar_entries = available_slots_for_doctor
            
            doctor_available_slots = 0
            for entry in calendar_entries:
                if hasattr(entry, 'slot') and entry.slot:
                    if entry.SlotLeave != '1' and entry.SlotLeave != 'Y':
                        doctor_available_slots += 1
                else:
                    doctor_available_slots += 1
            
            total_available_slots += doctor_available_slots
        
        return total_available_slots
        
    except Exception as e:
        print(f"Error in calculate_available_slots_like_doctor_details: {str(e)}")
        return calculate_total_facility_slots(db, facility_id, target_date)

@router.get("/getDoctorDetails", response_model=DashboardResponse)
async def get_doctor_details_for_dashboard(
    FacilityID: int = Query(..., description="Facility ID"),
    Date: date = Query(..., description="Date in YYYY-MM-DD format (e.g., 2025-07-26)"),
    DoctorID: Optional[int] = Query(None, description="Optional Doctor ID to filter specific doctor"),
    db: Session = Depends(get_db)
):
    try:
        day_of_week = get_day_of_week(Date)
        
        facility = db.query(model.Facility).filter(model.Facility.FacilityID == FacilityID).first()
        if not facility:
            raise HTTPException(status_code=404, detail="Facility not found")
        
        doctor_query = db.query(model.Doctors).filter(model.Doctors.FacilityID == FacilityID)
        
        if DoctorID is not None:
            doctor_query = doctor_query.filter(model.Doctors.id == DoctorID)
            doctor_exists = doctor_query.first()
            if not doctor_exists:
                raise HTTPException(status_code=404, detail=f"Doctor with ID {DoctorID} not found in facility {FacilityID}")
        
        doctors = doctor_query.options(joinedload(model.Doctors.schedules)).all()
        
        if not doctors:
            return DashboardResponse(
                facility_id=FacilityID, date=Date.strftime("%Y-%m-%d"), day_of_week=day_of_week, doctors=[],
                summary={"total_doctors": 0, "doctors_available": 0, "doctors_on_leave": 0, "total_available_slots": 0, "total_free_slots": 0, "total_booked_slots": 0}
            )
        
        appointments = db.query(model.Appointment).filter(
            and_(model.Appointment.FacilityID == FacilityID, model.Appointment.AppointmentDate == Date, model.Appointment.Cancelled == False)
        ).options(joinedload(model.Appointment.patient)).all()
        
        appointments_by_doctor = {}
        for app in appointments:
            if app.DoctorID not in appointments_by_doctor:
                appointments_by_doctor[app.DoctorID] = []
            appointments_by_doctor[app.DoctorID].append(app)
        
        def find_appointment_in_slot(appointments: List[model.Appointment], slot_start: time, slot_end: time) -> Optional[model.Appointment]:
            for app in appointments:
                if slot_start <= app.AppointmentTime < slot_end:
                    return app
            return None
        
        doctors_info = []
        total_available_slots = total_free_slots = total_booked_slots = doctors_available = doctors_on_leave = 0
        
        for doctor in doctors:
            doctor_schedule = None
            for schedule in doctor.schedules:
                if schedule.DayOfWeek.lower() == day_of_week.lower():
                    doctor_schedule = schedule
                    break
            
            if not doctor_schedule:
                doctors_info.append(DoctorSlotInfo(
                    doctor_id=doctor.id, 
                    doctor_first_name=doctor.firstname,  # Updated to first name
                    doctor_last_name=doctor.lastname,    # Updated to last name
                    specialization=doctor.specialization or "General",
                    available_slots=[], free_slots=[], total_available_slots=0, total_free_slots=0, is_on_leave=False
                ))
                continue
            
            calendar_entries = db.query(model.DoctorCalendar).filter(
                and_(model.DoctorCalendar.DoctorID == doctor.id, model.DoctorCalendar.Date == Date, model.DoctorCalendar.FacilityID == FacilityID)
            ).options(joinedload(model.DoctorCalendar.slot)).all()
            
            is_on_full_leave = any(entry.FullDayLeave == '1' or entry.FullDayLeave == 'Y' for entry in calendar_entries)
            
            if is_on_full_leave:
                doctors_on_leave += 1
                doctors_info.append(DoctorSlotInfo(
                    doctor_id=doctor.id,
                    doctor_first_name=doctor.firstname,  # Updated to first name
                    doctor_last_name=doctor.lastname,    # Updated to last name
                    specialization=doctor.specialization or "General",
                    available_slots=[], free_slots=[], total_available_slots=0, total_free_slots=0, is_on_leave=True
                ))
                continue
            
            doctor_appointments = appointments_by_doctor.get(doctor.id, [])
            
            if not calendar_entries:
                slots = db.query(model.SlotLookup).filter(
                    and_(model.SlotLookup.FacilityID == FacilityID, model.SlotLookup.SlotSize == "30")
                ).all()
                
                try:
                    schedule_start = datetime.strptime(doctor_schedule.StartTime, '%H:%M').time()
                    schedule_end = datetime.strptime(doctor_schedule.EndTime, '%H:%M').time()
                except ValueError:
                    try:
                        schedule_start = datetime.strptime(doctor_schedule.StartTime, '%H:%M:%S').time()
                        schedule_end = datetime.strptime(doctor_schedule.EndTime, '%H:%M:%S').time()
                    except ValueError:
                        continue
                
                available_slots_for_doctor = [slot for slot in slots if schedule_start <= slot.SlotStartTime < schedule_end]
                calendar_entries = available_slots_for_doctor
            
            available_slots = []
            free_slots = []
            
            for entry in calendar_entries:
                if hasattr(entry, 'slot') and entry.slot:
                    slot_start = entry.slot.SlotStartTime
                    slot_end = entry.slot.SlotEndTime
                    slot_time_str = format_time_slot(slot_start, slot_end)
                    is_available = (entry.SlotLeave != '1' and entry.SlotLeave != 'Y')
                else:
                    slot_start = entry.SlotStartTime
                    slot_end = entry.SlotEndTime
                    slot_time_str = format_time_slot(slot_start, slot_end)
                    is_available = True
                
                appointment_in_slot = find_appointment_in_slot(doctor_appointments, slot_start, slot_end)
                is_booked = appointment_in_slot is not None
                appointment_id = None
                patient_name = None
                
                if is_booked and appointment_in_slot:
                    appointment_id = appointment_in_slot.AppointmentID
                    if appointment_in_slot.patient:
                        patient_name = f"{appointment_in_slot.patient.firstname} {appointment_in_slot.patient.lastname}"
                
                slot_info = SlotDetail(
                    slot_time=slot_time_str, is_booked=is_booked, appointment_id=appointment_id, patient_name=patient_name
                )
                
                if is_available:
                    available_slots.append(slot_info)
                    if not is_booked:
                        free_slots.append(slot_info)
            
            if available_slots:
                doctors_available += 1
            
            doctors_info.append(DoctorSlotInfo(
                doctor_id=doctor.id,
                doctor_first_name=doctor.firstname,  # Updated to first name
                doctor_last_name=doctor.lastname,    # Updated to last name
                specialization=doctor.specialization or "General",
                available_slots=available_slots, 
                free_slots=free_slots, 
                total_available_slots=len(available_slots),
                total_free_slots=len(free_slots), 
                is_on_leave=False
            ))
            
            total_available_slots += len(available_slots)
            total_free_slots += len(free_slots)
            total_booked_slots += len([slot for slot in available_slots if slot.is_booked])
        
        return DashboardResponse(
            facility_id=FacilityID, date=Date.strftime("%Y-%m-%d"), day_of_week=day_of_week, doctors=doctors_info,
            summary={
                "total_doctors": len(doctors), "doctors_available": doctors_available, "doctors_on_leave": doctors_on_leave,
                "total_available_slots": total_available_slots, "total_free_slots": total_free_slots, "total_booked_slots": total_booked_slots
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving dashboard data: {str(e)}")

@router.get("/getCheckinDetails", response_model=CheckinResponse)
async def get_checkin_details_for_dashboard(
    FacilityID: int = Query(..., description="Facility ID"),
    Date: date = Query(..., description="Date in YYYY-MM-DD format (e.g., 2025-07-26)"),
    db: Session = Depends(get_db)
):
    try:
        day_of_week = get_day_of_week(Date)
        
        facility = db.query(model.Facility).filter(model.Facility.FacilityID == FacilityID).first()
        if not facility:
            raise HTTPException(status_code=404, detail="Facility not found")
        
        appointments = db.query(model.Appointment).filter(
            and_(model.Appointment.FacilityID == FacilityID, model.Appointment.AppointmentDate == Date, model.Appointment.Cancelled == False)
        ).options(joinedload(model.Appointment.patient), joinedload(model.Appointment.doctor)).order_by(model.Appointment.AppointmentTime).all()
        
        if not appointments:
            return CheckinResponse(
                facility_id=FacilityID, date=Date.strftime("%Y-%m-%d"), day_of_week=day_of_week,
                appointments=[], summary=CheckinSummary()
            )
        
        appointments_info = []
        checked_in_count = not_checked_in_count = cancelled_count = 0
        
        for appointment in appointments:
            patient = appointment.patient
            patient_name = f"{patient.firstname} {patient.lastname}"
            doctor = appointment.doctor
            appointment_datetime = datetime.combine(appointment.AppointmentDate, appointment.AppointmentTime)
            
            checkin_time_str = None
            checkin_status = "Not Checked In"
            
            if appointment.Cancelled:
                checkin_status = "Cancelled"
                cancelled_count += 1
            elif appointment.CheckinTime:
                checkin_time_str = appointment.CheckinTime.strftime("%Y-%m-%d %H:%M")
                checkin_status = "Checked In"
                checked_in_count += 1
            else:
                not_checked_in_count += 1
            
            appointments_info.append(PatientCheckinInfo(
                appointment_id=appointment.AppointmentID, 
                patient_id=appointment.PatientID, 
                patient_name=patient_name,
                patient_contact=patient.contact_number, 
                patient_email=patient.email_id, 
                patient_age=patient.age,
                patient_gender=patient.gender, 
                doctor_id=appointment.DoctorID, 
                doctor_first_name=doctor.firstname,  # Updated to first name
                doctor_last_name=doctor.lastname,     # Updated to last name
                doctor_specialization=doctor.specialization or "General", 
                appointment_date=appointment.AppointmentDate.strftime("%Y-%m-%d"),
                appointment_time=appointment.AppointmentTime.strftime("%H:%M"), 
                scheduled_datetime=appointment_datetime.strftime("%Y-%m-%d %H:%M"),
                reason=appointment.Reason, 
                appointment_mode=appointment.AppointmentMode, 
                appointment_status=appointment.AppointmentStatus or "Scheduled",
                token_id=appointment.TokenID, 
                checkin_time=checkin_time_str, 
                checkin_status=checkin_status, 
                cancelled=appointment.Cancelled
            ))
        
        summary = CheckinSummary(
            total_appointments=len(appointments), 
            checked_in=checked_in_count,
            not_checked_in=not_checked_in_count, 
            cancelled=cancelled_count
        )
        
        return CheckinResponse(
            facility_id=FacilityID, 
            date=Date.strftime("%Y-%m-%d"), 
            day_of_week=day_of_week,
            appointments=appointments_info, 
            summary=summary
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving check-in details: {str(e)}")