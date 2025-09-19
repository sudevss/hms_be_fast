from typing import List, Optional, Dict, Any
from datetime import date
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from fastapi import HTTPException, APIRouter, Depends, Query
from sqlalchemy import and_

# Import your existing database setup and models (same as doctor.py)
import model
from database import engine, SessionLocal

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
    FACILITY_ID: int = Field(..., description="Facility ID where diagnosis was made")
    PATIENT_ID: int = Field(..., description="Patient ID")
    DATE: date = Field(..., description="Diagnosis date")
    APPOINTMENT_ID: Optional[int] = Field(None, description="Associated appointment ID")
    DOCTOR_ID: int = Field(..., description="Doctor ID who made the diagnosis")
    VITAL_BP: Optional[str] = Field(None, max_length=50, description="Blood pressure reading")
    VITAL_HR: Optional[str] = Field(None, max_length=50, description="Heart rate")
    VITAL_TEMP: Optional[str] = Field(None, max_length=50, description="Temperature")
    VITAL_SPO2: Optional[str] = Field(None, max_length=50, description="Blood oxygen saturation")
    CHIEF_COMPLAINT: Optional[str] = Field(None, description="Patient's chief complaint")
    ASSESSMENT_NOTES: Optional[str] = Field(None, description="Doctor's assessment notes")
    TREATMENT_PLAN: Optional[str] = Field(None, description="Prescribed treatment plan")
    RECOMM_TESTS: Optional[str] = Field(None, description="Recommended tests")
    FOLLOWUP_DATE: Optional[date] = Field(None, description="Follow-up appointment date")

    class Config:
        json_encoders = {
            date: lambda v: v.isoformat() if v else None
        }
        json_schema_extra = {
            "example": {
                "FACILITY_ID": 0,
                "PATIENT_ID": 0,
                "DATE": "2025-09-15",
                "APPOINTMENT_ID": 0,
                "DOCTOR_ID": 0,
                "VITAL_BP": "120/80",
                "VITAL_HR": "72",
                "VITAL_TEMP": "98.6",
                "VITAL_SPO2": "99",
                "CHIEF_COMPLAINT": "Chest pain and shortness of breath",
                "ASSESSMENT_NOTES": "Patient presents with mild chest discomfort, likely muscular strain",
                "TREATMENT_PLAN": "Rest, pain medication as needed, follow-up in 1 week",
                "RECOMM_TESTS": "ECG, Complete Blood Count, Chest X-ray",
                "FOLLOWUP_DATE": "2025-09-22"
            }
        }

# Helper function to convert SQLAlchemy model to dict
def diagnosis_to_dict(diagnosis) -> Dict[str, Any]:
    """Convert PatientDiagnosis object to dictionary for JSON response"""
    return {
        "DIAGNOSIS_ID": diagnosis.DIAGNOSIS_ID,
        "FACILITY_ID": diagnosis.FACILITY_ID,
        "PATIENT_ID": diagnosis.PATIENT_ID,
        "DATE": diagnosis.DATE.isoformat() if diagnosis.DATE else None,
        "APPOINTMENT_ID": diagnosis.APPOINTMENT_ID,
        "DOCTOR_ID": diagnosis.DOCTOR_ID,
        "VITAL_BP": diagnosis.VITAL_BP,
        "VITAL_HR": diagnosis.VITAL_HR,
        "VITAL_TEMP": diagnosis.VITAL_TEMP,
        "VITAL_SPO2": diagnosis.VITAL_SPO2,
        "CHIEF_COMPLAINT": diagnosis.CHIEF_COMPLAINT,
        "ASSESSMENT_NOTES": diagnosis.ASSESSMENT_NOTES,
        "TREATMENT_PLAN": diagnosis.TREATMENT_PLAN,
        "RECOMM_TESTS": diagnosis.RECOMM_TESTS,
        "FOLLOWUP_DATE": diagnosis.FOLLOWUP_DATE.isoformat() if diagnosis.FOLLOWUP_DATE else None
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
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Create or update a patient diagnosis record.
    
    All required fields must be provided:
    - FACILITY_ID: ID of the facility (required)
    - PATIENT_ID: ID of the patient (required)
    - DATE: Date of diagnosis (required)
    - DOCTOR_ID: ID of the doctor making the diagnosis (required)
    
    Returns: JSON object with success message and created/updated record
    """
    try:
        # Validate that the facility exists
        if diagnosis_data.FACILITY_ID:
            facility = db.query(model.Facility).filter(
                model.Facility.FacilityID == diagnosis_data.FACILITY_ID
            ).first()
            if not facility:
                raise HTTPException(status_code=400, detail="Facility not found")
        
        # Validate that the patient exists
        patient = db.query(model.Patients).filter(
            model.Patients.id == diagnosis_data.PATIENT_ID
        ).first()
        if not patient:
            raise HTTPException(status_code=400, detail="Patient not found")
        
        # Validate that the doctor exists
        doctor = db.query(model.Doctors).filter(
            model.Doctors.id == diagnosis_data.DOCTOR_ID,
            model.Doctors.is_deleted == False,
            model.Doctors.is_active == True
        ).first()
        if not doctor:
            raise HTTPException(status_code=400, detail="Active doctor not found")
        
        # Validate appointment if provided
        if diagnosis_data.APPOINTMENT_ID:
            appointment = db.query(model.Appointment).filter(
                model.Appointment.AppointmentID == diagnosis_data.APPOINTMENT_ID
            ).first()
            if not appointment:
                raise HTTPException(status_code=400, detail="Appointment not found")
        
        # Create new diagnosis record
        new_diagnosis = model.PatientDiagnosis(**diagnosis_data.dict())
        
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
    date: Optional[date] = Query(None, description="Diagnosis date (optional)"),
    diagnosis_id: Optional[int] = Query(None, description="Diagnosis ID (optional)"),
    db: Session = Depends(get_db)
) -> List[Dict[str, Any]]:
    """
    Get patient diagnoses with filtering.
    
    Mandatory parameters:
    - facility_id: Filter by facility ID
    - patient_id: Filter by patient ID
    
    Optional parameters:
    - doctor_id: Filter by doctor ID
    - date: Filter by specific diagnosis date
    - diagnosis_id: Filter by specific diagnosis ID
    
    Returns: JSON array of diagnosis records
    """
    try:
        # Start with mandatory filters
        query = db.query(model.PatientDiagnosis).filter(
            and_(
                model.PatientDiagnosis.FACILITY_ID == facility_id,
                model.PatientDiagnosis.PATIENT_ID == patient_id
            )
        )
        
        # Apply optional filters
        if doctor_id is not None:
            query = query.filter(model.PatientDiagnosis.DOCTOR_ID == doctor_id)
        
        if date is not None:
            query = query.filter(model.PatientDiagnosis.DATE == date)
        
        if diagnosis_id is not None:
            query = query.filter(model.PatientDiagnosis.DIAGNOSIS_ID == diagnosis_id)
        
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