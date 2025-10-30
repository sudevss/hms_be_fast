
from typing import List, Optional, Dict, Any
from datetime import date
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session
from fastapi import HTTPException, APIRouter, Depends, Query
from sqlalchemy import and_

# Import your existing database setup and models (same as doctor.py)
import model
from database import engine, SessionLocal
from auth_middleware import get_current_user, CurrentUser, require_roles

# Create all tables
model.Base.metadata.create_all(bind=engine)

# Database dependency (same as doctor.py)
def get_db():
    try:
        db = SessionLocal()
        yield db
    finally:
        db.close()

# Create API Router
router = APIRouter(
    prefix="/patient_diagnosis",
    tags=["patient-diagnosis"],
    responses={404: {"description": "Not found"}}
)

# Pydantic Models for Request/Response
class PatientDiagnosisCreate(BaseModel):
    """Request model for creating/updating patient diagnosis - all fields included"""
    diagnosis_id: Optional[int] = Field(None, description="Diagnosis ID for update, null for create")
    facility_id: int = Field(..., description="Facility ID where diagnosis was made")
    patient_id: int = Field(..., description="Patient ID")
    diagnosis_date: date = Field(..., description="Diagnosis date")
    appointment_id: Optional[int] = Field(None, description="Associated appointment ID")
    doctor_id: int = Field(..., description="Doctor ID who made the diagnosis")
    vital_bp: Optional[str] = Field(None, max_length=50, description="Blood pressure reading")
    vital_hr: Optional[str] = Field(None, max_length=50, description="Heart rate")
    vital_temp: Optional[str] = Field(None, max_length=50, description="Temperature")
    vital_spo2: Optional[str] = Field(None, max_length=50, description="Blood oxygen saturation")
    weight: Optional[str] = Field(None, max_length=50, description="Patient weight")
    height: Optional[str] = Field(None, max_length=50, description="Patient height")
    chief_complaint: Optional[str] = Field(None, description="Patient's chief complaint")
    assessment_notes: Optional[str] = Field(None, description="Doctor's assessment notes")
    treatment_plan: Optional[str] = Field(None, description="Prescribed treatment plan")
    recomm_tests: Optional[str] = Field(None, description="Recommended tests")
    followup_date: Optional[date] = Field(None, description="Follow-up appointment date")

    @field_validator('appointment_id', 'diagnosis_id')
    @classmethod
    def validate_optional_ids(cls, v):
        """Convert 0 to None for optional foreign key fields"""
        if v == 0:
            return None
        return v

    class Config:
        json_encoders = {
            date: lambda v: v.isoformat() if v else None
        }
        json_schema_extra = {
            "example": {
                "diagnosis_id": None,
                "facility_id": 1,
                "patient_id": 1,
                "diagnosis_date": "2025-09-15",
                "appointment_id": None,
                "doctor_id": 1,
                "vital_bp": "120/80",
                "vital_hr": "72",
                "vital_temp": "98.6",
                "vital_spo2": "99",
                "weight": "70.5",
                "height": "175",
                "chief_complaint": "Chest pain and shortness of breath",
                "assessment_notes": "Patient presents with mild chest discomfort, likely muscular strain",
                "treatment_plan": "Rest, pain medication as needed, follow-up in 1 week",
                "recomm_tests": "ECG, Complete Blood Count, Chest X-ray",
                "followup_date": "2025-09-22"
            }
        }

# Helper function to convert SQLAlchemy model to dict
def diagnosis_to_dict(diagnosis) -> Dict[str, Any]:
    """Convert PatientDiagnosis object to dictionary for JSON response"""
    return {
        "diagnosis_id": diagnosis.diagnosis_id,
        "facility_id": diagnosis.facility_id,
        "patient_id": diagnosis.patient_id,
        "diagnosis_date": diagnosis.DATE.isoformat() if diagnosis.DATE else None,
        "appointment_id": diagnosis.appointment_id,
        "doctor_id": diagnosis.doctor_id,
        "vital_bp": diagnosis.VITAL_BP,
        "vital_hr": diagnosis.VITAL_HR,
        "vital_temp": diagnosis.VITAL_TEMP,
        "vital_spo2": diagnosis.VITAL_SPO2,
        "weight": diagnosis.weight,
        "height": diagnosis.height,
        "chief_complaint": diagnosis.CHIEF_COMPLAINT,
        "assessment_notes": diagnosis.ASSESSMENT_NOTES,
        "treatment_plan": diagnosis.TREATMENT_PLAN,
        "recomm_tests": diagnosis.RECOMM_TESTS,
        "followup_date": diagnosis.FOLLOWUP_DATE.isoformat() if diagnosis.FOLLOWUP_DATE else None
    }

# Utility function for success responses (same pattern as doctor.py)
def successful_response(status_code: int, message: str = "Operation successful"):
    return {
        "status_code": status_code,
        "message": message
    }

# API Endpoints
@router.put("/", tags=["patient-diagnosis"])
async def create_or_update_patient_diagnosis(
    diagnosis_data: PatientDiagnosisCreate,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Create or update a patient diagnosis record.
    
    If diagnosis_id is null: Creates a new diagnosis record
    If diagnosis_id is provided: Updates the existing diagnosis record
    
    All required fields must be provided:
    - facility_id: ID of the facility (required)
    - patient_id: ID of the patient (required)
    - diagnosis_date: Date of diagnosis (required)
    - doctor_id: ID of the doctor making the diagnosis (required)
    
    Returns: JSON object with success message and created/updated record
    """
    try:
        # Verify user belongs to the same facility
        if diagnosis_data.facility_id != current_user.facility_id:
            raise HTTPException(status_code=403, detail="You can only access data from your facility")
        
        # Validate that the facility exists
        if diagnosis_data.facility_id:
            facility = db.query(model.Facility).filter(
                model.Facility.facility_id == diagnosis_data.facility_id
            ).first()
            if not facility:
                raise HTTPException(status_code=400, detail="Facility not found")
        
        # Validate that the patient exists
        patient = db.query(model.Patients).filter(
            model.Patients.id == diagnosis_data.patient_id
        ).first()
        if not patient:
            raise HTTPException(status_code=400, detail="Patient not found")
        
        # Validate that the doctor exists
        doctor = db.query(model.Doctors).filter(
            model.Doctors.id == diagnosis_data.doctor_id,
            model.Doctors.is_deleted == False,
            model.Doctors.is_active == True
        ).first()
        if not doctor:
            raise HTTPException(status_code=400, detail="Active doctor not found")
        
        # Validate appointment if provided
        if diagnosis_data.appointment_id:
            appointment = db.query(model.Appointment).filter(
                model.Appointment.appointment_id == diagnosis_data.appointment_id
            ).first()
            if not appointment:
                raise HTTPException(status_code=400, detail="Appointment not found")
        
        # Check if this is an update or create operation
        if diagnosis_data.diagnosis_id is not None:
            # UPDATE existing diagnosis
            existing_diagnosis = db.query(model.PatientDiagnosis).filter(
                model.PatientDiagnosis.diagnosis_id == diagnosis_data.diagnosis_id
            ).first()
            
            if not existing_diagnosis:
                raise HTTPException(status_code=404, detail="Diagnosis record not found")
            
            # Update fields
            existing_diagnosis.facility_id = diagnosis_data.facility_id
            existing_diagnosis.patient_id = diagnosis_data.patient_id
            existing_diagnosis.DATE = diagnosis_data.diagnosis_date
            existing_diagnosis.appointment_id = diagnosis_data.appointment_id
            existing_diagnosis.doctor_id = diagnosis_data.doctor_id
            existing_diagnosis.VITAL_BP = diagnosis_data.vital_bp
            existing_diagnosis.VITAL_HR = diagnosis_data.vital_hr
            existing_diagnosis.VITAL_TEMP = diagnosis_data.vital_temp
            existing_diagnosis.VITAL_SPO2 = diagnosis_data.vital_spo2
            existing_diagnosis.weight = diagnosis_data.weight
            existing_diagnosis.height = diagnosis_data.height
            existing_diagnosis.CHIEF_COMPLAINT = diagnosis_data.chief_complaint
            existing_diagnosis.ASSESSMENT_NOTES = diagnosis_data.assessment_notes
            existing_diagnosis.TREATMENT_PLAN = diagnosis_data.treatment_plan
            existing_diagnosis.RECOMM_TESTS = diagnosis_data.recomm_tests
            existing_diagnosis.FOLLOWUP_DATE = diagnosis_data.followup_date
            
            db.commit()
            db.refresh(existing_diagnosis)
            
            return {
                "status_code": 200,
                "message": "Patient diagnosis updated successfully",
                "data": diagnosis_to_dict(existing_diagnosis)
            }
        else:
            # CREATE new diagnosis
            diagnosis_dict = {
                "facility_id": diagnosis_data.facility_id,
                "patient_id": diagnosis_data.patient_id,
                "DATE": diagnosis_data.diagnosis_date,
                "appointment_id": diagnosis_data.appointment_id,
                "doctor_id": diagnosis_data.doctor_id,
                "VITAL_BP": diagnosis_data.vital_bp,
                "VITAL_HR": diagnosis_data.vital_hr,
                "VITAL_TEMP": diagnosis_data.vital_temp,
                "VITAL_SPO2": diagnosis_data.vital_spo2,
                "weight": diagnosis_data.weight,
                "height": diagnosis_data.height,
                "CHIEF_COMPLAINT": diagnosis_data.chief_complaint,
                "ASSESSMENT_NOTES": diagnosis_data.assessment_notes,
                "TREATMENT_PLAN": diagnosis_data.treatment_plan,
                "RECOMM_TESTS": diagnosis_data.recomm_tests,
                "FOLLOWUP_DATE": diagnosis_data.followup_date
            }
            
            new_diagnosis = model.PatientDiagnosis(**diagnosis_dict)
            
            db.add(new_diagnosis)
            db.commit()
            db.refresh(new_diagnosis)
            
            return {
                "status_code": 201,
                "message": "Patient diagnosis created successfully",
                "data": diagnosis_to_dict(new_diagnosis)
            }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error creating/updating diagnosis: {str(e)}")

@router.get("/", tags=["patient-diagnosis"])
async def get_patient_diagnosis(
    facility_id: int = Query(..., description="Facility ID (mandatory)"),
    patient_id: int = Query(..., description="Patient ID (mandatory)"),
    doctor_id: Optional[int] = Query(None, description="Doctor ID (optional)"),
    diagnosis_date: Optional[date] = Query(None, description="Diagnosis date (optional)"),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> List[Dict[str, Any]]:
    """
    Get patient diagnoses with filtering.
    
    Mandatory parameters:
    - facility_id: Filter by facility ID
    - patient_id: Filter by patient ID
    
    Optional parameters:
    - doctor_id: Filter by doctor ID
    - diagnosis_date: Filter by specific diagnosis date
    
    Returns: JSON array of diagnosis records
    """
    try:
        # Verify user belongs to the same facility
        if facility_id != current_user.facility_id:
            raise HTTPException(status_code=403, detail="You can only access data from your facility")
        
        # Start with mandatory filters
        query = db.query(model.PatientDiagnosis).filter(
            and_(
                model.PatientDiagnosis.facility_id == facility_id,
                model.PatientDiagnosis.patient_id == patient_id
            )
        )
        
        # Apply optional filters
        if doctor_id is not None:
            query = query.filter(model.PatientDiagnosis.doctor_id == doctor_id)
        
        if diagnosis_date is not None:
            query = query.filter(model.PatientDiagnosis.DATE == diagnosis_date)
        
        # Order by date (most recent first)
        query = query.order_by(model.PatientDiagnosis.DATE.desc())
        
        # Execute query and get results
        diagnoses = query.all()
        
        # Convert to list of dictionaries for JSON array response
        result = [diagnosis_to_dict(diagnosis) for diagnosis in diagnoses]
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving diagnoses: {str(e)}")