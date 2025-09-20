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
    facility_id: int = Field(..., description="Facility ID where diagnosis was made")
    patient_id: int = Field(..., description="Patient ID")
    diagnosis_date: date = Field(..., description="Diagnosis date")
    appointment_id: Optional[int] = Field(None, description="Associated appointment ID")
    doctor_id: int = Field(..., description="Doctor ID who made the diagnosis")
    vital_bp: Optional[str] = Field(None, max_length=50, description="Blood pressure reading")
    vital_hr: Optional[str] = Field(None, max_length=50, description="Heart rate")
    vital_temp: Optional[str] = Field(None, max_length=50, description="Temperature")
    vital_spo2: Optional[str] = Field(None, max_length=50, description="Blood oxygen saturation")
    chief_complaint: Optional[str] = Field(None, description="Patient's chief complaint")
    assessment_notes: Optional[str] = Field(None, description="Doctor's assessment notes")
    treatment_plan: Optional[str] = Field(None, description="Prescribed treatment plan")
    recomm_tests: Optional[str] = Field(None, description="Recommended tests")
    followup_date: Optional[date] = Field(None, description="Follow-up appointment date")

    class Config:
        json_encoders = {
            date: lambda v: v.isoformat() if v else None
        }
        json_schema_extra = {
            "example": {
                "facility_id": 0,
                "patient_id": 0,
                "diagnosis_date": "2025-09-15",
                "appointment_id": 0,
                "doctor_id": 0,
                "vital_bp": "120/80",
                "vital_hr": "72",
                "vital_temp": "98.6",
                "vital_spo2": "99",
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
        "diagnosis_id": diagnosis.DIAGNOSIS_ID,
        "facility_id": diagnosis.FACILITY_ID,
        "patient_id": diagnosis.PATIENT_ID,
        "diagnosis_date": diagnosis.DATE.isoformat() if diagnosis.DATE else None,
        "appointment_id": diagnosis.APPOINTMENT_ID,
        "doctor_id": diagnosis.DOCTOR_ID,
        "vital_bp": diagnosis.VITAL_BP,
        "vital_hr": diagnosis.VITAL_HR,
        "vital_temp": diagnosis.VITAL_TEMP,
        "vital_spo2": diagnosis.VITAL_SPO2,
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
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Create or update a patient diagnosis record.
    
    All required fields must be provided:
    - facility_id: ID of the facility (required)
    - patient_id: ID of the patient (required)
    - diagnosis_date: Date of diagnosis (required)
    - doctor_id: ID of the doctor making the diagnosis (required)
    
    Returns: JSON object with success message and created/updated record
    """
    try:
        # Validate that the facility exists
        if diagnosis_data.facility_id:
            facility = db.query(model.Facility).filter(
                model.Facility.FacilityID == diagnosis_data.facility_id
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
                model.Appointment.AppointmentID == diagnosis_data.appointment_id
            ).first()
            if not appointment:
                raise HTTPException(status_code=400, detail="Appointment not found")
        
        # Convert lowercase field names to uppercase for database model
        diagnosis_dict = {
            "FACILITY_ID": diagnosis_data.facility_id,
            "PATIENT_ID": diagnosis_data.patient_id,
            "DATE": diagnosis_data.diagnosis_date,
            "APPOINTMENT_ID": diagnosis_data.appointment_id,
            "DOCTOR_ID": diagnosis_data.doctor_id,
            "VITAL_BP": diagnosis_data.vital_bp,
            "VITAL_HR": diagnosis_data.vital_hr,
            "VITAL_TEMP": diagnosis_data.vital_temp,
            "VITAL_SPO2": diagnosis_data.vital_spo2,
            "CHIEF_COMPLAINT": diagnosis_data.chief_complaint,
            "ASSESSMENT_NOTES": diagnosis_data.assessment_notes,
            "TREATMENT_PLAN": diagnosis_data.treatment_plan,
            "RECOMM_TESTS": diagnosis_data.recomm_tests,
            "FOLLOWUP_DATE": diagnosis_data.followup_date
        }
        
        # Create new diagnosis record
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
    - diagnosis_date: Filter by specific diagnosis date
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
        
        if diagnosis_date is not None:
            query = query.filter(model.PatientDiagnosis.DATE == diagnosis_date)
        
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