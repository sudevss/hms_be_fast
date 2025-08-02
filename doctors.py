from typing import List, Optional

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
    ABDM_NHPR_id: Optional[str] = None
    FacilityID: Optional[int] = None

    class Config:
        schema_extra = {
            "example": {
                "firstname": "John",
                "lastname": "Smith",
                "specialization": "Cardiology",
                "ABDM_NHPR_id": "ABDM123456",
                "FacilityID": 1,
            }
        }

class ui_DoctorsUpdate(BaseModel):
    firstname: Optional[str] = None
    lastname: Optional[str] = None
    specialization: Optional[str] = None
    ABDM_NHPR_id: Optional[str] = None
    FacilityID: Optional[int] = None
    

    class Config:
        schema_extra = {
            "example": {
                "firstname": "John",
                "lastname": "Smith",
                "specialization": "Cardiology",
                "ABDM_NHPR_id": "ABDM123456",
                "FacilityID": 1,
            }
        }

class schedule_response(BaseModel):
    day: str
    start_time: str
    end_time: str

    class Config:
        from_attributes = True

class facility_response(BaseModel):
    FacilityID: int
    name: str

    class Config:
        from_attributes = True

class doctor_response(BaseModel):
    id: int
    firstname: str
    lastname: str
    specialization: str
    ABDM_NHPR_id: Optional[str] = None
    FacilityID: Optional[int] = None
    schedules: List[schedule_response] = []

    class Config:
        from_attributes = True

class doctor_schema_with_schedule(BaseModel):
    id: int
    firstname: str
    lastname: str
    specialization: str
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
            schedules = [
                schedule_response(
                    day=schedule.DayOfWeek,
                    start_time=str(schedule.StartTime),
                    end_time=str(schedule.EndTime)
                )
                for schedule in getattr(doctor, 'schedules', [])
            ]

            result.append(doctor_response(
                id=doctor.id,
                firstname=doctor.firstname,
                lastname=doctor.lastname,
                specialization=doctor.specialization,
                ABDM_NHPR_id=doctor.ABDM_NHPR_id,
                FacilityID=doctor.FacilityID,
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

        return doctor_schema_with_schedule(
            id=doctor.id,
            firstname=doctor.firstname,
            lastname=doctor.lastname,
            specialization=doctor.specialization,
            ABDM_NHPR_id=doctor.ABDM_NHPR_id,
            FacilityID=doctor.FacilityID,
            schedules=[
                schedule_response(
                    day=schedule.DayOfWeek,
                    start_time=str(schedule.StartTime),
                    end_time=str(schedule.EndTime)
                ) for schedule in doctor.schedules
            ],
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

        update_data = doctor.dict(exclude_unset=True, exclude_none=True)
        filtered_data = {}

        for key, value in update_data.items():
            if isinstance(value, str):
                if value.strip() and value != "string":
                    filtered_data[key] = value
            elif isinstance(value, int) and value > 0:
                filtered_data[key] = value
            elif value is not None:
                filtered_data[key] = value

        if not filtered_data:
            raise HTTPException(status_code=400, detail="No valid fields provided for update")

        if "FacilityID" in filtered_data:
            facility = db.query(model.Facility).filter(model.Facility.FacilityID == filtered_data["FacilityID"]).first()
            if not facility:
                raise HTTPException(status_code=400, detail="Facility not found")

        for key, value in filtered_data.items():
            if hasattr(existing_doctor, key):
                setattr(existing_doctor, key, value)

        db.commit()
        db.refresh(existing_doctor)

        doctor_schedules = db.query(model.DoctorSchedule).filter(
            model.DoctorSchedule.DoctorID == existing_doctor.id
        ).all()

        schedules = [
            schedule_response(
                day=s.DayOfWeek,
                start_time=str(s.StartTime),
                end_time=str(s.EndTime)
            ) for s in doctor_schedules
        ]

        return doctor_response(
            id=existing_doctor.id,
            firstname=existing_doctor.firstname,
            lastname=existing_doctor.lastname,
            specialization=existing_doctor.specialization,
            ABDM_NHPR_id=existing_doctor.ABDM_NHPR_id,
            FacilityID=existing_doctor.FacilityID,
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