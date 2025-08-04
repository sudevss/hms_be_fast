from typing import List, Optional
from decimal import Decimal

from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload
from fastapi import FastAPI, Depends, HTTPException, APIRouter
from .auth import get_current_user, get_user_exception
import model
from database import engine, SessionLocal

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
    FacilityID: Optional[int] = None

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
                "FacilityID": 1,
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
    FacilityID: Optional[int] = None
    
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
                "FacilityID": 1,
            }
        }

class schedule_response(BaseModel):
    schedule: str  # e.g., "Mon-Fri" or "Monday, Wednesday"
    consultation_time: str  # e.g., "9:00 AM - 4:00 PM"
    slot_per_hour: Optional[int] = None
    appointments_per_slot: Optional[int] = None  # from AppointmentsPerSlot

    class Config:
        from_attributes = True

class facility_response(BaseModel):
    FacilityID: int
    name: str

    class Config:
        from_attributes = True

class doctor_response(BaseModel):
    id: int
    doctor_name: str  # Combined first and last name
    phone_number: Optional[str] = None
    email: Optional[str] = None
    specialization: str
    consultation_fee: Optional[Decimal] = None
    schedules: List[schedule_response] = []

    class Config:
        from_attributes = True

class doctor_schema_with_schedule(BaseModel):
    id: int
    doctor_name: str  # Combined first and last name
    phone_number: Optional[str] = None
    email: Optional[str] = None
    specialization: str
    consultation_fee: Optional[Decimal] = None
    ABDM_NHPR_id: Optional[str] = None
    FacilityID: Optional[int] = None
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

def get_schedule_details(schedule):
    """Extract slot duration and slots per hour from schedule"""
    slot_duration = None
    slot_per_hour = None
    
    # Get slot duration from Slotsize (which is in minutes as string)
    if hasattr(schedule, 'Slotsize') and schedule.Slotsize:
        try:
            slot_duration = int(schedule.Slotsize)  # Convert string to int
            # Calculate slots per hour based on slot duration
            slot_per_hour = 60 // slot_duration if slot_duration > 0 else None
        except (ValueError, TypeError):
            slot_duration = None
            slot_per_hour = None
    
    return slot_duration, slot_per_hour

def format_time_to_12hour(time_str):
    """Convert 24-hour format to 12-hour format with AM/PM"""
    try:
        from datetime import datetime
        time_obj = datetime.strptime(time_str, "%H:%M")
        return time_obj.strftime("%I:%M %p").lstrip('0')
    except:
        return time_str

def format_consultation_time(start_time, end_time):
    """Format consultation time as '9:00 AM - 4:00 PM'"""
    start_formatted = format_time_to_12hour(str(start_time))
    end_formatted = format_time_to_12hour(str(end_time))
    return f"{start_formatted} - {end_formatted}"

def group_schedules_by_time(schedules):
    """Group schedules by consultation time and format days"""
    grouped = {}
    
    for schedule in schedules:
        consultation_time = format_consultation_time(schedule.StartTime, schedule.EndTime)
        slot_duration, slot_per_hour = get_schedule_details(schedule)
        appointments_per_slot = getattr(schedule, 'AppointmentsPerSlot', None)
        
        key = f"{consultation_time}_{slot_per_hour}_{appointments_per_slot}"
        
        if key not in grouped:
            grouped[key] = {
                'consultation_time': consultation_time,
                'slot_per_hour': slot_per_hour,
                'appointments_per_slot': appointments_per_slot,
                'days': []
            }
        
        grouped[key]['days'].append(schedule.DayOfWeek)
    
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
        
        sorted_days = sorted(days, key=lambda x: day_order.index(x) if x in day_order else 999)
        
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
            slot_per_hour=group_data['slot_per_hour'],
            appointments_per_slot=group_data['appointments_per_slot']
        ))
    
    return result

# API Routes
@router.get("/", tags=["doctors"], response_model=List[doctor_response])
async def get_all_doctors(facility_id: Optional[int] = None, db: Session = Depends(get_db)):
    try:
        query = db.query(model.Doctors).options(joinedload(model.Doctors.schedules))
        if facility_id is not None:
            query = query.filter(model.Doctors.FacilityID == facility_id)
        doctors = query.all()

        if not doctors:
            return []

        result = []
        for doctor in doctors:
            # Group and format schedules
            schedules = group_schedules_by_time(getattr(doctor, 'schedules', []))

            result.append(doctor_response(
                id=doctor.id,
                doctor_name=combine_doctor_name(doctor.firstname, doctor.lastname),
                phone_number=getattr(doctor, 'phone_number', None),
                email=getattr(doctor, 'email', None),
                specialization=doctor.specialization,
                consultation_fee=getattr(doctor, 'consultation_fee', None),
                schedules=schedules
            ))
        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving doctors: {str(e)}")


@router.get("/{doctor_id}", tags=["doctors"], response_model=doctor_schema_with_schedule)
async def get_doctor_by_id(doctor_id: int, db: Session = Depends(get_db)):
    try:
        doctor = (
            db.query(model.Doctors)
            .filter(model.Doctors.id == doctor_id)
            .options(joinedload(model.Doctors.schedules), joinedload(model.Doctors.facility))
            .first()
        )

        if not doctor:
            raise HTTPException(status_code=404, detail="Doctor not found")

        facility_info = None
        if doctor.facility:
            facility_name = getattr(doctor.facility, 'name', None) or \
                            getattr(doctor.facility, 'facility_name', None) or \
                            getattr(doctor.facility, 'FacilityName', None) or \
                            "Unknown Facility"
            facility_info = facility_response(FacilityID=doctor.facility.FacilityID, name=facility_name)

        elif doctor.FacilityID and doctor.FacilityID > 0:
            facility = db.query(model.Facilities).filter(
                model.Facilities.FacilityID == doctor.FacilityID
            ).first()
            if facility:
                facility_name = getattr(facility, 'name', None) or \
                                getattr(facility, 'facility_name', None) or \
                                getattr(facility, 'FacilityName', None) or \
                                "Unknown Facility"
                facility_info = facility_response(FacilityID=facility.FacilityID, name=facility_name)

        # Group and format schedules
        schedules = group_schedules_by_time(doctor.schedules)

        return doctor_schema_with_schedule(
            id=doctor.id,
            doctor_name=combine_doctor_name(doctor.firstname, doctor.lastname),
            phone_number=getattr(doctor, 'phone_number', None),
            email=getattr(doctor, 'email', None),
            specialization=doctor.specialization,
            consultation_fee=getattr(doctor, 'consultation_fee', None),
            ABDM_NHPR_id=doctor.ABDM_NHPR_id,
            FacilityID=doctor.FacilityID,
            schedules=schedules,
            facility=facility_info
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving doctor: {str(e)}")


@router.post("/", tags=["doctors"])
async def add_new_doctor(doctor: ui_Doctors, db: Session = Depends(get_db), adm: dict = Depends(get_current_user)):
    try:
        if not adm:
            raise get_user_exception()

        if doctor.FacilityID:
            facility = db.query(model.Facility).filter(model.Facility.FacilityID == doctor.FacilityID).first()
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
        doctor_model.FacilityID = doctor.FacilityID

        db.add(doctor_model)
        db.commit()
        db.refresh(doctor_model)

        return successful_response(201)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error adding doctor: {str(e)}")
@router.api_route("/{doctor_id}", methods=["PUT"], tags=["doctors"], response_model=doctor_response)
async def edit_doctor_details(doctor_id: int, doctor: ui_DoctorsUpdate, adm: dict = Depends(get_current_user),
                              db: Session = Depends(get_db)):
    try:
        if not adm:
            raise get_user_exception()

        existing_doctor = db.query(model.Doctors).filter(model.Doctors.id == doctor_id).first()
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
                # ✅ Skip updating consultation_fee to 0 accidentally
                if key == "consultation_fee" and float(value) == 0.0:
                    continue
                filtered_data[key] = value
            elif value is not None:
                filtered_data[key] = value

        if not filtered_data:
            raise HTTPException(status_code=400, detail="No valid fields provided for update")

        # ✅ Validate FacilityID only if it's provided and truthy
        if "FacilityID" in filtered_data:
            facility_id = filtered_data.get("FacilityID")
            if facility_id:
                facility = db.query(model.Facility).filter(
                    model.Facility.FacilityID == facility_id
                ).first()
                if not facility:
                    raise HTTPException(status_code=400, detail="Facility not found")
            else:
                # If facility_id is None or falsy (0), remove it to avoid overwriting
                filtered_data.pop("FacilityID")

        # Apply updates
        for key, value in filtered_data.items():
            if hasattr(existing_doctor, key):
                setattr(existing_doctor, key, value)

        db.commit()
        db.refresh(existing_doctor)

        doctor_schedules = db.query(model.DoctorSchedule).filter(
            model.DoctorSchedule.DoctorID == existing_doctor.id
        ).all()

        schedules = group_schedules_by_time(doctor_schedules)

        return doctor_response(
            id=existing_doctor.id,
            doctor_name=combine_doctor_name(existing_doctor.firstname, existing_doctor.lastname),
            phone_number=getattr(existing_doctor, 'phone_number', None),
            email=getattr(existing_doctor, 'email', None),
            specialization=existing_doctor.specialization,
            consultation_fee=existing_doctor.consultation_fee,
            schedules=schedules
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error updating doctor: {str(e)}")





@router.delete("/{doctor_id}", tags=["doctors"])
async def delete_doctor_details(doctor_id: int, db: Session = Depends(get_db), adm: dict = Depends(get_current_user)):
    try:
        if not adm:
            raise get_user_exception()

        req_doc = db.query(model.Doctors).filter(model.Doctors.id == doctor_id).first()
        if not req_doc:
            raise get_postnotfound_exception()

        db.query(model.Doctors).filter(model.Doctors.id == doctor_id).delete()
        db.commit()
        return successful_response(200)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deleting doctor: {str(e)}")