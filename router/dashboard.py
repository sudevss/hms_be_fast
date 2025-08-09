from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, func, or_, extract, text
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime, date, time, timedelta
from database import get_db
import model
from typing import Optional, List, Dict
import time as time_module
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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

class HourlyBookingData(BaseModel):
    hour: int
    booking_count: int
    time_slot: str  # e.g., "9 AM", "10 AM"

class DoctorSummary(BaseModel):
    total_appointments: int
    total_checkin: int
    available_slots: int
    total_walkin_patients: int

class DoctorInfo(BaseModel):
    doctor_id: int
    name: str
    specialization: str
    status: str  # "On Duty" / "Off Duty"
    available_slots: int
    total_slots: int

class TokenData(BaseModel):
    appointment_id: int
    token: str
    patient_name: str
    age: int
    doctor_name: str
    specialization: str
    checkin_time: Optional[str]
    payment_type: Optional[str]  # "Cash", "UPI", "Debit Card/Credit Card", "Net Banking"
    is_paid: bool
    status: str  # "Scheduled", "Completed", "Cancelled"

class DoctorDashboardResponse(BaseModel):
    facility_id: int
    date: str
    day_of_week: str
    doctor_filter: Optional[dict]  # Applied filter info
    hourly_booking_chart: List[HourlyBookingData]
    summary: DoctorSummary
    doctors: List[DoctorInfo]
    token_data: List[TokenData]

class PatientCheckinInfo(BaseModel):
    appointment_id: int
    patient_id: int
    patient_name: str
    patient_contact: str
    patient_email: str
    patient_age: Optional[int] = None
    patient_gender: Optional[str] = None
    doctor_id: int
    doctor_name: str  # Combined name instead of separate fields
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
                    "doctor_name": "Dr. John Smith", 
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



# Helper functions
def get_day_of_week(date_obj: date) -> str:
    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    return days[date_obj.weekday()]

def format_time_slot(start_time: time, end_time: time) -> str:
    return f"{start_time.strftime('%H:%M')}-{end_time.strftime('%H:%M')}"

def calculate_total_facility_slots_optimized(db: Session, facility_id: int, target_date: date) -> int:
    """Optimized version with better error handling and logging"""
    start_time = time_module.time()
    
    try:
        day_of_week = get_day_of_week(target_date)
        
        # First try calendar-based slots with a single query
        calendar_slots = db.query(func.count(model.DoctorCalendar.SlotID)).filter(
            and_(
                model.DoctorCalendar.FacilityID == facility_id,
                model.DoctorCalendar.Date == target_date,
                or_(
                    model.DoctorCalendar.SlotLeave.is_(None),
                    and_(model.DoctorCalendar.SlotLeave != '1', model.DoctorCalendar.SlotLeave != 'Y')
                ),
                or_(
                    model.DoctorCalendar.FullDayLeave.is_(None),
                    and_(model.DoctorCalendar.FullDayLeave != '1', model.DoctorCalendar.FullDayLeave != 'Y')
                )
            )
        ).scalar() or 0
        
        logger.info(f"Calendar slots query took: {time_module.time() - start_time:.2f}s")
        
        if calendar_slots > 0:
            return calendar_slots
        
        # Fallback to schedule-based calculation with optimized queries
        schedule_start_time = time_module.time()
        
        # Get all doctors with schedules in one query
        doctors_with_schedule = db.query(
            model.Doctors.id,
            model.DoctorSchedule.StartTime,
            model.DoctorSchedule.EndTime
        ).join(
            model.DoctorSchedule, model.Doctors.id == model.DoctorSchedule.DoctorID
        ).filter(
            and_(
                model.Doctors.FacilityID == facility_id, 
                func.lower(model.DoctorSchedule.DayOfWeek) == day_of_week.lower()
            )
        ).all()
        
        if not doctors_with_schedule:
            logger.warning(f"No doctors with schedule found for facility {facility_id} on {day_of_week}")
            return 0
        
        # Get all relevant slots in one query
        slots = db.query(model.SlotLookup).filter(
            and_(
                model.SlotLookup.FacilityID == facility_id,
                or_(
                    model.SlotLookup.SlotSize == "15", 
                    model.SlotLookup.SlotSize == "30", 
                    model.SlotLookup.SlotSize == 15, 
                    model.SlotLookup.SlotSize == 30
                )
            )
        ).all()
        
        total_slots = 0
        for doctor_id, start_time_str, end_time_str in doctors_with_schedule:
            try:
                # Try different time formats
                for time_format in ['%H:%M', '%H:%M:%S']:
                    try:
                        schedule_start = datetime.strptime(start_time_str, time_format).time()
                        schedule_end = datetime.strptime(end_time_str, time_format).time()
                        break
                    except ValueError:
                        continue
                else:
                    logger.warning(f"Could not parse time format for doctor {doctor_id}: {start_time_str}-{end_time_str}")
                    continue
                
                # Count slots within schedule
                available_slots = sum(1 for slot in slots 
                                    if schedule_start <= slot.SlotStartTime < schedule_end)
                total_slots += available_slots
                
            except Exception as e:
                logger.error(f"Error processing doctor {doctor_id}: {str(e)}")
                continue
        
        logger.info(f"Schedule calculation took: {time_module.time() - schedule_start_time:.2f}s")
        logger.info(f"Total facility slots calculation took: {time_module.time() - start_time:.2f}s")
        
        return total_slots
        
    except Exception as e:
        logger.error(f"Error in calculate_total_facility_slots_optimized: {str(e)}")
        return 0

def is_slot_available(db: Session, facility_id: int, doctor_id: int, 
                     appointment_date: date, appointment_time: time) -> bool:
    """Check if a time slot is available for booking"""
    try:
        existing = db.query(model.Appointment.AppointmentID).filter(
            model.Appointment.FacilityID == facility_id,
            model.Appointment.DoctorID == doctor_id,
            model.Appointment.AppointmentDate == appointment_date,
            model.Appointment.AppointmentTime == appointment_time,
            model.Appointment.Cancelled == False
        ).first()
        
        return existing is None
    except Exception as e:
        logger.error(f"Error checking slot availability: {str(e)}")
        return False
@router.get("/details", response_model=AppointmentDetailsResponse_Original)
def get_appointment_details(FacilityID: int = Query(...), date: date = Query(...), db: Session = Depends(get_db)):
    start_time = time_module.time()
    logger.info(f"Starting appointment details query for facility {FacilityID} on {date}")
    
    try:
        # Optimized hourly data query
        raw = db.query(
            extract("hour", model.Appointment.AppointmentTime).label("hour"), 
            func.count(model.Appointment.AppointmentID).label("count")
        ).filter(
            model.Appointment.FacilityID == FacilityID, 
            model.Appointment.AppointmentDate == date,
            model.Appointment.Cancelled == False  # Only active appointments
        ).group_by("hour").order_by("hour").all()
        
        hourly_dict = {int(r.hour): r.count for r in raw}
        hourly = [HourlyData(hour=hour, count=hourly_dict.get(hour, 0)) for hour in range(9, 22)]

        # Now we can use the correct attribute name in SQL
        total_appointments = db.query(func.count(model.Appointment.AppointmentID)).filter(
            model.Appointment.FacilityID == FacilityID, 
            model.Appointment.AppointmentDate == date,
            model.Appointment.Cancelled == False
        ).scalar() or 0

        total_checkin = db.query(func.count(model.Appointment.AppointmentID)).filter(
            model.Appointment.FacilityID == FacilityID, 
            model.Appointment.AppointmentDate == date,
            model.Appointment.Cancelled == False,
            model.Appointment.CheckinTime.isnot(None)
        ).scalar() or 0

        total_walkins = db.query(func.count(model.Appointment.AppointmentID)).filter(
            model.Appointment.FacilityID == FacilityID, 
            model.Appointment.AppointmentDate == date,
            model.Appointment.Cancelled == False,
            func.lower(model.Appointment.AppointmentMode).like('w%')
        ).scalar() or 0

        # Use optimized slot calculation for total slots
        total_facility_slots = calculate_total_facility_slots_optimized(db, FacilityID, date)
        
        # Calculate available (free) slots = Total slots - Booked appointments
        available_slots = max(0, total_facility_slots - total_appointments)

        summary = AppointmentSummary(
            totalAppointments=total_appointments,
            totalCheckin=total_checkin,
            availableSlots=available_slots,  # Now shows actual free slots
            totalWalkInPatients=total_walkins
        )

        logger.info(f"Appointment details query completed in {time_module.time() - start_time:.2f}s")
        return AppointmentDetailsResponse_Original(hourly=hourly, summary=summary)
        
    except Exception as e:
        logger.error(f"Error in get_appointment_details: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error retrieving appointment details: {str(e)}")
@router.get("/getDoctorDetails", response_model=DoctorDashboardResponse)
async def get_doctor_details_for_dashboard(
    FacilityID: int = Query(..., description="Facility ID"),
    Date: date = Query(..., description="Date in YYYY-MM-DD format"),
    DoctorID: Optional[int] = Query(None, description="Optional Doctor ID for filtering"),
    DoctorName: Optional[str] = Query(None, description="Optional Doctor Name for filtering"),
    db: Session = Depends(get_db)
):
    start_time = time_module.time()
    logger.info(f"Starting doctor dashboard query for facility {FacilityID} on {Date}")
    
    try:
        day_of_week = get_day_of_week(Date)
        
        # Verify facility exists
        facility = db.query(model.Facility.FacilityID).filter(model.Facility.FacilityID == FacilityID).first()
        if not facility:
            raise HTTPException(status_code=404, detail="Facility not found")

        # Get ALL doctors in the facility for display
        all_doctors = db.query(model.Doctors).filter(model.Doctors.FacilityID == FacilityID).all()
        
        # Build filtered appointments query based on doctor filter
        appointments_query = db.query(model.Appointment).filter(
            and_(
                model.Appointment.FacilityID == FacilityID,
                model.Appointment.AppointmentDate == Date
            )
        )
        
        doctor_filter_info = {}
        filtered_doctor_ids = []
        
        if DoctorID is not None:
            appointments_query = appointments_query.filter(model.Appointment.DoctorID == DoctorID)
            doctor_filter_info["doctor_id"] = DoctorID
            filtered_doctor_ids = [DoctorID]
            
        if DoctorName is not None:
            # Find doctors matching the name
            matching_doctors = db.query(model.Doctors.id).filter(
                and_(
                    model.Doctors.FacilityID == FacilityID,
                    func.concat(model.Doctors.firstname, ' ', model.Doctors.lastname).ilike(f"%{DoctorName}%")
                )
            ).all()
            
            if matching_doctors:
                matching_doctor_ids = [doctor.id for doctor in matching_doctors]
                appointments_query = appointments_query.filter(model.Appointment.DoctorID.in_(matching_doctor_ids))
                doctor_filter_info["doctor_name"] = DoctorName
                filtered_doctor_ids = matching_doctor_ids
            else:
                # No matching doctors found
                return create_empty_response_with_all_doctors(FacilityID, Date, day_of_week, doctor_filter_info, all_doctors, db)

        appointments = appointments_query.options(joinedload(model.Appointment.patient)).all()

        # Get hourly booking data (only for filtered appointments)
        hourly_data = get_hourly_booking_data_optimized(appointments)
        
        # Calculate summary with filtered appointments and filtered doctor IDs for available slots
        # If no doctor filter is applied, use all doctor IDs
        doctor_ids_for_summary = filtered_doctor_ids if filtered_doctor_ids else [doctor.id for doctor in all_doctors]
        summary = calculate_summary_for_filtered_doctors(appointments, doctor_ids_for_summary, db, FacilityID, Date)
        
        # Get ALL doctors info with their status (not just filtered ones)
        doctors_info = get_doctors_info_optimized(all_doctors, Date, FacilityID, db, day_of_week)
        
        # Get token data (only for filtered appointments)
        token_data = get_token_data_optimized(appointments, all_doctors)

        logger.info(f"Doctor dashboard query completed in {time_module.time() - start_time:.2f}s")

        return DoctorDashboardResponse(
            facility_id=FacilityID,
            date=Date.strftime("%Y-%m-%d"),
            day_of_week=day_of_week,
            doctor_filter=doctor_filter_info if doctor_filter_info else None,
            hourly_booking_chart=hourly_data,
            summary=summary,
            doctors=doctors_info,
            token_data=token_data
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in get_doctor_details_for_dashboard: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error retrieving dashboard data: {str(e)}")


def calculate_summary_for_filtered_doctors(appointments: List[model.Appointment], doctor_ids: List[int], 
                                         db: Session, facility_id: int, date: date) -> DoctorSummary:
    """Calculate summary with available slots based on specific filtered doctors only"""
    
    # Count only non-cancelled appointments for totals
    active_appointments = [app for app in appointments if not app.Cancelled]
    
    total_appointments = len(active_appointments)
    total_checkin = sum(1 for app in active_appointments if app.CheckinTime is not None)
    total_walkin_patients = sum(1 for app in active_appointments if 
                               hasattr(app, 'AppointmentMode') and 
                               app.AppointmentMode and 
                               app.AppointmentMode.lower().startswith('w'))
    
    # Calculate available slots ONLY for the filtered doctors
    available_slots = 0
    
    if doctor_ids:  # Only calculate if we have doctor IDs
        try:
            # Get total slots from doctor calendar for filtered doctors only
            total_calendar_slots = db.query(func.count(model.DoctorCalendar.SlotID)).filter(
                and_(
                    model.DoctorCalendar.DoctorID.in_(doctor_ids),
                    model.DoctorCalendar.Date == date,
                    model.DoctorCalendar.FacilityID == facility_id,
                    or_(
                        model.DoctorCalendar.SlotLeave.is_(None),
                        and_(model.DoctorCalendar.SlotLeave != '1', model.DoctorCalendar.SlotLeave != 'Y')
                    ),
                    or_(
                        model.DoctorCalendar.FullDayLeave.is_(None),
                        and_(model.DoctorCalendar.FullDayLeave != '1', model.DoctorCalendar.FullDayLeave != 'Y')
                    )
                )
            ).scalar() or 0
            
            logger.info(f"Total calendar slots for filtered doctors {doctor_ids}: {total_calendar_slots}")
            
            # Available slots = Total calendar slots - Booked appointments (only non-cancelled)
            available_slots = max(0, total_calendar_slots - total_appointments)
            
            # If no calendar entries found for filtered doctors, available_slots will be 0
            if total_calendar_slots == 0:
                logger.info(f"No calendar entries found for doctors {doctor_ids} on {date}, setting available_slots to 0")
                available_slots = 0
            
        except Exception as e:
            logger.error(f"Error calculating available slots from calendar for filtered doctors: {str(e)}")
            # If calendar query fails, set available_slots to 0 (conservative approach)
            available_slots = 0
    
    return DoctorSummary(
        total_appointments=total_appointments,
        total_checkin=total_checkin,
        available_slots=available_slots,
        total_walkin_patients=total_walkin_patients
    )


def create_empty_response_with_all_doctors(facility_id: int, date: date, day_of_week: str, doctor_filter: dict, all_doctors: List[model.Doctors], db: Session):
    """Create response with empty appointments but show all doctors - updated to use new summary function"""
    doctors_info = get_doctors_info_optimized(all_doctors, date, facility_id, db, day_of_week)
    
    # Calculate available slots for all doctors when no appointments found
    all_doctor_ids = [doctor.id for doctor in all_doctors]
    summary = calculate_summary_for_filtered_doctors([], all_doctor_ids, db, facility_id, date)
    
    return DoctorDashboardResponse(
        facility_id=facility_id,
        date=date.strftime("%Y-%m-%d"),
        day_of_week=day_of_week,
        doctor_filter=doctor_filter if doctor_filter else None,
        hourly_booking_chart=[],
        summary=summary,
        doctors=doctors_info,
        token_data=[]
    )

def get_hourly_booking_data_optimized(appointments: List[model.Appointment]) -> List[HourlyBookingData]:
    """Optimized hourly booking data generation - exclude cancelled appointments"""
    hourly_counts = {hour: 0 for hour in range(9, 22)}
    
    # Single pass through appointments - only count non-cancelled appointments
    for appointment in appointments:
        # Only include non-cancelled appointments for hourly data (matching appointment details logic)
        if not appointment.Cancelled and appointment.AppointmentTime and 9 <= appointment.AppointmentTime.hour <= 21:
            hourly_counts[appointment.AppointmentTime.hour] += 1
    
    return [
        HourlyBookingData(
            hour=hour,
            booking_count=count,
            time_slot=format_hour_display(hour)
        )
        for hour, count in hourly_counts.items()
    ]

def format_hour_display(hour: int) -> str:
    """Convert 24-hour format to 12-hour format display"""
    if hour == 0:
        return "12 AM"
    elif hour < 12:
        return f"{hour} AM"
    elif hour == 12:
        return "12 PM"
    else:
        return f"{hour - 12} PM"

def get_checkin_time_attr(appointment):
    """Get checkin time attribute - now we know it's CheckinTime"""
    return getattr(appointment, 'CheckinTime', None)

def calculate_summary_optimized(appointments: List[model.Appointment], doctor_count: int, 
                               db: Session, doctor_ids: List[int], facility_id: int, date: date) -> DoctorSummary:
    """Optimized summary calculation with correct available slots from doctor calendar"""
    
    # Count only non-cancelled appointments for totals
    active_appointments = [app for app in appointments if not app.Cancelled]
    
    total_appointments = len(active_appointments)
    total_checkin = sum(1 for app in active_appointments if app.CheckinTime is not None)
    total_walkin_patients = sum(1 for app in active_appointments if 
                               hasattr(app, 'AppointmentMode') and 
                               app.AppointmentMode and 
                               app.AppointmentMode.lower().startswith('w'))
    
    # Calculate actual available slots from doctor calendar
    try:
        # Get total slots from doctor calendar (not on leave)
        total_calendar_slots = db.query(func.count(model.DoctorCalendar.SlotID)).filter(
            and_(
                model.DoctorCalendar.DoctorID.in_(doctor_ids),
                model.DoctorCalendar.Date == date,
                model.DoctorCalendar.FacilityID == facility_id,
                or_(
                    model.DoctorCalendar.SlotLeave.is_(None),
                    and_(model.DoctorCalendar.SlotLeave != '1', model.DoctorCalendar.SlotLeave != 'Y')
                ),
                or_(
                    model.DoctorCalendar.FullDayLeave.is_(None),
                    and_(model.DoctorCalendar.FullDayLeave != '1', model.DoctorCalendar.FullDayLeave != 'Y')
                )
            )
        ).scalar() or 0
        
        # Available slots = Total calendar slots - Booked appointments (only non-cancelled)
        available_slots = max(0, total_calendar_slots - total_appointments)
        
    except Exception as e:
        logger.error(f"Error calculating available slots from calendar: {str(e)}")
        # Fallback to rough estimate if calendar query fails
        available_slots = max(0, doctor_count * 20 - total_appointments)
    
    return DoctorSummary(
        total_appointments=total_appointments,
        total_checkin=total_checkin,
        available_slots=available_slots,
        total_walkin_patients=total_walkin_patients
    )

def get_doctors_info_optimized(doctors: List[model.Doctors], date: date, facility_id: int, 
                              db: Session, day_of_week: str) -> List[DoctorInfo]:
    """Optimized doctor info retrieval with correct available (free) slots calculation"""
    
    # Get all doctor schedules in one query
    doctor_ids = [doctor.id for doctor in doctors]
    schedules = db.query(model.DoctorSchedule).filter(
        and_(
            model.DoctorSchedule.DoctorID.in_(doctor_ids),
            func.lower(model.DoctorSchedule.DayOfWeek) == day_of_week.lower()
        )
    ).all()
    
    schedule_dict = {s.DoctorID: s for s in schedules}
    
    # Get all calendar entries in one query
    calendar_entries = db.query(model.DoctorCalendar).filter(
        and_(
            model.DoctorCalendar.DoctorID.in_(doctor_ids),
            model.DoctorCalendar.Date == date,
            model.DoctorCalendar.FacilityID == facility_id
        )
    ).all()
    
    calendar_dict = {}
    for entry in calendar_entries:
        if entry.DoctorID not in calendar_dict:
            calendar_dict[entry.DoctorID] = []
        calendar_dict[entry.DoctorID].append(entry)
    
    # Get all booked appointments for these doctors on this date - only count non-cancelled
    booked_appointments = db.query(model.Appointment).filter(
        and_(
            model.Appointment.DoctorID.in_(doctor_ids),
            model.Appointment.AppointmentDate == date,
            model.Appointment.FacilityID == facility_id,
            model.Appointment.Cancelled == False  # Only count non-cancelled appointments for availability calculation
        )
    ).all()
    
    # Create a dictionary to count booked slots per doctor
    booked_slots_dict = {}
    for appointment in booked_appointments:
        doctor_id = appointment.DoctorID
        if doctor_id not in booked_slots_dict:
            booked_slots_dict[doctor_id] = 0
        booked_slots_dict[doctor_id] += 1
    
    doctors_info = []
    
    for doctor in doctors:
        doctor_name = f"Dr. {doctor.firstname} {doctor.lastname}".strip()
        doctor_schedule = schedule_dict.get(doctor.id)
        doctor_calendar = calendar_dict.get(doctor.id, [])
        
        # Check for full day leave
        is_on_full_leave = any(entry.FullDayLeave in ('1', 'Y') for entry in doctor_calendar)
        
        if not doctor_schedule or is_on_full_leave:
            status = "Off Duty"
            available_slots = 0
            total_slots = 0
        else:
            status = "On Duty"
            
            # Calculate total slots (slots not on leave)
            total_available_slots = len([entry for entry in doctor_calendar 
                                       if entry.SlotLeave not in ('1', 'Y')])
            
            # Calculate booked slots for this doctor
            booked_slots = booked_slots_dict.get(doctor.id, 0)
            
            # Available slots = Total available slots - Booked slots
            available_slots = max(0, total_available_slots - booked_slots)
            total_slots = len(doctor_calendar)
        
        doctors_info.append(DoctorInfo(
            doctor_id=doctor.id,
            name=doctor_name,
            specialization=doctor.specialization or "General",
            status=status,
            available_slots=available_slots,  # Now shows actual free slots
            total_slots=total_slots
        ))
    
    return doctors_info

def get_token_data_optimized(appointments: List[model.Appointment], doctors: List[model.Doctors]) -> List[TokenData]:
    """Optimized token data retrieval with correct payment info from patient table and appointment status"""
    
    # Create doctor lookup dictionary
    doctor_lookup = {doctor.id: doctor for doctor in doctors}
    
    token_data = []
    
    for appointment in appointments:
        doctor = doctor_lookup.get(appointment.DoctorID)
        doctor_name = f"Dr. {doctor.firstname} {doctor.lastname}".strip() if doctor else "Unknown"
        specialization = doctor.specialization if doctor else "General"
        
        # Get patient info safely
        patient_name = "Unknown"
        age = 0
        is_paid = False
        
        if appointment.patient:
            patient_name = f"{appointment.patient.firstname} {appointment.patient.lastname}".strip()
            age = getattr(appointment.patient, 'age', 0) or 0
            
            # Get is_paid from patient table - check common field names
            is_paid_value = getattr(appointment.patient, 'is_paid', None) or \
                           getattr(appointment.patient, 'payment_status', None) or \
                           getattr(appointment.patient, 'paid_status', None) or \
                           getattr(appointment.patient, 'PaymentStatus', None) or \
                           getattr(appointment.patient, 'IsPaid', None)
            
            # Handle different formats of payment status
            if isinstance(is_paid_value, bool):
                is_paid = is_paid_value
            elif isinstance(is_paid_value, str):
                is_paid = is_paid_value.lower() in ['paid', 'yes', 'y', '1', 'true']
            elif isinstance(is_paid_value, int):
                is_paid = bool(is_paid_value)
            else:
                is_paid = False
        
        # Format check-in time
        checkin_time = None
        if appointment.CheckinTime:
            checkin_time = appointment.CheckinTime.strftime("%I:%M %p")
        
        # Payment type with updated options - check multiple possible field names
        payment_type = "Cash"  # Default
        
        # Check appointment table for payment method
        appointment_payment = None
        for field_name in ['PaymentMethod', 'PaymentType', 'payment_method', 'payment_type', 
                          'PaymentMode', 'payment_mode', 'Method', 'Type']:
            value = getattr(appointment, field_name, None)
            if value:
                appointment_payment = value
                logger.info(f"Found payment method in appointment.{field_name}: {value}")
                break
        
        # Check patient table for payment method
        patient_payment = None
        if appointment.patient:
            for field_name in ['payment_method', 'PaymentMethod', 'payment_type', 'PaymentType',
                              'payment_mode', 'PaymentMode', 'Method', 'Type']:
                value = getattr(appointment.patient, field_name, None)
                if value:
                    patient_payment = value
                    logger.info(f"Found payment method in patient.{field_name}: {value}")
                    break
        
        # Use appointment payment method first, then patient payment method
        payment_method = appointment_payment or patient_payment
        
        if payment_method:
            payment_method_lower = str(payment_method).lower().strip()
            logger.info(f"Processing payment method: {payment_method} -> {payment_method_lower}")
            
            if 'upi' in payment_method_lower:
                payment_type = "UPI"
            elif any(card in payment_method_lower for card in ['debit', 'credit', 'card']):
                payment_type = "Debit Card/Credit Card"
            elif any(net in payment_method_lower for net in ['net banking', 'netbanking', 'internet banking', 'online', 'net_banking']):
                payment_type = "Net Banking"
            elif 'cash' in payment_method_lower:
                payment_type = "Cash"
            else:
                payment_type = str(payment_method).title()  # Use original with title case
            
            logger.info(f"Final payment type: {payment_type}")
        else:
            logger.info("No payment method found, using default: Cash")
        
        # Determine appointment status
        status = "Scheduled"  # Default status
        
        if appointment.Cancelled:
            status = "Cancelled"
        else:
            # Check for completion status - look for common completion indicators
            completion_status = getattr(appointment, 'AppointmentStatus', None) or \
                               getattr(appointment, 'Status', None) or \
                               getattr(appointment, 'appointment_status', None) or \
                               getattr(appointment, 'status', None)
            
            if completion_status:
                completion_status_lower = str(completion_status).lower().strip()
                if 'completed' in completion_status_lower or 'complete' in completion_status_lower:
                    status = "Completed"
                elif 'cancelled' in completion_status_lower or 'cancel' in completion_status_lower:
                    status = "Cancelled"
                elif 'scheduled' in completion_status_lower or 'schedule' in completion_status_lower:
                    status = "Scheduled"
                else:
                    # If we have a checkin time but no explicit completion status, assume scheduled
                    status = "Scheduled"
            else:
                # If no status field found, use checkin time as indicator
                status = "Scheduled"
        
        # MODIFIED: Only show token for checked-in appointments
        token = ""  # Default to empty string
        
        # Only get token if appointment has checkin time (is checked in)
        if appointment.CheckinTime:
            # Try to get token from various possible field names
            token_field_names = [
                'TokenNumber', 'token_number', 'Token', 'token', 
                'TokenID', 'token_id', 'AppointmentToken', 'appointment_token',
                'PatientToken', 'patient_token', 'QueueNumber', 'queue_number',
                'SequenceNumber', 'sequence_number'
            ]
            
            for field_name in token_field_names:
                token_value = getattr(appointment, field_name, None)
                if token_value is not None:
                    token = str(token_value)
                    logger.info(f"Found token in appointment.{field_name}: {token}")
                    break
            
            # If no token found in appointment, check patient table
            if token == "":
                if appointment.patient:
                    for field_name in token_field_names:
                        token_value = getattr(appointment.patient, field_name, None)
                        if token_value is not None:
                            token = str(token_value)
                            logger.info(f"Found token in patient.{field_name}: {token}")
                            break
            
            # If still no token found, generate a fallback token for checked-in appointments
            if token == "":
                token = f"A{appointment.AppointmentID}"
                logger.info(f"No token found for checked-in appointment, using fallback: {token}")
        else:
            # For non-checked-in appointments, token remains empty string
            logger.info(f"Appointment {appointment.AppointmentID} not checked in, token set to empty string")
        
        token_data.append(TokenData(
            appointment_id=appointment.AppointmentID,
            token=token,  # Will be empty string for non-checked-in appointments
            patient_name=patient_name,
            age=age,
            doctor_name=doctor_name,
            specialization=specialization,
            checkin_time=checkin_time,
            payment_type=payment_type,
            is_paid=is_paid,
            status=status
        ))
    
    return token_data
@router.get("/getCheckinDetails", response_model=CheckinResponse)
async def get_checkin_details_for_dashboard(
    FacilityID: int = Query(..., description="Facility ID"),
    Date: date = Query(..., description="Date in YYYY-MM-DD format (e.g., 2025-07-26)"),
    db: Session = Depends(get_db)
):
    start_time = time_module.time()
    logger.info(f"Starting checkin details query for facility {FacilityID} on {Date}")
    
    try:
        day_of_week = get_day_of_week(Date)
        
        facility = db.query(model.Facility.FacilityID).filter(model.Facility.FacilityID == FacilityID).first()
        if not facility:
            raise HTTPException(status_code=404, detail="Facility not found")
        
        # Optimized query with limited joins
        appointments = db.query(model.Appointment).filter(
            and_(
                model.Appointment.FacilityID == FacilityID, 
                model.Appointment.AppointmentDate == Date
            )
        ).options(
            joinedload(model.Appointment.patient),
            joinedload(model.Appointment.doctor)
        ).order_by(model.Appointment.AppointmentTime).all()
        
        if not appointments:
            return CheckinResponse(
                facility_id=FacilityID, 
                date=Date.strftime("%Y-%m-%d"), 
                day_of_week=day_of_week,
                appointments=[], 
                summary=CheckinSummary()
            )
        
        appointments_info = []
        checked_in_count = not_checked_in_count = cancelled_count = 0
        
        for appointment in appointments:
            try:
                patient = appointment.patient
                doctor = appointment.doctor
                
                if not patient or not doctor:
                    logger.warning(f"Missing patient or doctor data for appointment {appointment.AppointmentID}")
                    continue
                
                patient_name = f"{patient.firstname} {patient.lastname}".strip()
                doctor_name = f"Dr. {doctor.firstname} {doctor.lastname}".strip()
                
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
                    patient_contact=getattr(patient, 'contact_number', '') or '', 
                    patient_email=getattr(patient, 'email_id', '') or '', 
                    patient_age=getattr(patient, 'age', None),
                    patient_gender=getattr(patient, 'gender', None), 
                    doctor_id=appointment.DoctorID, 
                    doctor_name=doctor_name,
                    doctor_specialization=getattr(doctor, 'specialization', '') or "General", 
                    appointment_date=appointment.AppointmentDate.strftime("%Y-%m-%d"),
                    appointment_time=appointment.AppointmentTime.strftime("%H:%M"), 
                    scheduled_datetime=appointment_datetime.strftime("%Y-%m-%d %H:%M"),
                    reason=getattr(appointment, 'Reason', '') or '', 
                    appointment_mode=getattr(appointment, 'AppointmentMode', '') or '', 
                    appointment_status=getattr(appointment, 'AppointmentStatus', '') or "Scheduled",
                    token_id=getattr(appointment, 'TokenID', None), 
                    checkin_time=checkin_time_str, 
                    checkin_status=checkin_status, 
                    cancelled=bool(appointment.Cancelled)
                ))
                
            except Exception as e:
                logger.error(f"Error processing appointment {appointment.AppointmentID}: {str(e)}")
                continue
        
        summary = CheckinSummary(
            total_appointments=len(appointments), 
            checked_in=checked_in_count,
            not_checked_in=not_checked_in_count, 
            cancelled=cancelled_count
        )
        
        logger.info(f"Checkin details query completed in {time_module.time() - start_time:.2f}s")
        
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
        logger.error(f"Error in get_checkin_details_for_dashboard: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error retrieving check-in details: {str(e)}")