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

# Schemas (keeping existing schemas unchanged)
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
    """
    Updated function to calculate total slots using new doctor_schedule table
    Now calculates based on 15-minute slots (4 slots per hour)
    """
    start_time = time_module.time()
    
    try:
        day_of_week = get_day_of_week(target_date)
        
        # Get all schedule entries for the target date and weekday
        schedules = db.query(model.DoctorSchedule).filter(
            and_(
                model.DoctorSchedule.Facility_id == facility_id,
                model.DoctorSchedule.Start_Date <= target_date,
                model.DoctorSchedule.End_Date >= target_date,
                func.lower(model.DoctorSchedule.WeekDay) == day_of_week.lower()
            )
        ).all()
        
        if not schedules:
            logger.info(f"No schedules found for facility {facility_id} on {day_of_week} {target_date}")
            return 0
        
        total_slots = 0
        
        for schedule in schedules:
            try:
                # Get start and end times
                start_time_obj = schedule.Slot_Start_Time
                end_time_obj = schedule.Slot_End_Time
                
                # Convert string times to time objects if needed
                if isinstance(start_time_obj, str):
                    try:
                        start_time_obj = datetime.strptime(start_time_obj, '%H:%M:%S').time()
                    except ValueError:
                        start_time_obj = datetime.strptime(start_time_obj, '%H:%M').time()
                
                if isinstance(end_time_obj, str):
                    try:
                        end_time_obj = datetime.strptime(end_time_obj, '%H:%M:%S').time()
                    except ValueError:
                        end_time_obj = datetime.strptime(end_time_obj, '%H:%M').time()
                
                # Calculate duration in minutes
                start_datetime = datetime.combine(target_date, start_time_obj)
                end_datetime = datetime.combine(target_date, end_time_obj)
                
                # Handle case where end time is past midnight
                if end_datetime < start_datetime:
                    end_datetime += timedelta(days=1)
                
                duration_minutes = (end_datetime - start_datetime).total_seconds() / 60
                
                # Calculate number of 15-minute slots
                slots_in_this_schedule = int(duration_minutes / 15)
                
                total_slots += slots_in_this_schedule
                
                logger.info(f"Schedule for Doctor {schedule.Doctor_id}: {start_time_obj.strftime('%H:%M')} - {end_time_obj.strftime('%H:%M')} = {duration_minutes} minutes = {slots_in_this_schedule} slots")
                
            except Exception as e:
                logger.error(f"Error processing schedule {schedule.Window_Num} for doctor {schedule.Doctor_id}: {str(e)}")
                continue
        
        logger.info(f"Available slots calculation took: {time_module.time() - start_time:.2f}s")
        logger.info(f"Total facility slots for {target_date}: {total_slots} (based on 15-minute intervals)")
        
        return total_slots
        
    except Exception as e:
        logger.error(f"Error in calculate_total_facility_slots_optimized: {str(e)}")
        return 0

def is_slot_available(db: Session, facility_id: int, doctor_id: int, 
                     appointment_date: date, appointment_time: time) -> bool:
    """
    Updated function to check slot availability using new tables
    """
    try:
        # Check if appointment already exists
        existing_appointment = db.query(model.Appointment.AppointmentID).filter(
            model.Appointment.FacilityID == facility_id,
            model.Appointment.DoctorID == doctor_id,
            model.Appointment.AppointmentDate == appointment_date,
            model.Appointment.AppointmentTime == appointment_time,
            model.Appointment.Cancelled == False
        ).first()
        
        if existing_appointment:
            return False
        
        # Check if slot is marked as booked in doctor_booked_slots
        booked_slot = db.query(model.DoctorBookedSlots.DCID).filter(
            model.DoctorBookedSlots.Doctor_id == doctor_id,
            model.DoctorBookedSlots.Facility_id == facility_id,
            model.DoctorBookedSlots.Slot_date == appointment_date,
            model.DoctorBookedSlots.Start_Time <= appointment_time,
            model.DoctorBookedSlots.End_Time > appointment_time,
            model.DoctorBookedSlots.Booked_status == 'Y'
        ).first()
        
        return booked_slot is None
        
    except Exception as e:
        logger.error(f"Error checking slot availability: {str(e)}")
        return False

@router.get("/details", response_model=AppointmentDetailsResponse_Original)
def get_appointment_details(FacilityID: int = Query(...), date: date = Query(...), db: Session = Depends(get_db)):
    start_time = time_module.time()
    logger.info(f"Starting appointment details query for facility {FacilityID} on {date}")
    
    try:
        # Optimized hourly data query (unchanged - still uses Appointment table)
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

        # Total appointments (unchanged)
        total_appointments = db.query(func.count(model.Appointment.AppointmentID)).filter(
            model.Appointment.FacilityID == FacilityID, 
            model.Appointment.AppointmentDate == date,
            model.Appointment.Cancelled == False
        ).scalar() or 0

        # Total check-ins (unchanged)
        total_checkin = db.query(func.count(model.Appointment.AppointmentID)).filter(
            model.Appointment.FacilityID == FacilityID, 
            model.Appointment.AppointmentDate == date,
            model.Appointment.Cancelled == False,
            model.Appointment.CheckinTime.isnot(None)
        ).scalar() or 0

        # Total walk-ins (unchanged)
        total_walkins = db.query(func.count(model.Appointment.AppointmentID)).filter(
            model.Appointment.FacilityID == FacilityID, 
            model.Appointment.AppointmentDate == date,
            model.Appointment.Cancelled == False,
            func.lower(model.Appointment.AppointmentMode).like('w%')
        ).scalar() or 0

        # Use updated slot calculation for total slots
        total_facility_slots = calculate_total_facility_slots_optimized(db, FacilityID, date)
        
        # Calculate available (free) slots = Total slots - Booked appointments
        available_slots = max(0, total_facility_slots - total_appointments)

        summary = AppointmentSummary(
            totalAppointments=total_appointments,
            totalCheckin=total_checkin,
            availableSlots=available_slots,
            totalWalkInPatients=total_walkins
        )

        logger.info(f"Appointment details query completed in {time_module.time() - start_time:.2f}s")
        return AppointmentDetailsResponse_Original(hourly=hourly, summary=summary)
        
    except Exception as e:
        logger.error(f"Error in get_appointment_details: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error retrieving appointment details: {str(e)}")

@router.get("/getDoctorDetails", response_model=DoctorDashboardResponse)
async def get_doctor_details_for_dashboard(
    facility_id: int = Query(..., description="Facility ID"),
    date: date = Query(..., description="Date in YYYY-MM-DD format"),
    doctor_id: Optional[int] = Query(None, description="Optional Doctor ID for filtering"),
    DoctorName: Optional[str] = Query(None, description="Optional Doctor Name for filtering"),
    db: Session = Depends(get_db)
):
    start_time = time_module.time()
    logger.info(f"Starting doctor dashboard query for facility {facility_id} on {date}")
    
    try:
        day_of_week = get_day_of_week(date)
        
        # Verify facility exists
        facility = db.query(model.Facility.FacilityID).filter(model.Facility.FacilityID == facility_id).first()
        if not facility:
            raise HTTPException(status_code=404, detail="Facility not found")

        # Get ALL doctors in the facility for display
        all_doctors = db.query(model.Doctors).filter(model.Doctors.FacilityID == facility_id).all()
        
        # Build filtered appointments query based on doctor filter
        appointments_query = db.query(model.Appointment).filter(
            and_(
                model.Appointment.FacilityID == facility_id,
                model.Appointment.AppointmentDate == date
            )
        )
        
        doctor_filter_info = {}
        filtered_doctor_ids = []
        
        # Apply doctor ID filter only if provided and not None
        if doctor_id is not None and doctor_id > 0:
            appointments_query = appointments_query.filter(model.Appointment.DoctorID == doctor_id)
            doctor_filter_info["doctor_id"] = doctor_id
            filtered_doctor_ids = [doctor_id]
            logger.info(f"Filtering by Doctor ID: {doctor_id}")
            
        # Apply doctor name filter only if provided and not empty
        elif DoctorName is not None and DoctorName.strip():
            # Find doctors matching the name
            matching_doctors = db.query(model.Doctors.id).filter(
                and_(
                    model.Doctors.FacilityID == facility_id,
                    func.concat(model.Doctors.firstname, ' ', model.Doctors.lastname).ilike(f"%{DoctorName.strip()}%")
                )
            ).all()
            
            if matching_doctors:
                matching_doctor_ids = [doctor.id for doctor in matching_doctors]
                appointments_query = appointments_query.filter(model.Appointment.DoctorID.in_(matching_doctor_ids))
                doctor_filter_info["doctor_name"] = DoctorName.strip()
                filtered_doctor_ids = matching_doctor_ids
                logger.info(f"Filtering by Doctor Name: {DoctorName.strip()}, found IDs: {matching_doctor_ids}")
            else:
                # No matching doctors found
                logger.warning(f"No doctors found matching name: {DoctorName}")
                return create_empty_response_with_all_doctors(facility_id, date, day_of_week, doctor_filter_info, all_doctors, db)
        else:
            # No filters applied - show all doctors' appointments
            logger.info("No doctor filters applied, showing all appointments")

        appointments = appointments_query.options(joinedload(model.Appointment.patient)).all()
        logger.info(f"Found {len(appointments)} appointments for the query")

        # Get hourly booking data (only for filtered appointments)
        hourly_data = get_hourly_booking_data_optimized(appointments)
        
        # Calculate summary with filtered appointments and filtered doctor IDs for available slots
        # If no doctor filter is applied, use all doctor IDs
        doctor_ids_for_summary = filtered_doctor_ids if filtered_doctor_ids else [doctor.id for doctor in all_doctors]
        summary = calculate_summary_for_filtered_doctors(appointments, doctor_ids_for_summary, db, facility_id, date)
        
        # Get ALL doctors info with their status (not just filtered ones)
        doctors_info = get_doctors_info_optimized(all_doctors, date, facility_id, db, day_of_week)
        
        # Filter appointments by current date AND only show checked-in appointments in token data
        from datetime import date as date_class
        current_date = date_class.today()
        
        # Filter appointments to only include those from current date that are also waiting
        current_date_waiting_appointments = [app for app in appointments 
                                   if app.AppointmentDate == current_date and 
                                   app.AppointmentStatus == 'Waiting' and 
                                   not app.Cancelled]
        
        # Get token data (only for current date checked-in appointments)
        token_data = get_token_data_optimized(current_date_waiting_appointments, all_doctors)

        logger.info(f"Doctor dashboard query completed in {time_module.time() - start_time:.2f}s")

        return DoctorDashboardResponse(
            facility_id=facility_id,
            date=date.strftime("%Y-%m-%d"),
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
    """
    Updated function to calculate summary using new doctor_schedule table
    Now calculates available slots based on 15-minute intervals (4 slots per hour)
    """
    
    # Count only non-cancelled appointments for totals
    active_appointments = [app for app in appointments if not app.Cancelled]
    
    total_appointments = len(active_appointments)
    total_checkin = sum(1 for app in active_appointments if app.CheckinTime is not None)
    total_walkin_patients = sum(1 for app in active_appointments if 
                               hasattr(app, 'AppointmentMode') and 
                               app.AppointmentMode and 
                               app.AppointmentMode.lower().startswith('w'))
    
    # Calculate available slots for the filtered doctors using 15-minute slot logic
    available_slots = 0
    
    if doctor_ids:
        try:
            day_of_week = get_day_of_week(date)
            
            # Get all schedule entries for filtered doctors from doctor_schedule
            schedules = db.query(model.DoctorSchedule).filter(
                and_(
                    model.DoctorSchedule.Doctor_id.in_(doctor_ids),
                    model.DoctorSchedule.Facility_id == facility_id,
                    model.DoctorSchedule.Start_Date <= date,
                    model.DoctorSchedule.End_Date >= date,
                    func.lower(model.DoctorSchedule.WeekDay) == day_of_week.lower()
                )
            ).all()
            
            total_scheduled_slots = 0
            
            for schedule in schedules:
                try:
                    # Get start and end times
                    start_time_obj = schedule.Slot_Start_Time
                    end_time_obj = schedule.Slot_End_Time
                    
                    # Convert string times to time objects if needed
                    if isinstance(start_time_obj, str):
                        try:
                            start_time_obj = datetime.strptime(start_time_obj, '%H:%M:%S').time()
                        except ValueError:
                            start_time_obj = datetime.strptime(start_time_obj, '%H:%M').time()
                    
                    if isinstance(end_time_obj, str):
                        try:
                            end_time_obj = datetime.strptime(end_time_obj, '%H:%M:%S').time()
                        except ValueError:
                            end_time_obj = datetime.strptime(end_time_obj, '%H:%M').time()
                    
                    # Calculate duration in minutes
                    start_datetime = datetime.combine(date, start_time_obj)
                    end_datetime = datetime.combine(date, end_time_obj)
                    
                    # Handle case where end time is past midnight
                    if end_datetime < start_datetime:
                        end_datetime += timedelta(days=1)
                    
                    duration_minutes = (end_datetime - start_datetime).total_seconds() / 60
                    
                    # Calculate number of 15-minute slots
                    slots_in_this_schedule = int(duration_minutes / 15)
                    
                    total_scheduled_slots += slots_in_this_schedule
                    
                    logger.info(f"Doctor {schedule.Doctor_id} schedule: {start_time_obj.strftime('%H:%M')} - {end_time_obj.strftime('%H:%M')} = {duration_minutes} minutes = {slots_in_this_schedule} slots")
                    
                except Exception as e:
                    logger.error(f"Error processing schedule for doctor {schedule.Doctor_id}: {str(e)}")
                    continue
            
            logger.info(f"Total scheduled slots for filtered doctors {doctor_ids}: {total_scheduled_slots}")
            
            # Get count of booked slots from doctor_booked_slots for these doctors on this date
            booked_slots_count = db.query(func.count(model.DoctorBookedSlots.DCID)).filter(
                and_(
                    model.DoctorBookedSlots.Doctor_id.in_(doctor_ids),
                    model.DoctorBookedSlots.Facility_id == facility_id,
                    model.DoctorBookedSlots.Slot_date == date,
                    model.DoctorBookedSlots.Booked_status == 'Y'
                )
            ).scalar() or 0
            
            # Available slots = Total scheduled slots - max(Booked slots, Active appointments)
            # Use max to avoid negative values
            unavailable_slots = max(booked_slots_count, total_appointments)
            available_slots = max(0, total_scheduled_slots - unavailable_slots)
            
            logger.info(f"Booked slots count: {booked_slots_count}, Active appointments: {total_appointments}")
            logger.info(f"Available slots calculated: {available_slots} (Total: {total_scheduled_slots} - Unavailable: {unavailable_slots})")
            
        except Exception as e:
            logger.error(f"Error calculating available slots for filtered doctors: {str(e)}")
            available_slots = 0
    
    return DoctorSummary(
        total_appointments=total_appointments,
        total_checkin=total_checkin,
        available_slots=available_slots,
        total_walkin_patients=total_walkin_patients
    )
def create_empty_response_with_all_doctors(facility_id: int, date: date, day_of_week: str, doctor_filter: dict, all_doctors: List[model.Doctors], db: Session):
    """Create response with empty appointments but show all doctors - updated for new table structure"""
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
    """Optimized hourly booking data generation - exclude cancelled appointments (unchanged)"""
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
    """Convert 24-hour format to 12-hour format display (unchanged)"""
    if hour == 0:
        return "12 AM"
    elif hour < 12:
        return f"{hour} AM"
    elif hour == 12:
        return "12 PM"
    else:
        return f"{hour - 12} PM"

def get_doctors_info_optimized(doctors: List[model.Doctors], date: date, facility_id: int, 
                              db: Session, day_of_week: str) -> List[DoctorInfo]:
    """
    Updated function to get doctor info using new table structure
    Now calculates slots based on 15-minute intervals (4 slots per hour)
    """
    
    # Get all doctor IDs
    doctor_ids = [doctor.id for doctor in doctors]
    
    # Get all doctor schedules for this date and weekday using new table
    schedules = db.query(model.DoctorSchedule).filter(
        and_(
            model.DoctorSchedule.Doctor_id.in_(doctor_ids),
            model.DoctorSchedule.Facility_id == facility_id,
            model.DoctorSchedule.Start_Date <= date,
            model.DoctorSchedule.End_Date >= date,
            func.lower(model.DoctorSchedule.WeekDay) == day_of_week.lower()
        )
    ).all()
    
    # Group schedules by doctor_id and calculate total slots per doctor based on 15-minute intervals
    schedule_slots_dict = {}
    for schedule in schedules:
        doctor_id = schedule.Doctor_id
        
        try:
            # Get start and end times
            start_time_obj = schedule.Slot_Start_Time
            end_time_obj = schedule.Slot_End_Time
            
            # Convert string times to time objects if needed
            if isinstance(start_time_obj, str):
                try:
                    start_time_obj = datetime.strptime(start_time_obj, '%H:%M:%S').time()
                except ValueError:
                    start_time_obj = datetime.strptime(start_time_obj, '%H:%M').time()
            
            if isinstance(end_time_obj, str):
                try:
                    end_time_obj = datetime.strptime(end_time_obj, '%H:%M:%S').time()
                except ValueError:
                    end_time_obj = datetime.strptime(end_time_obj, '%H:%M').time()
            
            # Calculate duration in minutes
            start_datetime = datetime.combine(date, start_time_obj)
            end_datetime = datetime.combine(date, end_time_obj)
            
            # Handle case where end time is past midnight
            if end_datetime < start_datetime:
                end_datetime += timedelta(days=1)
            
            duration_minutes = (end_datetime - start_datetime).total_seconds() / 60
            
            # Calculate number of 15-minute slots
            slots_in_this_schedule = int(duration_minutes / 15)
            
            if doctor_id not in schedule_slots_dict:
                schedule_slots_dict[doctor_id] = 0
            schedule_slots_dict[doctor_id] += slots_in_this_schedule
            
            logger.info(f"Doctor {doctor_id} schedule window: {start_time_obj.strftime('%H:%M')} - {end_time_obj.strftime('%H:%M')} = {duration_minutes} minutes = {slots_in_this_schedule} slots")
            
        except Exception as e:
            logger.error(f"Error processing schedule for doctor {doctor_id}: {str(e)}")
            continue
    
    # Get booked slots from doctor_booked_slots table
    booked_slots = db.query(model.DoctorBookedSlots).filter(
        and_(
            model.DoctorBookedSlots.Doctor_id.in_(doctor_ids),
            model.DoctorBookedSlots.Facility_id == facility_id,
            model.DoctorBookedSlots.Slot_date == date,
            model.DoctorBookedSlots.Booked_status == 'Y'
        )
    ).all()
    
    booked_slots_dict = {}
    for slot in booked_slots:
        doctor_id = slot.Doctor_id
        if doctor_id not in booked_slots_dict:
            booked_slots_dict[doctor_id] = 0
        booked_slots_dict[doctor_id] += 1
    
    # Get all booked appointments for these doctors on this date - only count non-cancelled
    booked_appointments = db.query(model.Appointment).filter(
        and_(
            model.Appointment.DoctorID.in_(doctor_ids),
            model.Appointment.AppointmentDate == date,
            model.Appointment.FacilityID == facility_id,
            model.Appointment.Cancelled == False
        )
    ).all()
    
    # Create a dictionary to count booked appointments per doctor
    appointment_count_dict = {}
    for appointment in booked_appointments:
        doctor_id = appointment.DoctorID
        if doctor_id not in appointment_count_dict:
            appointment_count_dict[doctor_id] = 0
        appointment_count_dict[doctor_id] += 1
    
    doctors_info = []
    
    for doctor in doctors:
        doctor_name = f"Dr. {doctor.firstname} {doctor.lastname}".strip()
        
        # Get scheduled slots for this doctor (calculated from time duration)
        total_scheduled_slots = schedule_slots_dict.get(doctor.id, 0)
        
        # Get booked slots count
        booked_slots_count = booked_slots_dict.get(doctor.id, 0)
        
        # Get appointment count
        appointment_count = appointment_count_dict.get(doctor.id, 0)
        
        if total_scheduled_slots == 0:
            status = "Off Duty"
            available_slots = 0
            total_slots = 0
        else:
            status = "On Duty"
            
            # Available slots = Total scheduled slots - max(booked slots, appointments)
            # Use max because some slots might be booked but not have appointments yet
            unavailable_slots = max(booked_slots_count, appointment_count)
            available_slots = max(0, total_scheduled_slots - unavailable_slots)
            total_slots = total_scheduled_slots
        
        logger.info(f"Doctor {doctor.id} ({doctor_name}): Total slots: {total_slots}, Available: {available_slots}, Booked slots: {booked_slots_count}, Appointments: {appointment_count}")
        
        doctors_info.append(DoctorInfo(
            doctor_id=doctor.id,
            name=doctor_name,
            specialization=doctor.specialization or "General",
            status=status,
            available_slots=available_slots,
            total_slots=total_slots
        ))
    
    return doctors_info
def get_token_data_optimized(appointments: List[model.Appointment], doctors: List[model.Doctors]) -> List[TokenData]:
    """Token data retrieval function (unchanged - still uses Appointment and Patient tables)"""
    
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
    """
    Check-in details endpoint (unchanged - still uses Appointment, Patient, and Doctor tables)
    """
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