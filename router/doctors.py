from typing import List, Optional
from decimal import Decimal
from datetime import date

from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload
from fastapi import FastAPI, Depends, HTTPException, APIRouter
import model
from database import engine, SessionLocal
from auth_middleware import get_current_user, CurrentUser

# Create all tables
model.Base.metadata.create_all(bind=engine)

# Database dependency
def get_db():
    try:
        db = SessionLocal()
        yield db
    finally:
        db.close()

# Router setup
router = APIRouter(
    prefix="/doctors",
    responses={404: {"description": "Not found"}}
)

# Pydantic models
class ui_Doctors(BaseModel):
    firstname: str
    lastname: str
    specialization: str
    phone_number: Optional[str] = None
    email: Optional[str] = None
    consultation_fee: Optional[Decimal] = None
    ABDM_NHPR_id: Optional[str] = None
    facility_id: Optional[int] = None
    gender: Optional[str] = None
    age: Optional[int] = None
    experience: Optional[int] = None
    is_active: Optional[bool] = True

    class Config:
        schema_extra = {
            "example": {
                "firstname": "John",
                "lastname": "Smith",
                "specialization": "Cardiology",
                "phone_number": "+91-9876543210",
                "email": "john.smith@hospital.com",
                "consultation_fee": 500.00,
                "ABDM_NHPR_id": "ABDM123456",
                "facility_id": 1,
                "gender": "Male",
                "age": 35,
                "experience": 10,
                "is_active": True
            }
        }

class ui_DoctorsUpdate(BaseModel):
    firstname: Optional[str] = None
    lastname: Optional[str] = None
    specialization: Optional[str] = None
    phone_number: Optional[str] = None
    email: Optional[str] = None
    consultation_fee: Optional[Decimal] = None
    ABDM_NHPR_id: Optional[str] = None
    facility_id: Optional[int] = None
    gender: Optional[str] = None
    age: Optional[int] = None
    experience: Optional[int] = None
    is_active: Optional[bool] = None
    
    class Config:
        schema_extra = {
            "example": {
                "firstname": "John",
                "lastname": "Smith",
                "specialization": "Cardiology",
                "phone_number": "+91-9876543210",
                "email": "john.smith@hospital.com",
                "consultation_fee": 500.00,
                "ABDM_NHPR_id": "ABDM123456",
                "facility_id": 1,
                "gender": "Male",
                "age": 35,
                "experience": 10,
                "is_active": True
            }
        }

class schedule_response(BaseModel):
    schedule: str  # e.g., "Mon-Fri" or "Monday, Wednesday"
    consultation_time: str  # e.g., "9:00 AM - 4:00 PM"
    window_num: Optional[int] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None

    class Config:
        from_attributes = True

class facility_response(BaseModel):
    facility_id: int
    name: str

    class Config:
        from_attributes = True

class doctor_response(BaseModel):
    id: int
    doctor_name: str  # Combined first and last name
    firstname: str
    lastname: str
    phone_number: Optional[str] = None
    email: Optional[str] = None
    specialization: str
    consultation_fee: Optional[Decimal] = None
    ABDM_NHPR_id: Optional[str] = None
    gender: Optional[str] = None
    age: Optional[int] = None
    experience: Optional[int] = None
    is_active: bool
    schedules: List[schedule_response] = []

    class Config:
        from_attributes = True

class doctor_schema_with_schedule(BaseModel):
    id: int
    doctor_name: str  # Combined first and last name
    firstname: str
    lastname: str
    phone_number: Optional[str] = None
    email: Optional[str] = None
    specialization: str
    consultation_fee: Optional[Decimal] = None
    ABDM_NHPR_id: Optional[str] = None
    facility_id: Optional[int] = None
    gender: Optional[str] = None
    age: Optional[int] = None
    experience: Optional[int] = None
    is_active: bool
    schedules: List[schedule_response] = []
    facility: Optional[facility_response] = None

    class Config:
        from_attributes = True

# Utility functions
def get_postnotfound_exception():
    return HTTPException(status_code=404, detail="Doctor not found")

def successful_response(status_code):
    return {
        "status_code": status_code,
        "message": "Operation successful"
    }

def combine_doctor_name(firstname: str, lastname: str) -> str:
    """Combine first and last name with proper formatting"""
    if firstname and lastname:
        return f"Dr. {firstname.strip()} {lastname.strip()}"
    elif firstname:
        return f"Dr. {firstname.strip()}"
    elif lastname:
        return f"Dr. {lastname.strip()}"
    else:
        return "Dr. Unknown"

def format_time_to_12hour(time_obj):
    """Convert time object to 12-hour format with AM/PM"""
    try:
        from datetime import datetime
        if hasattr(time_obj, 'hour') and hasattr(time_obj, 'minute'):
            # It's already a time object
            time_str = f"{time_obj.hour:02d}:{time_obj.minute:02d}"
        else:
            # It's a string, convert it
            time_str = str(time_obj)
        
        time_dt = datetime.strptime(time_str, "%H:%M")
        return time_dt.strftime("%I:%M %p").lstrip('0')
    except:
        return str(time_obj)

def format_consultation_time(start_time, end_time):
    """Format consultation time as '9:00 AM - 4:00 PM'"""
    start_formatted = format_time_to_12hour(start_time)
    end_formatted = format_time_to_12hour(end_time)
    return f"{start_formatted} - {end_formatted}"

def group_schedules_by_time(schedules):
    """Group schedules by consultation time and format days for new schema"""
    grouped = {}
    
    for schedule in schedules:
        consultation_time = format_consultation_time(schedule.slot_start_time, schedule.slot_end_time)
        window_num = schedule.window_num
        start_date = schedule.start_date
        end_date = schedule.end_date
        
        key = f"{consultation_time}_{window_num}_{start_date}_{end_date}"
        
        if key not in grouped:
            grouped[key] = {
                'consultation_time': consultation_time,
                'window_num': window_num,
                'start_date': start_date,
                'end_date': end_date,
                'days': []
            }
        
        grouped[key]['days'].append(schedule.week_day)
    
    # Format the grouped schedules
    result = []
    for group_data in grouped.values():
        days = group_data['days']
        
        # Convert day names to abbreviations and sort
        day_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        day_abbrev = {
            'Monday': 'Mon', 'Tuesday': 'Tue', 'Wednesday': 'Wed', 
            'Thursday': 'Thu', 'Friday': 'Fri', 'Saturday': 'Sat', 'Sunday': 'Sun'
        }
        
        # Handle both abbreviated and full day names
        day_abbrev_reverse = {v: k for k, v in day_abbrev.items()}
        
        # Normalize to full day names
        normalized_days = []
        for day in days:
            if day in day_abbrev_reverse:
                normalized_days.append(day_abbrev_reverse[day])
            else:
                normalized_days.append(day)
        
        sorted_days = sorted(set(normalized_days), key=lambda x: day_order.index(x) if x in day_order else 999)
        
        # Format days (e.g., "Mon-Fri" for consecutive days, "Mon, Wed, Fri" for non-consecutive)
        if len(sorted_days) == 5 and all(day in sorted_days for day in ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']):
            schedule_str = "Mon-Fri"
        elif len(sorted_days) == 7:
            schedule_str = "Mon-Sun"
        elif len(sorted_days) == 2 and 'Saturday' in sorted_days and 'Sunday' in sorted_days:
            schedule_str = "Sat-Sun"
        else:
            # Non-consecutive days
            schedule_str = ", ".join([day_abbrev.get(day, day) for day in sorted_days])
        
        result.append(schedule_response(
            schedule=schedule_str,
            consultation_time=group_data['consultation_time'],
            window_num=group_data['window_num'],
            start_date=group_data['start_date'],
            end_date=group_data['end_date']
        ))
    
    return result

# API Routes
@router.get("/", tags=["doctors"], response_model=List[doctor_response])
async def get_all_doctors(
    facility_id: Optional[int] = None, 
    include_inactive: Optional[bool] = False,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get all doctors with soft delete filtering
    - By default, only returns active and non-deleted doctors
    - Set include_inactive=true to include inactive doctors
    - Deleted doctors are never returned
    - Regular users can only see doctors from their own facility
    - Super admins can see all doctors or filter by facility_id
    """
    try:
        query = db.query(model.Doctors).options(joinedload(model.Doctors.doctor_schedules))
        
        # Always filter out soft deleted doctors
        query = query.filter(model.Doctors.is_deleted == False)
        
        # Filter by active status unless explicitly requested to include inactive
        if not include_inactive:
            query = query.filter(model.Doctors.is_active == True)
        
        # For regular users (non-super admins), restrict to their facility only
        if not current_user.is_super_admin():
            query = query.filter(model.Doctors.facility_id == current_user.facility_id)
        # For super admins, allow optional facility filtering
        elif facility_id is not None:
            query = query.filter(model.Doctors.facility_id == facility_id)
            
        doctors = query.all()

        if not doctors:
            return []

        result = []
        for doctor in doctors:
            # Group and format schedules using new relationship
            schedules = group_schedules_by_time(getattr(doctor, 'doctor_schedules', []))

            result.append(doctor_response(
                id=doctor.id,
                doctor_name=combine_doctor_name(doctor.firstname, doctor.lastname),
                firstname=doctor.firstname,
                lastname=doctor.lastname,
                phone_number=getattr(doctor, 'phone_number', None),
                email=getattr(doctor, 'email', None),
                specialization=doctor.specialization,
                consultation_fee=getattr(doctor, 'consultation_fee', None),
                ABDM_NHPR_id=getattr(doctor, 'ABDM_NHPR_id', None),
                gender=getattr(doctor, 'gender', None),
                age=getattr(doctor, 'age', None),
                experience=getattr(doctor, 'experience', None),
                is_active=doctor.is_active,
                schedules=schedules
            ))
        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving doctors: {str(e)}")


@router.get("/{doctor_id}", tags=["doctors"], response_model=doctor_schema_with_schedule)
async def get_doctor_by_id(
    doctor_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get doctor by ID (only if not soft deleted)
    - Regular users can only access doctors from their own facility
    - Super admins can access any doctor
    """
    try:
        query = (
            db.query(model.Doctors)
            .filter(model.Doctors.id == doctor_id)
            .filter(model.Doctors.is_deleted == False)  # Filter out soft deleted doctors
        )
        
        # For regular users, restrict to their facility only
        if not current_user.is_super_admin():
            query = query.filter(model.Doctors.facility_id == current_user.facility_id)
        
        doctor = query.options(
            joinedload(model.Doctors.doctor_schedules), 
            joinedload(model.Doctors.facility)
        ).first()

        if not doctor:
            raise HTTPException(status_code=404, detail="Doctor not found")

        facility_info = None
        if doctor.facility:
            facility_name = getattr(doctor.facility, 'name', None) or \
                            getattr(doctor.facility, 'facility_name', None) or \
                            getattr(doctor.facility, 'FacilityName', None) or \
                            "Unknown Facility"
            facility_info = facility_response(facility_id=doctor.facility.facility_id, name=facility_name)

        elif doctor.facility_id and doctor.facility_id > 0:
            facility = db.query(model.Facility).filter(
                model.Facility.facility_id == doctor.facility_id
            ).first()
            if facility:
                facility_name = getattr(facility, 'name', None) or \
                                getattr(facility, 'facility_name', None) or \
                                getattr(facility, 'FacilityName', None) or \
                                "Unknown Facility"
                facility_info = facility_response(facility_id=facility.facility_id, name=facility_name)

        # Group and format schedules using new relationship
        schedules = group_schedules_by_time(doctor.doctor_schedules)

        return doctor_schema_with_schedule(
            id=doctor.id,
            doctor_name=combine_doctor_name(doctor.firstname, doctor.lastname),
            firstname=doctor.firstname,
            lastname=doctor.lastname,
            phone_number=getattr(doctor, 'phone_number', None),
            email=getattr(doctor, 'email', None),
            specialization=doctor.specialization,
            consultation_fee=getattr(doctor, 'consultation_fee', None),
            ABDM_NHPR_id=getattr(doctor, 'ABDM_NHPR_id', None),
            facility_id=doctor.facility_id,
            gender=getattr(doctor, 'gender', None),
            age=getattr(doctor, 'age', None),
            experience=getattr(doctor, 'experience', None),
            is_active=doctor.is_active,
            schedules=schedules,
            facility=facility_info
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving doctor: {str(e)}")


@router.post("/", tags=["doctors"])
async def add_new_doctor(
    doctor: ui_Doctors,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        # For regular users, enforce their facility_id
        if not current_user.is_super_admin():
            doctor.facility_id = current_user.facility_id
        
        if doctor.facility_id:
            facility = db.query(model.Facility).filter(model.Facility.facility_id == doctor.facility_id).first()
            if not facility:
                raise HTTPException(status_code=400, detail="Facility not found")

        doctor_model = model.Doctors()
        doctor_model.firstname = doctor.firstname
        doctor_model.lastname = doctor.lastname
        doctor_model.specialization = doctor.specialization
        doctor_model.phone_number = doctor.phone_number
        doctor_model.email = doctor.email
        doctor_model.consultation_fee = doctor.consultation_fee
        doctor_model.ABDM_NHPR_id = doctor.ABDM_NHPR_id
        doctor_model.facility_id = doctor.facility_id
        doctor_model.gender = doctor.gender
        doctor_model.age = doctor.age
        doctor_model.experience = doctor.experience
        doctor_model.is_active = doctor.is_active if doctor.is_active is not None else True
        doctor_model.is_deleted = False  # Always set to False for new doctors

        db.add(doctor_model)
        db.commit()
        db.refresh(doctor_model)

        return successful_response(201)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error adding doctor: {str(e)}")

@router.api_route("/{doctor_id}", methods=["PUT"], tags=["doctors"], response_model=doctor_response)
async def edit_doctor_details(
    doctor_id: int,
    doctor: ui_DoctorsUpdate,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        query = db.query(model.Doctors).filter(
            model.Doctors.id == doctor_id,
            model.Doctors.is_deleted == False  # Only allow updates for non-deleted doctors
        )
        
        # For regular users, restrict to their facility only
        if not current_user.is_super_admin():
            query = query.filter(model.Doctors.facility_id == current_user.facility_id)
        
        existing_doctor = query.first()
        
        if not existing_doctor:
            raise get_postnotfound_exception()

        # Extract only provided fields
        update_data = doctor.dict(exclude_unset=True)
        filtered_data = {}

        for key, value in update_data.items():
            if isinstance(value, str):
                if value.strip() and value != "string":
                    filtered_data[key] = value
            elif isinstance(value, (int, float, Decimal)):
                # Skip updating consultation_fee and age to 0 accidentally
                if key == "consultation_fee" and float(value) == 0.0:
                    continue
                elif key == "age" and int(value) == 0:
                    continue
                elif key == "experience" and int(value) == 0:
                    continue
                else:
                    filtered_data[key] = value
            elif isinstance(value, bool) or value is not None:
                filtered_data[key] = value

        if not filtered_data:
            raise HTTPException(status_code=400, detail="No valid fields provided for update")

        # Validate facility_id only if it's provided and truthy
        if "facility_id" in filtered_data:
            facility_id = filtered_data.get("facility_id")
            # For regular users, prevent changing facility_id
            if not current_user.is_super_admin():
                filtered_data.pop("facility_id")
            elif facility_id:
                facility = db.query(model.Facility).filter(
                    model.Facility.facility_id == facility_id
                ).first()
                if not facility:
                    raise HTTPException(status_code=400, detail="Facility not found")
            else:
                # If facility_id is None or falsy (0), remove it to avoid overwriting
                filtered_data.pop("facility_id")

        # Apply updates
        for key, value in filtered_data.items():
            if hasattr(existing_doctor, key):
                setattr(existing_doctor, key, value)

        db.commit()
        db.refresh(existing_doctor)

        # Updated to use correct lowercase column names
        doctor_schedules = db.query(model.DoctorSchedule).filter(
            model.DoctorSchedule.doctor_id == existing_doctor.id
        ).all()

        schedules = group_schedules_by_time(doctor_schedules)

        return doctor_response(
            id=existing_doctor.id,
            doctor_name=combine_doctor_name(existing_doctor.firstname, existing_doctor.lastname),
            firstname=existing_doctor.firstname,
            lastname=existing_doctor.lastname,
            phone_number=getattr(existing_doctor, 'phone_number', None),
            email=getattr(existing_doctor, 'email', None),
            specialization=existing_doctor.specialization,
            consultation_fee=existing_doctor.consultation_fee,
            ABDM_NHPR_id=getattr(existing_doctor, 'ABDM_NHPR_id', None),
            gender=getattr(existing_doctor, 'gender', None),
            age=getattr(existing_doctor, 'age', None),
            experience=getattr(existing_doctor, 'experience', None),
            is_active=existing_doctor.is_active,
            schedules=schedules
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error updating doctor: {str(e)}")

@router.delete("/{doctor_id}", tags=["doctors"])
async def delete_doctor_details(
    doctor_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Soft delete doctor by setting is_deleted=True
    - Regular users can only delete doctors from their own facility
    - Super admins can delete any doctor
    """
    try:
        query = db.query(model.Doctors).filter(
            model.Doctors.id == doctor_id,
            model.Doctors.is_deleted == False  # Only allow deletion of non-deleted doctors
        )
        
        # For regular users, restrict to their facility only
        if not current_user.is_super_admin():
            query = query.filter(model.Doctors.facility_id == current_user.facility_id)
        
        req_doc = query.first()
        
        if not req_doc:
            raise get_postnotfound_exception()

        # Soft delete: set is_deleted=True instead of actually deleting
        req_doc.is_deleted = True
        req_doc.is_active = False  # Also set inactive when deleted
        
        db.commit()
        return successful_response(200)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deleting doctor: {str(e)}")

# Additional endpoint to restore soft deleted doctor
@router.patch("/{doctor_id}/restore", tags=["doctors"])
async def restore_doctor(
    doctor_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Restore a soft deleted doctor
    - Regular users can only restore doctors from their own facility
    - Super admins can restore any doctor
    """
    try:
        query = db.query(model.Doctors).filter(
            model.Doctors.id == doctor_id,
            model.Doctors.is_deleted == True  # Only restore deleted doctors
        )
        
        # For regular users, restrict to their facility only
        if not current_user.is_super_admin():
            query = query.filter(model.Doctors.facility_id == current_user.facility_id)
        
        doctor = query.first()
        
        if not doctor:
            raise HTTPException(status_code=404, detail="Deleted doctor not found")

        doctor.is_deleted = False
        doctor.is_active = True  # Restore as active
        
        db.commit()
        return successful_response(200)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error restoring doctor: {str(e)}")