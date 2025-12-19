from datetime import date, time, timedelta
from typing import List, Dict, Optional, Any, Tuple
from fastapi import APIRouter, HTTPException, Depends, Body
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field, validator
import logging
from collections import defaultdict

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

def get_existing_leave_periods(db: Session, facility_id: int, doctor_id: int) -> List[Tuple[date, date]]:
    """
    Get all existing leave periods from schedules with availability_flag = 'L'.
    Returns list of (leave_start, leave_end) tuples.
    Filters for empty week_day to get only the single leave record (not duplicates).
    """
    leave_schedules = db.query(model.DoctorSchedule).filter(
        model.DoctorSchedule.facility_id == facility_id,
        model.DoctorSchedule.doctor_id == doctor_id,
        model.DoctorSchedule.availability_flag == 'L',
        model.DoctorSchedule.week_day == ""
    ).order_by(model.DoctorSchedule.start_date).all()
    
    return [(schedule.start_date, schedule.end_date) for schedule in leave_schedules]


def sync_leave_periods_to_db(db: Session, facility_id: int, doctor_id: int, 
                              leave_periods: List[Tuple[date, date]]) -> None:
    """
    Sync leave periods to the doctor_schedule table with availability_flag = 'L'.
    Removes all existing leave records and adds new ones.
    Uses empty string for week_day since it's NOT NULL in the schema.
    """
    db.query(model.DoctorSchedule).filter(
        model.DoctorSchedule.facility_id == facility_id,
        model.DoctorSchedule.doctor_id == doctor_id,
        model.DoctorSchedule.availability_flag == 'L'
    ).delete(synchronize_session=False)
    
    for leave_start, leave_end in leave_periods:
        new_leave = model.DoctorSchedule(
            facility_id=facility_id,
            doctor_id=doctor_id,
            start_date=leave_start,
            end_date=leave_end,
            week_day="",
            window_num=0,
            slot_start_time=time(0, 0),
            slot_end_time=time(0, 0),
            total_slots=None,
            slot_duration_minutes=0,
            availability_flag='L'
        )
        db.add(new_leave)
    
    logger.info(f"Synced {len(leave_periods)} leave periods to database for doctor {doctor_id}")


def restore_schedules_for_dates(db: Session, facility_id: int, doctor_id: int, 
                                restore_start: date, restore_end: date) -> None:
    """
    Restore schedules for dates that are no longer on leave.
    This extends existing schedules or creates new ones to fill the gap.
    """
    logger.info(f"Restoring schedules from {restore_start} to {restore_end}")
    
    all_schedules = db.query(model.DoctorSchedule).filter(
        model.DoctorSchedule.facility_id == facility_id,
        model.DoctorSchedule.doctor_id == doctor_id,
        model.DoctorSchedule.availability_flag == 'A'
    ).order_by(
        model.DoctorSchedule.week_day,
        model.DoctorSchedule.window_num,
        model.DoctorSchedule.start_date
    ).all()
    
    if not all_schedules:
        logger.warning("No existing schedules found to restore from")
        return
    
    schedule_patterns = defaultdict(list)
    for schedule in all_schedules:
        key = (schedule.week_day, schedule.window_num)
        schedule_patterns[key].append(schedule)
    
    for (weekday, window_num), schedules in schedule_patterns.items():
        schedules = sorted(schedules, key=lambda s: s.start_date)
        
        before_schedule = None
        after_schedule = None
        overlapping_schedules = []
        
        for schedule in schedules:
            # Check if schedule overlaps with restoration period
            if schedule.start_date <= restore_end and schedule.end_date >= restore_start:
                overlapping_schedules.append(schedule)
            elif schedule.end_date < restore_start:
                if before_schedule is None or schedule.end_date > before_schedule.end_date:
                    before_schedule = schedule
            elif schedule.start_date > restore_end:
                if after_schedule is None or schedule.start_date < after_schedule.start_date:
                    after_schedule = schedule
        
        # If there are already schedules in the restoration period, skip
        if overlapping_schedules:
            logger.info(f"Schedules already exist in restoration period for {weekday} window {window_num}")
            continue
        
        template = before_schedule or after_schedule
        
        if not template:
            logger.warning(f"No template found for {weekday} window {window_num}")
            continue
        
        can_merge_before = (before_schedule and 
                           before_schedule.end_date + timedelta(days=1) == restore_start and
                           before_schedule.slot_start_time == template.slot_start_time and
                           before_schedule.slot_end_time == template.slot_end_time and
                           before_schedule.slot_duration_minutes == template.slot_duration_minutes)
        
        can_merge_after = (after_schedule and 
                          after_schedule.start_date - timedelta(days=1) == restore_end and
                          after_schedule.slot_start_time == template.slot_start_time and
                          after_schedule.slot_end_time == template.slot_end_time and
                          after_schedule.slot_duration_minutes == template.slot_duration_minutes)
        
        if can_merge_before and can_merge_after:
            logger.info(f"Merging three segments for {weekday} window {window_num}")
            before_schedule.end_date = after_schedule.end_date
            db.delete(after_schedule)
        elif can_merge_before:
            logger.info(f"Extending before_schedule for {weekday} window {window_num} to {restore_end}")
            before_schedule.end_date = restore_end
        elif can_merge_after:
            logger.info(f"Extending after_schedule for {weekday} window {window_num} from {restore_start}")
            after_schedule.start_date = restore_start
        else:
            logger.info(f"Creating new schedule for {weekday} window {window_num} from {restore_start} to {restore_end}")
            new_schedule = model.DoctorSchedule(
                facility_id=facility_id,
                doctor_id=doctor_id,
                start_date=restore_start,
                end_date=restore_end,
                week_day=weekday,
                window_num=window_num,
                slot_start_time=template.slot_start_time,
                slot_end_time=template.slot_end_time,
                total_slots=template.total_slots,
                slot_duration_minutes=template.slot_duration_minutes,
                availability_flag='A'
            )
            db.add(new_schedule)


def handle_schedule_overlap(db: Session, facility_id: int, doctor_id: int,
                            new_start_date: date, new_end_date: date, weekday: str, window_num: int,
                            exclude_schedule_id: Optional[int] = None) -> None:
    """
    Handle overlapping schedules according to business logic.
    FIXED: Improved overlap detection and handling logic.
    """
    query = db.query(model.DoctorSchedule).filter(
        model.DoctorSchedule.facility_id == facility_id,
        model.DoctorSchedule.doctor_id == doctor_id,
        model.DoctorSchedule.week_day == weekday,
        model.DoctorSchedule.window_num == window_num,
        model.DoctorSchedule.availability_flag == 'A'
    )

    existing_schedules = query.all()

    for existing_schedule in existing_schedules:
        existing_start = existing_schedule.start_date
        existing_end = existing_schedule.end_date

        # Check if there's any overlap
        has_overlap = not (new_end_date < existing_start or new_start_date > existing_end)
        
        if not has_overlap:
            continue
            
        logger.info(f"Found overlapping schedule: {existing_start} to {existing_end} overlaps with {new_start_date} to {new_end_date}")

        # Case 1: Exact match -> delete
        if existing_start == new_start_date and existing_end == new_end_date:
            logger.info("Deleting existing schedule with exact date match")
            db.delete(existing_schedule)
            continue

        # Case 2: New schedule completely contains existing schedule
        if new_start_date <= existing_start and new_end_date >= existing_end:
            logger.info("Deleting existing schedule completely contained within new schedule")
            db.delete(existing_schedule)
            continue

        # Case 3: Existing schedule completely contains new schedule (split into two)
        if existing_start < new_start_date and existing_end > new_end_date:
            logger.info(f"Splitting existing schedule around new schedule")
            
            # Keep first part (before new schedule)
            existing_schedule.end_date = new_start_date - timedelta(days=1)
            
            # Create second part (after new schedule)
            continuation_schedule = model.DoctorSchedule(
                facility_id=facility_id,
                doctor_id=doctor_id,
                start_date=new_end_date + timedelta(days=1),
                end_date=existing_end,
                week_day=weekday,
                window_num=window_num,
                slot_start_time=existing_schedule.slot_start_time,
                slot_end_time=existing_schedule.slot_end_time,
                total_slots=existing_schedule.total_slots,
                slot_duration_minutes=existing_schedule.slot_duration_minutes,
                availability_flag='A'
            )
            db.add(continuation_schedule)
            logger.info(f"Created continuation schedule from {new_end_date + timedelta(days=1)} to {existing_end}")
            continue

        # Case 4: New schedule overlaps beginning of existing schedule
        if new_start_date <= existing_start and new_end_date < existing_end and new_end_date >= existing_start:
            logger.info(f"New schedule overlaps beginning, moving existing start to {new_end_date + timedelta(days=1)}")
            existing_schedule.start_date = new_end_date + timedelta(days=1)
            continue

        # Case 5: New schedule overlaps end of existing schedule
        if new_start_date > existing_start and new_start_date <= existing_end and new_end_date >= existing_end:
            logger.info(f"New schedule overlaps end, moving existing end to {new_start_date - timedelta(days=1)}")
            existing_schedule.end_date = new_start_date - timedelta(days=1)
            continue


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
        return time_obj.strftime("%H:%M")


def split_ranges_around_leaves(start_date: date, end_date: date,
                               leave_periods: List[Tuple[date, date]]) -> List[Tuple[date, date]]:
    """
    Return list of (seg_start, seg_end) date tuples that exclude all leave ranges.
    FIXED: Improved logic to handle all edge cases properly.
    """
    if not leave_periods:
        return [(start_date, end_date)]
    
    # Filter and sort leave periods that actually overlap with the date range
    relevant_leaves = []
    for leave_start, leave_end in leave_periods:
        # Only include leaves that overlap with our date range
        if not (leave_end < start_date or leave_start > end_date):
            # Clip leave period to our date range
            clipped_start = max(leave_start, start_date)
            clipped_end = min(leave_end, end_date)
            relevant_leaves.append((clipped_start, clipped_end))
    
    if not relevant_leaves:
        return [(start_date, end_date)]
    
    # Sort by start date
    relevant_leaves.sort(key=lambda x: x[0])
    
    # Merge overlapping leave periods
    merged_leaves = [relevant_leaves[0]]
    for leave_start, leave_end in relevant_leaves[1:]:
        last_start, last_end = merged_leaves[-1]
        
        # If current leave overlaps or is adjacent to last leave, merge them
        if leave_start <= last_end + timedelta(days=1):
            merged_leaves[-1] = (last_start, max(last_end, leave_end))
        else:
            merged_leaves.append((leave_start, leave_end))
    
    # Build segments between leaves
    segments = []
    current_start = start_date
    
    for leave_start, leave_end in merged_leaves:
        # Add segment before this leave
        if current_start < leave_start:
            segments.append((current_start, leave_start - timedelta(days=1)))
        
        # Move past this leave
        current_start = leave_end + timedelta(days=1)
    
    # Add final segment after all leaves
    if current_start <= end_date:
        segments.append((current_start, end_date))
    
    return segments


def delete_schedules_in_leave_periods(db: Session, facility_id: int, doctor_id: int,
                                      leave_periods: List[Tuple[date, date]]) -> None:
    """
    Delete or adjust all existing available schedules that overlap with any leave period.
    FIXED: Improved handling of all overlap cases.
    """
    for leave_start, leave_end in leave_periods:
        logger.info(f"Processing leave period: {leave_start} to {leave_end}")
        
        schedules_in_leave = db.query(model.DoctorSchedule).filter(
            model.DoctorSchedule.facility_id == facility_id,
            model.DoctorSchedule.doctor_id == doctor_id,
            model.DoctorSchedule.availability_flag == 'A',
            model.DoctorSchedule.start_date <= leave_end,
            model.DoctorSchedule.end_date >= leave_start
        ).all()
        
        for existing_schedule in schedules_in_leave:
            existing_start = existing_schedule.start_date
            existing_end = existing_schedule.end_date
            
            # Case 1: Schedule completely within leave period - delete it
            if existing_start >= leave_start and existing_end <= leave_end:
                logger.info(f"Deleting schedule completely within leave: {existing_start} to {existing_end}")
                db.delete(existing_schedule)
            
            # Case 2: Leave period completely within schedule - split schedule
            elif existing_start < leave_start and existing_end > leave_end:
                logger.info(f"Splitting schedule around leave period: {existing_start} to {existing_end}, leave {leave_start} to {leave_end}")
                
                existing_schedule.end_date = leave_start - timedelta(days=1)
                
                continuation_schedule = model.DoctorSchedule(
                    facility_id=existing_schedule.facility_id,
                    doctor_id=existing_schedule.doctor_id,
                    start_date=leave_end + timedelta(days=1),
                    end_date=existing_end,
                    week_day=existing_schedule.week_day,
                    window_num=existing_schedule.window_num,
                    slot_start_time=existing_schedule.slot_start_time,
                    slot_end_time=existing_schedule.slot_end_time,
                    total_slots=existing_schedule.total_slots,
                    slot_duration_minutes=existing_schedule.slot_duration_minutes,
                    availability_flag='A'
                )
                db.add(continuation_schedule)
                logger.info(f"Created continuation from {leave_end + timedelta(days=1)} to {existing_end}")
            
            # Case 3: Leave overlaps end of schedule
            elif existing_start < leave_start and existing_end >= leave_start and existing_end <= leave_end:
                new_end = leave_start - timedelta(days=1)
                if new_end >= existing_start:
                    logger.info(f"Truncating schedule end date to {new_end} (before leave)")
                    existing_schedule.end_date = new_end
                else:
                    logger.info(f"Deleting schedule that would become invalid after truncation")
                    db.delete(existing_schedule)
            
            # Case 4: Leave overlaps beginning of schedule
            elif existing_start >= leave_start and existing_start <= leave_end and existing_end > leave_end:
                new_start = leave_end + timedelta(days=1)
                if new_start <= existing_end:
                    logger.info(f"Moving schedule start date to {new_start} (after leave)")
                    existing_schedule.start_date = new_start
                else:
                    logger.info(f"Deleting schedule that would become invalid after adjustment")
                    db.delete(existing_schedule)


def merge_adjacent_schedules(db: Session, facility_id: int, doctor_id: int) -> None:
    """
    Merge schedules that are adjacent (end_date + 1 = next start_date) 
    and have the same weekday, window, and time settings.
    """
    all_schedules = db.query(model.DoctorSchedule).filter(
        model.DoctorSchedule.facility_id == facility_id,
        model.DoctorSchedule.doctor_id == doctor_id,
        model.DoctorSchedule.availability_flag == 'A'
    ).order_by(
        model.DoctorSchedule.week_day,
        model.DoctorSchedule.window_num,
        model.DoctorSchedule.slot_start_time,
        model.DoctorSchedule.start_date
    ).all()
    
    groups = defaultdict(list)
    
    for schedule in all_schedules:
        key = (
            schedule.week_day,
            schedule.window_num,
            schedule.slot_start_time,
            schedule.slot_end_time,
            schedule.slot_duration_minutes,
            schedule.total_slots
        )
        groups[key].append(schedule)
    
    for key, schedules in groups.items():
        if len(schedules) <= 1:
            continue
        
        schedules = sorted(schedules, key=lambda s: s.start_date)
        
        i = 0
        while i < len(schedules) - 1:
            current = schedules[i]
            next_schedule = schedules[i + 1]
            
            if current.end_date + timedelta(days=1) == next_schedule.start_date:
                logger.info(f"Merging schedules: {current.start_date} to {current.end_date} "
                          f"with {next_schedule.start_date} to {next_schedule.end_date}")
                
                current.end_date = next_schedule.end_date
                db.delete(next_schedule)
                schedules.pop(i + 1)
            else:
                i += 1


# ---------------- Pydantic Models ----------------

class SlotWeek(BaseModel):
    startTime: str = ""
    endTime: str = ""
    totalSlots: str = ""
    slotDurationMinutes: int = 15


class WeekDaySlot(BaseModel):
    weekDay: str = Field(..., pattern="^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)$")
    slotWeeks: List[SlotWeek] = Field(default_factory=lambda: [SlotWeek(), SlotWeek(), SlotWeek()])


class LeavePeriod(BaseModel):
    """Model for a single leave period"""
    leaveStartDate: date = Field(..., description="Leave start date")
    leaveEndDate: date = Field(..., description="Leave end date")
    
    @validator('leaveStartDate', 'leaveEndDate', pre=True)
    def empty_string_to_none(cls, v):
        """Convert empty strings to None, which will be rejected by date field"""
        if v == "" or v is None:
            raise ValueError('Leave date cannot be empty')
        return v
    
    @validator('leaveEndDate')
    def validate_leave_dates(cls, v, values):
        if 'leaveStartDate' in values and v < values['leaveStartDate']:
            raise ValueError('leaveEndDate must be greater than or equal to leaveStartDate')
        return v


def get_default_weekdays_list() -> List[WeekDaySlot]:
    """Generate default weekdays list with all 7 days and empty slots"""
    weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    return [
        WeekDaySlot(weekDay=day, slotWeeks=[SlotWeek(), SlotWeek(), SlotWeek()])
        for day in weekdays
    ]


class ScheduleCreate(BaseModel):
    startDate: date = Field(..., description="Start date for the schedule")
    endDate: date = Field(..., description="End date for the schedule") 
    facility_id: int = Field(..., gt=0, description="Facility ID")
    doctor_id: int = Field(..., gt=0, description="Doctor ID")
    leavePeriods: Optional[List[LeavePeriod]] = Field(None, description="List of leave periods (None = preserve existing, [] = remove all, [...] = set new)")
    weekDaysList: List[WeekDaySlot] = Field(default_factory=get_default_weekdays_list)

    @validator('endDate')
    def validate_date_range(cls, v, values):
        if 'startDate' in values and values['startDate'] and v and v < values['startDate']:
            raise ValueError('endDate must be greater than or equal to startDate')
        return v
    
    @validator('leavePeriods', pre=True)
    def filter_empty_leaves(cls, v):
        """Filter out leave periods with empty strings"""
        if v is None:
            return None
        
        if not v:
            return []
        
        filtered = []
        for leave in v:
            if isinstance(leave, dict):
                start = leave.get('leaveStartDate', '')
                end = leave.get('leaveEndDate', '')
                if start == '' and end == '':
                    continue
            filtered.append(leave)
        
        return filtered
    
    @validator('leavePeriods')
    def validate_no_overlapping_leaves(cls, v):
        """Ensure leave periods don't overlap with each other"""
        if v is None:
            return v
        
        if len(v) <= 1:
            return v
        
        sorted_leaves = sorted(v, key=lambda x: x.leaveStartDate)
        
        for i in range(len(sorted_leaves) - 1):
            current_end = sorted_leaves[i].leaveEndDate
            next_start = sorted_leaves[i + 1].leaveStartDate
            
            if next_start <= current_end:
                raise ValueError(f'Leave periods overlap: {sorted_leaves[i].leaveStartDate} to {current_end} '
                               f'overlaps with {next_start} to {sorted_leaves[i + 1].leaveEndDate}')
        
        return v


class ScheduleResponse(BaseModel):
    facility_id: int
    doctor_id: int
    start_date: date
    end_date: date
    weekday: str
    window_num: int
    slot_start_time: str
    slot_end_time: str
    slot_duration_minutes: int

    class Config:
        from_attributes = True


class AvailabilityResponse(BaseModel):
    facility_id: int
    doctor_id: int
    start_date: date
    end_date: date
    availability_details: List[Dict]


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
                    "leavePeriods": [
                        {
                            "leaveStartDate": "",
                            "leaveEndDate": ""
                        }
                    ],
                    "weekDaysList": [
                        {
                            "weekDay": "Monday",
                            "slotWeeks": [
                                {"startTime": "", "endTime": "", "totalSlots": "", "slotDurationMinutes": 15},
                                {"startTime": "", "endTime": "", "totalSlots": "", "slotDurationMinutes": 15},
                                {"startTime": "", "endTime": "", "totalSlots": "", "slotDurationMinutes": 15}
                            ]
                        },
                        {
                            "weekDay": "Tuesday",
                            "slotWeeks": [
                                {"startTime": "", "endTime": "", "totalSlots": "", "slotDurationMinutes": 15},
                                {"startTime": "", "endTime": "", "totalSlots": "", "slotDurationMinutes": 15},
                                {"startTime": "", "endTime": "", "totalSlots": "", "slotDurationMinutes": 15}
                            ]
                        },
                        {
                            "weekDay": "Wednesday",
                            "slotWeeks": [
                                {"startTime": "", "endTime": "", "totalSlots": "", "slotDurationMinutes": 15},
                                {"startTime": "", "endTime": "", "totalSlots": "", "slotDurationMinutes": 15},
                                {"startTime": "", "endTime": "", "totalSlots": "", "slotDurationMinutes": 15}
                            ]
                        },
                        {
                            "weekDay": "Thursday",
                            "slotWeeks": [
                                {"startTime": "", "endTime": "", "totalSlots": "", "slotDurationMinutes": 15},
                                {"startTime": "", "endTime": "", "totalSlots": "", "slotDurationMinutes": 15},
                                {"startTime": "", "endTime": "", "totalSlots": "", "slotDurationMinutes": 15}
                            ]
                        },
                        {
                            "weekDay": "Friday",
                            "slotWeeks": [
                                {"startTime": "", "endTime": "", "totalSlots": "", "slotDurationMinutes": 15},
                                {"startTime": "", "endTime": "", "totalSlots": "", "slotDurationMinutes": 15},
                                {"startTime": "", "endTime": "", "totalSlots": "", "slotDurationMinutes": 15}
                            ]
                        },
                        {
                            "weekDay": "Saturday",
                            "slotWeeks": [
                                {"startTime": "", "endTime": "", "totalSlots": "", "slotDurationMinutes": 15},
                                {"startTime": "", "endTime": "", "totalSlots": "", "slotDurationMinutes": 15},
                                {"startTime": "", "endTime": "", "totalSlots": "", "slotDurationMinutes": 15}
                            ]
                        },
                        {
                            "weekDay": "Sunday",
                            "slotWeeks": [
                                {"startTime": "", "endTime": "", "totalSlots": "", "slotDurationMinutes": 15},
                                {"startTime": "", "endTime": "", "totalSlots": "", "slotDurationMinutes": 15},
                                {"startTime": "", "endTime": "", "totalSlots": "", "slotDurationMinutes": 15}
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
    """Create new schedules with overlap handling and honor multiple leave periods."""
    try:
        old_leave_periods = get_existing_leave_periods(db, schedule.facility_id, schedule.doctor_id)
        
        new_leave_periods = [(lp.leaveStartDate, lp.leaveEndDate) for lp in schedule.leavePeriods] if schedule.leavePeriods is not None else None
        
        has_schedule_data = False
        for weekday_data in schedule.weekDaysList:
            for slot in weekday_data.slotWeeks:
                if slot.startTime and slot.startTime.strip() and slot.endTime and slot.endTime.strip():
                    has_schedule_data = True
                    break
            if has_schedule_data:
                break
        
        if schedule.leavePeriods is None and not has_schedule_data:
            logger.info("No schedule data and leavePeriods not provided - preserving existing state")
            effective_leave_periods = old_leave_periods
        elif schedule.leavePeriods is None and has_schedule_data:
            effective_leave_periods = old_leave_periods if old_leave_periods else []
            logger.info(f"Preserving existing leave periods during schedule update")
        else:
            effective_leave_periods = new_leave_periods if new_leave_periods else []
            logger.info(f"Using explicitly provided leave periods: {len(effective_leave_periods)} period(s)")
        
        dates_to_restore = []
        
        if new_leave_periods is not None:
            old_leave_dates = set()
            for old_start, old_end in old_leave_periods:
                current = old_start
                while current <= old_end:
                    old_leave_dates.add(current)
                    current += timedelta(days=1)
            
            new_leave_dates = set()
            for new_start, new_end in new_leave_periods:
                current = new_start
                while current <= new_end:
                    new_leave_dates.add(current)
                    current += timedelta(days=1)
            
            dates_to_restore_set = old_leave_dates - new_leave_dates
            
            if dates_to_restore_set:
                sorted_dates = sorted(list(dates_to_restore_set))
                
                range_start = sorted_dates[0]
                range_end = sorted_dates[0]
                
                for i in range(1, len(sorted_dates)):
                    if sorted_dates[i] == range_end + timedelta(days=1):
                        range_end = sorted_dates[i]
                    else:
                        dates_to_restore.append((range_start, range_end))
                        range_start = sorted_dates[i]
                        range_end = sorted_dates[i]
                
                dates_to_restore.append((range_start, range_end))
        
        for restore_start, restore_end in dates_to_restore:
            restore_schedules_for_dates(db, schedule.facility_id, schedule.doctor_id, 
                                      restore_start, restore_end)
            db.flush()
        
        if dates_to_restore:
            merge_adjacent_schedules(db, schedule.facility_id, schedule.doctor_id)
            db.flush()
        
        if not has_schedule_data:
            if new_leave_periods is not None:
                sync_leave_periods_to_db(db, schedule.facility_id, schedule.doctor_id, new_leave_periods)
                
                if new_leave_periods:
                    delete_schedules_in_leave_periods(
                        db,
                        schedule.facility_id,
                        schedule.doctor_id,
                        new_leave_periods
                    )
                    db.flush()
                    
                    merge_adjacent_schedules(db, schedule.facility_id, schedule.doctor_id)
                    db.flush()
            
            db.commit()
            logger.info(f"Updated leave periods for doctor {schedule.doctor_id}: {len(effective_leave_periods)} leave period(s)")
            
            original_payload = {
                "startDate": str(schedule.startDate),
                "endDate": str(schedule.endDate),
                "facility_id": schedule.facility_id,
                "doctor_id": schedule.doctor_id,
                "leavePeriods": [
                    {
                        "leaveStartDate": str(lp.leaveStartDate),
                        "leaveEndDate": str(lp.leaveEndDate)
                    }
                    for lp in schedule.leavePeriods
                ] if schedule.leavePeriods is not None else [],
                "weekDaysList": [
                    {
                        "weekDay": weekday_data.weekDay,
                        "slotWeeks": [
                            {
                                "startTime": slot.startTime,
                                "endTime": slot.endTime,
                                "totalSlots": slot.totalSlots,
                                "slotDurationMinutes": slot.slotDurationMinutes
                            }
                            for slot in weekday_data.slotWeeks
                        ]
                    }
                    for weekday_data in schedule.weekDaysList
                ]
            }
            
            return {
                "success": True,
                "message": f"Successfully updated {len(effective_leave_periods)} leave period(s)",
                "payload": original_payload,
                "created_schedules": []
            }
        
        if schedule.leavePeriods is not None:
            sync_leave_periods_to_db(db, schedule.facility_id, schedule.doctor_id, effective_leave_periods)
        
        if effective_leave_periods:
            delete_schedules_in_leave_periods(
                db,
                schedule.facility_id,
                schedule.doctor_id,
                effective_leave_periods
            )
            db.flush()
            
            merge_adjacent_schedules(db, schedule.facility_id, schedule.doctor_id)
            db.flush()
        
        created_schedules: List[Dict[str, Any]] = []

        for weekday_data in schedule.weekDaysList:
            weekday = weekday_data.weekDay

            for window_num, slot in enumerate(weekday_data.slotWeeks, 1):
                if not slot.startTime or not slot.endTime:
                    continue
                if not slot.startTime.strip() or not slot.endTime.strip():
                    continue

                try:
                    start_time_obj = parse_time_string(slot.startTime)
                    end_time_obj = parse_time_string(slot.endTime)

                    if not start_time_obj or not end_time_obj:
                        continue

                    if start_time_obj >= end_time_obj:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Start time must be less than end time for {weekday} window {window_num}"
                        )

                    slot_duration = slot.slotDurationMinutes
                    if slot_duration <= 0 or slot_duration > 120:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Slot duration must be between 1 and 120 minutes for {weekday} window {window_num}"
                        )

                    segments = split_ranges_around_leaves(
                        schedule.startDate,
                        schedule.endDate,
                        effective_leave_periods
                    )

                    for seg_start, seg_end in segments:
                        handle_schedule_overlap(
                            db,
                            schedule.facility_id,
                            schedule.doctor_id,
                            seg_start,
                            seg_end,
                            weekday,
                            window_num
                        )

                        total_slots = slot.totalSlots if slot.totalSlots and slot.totalSlots.strip() else None

                        new_schedule = model.DoctorSchedule(
                            facility_id=schedule.facility_id,
                            doctor_id=schedule.doctor_id,
                            start_date=seg_start,
                            end_date=seg_end,
                            week_day=weekday,
                            window_num=window_num,
                            slot_start_time=start_time_obj,
                            slot_end_time=end_time_obj,
                            total_slots=total_slots,
                            slot_duration_minutes=slot_duration,
                            availability_flag='A'
                        )

                        db.add(new_schedule)
                        created_schedules.append({
                            'weekday': weekday,
                            'window': window_num,
                            'start_time': slot.startTime,
                            'end_time': slot.endTime,
                            'segment_start_date': str(seg_start),
                            'segment_end_date': str(seg_end),
                            'totalSlots': slot.totalSlots,
                            'slotDurationMinutes': slot_duration
                        })

                except ValueError as e:
                    logger.warning(f"Skipping invalid time for {weekday} window {window_num}: {str(e)}")
                    continue

        if not created_schedules:
            raise HTTPException(status_code=400, detail="No valid schedules found to create")

        db.commit()

        logger.info(f"Created {len(created_schedules)} schedules for doctor {schedule.doctor_id}")
        
        original_payload = {
            "startDate": str(schedule.startDate),
            "endDate": str(schedule.endDate),
            "facility_id": schedule.facility_id,
            "doctor_id": schedule.doctor_id,
            "leavePeriods": [
                {
                    "leaveStartDate": str(lp.leaveStartDate),
                    "leaveEndDate": str(lp.leaveEndDate)
                }
                for lp in schedule.leavePeriods
            ] if schedule.leavePeriods is not None else [],
            "weekDaysList": [
                {
                    "weekDay": weekday_data.weekDay,
                    "slotWeeks": [
                        {
                            "startTime": slot.startTime,
                            "endTime": slot.endTime,
                            "totalSlots": slot.totalSlots,
                            "slotDurationMinutes": slot.slotDurationMinutes
                        }
                        for slot in weekday_data.slotWeeks
                    ]
                }
                for weekday_data in schedule.weekDaysList
            ]
        }
        
        return {
            "success": True,
            "message": f"Successfully created {len(created_schedules)} schedules with {len(effective_leave_periods)} leave period(s)",
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
            model.DoctorSchedule.doctor_id == doctor_id,
            model.DoctorSchedule.availability_flag == 'A'
        ).order_by(
            model.DoctorSchedule.start_date,
            model.DoctorSchedule.week_day,
            model.DoctorSchedule.window_num,
            model.DoctorSchedule.slot_start_time
        ).all()

        if not schedules:
            raise HTTPException(status_code=404, detail="No schedules found")

        overall_start = min(s.start_date for s in schedules)
        overall_end = max(s.end_date for s in schedules)

        leave_periods_list = []
        leave_records = get_existing_leave_periods(db, facility_id, doctor_id)
        
        for leave_start, leave_end in leave_records:
            leave_periods_list.append({
                "leaveStartDate": str(leave_start),
                "leaveEndDate": str(leave_end)
            })

        weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        weekdays_list = []
        
        for weekday in weekdays:
            weekday_schedules = [s for s in schedules if s.week_day == weekday]
            
            window_dict = {}
            
            for schedule in weekday_schedules:
                window_num = schedule.window_num
                
                if window_num not in window_dict:
                    window_dict[window_num] = {
                        "startTime": time_to_string(schedule.slot_start_time),
                        "endTime": time_to_string(schedule.slot_end_time),
                        "totalSlots": schedule.total_slots if schedule.total_slots is not None else "",
                        "slotDurationMinutes": getattr(schedule, 'slot_duration_minutes', 15) or 15
                    }
            
            slot_weeks = []
            for window_num in range(1, 4):
                if window_num in window_dict:
                    slot_weeks.append(window_dict[window_num])
                else:
                    slot_weeks.append({
                        "startTime": "",
                        "endTime": "",
                        "totalSlots": "",
                        "slotDurationMinutes": 15
                    })
            
            weekdays_list.append({
                "weekDay": weekday,
                "slotWeeks": slot_weeks
            })

        payload = {
            "startDate": str(overall_start),
            "endDate": str(overall_end),
            "facility_id": facility_id,
            "doctor_id": doctor_id,
            "leavePeriods": leave_periods_list,
            "weekDaysList": weekdays_list
        }

        return payload

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting schedules: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error getting schedules: {str(e)}")


@router.delete("/{facility_id}/{doctor_id}/{week_day}/{window_num}", response_model=Dict)
async def delete_schedule(
    facility_id: int, 
    doctor_id: int,
    week_day: str,
    window_num: int, 
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete all schedules for a specific weekday and window"""
    try:
        deleted_count = db.query(model.DoctorSchedule).filter(
            model.DoctorSchedule.facility_id == facility_id,
            model.DoctorSchedule.doctor_id == doctor_id,
            model.DoctorSchedule.week_day == week_day,
            model.DoctorSchedule.window_num == window_num,
            model.DoctorSchedule.availability_flag == 'A'
        ).delete(synchronize_session=False)

        if deleted_count == 0:
            raise HTTPException(status_code=404, detail="No schedules found to delete")

        db.commit()

        return {
            "success": True, 
            "message": f"Successfully deleted {deleted_count} schedule(s) for {week_day} window {window_num}"
        }

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

        schedules = db.query(model.DoctorSchedule).filter(
            model.DoctorSchedule.facility_id == facility_id,
            model.DoctorSchedule.doctor_id == doctor_id,
            model.DoctorSchedule.availability_flag == 'A',
            model.DoctorSchedule.end_date >= start_date,
            model.DoctorSchedule.start_date <= end_date
        ).order_by(
            model.DoctorSchedule.start_date,
            model.DoctorSchedule.week_day,
            model.DoctorSchedule.slot_start_time
        ).all()

        leave_periods = get_existing_leave_periods(db, facility_id, doctor_id)

        availability_details = []

        current_date = start_date
        while current_date <= end_date:
            weekday = get_weekday_name(current_date)

            is_on_leave = False
            for leave_start, leave_end in leave_periods:
                if leave_start <= current_date <= leave_end:
                    is_on_leave = True
                    break

            matching_schedules = [
                s for s in schedules
                if (s.week_day == weekday and
                    s.start_date <= current_date and
                    s.end_date >= current_date)
            ]

            date_availability = {
                "date": str(current_date),
                "weekday": weekday,
                "is_available": len(matching_schedules) > 0 and not is_on_leave,
                "is_on_leave": is_on_leave,
                "schedules": []
            }

            for schedule_obj in matching_schedules:
                date_availability["schedules"].append({
                    "window_num": schedule_obj.window_num,
                    "slot_start_time": str(schedule_obj.slot_start_time),
                    "slot_end_time": str(schedule_obj.slot_end_time),
                    "slot_duration_minutes": getattr(schedule_obj, 'slot_duration_minutes', 15) or 15,
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