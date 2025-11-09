from datetime import date, time, timedelta
from typing import List, Dict, Optional, Any, Tuple
from fastapi import APIRouter, HTTPException, Depends, Body
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field, validator
import logging

# Import your SQLAlchemy setup
from database import get_db
import model
from auth_middleware import get_current_user, CurrentUser, require_admin_role

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create FastAPI router
router = APIRouter(prefix="/doctor-schedule", tags=["Doctor Schedule"])


# ---------------- Helper Functions ----------------

def handle_schedule_overlap(db: Session, facility_id: int, doctor_id: int,
                            new_start_date: date, new_end_date: date, weekday: str, window_num: int,
                            exclude_schedule_id: Optional[int] = None) -> None:
    """
    Handle overlapping schedules according to business logic:
    1. Delete existing schedule if start and end dates match exactly
    2. If existing schedule overlaps with incoming dates:
       2.a) Update existing end date to incoming start date - 1 if existing end >= incoming start
       2.b) If existing end > incoming end, duplicate existing record and create schedule with
            start_date = incoming end_date + 1 and end_date = existing end_date
       2.c) Create new schedule records with incoming start and end dates
    """
    query = db.query(model.DoctorSchedule).filter(
        model.DoctorSchedule.facility_id == facility_id,
        model.DoctorSchedule.doctor_id == doctor_id,
        model.DoctorSchedule.week_day == weekday,
        model.DoctorSchedule.window_num == window_num
    )

    # If you later add a surrogate id to DoctorSchedule, this check will work.
    if exclude_schedule_id and hasattr(model.DoctorSchedule, "id"):
        query = query.filter(model.DoctorSchedule.id != exclude_schedule_id)

    existing_schedules = query.all()

    for existing_schedule in existing_schedules:
        existing_start = existing_schedule.start_date
        existing_end = existing_schedule.end_date

        # Check overlap
        if (existing_start <= new_end_date and existing_end >= new_start_date):
            logger.info(f"Found overlapping schedule: {existing_start} to {existing_end} overlaps with {new_start_date} to {new_end_date}")

            # Exact match -> delete
            if existing_start == new_start_date and existing_end == new_end_date:
                logger.info("Deleting existing schedule with exact date match")
                db.delete(existing_schedule)
                continue

            # Update existing end date if it overlaps at the beginning
            if existing_end >= new_start_date and existing_start < new_start_date:
                new_existing_end_date = new_start_date - timedelta(days=1)
                if new_existing_end_date >= existing_start:
                    logger.info(f"Updating existing schedule end date from {existing_end} to {new_existing_end_date}")
                    existing_schedule.end_date = new_existing_end_date
                else:
                    logger.info("Deleting existing schedule as adjustment would make it invalid")
                    db.delete(existing_schedule)
                    continue

            # If existing end > incoming end, create continuation schedule after incoming end
            if existing_end > new_end_date and existing_start < new_end_date:
                continuation_start_date = new_end_date + timedelta(days=1)

                continuation_schedule = model.DoctorSchedule(
                    facility_id=facility_id,
                    doctor_id=doctor_id,
                    start_date=continuation_start_date,
                    end_date=existing_end,
                    week_day=weekday,
                    window_num=window_num,
                    slot_start_time=existing_schedule.slot_start_time,
                    slot_end_time=existing_schedule.slot_end_time,
                    total_slots=existing_schedule.total_slots
                )

                db.add(continuation_schedule)
                logger.info(f"Created continuation schedule from {continuation_start_date} to {existing_end}")

                # Update or delete original depending on coverage
                if existing_start < new_start_date:
                    existing_schedule.end_date = new_start_date - timedelta(days=1)
                    logger.info(f"Updated existing schedule end date to {new_start_date - timedelta(days=1)}")
                else:
                    logger.info("Deleting original schedule as it's completely covered by new schedule")
                    db.delete(existing_schedule)

            # Existing end inside new range but overlapping
            elif existing_end < new_end_date and existing_end >= new_start_date:
                if existing_start < new_start_date:
                    existing_schedule.end_date = new_start_date - timedelta(days=1)
                    logger.info(f"Truncated existing schedule to end on {new_start_date - timedelta(days=1)}")
                else:
                    logger.info("Deleting completely overlapped schedule")
                    db.delete(existing_schedule)

            # Existing completely contained in new schedule
            elif existing_start >= new_start_date and existing_end <= new_end_date:
                logger.info("Deleting schedule completely contained within new schedule")
                db.delete(existing_schedule)


def get_weekday_name(target_date: date) -> str:
    """Get weekday name for a given date"""
    weekday_mapping = {
        0: "Monday", 1: "Tuesday", 2: "Wednesday", 3: "Thursday",
        4: "Friday", 5: "Saturday", 6: "Sunday"
    }
    return weekday_mapping[target_date.weekday()]


def parse_time_string(time_str: str) -> Optional[time]:
    """Parse time strings like '9am', '11am', '2pm', '4pm' or '14:30' to time objects"""
    if not time_str or time_str.strip() == "":
        return None

    time_str = time_str.lower().strip()

    # Handle formats like '9am', '11am', '2pm', '4pm'
    if time_str.endswith('am') or time_str.endswith('pm'):
        is_pm = time_str.endswith('pm')
        time_part = time_str[:-2]

        try:
            hour = int(time_part)
            if is_pm and hour != 12:
                hour += 12
            elif not is_pm and hour == 12:
                hour = 0

            return time(hour=hour, minute=0)
        except ValueError:
            pass

    # Handle HH:MM format
    if ':' in time_str:
        try:
            return time.fromisoformat(time_str)
        except ValueError:
            pass

    raise ValueError(f"Invalid time format: {time_str}")


def time_to_string(time_obj: time) -> str:
    """Convert time object back to string format (like 9am, 2pm)"""
    if not time_obj:
        return ""
    
    hour = time_obj.hour
    minute = time_obj.minute
    
    # If it's exactly on the hour, use am/pm format
    if minute == 0:
        if hour == 0:
            return "12am"
        elif hour < 12:
            return f"{hour}am"
        elif hour == 12:
            return "12pm"
        else:
            return f"{hour - 12}pm"
    else:
        # Use HH:MM format for times with minutes
        return time_obj.strftime("%H:%M")


def split_ranges_around_leave(start_date: date, end_date: date,
                              leave_start: Optional[date], leave_end: Optional[date]) -> List[Tuple[date, date]]:
    """
    Return list of (seg_start, seg_end) date tuples that exclude the leave range.
    If no leave provided or leave doesn't overlap, returns [(start_date, end_date)].
    """
    segments: List[Tuple[date, date]] = []

    # no leave provided -> return original range
    if not leave_start or not leave_end:
        return [(start_date, end_date)]

    # leave completely outside requested range -> return original
    if leave_end < start_date or leave_start > end_date:
        return [(start_date, end_date)]

    # segment before leave
    if leave_start > start_date:
        before_end = leave_start - timedelta(days=1)
        if before_end >= start_date:
            segments.append((start_date, before_end))

    # segment after leave
    if leave_end < end_date:
        after_start = leave_end + timedelta(days=1)
        if after_start <= end_date:
            segments.append((after_start, end_date))

    return segments


def delete_schedules_in_leave_period(db: Session, facility_id: int, doctor_id: int,
                                     leave_start: date, leave_end: date) -> None:
    """
    Delete or adjust all existing schedules that overlap with the leave period.
    This ensures no schedules exist during the leave dates.
    """
    schedules_in_leave = db.query(model.DoctorSchedule).filter(
        model.DoctorSchedule.facility_id == facility_id,
        model.DoctorSchedule.doctor_id == doctor_id,
        model.DoctorSchedule.start_date <= leave_end,
        model.DoctorSchedule.end_date >= leave_start
    ).all()
    
    for existing_schedule in schedules_in_leave:
        existing_start = existing_schedule.start_date
        existing_end = existing_schedule.end_date
        
        # Case 1: Schedule completely within leave period - delete it
        if (existing_start >= leave_start and existing_end <= leave_end):
            logger.info(f"Deleting schedule completely within leave: {existing_start} to {existing_end}")
            db.delete(existing_schedule)
        
        # Case 2: Schedule starts before leave, ends during/after leave
        elif (existing_start < leave_start and existing_end >= leave_start):
            new_end = leave_start - timedelta(days=1)
            if new_end >= existing_start:
                logger.info(f"Truncating schedule end date to {new_end} (before leave)")
                existing_schedule.end_date = new_end
            else:
                logger.info(f"Deleting schedule that would become invalid after truncation")
                db.delete(existing_schedule)
        
        # Case 3: Schedule starts during leave, ends after leave
        elif (existing_start <= leave_end and existing_end > leave_end):
            new_start = leave_end + timedelta(days=1)
            if new_start <= existing_end:
                logger.info(f"Moving schedule start date to {new_start} (after leave)")
                existing_schedule.start_date = new_start
            else:
                logger.info(f"Deleting schedule that would become invalid after adjustment")
                db.delete(existing_schedule)
        
        # Case 4: Leave period is in the middle of the schedule
        elif (existing_start < leave_start and existing_end > leave_end):
            logger.info(f"Splitting schedule around leave period")
            
            # Keep the first part (before leave)
            existing_schedule.end_date = leave_start - timedelta(days=1)
            
            # Create second part (after leave)
            continuation_schedule = model.DoctorSchedule(
                facility_id=existing_schedule.facility_id,
                doctor_id=existing_schedule.doctor_id,
                start_date=leave_end + timedelta(days=1),
                end_date=existing_end,
                week_day=existing_schedule.week_day,
                window_num=existing_schedule.window_num,
                slot_start_time=existing_schedule.slot_start_time,
                slot_end_time=existing_schedule.slot_end_time,
                total_slots=existing_schedule.total_slots
            )
            db.add(continuation_schedule)


# ---------------- Pydantic Models ----------------

class SlotWeek(BaseModel):
    startTime: str = ""
    endTime: str = ""
    totalSlots: str = ""


class WeekDaySlot(BaseModel):
    weekDay: str = Field(..., pattern="^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)$")
    slotWeeks: List[SlotWeek] = Field(default_factory=lambda: [SlotWeek(), SlotWeek(), SlotWeek()])


def get_default_weekdays_list() -> List[WeekDaySlot]:
    """Generate default weekdays list with all 7 days and empty slots"""
    weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    return [
        WeekDaySlot(weekDay=day, slotWeeks=[SlotWeek(), SlotWeek(), SlotWeek()])
        for day in weekdays
    ]


class ScheduleCreate(BaseModel):
    # Changed from Optional to required fields
    startDate: date = Field(..., description="Start date for the schedule")
    endDate: date = Field(..., description="End date for the schedule") 
    facility_id: int = Field(..., gt=0, description="Facility ID")
    doctor_id: int = Field(..., gt=0, description="Doctor ID")
    # Leave dates remain optional
    leaveStartDate: Optional[date] = Field(None, description="Leave start date (optional)")
    leaveEndDate: Optional[date] = Field(None, description="Leave end date (optional)")
    weekDaysList: List[WeekDaySlot] = Field(default_factory=get_default_weekdays_list)

    @validator('leaveStartDate', pre=True)
    def validate_leave_start_date(cls, v):
        if v == "" or v is None:
            return None
        return v

    @validator('leaveEndDate', pre=True)
    def validate_leave_end_date(cls, v):
        if v == "" or v is None:
            return None
        return v

    @validator('endDate')
    def validate_date_range(cls, v, values):
        if 'startDate' in values and values['startDate'] and v and v < values['startDate']:
            raise ValueError('endDate must be greater than or equal to startDate')
        return v

    @validator('leaveEndDate')
    def validate_leave_date_range(cls, v, values):
        if 'leaveStartDate' in values and values['leaveStartDate'] and v and v < values['leaveStartDate']:
            raise ValueError('leaveEndDate must be greater than or equal to leaveStartDate')
        return v

    class Config:
        schema_extra = {
            "example": {
                "startDate": "2025-09-01",
                "endDate": "2025-12-31", 
                "facility_id": 1,
                "doctor_id": 1,
                "leaveStartDate": "0000-00-00",
                "leaveEndDate": "0000-00-00",
                "weekDaysList": [
                    {
                        "weekDay": "Monday",
                        "slotWeeks": [
                            {"startTime": "", "endTime": "", "totalSlots": ""},
                            {"startTime": "", "endTime": "", "totalSlots": ""},
                            {"startTime": "", "endTime": "", "totalSlots": ""}
                        ]
                    },
                    {
                        "weekDay": "Tuesday",
                        "slotWeeks": [
                            {"startTime": "", "endTime": "", "totalSlots": ""},
                            {"startTime": "", "endTime": "", "totalSlots": ""},
                            {"startTime": "", "endTime": "", "totalSlots": ""}
                        ]
                    },
                    {
                        "weekDay": "Wednesday",
                        "slotWeeks": [
                            {"startTime": "", "endTime": "", "totalSlots": ""},
                            {"startTime": "", "endTime": "", "totalSlots": ""},
                            {"startTime": "", "endTime": "", "totalSlots": ""}
                        ]
                    },
                    {
                        "weekDay": "Thursday",
                        "slotWeeks": [
                            {"startTime": "", "endTime": "", "totalSlots": ""},
                            {"startTime": "", "endTime": "", "totalSlots": ""},
                            {"startTime": "", "endTime": "", "totalSlots": ""}
                        ]
                    },
                    {
                        "weekDay": "Friday",
                        "slotWeeks": [
                            {"startTime": "9am", "endTime": "11am", "totalSlots": ""},
                            {"startTime": "2pm", "endTime": "4pm", "totalSlots": ""},
                            {"startTime": "", "endTime": "", "totalSlots": ""}
                        ]
                    },
                    {
                        "weekDay": "Saturday",
                        "slotWeeks": [
                            {"startTime": "", "endTime": "", "totalSlots": ""},
                            {"startTime": "", "endTime": "", "totalSlots": ""},
                            {"startTime": "", "endTime": "", "totalSlots": ""}
                        ]
                    },
                    {
                        "weekDay": "Sunday",
                        "slotWeeks": [
                            {"startTime": "", "endTime": "", "totalSlots": ""},
                            {"startTime": "", "endTime": "", "totalSlots": ""},
                            {"startTime": "", "endTime": "", "totalSlots": ""}
                        ]
                    }
                ]
            }
        }


class ScheduleResponse(BaseModel):
    facility_id: int
    doctor_id: int
    start_date: date
    end_date: date
    weekday: str
    window_num: int
    slot_start_time: str
    slot_end_time: str

    class Config:
        from_attributes = True


class AvailabilityResponse(BaseModel):
    facility_id: int
    doctor_id: int
    start_date: date
    end_date: date
    availability_details: List[Dict]


# ---------------- explicit example for the route ----------------
example_payload = ScheduleCreate.Config.schema_extra["example"]


# ---------------- CRUD API Endpoints ----------------

@router.post("/", response_model=Dict)
async def create_schedule(
    schedule: ScheduleCreate = Body(
        ..., 
        openapi_examples={
            "template": {
                "summary": "Schedule Template",
                "description": "Template with all fields shown",
                "value": {
                    "startDate": "2025-09-01",
                    "endDate": "2025-12-31",
                    "facility_id": 1,
                    "doctor_id": 1,
                    "leaveStartDate": "0000-00-00",
                    "leaveEndDate": "0000-00-00",
                    "weekDaysList": [
                        {
                            "weekDay": "Monday",
                            "slotWeeks": [
                                {"startTime": "", "endTime": "", "totalSlots": ""},
                                {"startTime": "", "endTime": "", "totalSlots": ""},
                                {"startTime": "", "endTime": "", "totalSlots": ""}
                            ]
                        },
                        {
                            "weekDay": "Tuesday",
                            "slotWeeks": [
                                {"startTime": "", "endTime": "", "totalSlots": ""},
                                {"startTime": "", "endTime": "", "totalSlots": ""},
                                {"startTime": "", "endTime": "", "totalSlots": ""}
                            ]
                        },
                        {
                            "weekDay": "Wednesday",
                            "slotWeeks": [
                                {"startTime": "", "endTime": "", "totalSlots": ""},
                                {"startTime": "", "endTime": "", "totalSlots": ""},
                                {"startTime": "", "endTime": "", "totalSlots": ""}
                            ]
                        },
                        {
                            "weekDay": "Thursday",
                            "slotWeeks": [
                                {"startTime": "", "endTime": "", "totalSlots": ""},
                                {"startTime": "", "endTime": "", "totalSlots": ""},
                                {"startTime": "", "endTime": "", "totalSlots": ""}
                            ]
                        },
                        {
                            "weekDay": "Friday",
                            "slotWeeks": [
                                {"startTime": "", "endTime": "", "totalSlots": ""},
                                {"startTime": "", "endTime": "", "totalSlots": ""},
                                {"startTime": "", "endTime": "", "totalSlots": ""}
                            ]
                        },
                        {
                            "weekDay": "Saturday",
                            "slotWeeks": [
                                {"startTime": "", "endTime": "", "totalSlots": ""},
                                {"startTime": "", "endTime": "", "totalSlots": ""},
                                {"startTime": "", "endTime": "", "totalSlots": ""}
                            ]
                        },
                        {
                            "weekDay": "Sunday",
                            "slotWeeks": [
                                {"startTime": "", "endTime": "", "totalSlots": ""},
                                {"startTime": "", "endTime": "", "totalSlots": ""},
                                {"startTime": "", "endTime": "", "totalSlots": ""}
                            ]
                        }
                    ]
                }
            }
        }
    ), 
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create new schedules with overlap handling and honor leave ranges."""
    try:
        # Delete or adjust all existing schedules that fall within the leave period
        if schedule.leaveStartDate and schedule.leaveEndDate:
            delete_schedules_in_leave_period(
                db,
                schedule.facility_id,
                schedule.doctor_id,
                schedule.leaveStartDate,
                schedule.leaveEndDate
            )
            db.flush()
        
        created_schedules: List[Dict[str, Any]] = []

        # Process each weekday
        for weekday_data in schedule.weekDaysList:
            weekday = weekday_data.weekDay

            # Process each slot for this weekday (up to 3 windows)
            for window_num, slot in enumerate(weekday_data.slotWeeks, 1):
                # Skip empty slots (both start and end required)
                if not slot.startTime or not slot.endTime:
                    continue
                if not slot.startTime.strip() or not slot.endTime.strip():
                    continue

                try:
                    start_time_obj = parse_time_string(slot.startTime)
                    end_time_obj = parse_time_string(slot.endTime)

                    if not start_time_obj or not end_time_obj:
                        continue

                    # Validate time range
                    if start_time_obj >= end_time_obj:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Start time must be less than end time for {weekday} window {window_num}"
                        )

                    # Split the overall date range around leave (if any)
                    segments = split_ranges_around_leave(
                        schedule.startDate,
                        schedule.endDate,
                        schedule.leaveStartDate,
                        schedule.leaveEndDate
                    )

                    # For each valid segment (before/after leave), create schedules
                    for seg_start, seg_end in segments:
                        # call overlap handling which may update/delete existing rows
                        handle_schedule_overlap(
                            db,
                            schedule.facility_id,
                            schedule.doctor_id,
                            seg_start,
                            seg_end,
                            weekday,
                            window_num
                        )

                        # Parse totalSlots - convert empty string or None to None, otherwise keep as string
                        total_slots = slot.totalSlots if slot.totalSlots and slot.totalSlots.strip() else None

                        # create new schedule for this segment
                        new_schedule = model.DoctorSchedule(
                            facility_id=schedule.facility_id,
                            doctor_id=schedule.doctor_id,
                            start_date=seg_start,
                            end_date=seg_end,
                            week_day=weekday,
                            window_num=window_num,
                            slot_start_time=start_time_obj,
                            slot_end_time=end_time_obj,
                            total_slots=total_slots
                        )

                        db.add(new_schedule)
                        created_schedules.append({
                            'weekday': weekday,
                            'window': window_num,
                            'start_time': slot.startTime,
                            'end_time': slot.endTime,
                            'segment_start_date': str(seg_start),
                            'segment_end_date': str(seg_end),
                            'totalSlots': slot.totalSlots
                        })

                except ValueError as e:
                    logger.warning(f"Skipping invalid time for {weekday} window {window_num}: {str(e)}")
                    continue

        if not created_schedules:
            raise HTTPException(status_code=400, detail="No valid schedules found to create")

        db.commit()

        logger.info(f"Created {len(created_schedules)} schedules for doctor {schedule.doctor_id}")
        
        # Convert the original payload to dict format for response
        original_payload = {
            "startDate": str(schedule.startDate),
            "endDate": str(schedule.endDate),
            "facility_id": schedule.facility_id,
            "doctor_id": schedule.doctor_id,
            "leaveStartDate": str(schedule.leaveStartDate) if schedule.leaveStartDate else "",
            "leaveEndDate": str(schedule.leaveEndDate) if schedule.leaveEndDate else "",
            "weekDaysList": [
                {
                    "weekDay": weekday_data.weekDay,
                    "slotWeeks": [
                        {
                            "startTime": slot.startTime,
                            "endTime": slot.endTime,
                            "totalSlots": slot.totalSlots
                        }
                        for slot in weekday_data.slotWeeks
                    ]
                }
                for weekday_data in schedule.weekDaysList
            ]
        }
        
        return {
            "success": True,
            "message": f"Successfully created {len(created_schedules)} schedules",
            "payload": original_payload,
            "created_schedules": created_schedules
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating schedule: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error creating schedule: {str(e)}")
@router.get("/{facility_id}/{doctor_id}", response_model=Dict)
async def get_schedules(
    facility_id: int, 
    doctor_id: int, 
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get schedules for a doctor in a facility in the same payload format as create"""
    try:
        schedules = db.query(model.DoctorSchedule).filter(
            model.DoctorSchedule.facility_id == facility_id,
            model.DoctorSchedule.doctor_id == doctor_id
        ).order_by(
            model.DoctorSchedule.start_date,
            model.DoctorSchedule.week_day,
            model.DoctorSchedule.window_num,
            model.DoctorSchedule.slot_start_time
        ).all()

        if not schedules:
            raise HTTPException(status_code=404, detail="No schedules found")

        # Find the overall date range
        overall_start = min(s.start_date for s in schedules)
        overall_end = max(s.end_date for s in schedules)

        # Detect leave period by finding gaps in date ranges
        leave_start_date = ""
        leave_end_date = ""
        
        # Get all unique date ranges, sorted
        date_ranges = sorted(set((s.start_date, s.end_date) for s in schedules))
        
        # Check for gaps between consecutive date ranges
        for i in range(len(date_ranges) - 1):
            current_end = date_ranges[i][1]
            next_start = date_ranges[i + 1][0]
            
            # If there's a gap of more than 1 day, it's likely a leave period
            if (next_start - current_end).days > 1:
                leave_start_date = str(current_end + timedelta(days=1))
                leave_end_date = str(next_start - timedelta(days=1))
                break  # Assuming only one leave period

        # Initialize weekdays structure
        weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        weekdays_list = []
        
        for weekday in weekdays:
            # Get all schedules for this weekday
            weekday_schedules = [s for s in schedules if s.week_day == weekday]
            
            if weekday_schedules:
                # Group schedules by window_num for this weekday
                # Use a dictionary to collect unique window entries
                window_dict = {}
                
                for schedule in weekday_schedules:
                    window_num = schedule.window_num
                    
                    # Only add if this window hasn't been added yet
                    # (multiple date ranges might exist for same window/weekday combo)
                    if window_num not in window_dict:
                        window_dict[window_num] = {
                            "startTime": time_to_string(schedule.slot_start_time),
                            "endTime": time_to_string(schedule.slot_end_time),
                            "totalSlots": schedule.total_slots if schedule.total_slots is not None else ""
                        }
                
                # Convert to list and ensure we have exactly 3 slots
                slot_weeks = []
                for window_num in range(1, 4):  # Windows 1, 2, 3
                    if window_num in window_dict:
                        slot_weeks.append(window_dict[window_num])
                    else:
                        # Add empty slot if window doesn't exist
                        slot_weeks.append({
                            "startTime": "",
                            "endTime": "",
                            "totalSlots": ""
                        })
                
                weekdays_list.append({
                    "weekDay": weekday,
                    "slotWeeks": slot_weeks
                })

        # Build the payload in the same format as create_schedule
        payload = {
            "startDate": str(overall_start),
            "endDate": str(overall_end),
            "facility_id": facility_id,
            "doctor_id": doctor_id,
            "leaveStartDate": leave_start_date if leave_start_date else "0000-00-00",
            "leaveEndDate": leave_end_date if leave_end_date else "0000-00-00",
            "weekDaysList": weekdays_list
        }

        return payload

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting schedules: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error getting schedules: {str(e)}")

@router.delete("/{facility_id}/{doctor_id}/{start_date}/{end_date}/{window_num}", response_model=Dict)
async def delete_schedule(
    facility_id: int, 
    doctor_id: int, 
    start_date: date, 
    end_date: date, 
    window_num: int, 
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a schedule"""
    try:
        if end_date < start_date:
            raise HTTPException(status_code=400, detail="end_date must be greater than or equal to start_date")

        existing_schedule = db.query(model.DoctorSchedule).filter(
            model.DoctorSchedule.facility_id == facility_id,
            model.DoctorSchedule.doctor_id == doctor_id,
            model.DoctorSchedule.start_date == start_date,
            model.DoctorSchedule.end_date == end_date,
            model.DoctorSchedule.window_num == window_num
        ).first()

        if not existing_schedule:
            raise HTTPException(status_code=404, detail="Schedule not found")

        db.delete(existing_schedule)
        db.commit()

        return {"success": True, "message": "Schedule deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting schedule: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error deleting schedule: {str(e)}")


@router.get("/availability/{facility_id}/{doctor_id}/{start_date}/{end_date}", response_model=AvailabilityResponse)
async def check_doctor_availability(
    facility_id: int, 
    doctor_id: int, 
    start_date: date, 
    end_date: date, 
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Check doctor availability between start_date and end_date"""
    try:
        if end_date < start_date:
            raise HTTPException(status_code=400, detail="end_date must be greater than or equal to start_date")

        # Find all schedules that overlap with the requested date range
        schedules = db.query(model.DoctorSchedule).filter(
            model.DoctorSchedule.facility_id == facility_id,
            model.DoctorSchedule.doctor_id == doctor_id,
            model.DoctorSchedule.end_date >= start_date,
            model.DoctorSchedule.start_date <= end_date
        ).order_by(
            model.DoctorSchedule.start_date,
            model.DoctorSchedule.week_day,
            model.DoctorSchedule.slot_start_time
        ).all()

        availability_details = []

        # Create a list of available dates within the range
        current_date = start_date
        while current_date <= end_date:
            weekday = get_weekday_name(current_date)

            # Check if doctor has schedule for this weekday and date
            matching_schedules = [
                s for s in schedules
                if (s.week_day == weekday and
                    s.start_date <= current_date and
                    s.end_date >= current_date)
            ]

            date_availability = {
                "date": str(current_date),
                "weekday": weekday,
                "is_available": len(matching_schedules) > 0,
                "schedules": []
            }

            for schedule_obj in matching_schedules:
                date_availability["schedules"].append({
                    "window_num": schedule_obj.window_num,
                    "slot_start_time": str(schedule_obj.slot_start_time),
                    "slot_end_time": str(schedule_obj.slot_end_time),
                    "schedule_start_date": str(schedule_obj.start_date),
                    "schedule_end_date": str(schedule_obj.end_date)
                })

            availability_details.append(date_availability)
            current_date += timedelta(days=1)

        return AvailabilityResponse(
            facility_id=facility_id,
            doctor_id=doctor_id,
            start_date=start_date,
            end_date=end_date,
            availability_details=availability_details
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error checking doctor availability: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error checking doctor availability: {str(e)}")