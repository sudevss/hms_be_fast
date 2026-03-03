from typing import List, Optional, Dict, Any
from datetime import date, datetime
from pydantic import BaseModel, Field, field_validator,model_validator
from sqlalchemy.orm import Session, joinedload
from fastapi import HTTPException, APIRouter, Depends, Query
from sqlalchemy import and_, desc

import model
from database import SessionLocal
from auth_middleware import get_current_user, CurrentUser

router = APIRouter(
    prefix="/patient_diagnosis",
    tags=["patient-diagnosis"],
    responses={404: {"description": "Not found"}}
)

def get_db():
    try:
        db = SessionLocal()
        yield db
    finally:
        db.close()

# ==================== HELPER FUNCTIONS ====================

def get_effective_facility_id(current_user: CurrentUser, requested_facility_id: Optional[int] = None) -> int:
    """
    Determine the effective facility_id based on user role.
    - Super Admin: Can use requested_facility_id if provided, otherwise use token facility_id
    - Regular User: Always use token facility_id (ignore requested_facility_id)
    """
    if current_user.is_super_admin:
        return requested_facility_id if requested_facility_id is not None else current_user.facility_id
    else:
        return current_user.facility_id

# ==================== PYDANTIC MODELS ====================

class DiagnosisSymptomItem(BaseModel):
    symptom_id: Optional[int] = None          # ← now optional
    free_text_symptom: Optional[str] = Field(None, max_length=255)  # ← new
    duration_days: Optional[int] = Field(None, gt=0)
    remarks: Optional[str] = None

    @field_validator('symptom_id', 'duration_days')
    @classmethod
    def convert_zero_to_none(cls, v):
        if v == 0:
            return None
        return v

    @model_validator(mode='after')
    def validate_symptom_source(self):
        if not self.symptom_id and not self.free_text_symptom:
            raise ValueError("Either symptom_id or free_text_symptom must be provided")
        return self

class DiagnosisPrescriptionItem(BaseModel):
    medicine_id: int
    morning_dosage: Optional[str] = Field(None, max_length=50)
    afternoon_dosage: Optional[str] = Field(None, max_length=50)
    night_dosage: Optional[str] = Field(None, max_length=50)
    food_timing: Optional[str] = Field(None, max_length=50)
    duration_days: Optional[int] = Field(None, gt=0)
    special_instructions: Optional[str] = None

class DiagnosisLabTestItem(BaseModel):
    test_id: int
    prerequisite_text: Optional[str] = None

class DiagnosisProcedureItem(BaseModel):
    procedure_text: str = Field(..., min_length=5)
    price: Optional[float] = Field(None, ge=0)

class PatientDiagnosisCreate(BaseModel):
    """Request model for creating/updating patient diagnosis"""
    diagnosis_id: Optional[int] = Field(None, description="Diagnosis ID for update, null for create")
    facility_id: Optional[int] = Field(None, description="Facility ID where diagnosis was made (optional, uses token facility_id if not provided)")
    patient_id: int = Field(..., description="Patient ID")
    diagnosis_date: date = Field(..., description="Diagnosis date")
    appointment_id: Optional[int] = Field(None, description="Associated appointment ID")
    doctor_id: int = Field(..., description="Doctor ID who made the diagnosis")
    
    # Vitals
    vital_bp: Optional[str] = Field(None, max_length=50, description="Blood pressure reading")
    vital_hr: Optional[str] = Field(None, max_length=50, description="Heart rate")
    vital_temp: Optional[str] = Field(None, max_length=50, description="Temperature")
    vital_spo2: Optional[str] = Field(None, max_length=50, description="Blood oxygen saturation")
    weight: Optional[str] = Field(None, max_length=50, description="Patient weight")
    height: Optional[str] = Field(None, max_length=50, description="Patient height")
    
    # Chief complaint and template
    chief_complaint: Optional[str] = Field(None, description="Patient's chief complaint")
    template_id: Optional[int] = Field(None, description="Template ID if using a template")
    
    # Follow-up
    followup_date: Optional[date] = Field(None, description="Follow-up appointment date")
    
    # Detailed diagnosis data
    symptoms: List[DiagnosisSymptomItem] = Field(default=[], description="List of symptoms")
    prescriptions: List[DiagnosisPrescriptionItem] = Field(default=[], description="List of prescriptions")
    lab_tests: List[DiagnosisLabTestItem] = Field(default=[], description="List of lab tests")
    procedures: List[DiagnosisProcedureItem] = Field(default=[], description="List of procedures")

    @field_validator('appointment_id', 'diagnosis_id', 'template_id', 'facility_id')
    @classmethod
    def validate_optional_ids(cls, v):
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
                "facility_id": None,
                "patient_id": 0,
                "diagnosis_date": "2025-11-29",
                "appointment_id": None,
                "doctor_id": 0,
                "vital_bp": "",
                "vital_hr": "",
                "vital_temp": "",
                "vital_spo2": "",
                "weight": "",
                "height": "",
                "chief_complaint": "",
                "template_id": 0,
                "followup_date": "2025-12-06",
                "symptoms": [
                    {
                    "symptom_id": 1,
                    "free_text_symptom": None,
                    "duration_days": 3,
                    "remarks": "High fever"
                },
                {
                    "symptom_id": None,
                    "free_text_symptom": "Burning sensation in chest",
                    "duration_days": 2,
                    "remarks": "Started yesterday"
                }
                ],
                "prescriptions": [
                    {
                        "medicine_id": 0,
                        "morning_dosage": "0",
                        "afternoon_dosage": "0",
                        "night_dosage": "0",
                        "food_timing": "",
                        "duration_days": 0
                    }
                ],
                "lab_tests": [
                    {"test_id": 0, "prerequisite_text": "Fasting required"}
                ],
                "procedures": [
                    {"procedure_text": "Blood pressure monitoring", "price": 50.0}
                ]
            }
        }
        

class LoadTemplateRequest(BaseModel):
    """Request to load template data for a diagnosis"""
    template_id: int

# ==================== HELPER FUNCTIONS ====================

def diagnosis_to_dict(diagnosis, include_details: bool = True) -> Dict[str, Any]:
    """Convert PatientDiagnosis object to dictionary"""
    result = {
        "diagnosis_id": diagnosis.diagnosis_id,
        "facility_id": diagnosis.facility_id,
        "patient_id": diagnosis.patient_id,
        "diagnosis_date": diagnosis.date.isoformat() if diagnosis.date else None,
        "appointment_id": diagnosis.appointment_id,
        "doctor_id": diagnosis.doctor_id,
        "vital_bp": diagnosis.vital_bp,
        "vital_hr": diagnosis.vital_hr,
        "vital_temp": diagnosis.vital_temp,
        "vital_spo2": diagnosis.vital_spo2,
        "weight": diagnosis.weight,
        "height": diagnosis.height,
        "chief_complaint": diagnosis.chief_complaint,
        "template_id": diagnosis.template_id,
        "followup_date": diagnosis.followup_date.isoformat() if diagnosis.followup_date else None
    }
    
    if include_details:
        result["symptoms"] = [{
            "patient_symptom_id": s.patient_symptom_id,
            "symptom_id": s.symptom_id,
            "symptom_name": s.symptom.symptom_name if s.symptom else None,
            "free_text_symptom": s.free_text_symptom,  # ← new
            "duration_days": s.duration_days,
            "remarks": s.remarks
        } for s in diagnosis.symptoms]
        
        result["prescriptions"] = [{
            "prescription_id": p.prescription_id,
            "medicine_id": p.medicine_id,
            "medicine_name": p.medicine.medicine_name if p.medicine else None,
            "generic_name": p.medicine.generic_name if p.medicine else None,
            "strength": p.medicine.strength if p.medicine else None,
            "morning_dosage": p.morning_dosage,
            "afternoon_dosage": p.afternoon_dosage,
            "night_dosage": p.night_dosage,
            "food_timing": p.food_timing,
            "duration_days": p.duration_days,
            "special_instructions": p.special_instructions
        } for p in diagnosis.prescriptions]
        
        result["lab_tests"] = [{
            "lab_test_id": lt.lab_test_id,
            "test_id": lt.test_id,
            "test_name": lt.test.test_name if lt.test else None,
            "prerequisite_text": lt.prerequisite_text,
            "price": lt.test.price if lt.test else None
        } for lt in diagnosis.lab_tests]
        
        result["procedures"] = [{
            "procedure_id": proc.procedure_id,
            "procedure_text": proc.procedure_text,
            "price": proc.price
        } for proc in diagnosis.procedures]
    
    return result

# ==================== API ENDPOINTS ====================

@router.post("/load-template", tags=["patient-diagnosis"])
async def load_template(
    request: LoadTemplateRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Load template data to populate diagnosis form.
    Returns symptoms, prescriptions, and lab tests from the template.
    Doctor can then modify before saving.
    """
    try:
        # Use facility_id from token
        effective_facility_id = current_user.facility_id
        
        template = db.query(model.Template).options(
            joinedload(model.Template.symptoms).joinedload(model.SymptomTemplate.symptom),
            joinedload(model.Template.prescriptions).joinedload(model.PrescriptionTemplate.medicine),
            joinedload(model.Template.lab_tests).joinedload(model.LabTemplate.test)
        ).filter(
            model.Template.template_id == request.template_id,
            model.Template.facility_id == effective_facility_id,
            model.Template.is_active == True,
            model.Template.is_deleted == False
        ).first()
        
        if not template:
            raise HTTPException(status_code=404, detail="Template not found or inactive")
        
        return {
            "status_code": 200,
            "message": "Template loaded successfully",
            "data": {
                "template_id": template.template_id,
                "template_name": template.template_name,
                "template_type": template.template_type,
                "symptoms": [{
                    "symptom_id": st.symptom_id,
                    "symptom_name": st.symptom.symptom_name,
                    "duration_days": st.default_duration_days,
                    "remarks": st.default_remarks
                } for st in template.symptoms],
                "prescriptions": [{
                    "medicine_id": pt.medicine_id,
                    "medicine_name": pt.medicine.medicine_name,
                    "generic_name": pt.medicine.generic_name,
                    "strength": pt.medicine.strength,
                    "morning_dosage": pt.morning_dosage,
                    "afternoon_dosage": pt.afternoon_dosage,
                    "night_dosage": pt.night_dosage,
                    "food_timing": pt.food_timing,
                    "duration_days": pt.duration_days,
                    "special_instructions": pt.special_instructions
                } for pt in template.prescriptions],
                "lab_tests": [{
                    "test_id": lt.test_id,
                    "test_name": lt.test.test_name,
                    "prerequisite_text": lt.test.prerequisite_text
                } for lt in template.lab_tests]
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error loading template: {str(e)}")

@router.put("/", tags=["patient-diagnosis"])
async def create_or_update_patient_diagnosis(
    diagnosis_data: PatientDiagnosisCreate,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Create or update a patient diagnosis record with all related data.
    
    If diagnosis_id is null: Creates new diagnosis
    If diagnosis_id is provided: Updates existing diagnosis
    
    This endpoint handles:
    - Basic diagnosis info (vitals, chief complaint, etc.)
    - Symptoms
    - Prescriptions
    - Lab tests
    - Procedures
    
    facility_id behavior:
    - Regular users: Always uses token facility_id (ignores provided facility_id)
    - Super admin: Uses provided facility_id if given, otherwise uses token facility_id
    """
    try:
        # Determine effective facility_id based on user role
        effective_facility_id = get_effective_facility_id(current_user, diagnosis_data.facility_id)
        
        # Validate facility
        facility = db.query(model.Facility).filter(
            model.Facility.facility_id == effective_facility_id
        ).first()
        if not facility:
            raise HTTPException(status_code=400, detail="Facility not found")
        
        # Validate patient
        patient = db.query(model.Patients).filter(
            model.Patients.id == diagnosis_data.patient_id
        ).first()
        if not patient:
            raise HTTPException(status_code=400, detail="Patient not found")
        
        # Validate doctor
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
        
        # Validate template if provided
        if diagnosis_data.template_id:
            template = db.query(model.Template).filter(
                model.Template.template_id == diagnosis_data.template_id,
                model.Template.is_deleted == False,
                model.Template.is_active == True
            ).first()
            if not template:
                raise HTTPException(status_code=400, detail="Template not found or inactive")
        
        # Validate followup_date is after diagnosis_date
        if diagnosis_data.followup_date and diagnosis_data.followup_date <= diagnosis_data.diagnosis_date:
            raise HTTPException(status_code=400, detail="Follow-up date must be after diagnosis date")
        
        # Check if this is UPDATE or CREATE
        if diagnosis_data.diagnosis_id is not None:
            # UPDATE EXISTING DIAGNOSIS
            existing_diagnosis = db.query(model.PatientDiagnosis).filter(
                model.PatientDiagnosis.diagnosis_id == diagnosis_data.diagnosis_id
            ).first()
            
            if not existing_diagnosis:
                raise HTTPException(status_code=404, detail="Diagnosis record not found")
            
            # Super admin can access any facility, regular users only their own
            if not current_user.is_super_admin and existing_diagnosis.facility_id != current_user.facility_id:
                raise HTTPException(status_code=403, detail="You can only update data from your facility")
            
            # Update basic fields
            existing_diagnosis.facility_id = effective_facility_id
            existing_diagnosis.patient_id = diagnosis_data.patient_id
            existing_diagnosis.date = diagnosis_data.diagnosis_date
            existing_diagnosis.appointment_id = diagnosis_data.appointment_id
            existing_diagnosis.doctor_id = diagnosis_data.doctor_id
            existing_diagnosis.vital_bp = diagnosis_data.vital_bp
            existing_diagnosis.vital_hr = diagnosis_data.vital_hr
            existing_diagnosis.vital_temp = diagnosis_data.vital_temp
            existing_diagnosis.vital_spo2 = diagnosis_data.vital_spo2
            existing_diagnosis.weight = diagnosis_data.weight
            existing_diagnosis.height = diagnosis_data.height
            existing_diagnosis.chief_complaint = diagnosis_data.chief_complaint
            existing_diagnosis.template_id = diagnosis_data.template_id
            existing_diagnosis.followup_date = diagnosis_data.followup_date
            existing_diagnosis.updated_by = current_user.user_id
            
            # Delete existing related data
            db.query(model.DiagnosisSymptoms).filter(
                model.DiagnosisSymptoms.diagnosis_id == diagnosis_data.diagnosis_id
            ).delete()
            db.query(model.DiagnosisPrescription).filter(
                model.DiagnosisPrescription.diagnosis_id == diagnosis_data.diagnosis_id
            ).delete()
            db.query(model.DiagnosisLabTests).filter(
                model.DiagnosisLabTests.diagnosis_id == diagnosis_data.diagnosis_id
            ).delete()
            db.query(model.DiagnosisProcedures).filter(
                model.DiagnosisProcedures.diagnosis_id == diagnosis_data.diagnosis_id
            ).delete()
            
            diagnosis_id = existing_diagnosis.diagnosis_id
            message = "Patient diagnosis updated successfully"
            status_code = 200
            
        else:
            # CREATE NEW DIAGNOSIS
            new_diagnosis = model.PatientDiagnosis(
                facility_id=effective_facility_id,
                patient_id=diagnosis_data.patient_id,
                date=diagnosis_data.diagnosis_date,
                appointment_id=diagnosis_data.appointment_id,
                doctor_id=diagnosis_data.doctor_id,
                vital_bp=diagnosis_data.vital_bp,
                vital_hr=diagnosis_data.vital_hr,
                vital_temp=diagnosis_data.vital_temp,
                vital_spo2=diagnosis_data.vital_spo2,
                weight=diagnosis_data.weight,
                height=diagnosis_data.height,
                chief_complaint=diagnosis_data.chief_complaint,
                template_id=diagnosis_data.template_id,
                followup_date=diagnosis_data.followup_date,
                created_by=current_user.user_id
            )
            
            db.add(new_diagnosis)
            db.flush()  # Get diagnosis_id
            diagnosis_id = new_diagnosis.diagnosis_id
            message = "Patient diagnosis created successfully"
            status_code = 201
        
        # Add symptoms
        for symptom_item in diagnosis_data.symptoms:
            diagnosis_symptom = model.DiagnosisSymptoms(
                facility_id=effective_facility_id,
                diagnosis_id=diagnosis_id,
                symptom_id=symptom_item.symptom_id,
                free_text_symptom=symptom_item.free_text_symptom,
                duration_days=symptom_item.duration_days,
                remarks=symptom_item.remarks,
                created_by=current_user.user_id
            )
            db.add(diagnosis_symptom)
        
        # Add prescriptions
        for prescription_item in diagnosis_data.prescriptions:
            diagnosis_prescription = model.DiagnosisPrescription(
                facility_id=effective_facility_id,
                diagnosis_id=diagnosis_id,
                medicine_id=prescription_item.medicine_id,
                morning_dosage=prescription_item.morning_dosage,
                afternoon_dosage=prescription_item.afternoon_dosage,
                night_dosage=prescription_item.night_dosage,
                food_timing=prescription_item.food_timing,
                duration_days=prescription_item.duration_days,
                special_instructions=prescription_item.special_instructions,
                created_by=current_user.user_id
            )
            db.add(diagnosis_prescription)
        
        # Add lab tests
        for lab_test_item in diagnosis_data.lab_tests:
            diagnosis_lab_test = model.DiagnosisLabTests(
                facility_id=effective_facility_id,
                diagnosis_id=diagnosis_id,
                test_id=lab_test_item.test_id,
                prerequisite_text=lab_test_item.prerequisite_text,
                created_by=current_user.user_id
            )
            db.add(diagnosis_lab_test)
        
        # Add procedures
        for procedure_item in diagnosis_data.procedures:
            diagnosis_procedure = model.DiagnosisProcedures(
                facility_id=effective_facility_id,
                diagnosis_id=diagnosis_id,
                procedure_text=procedure_item.procedure_text,
                price=procedure_item.price,
                created_by=current_user.user_id
            )
            db.add(diagnosis_procedure)
        
        db.commit()
        
        # Fetch complete diagnosis with all relationships
        complete_diagnosis = db.query(model.PatientDiagnosis).options(
            joinedload(model.PatientDiagnosis.symptoms).joinedload(model.DiagnosisSymptoms.symptom),
            joinedload(model.PatientDiagnosis.prescriptions).joinedload(model.DiagnosisPrescription.medicine),
            joinedload(model.PatientDiagnosis.lab_tests).joinedload(model.DiagnosisLabTests.test),
            joinedload(model.PatientDiagnosis.procedures)
        ).filter(model.PatientDiagnosis.diagnosis_id == diagnosis_id).first()
        
        return {
            "status_code": status_code,
            "message": message,
            "data": diagnosis_to_dict(complete_diagnosis, include_details=True)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error creating/updating diagnosis: {str(e)}")

@router.get("/", tags=["patient-diagnosis"])
async def get_patient_diagnosis(
    patient_id: int = Query(..., description="Patient ID (mandatory)"),
    facility_id: Optional[int] = Query(None, description="Facility ID (optional for super admin)"),
    doctor_id: Optional[int] = Query(None, description="Doctor ID (optional)"),
    diagnosis_date: Optional[date] = Query(None, description="Diagnosis date (optional)"),
    from_date: Optional[date] = Query(None, description="From date for range query"),
    to_date: Optional[date] = Query(None, description="To date for range query"),
    include_details: bool = Query(True, description="Include symptoms, prescriptions, lab tests"),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> List[Dict[str, Any]]:
    """
    Get patient diagnoses with filtering.
    
    Mandatory: patient_id
    Optional: facility_id (super admin only), doctor_id, diagnosis_date, date range, include_details
    """
    try:
        # Determine effective facility_id based on user role
        effective_facility_id = get_effective_facility_id(current_user, facility_id)
        
        # Build query with eager loading if details requested
        if include_details:
            query = db.query(model.PatientDiagnosis).options(
                joinedload(model.PatientDiagnosis.symptoms).joinedload(model.DiagnosisSymptoms.symptom),
                joinedload(model.PatientDiagnosis.prescriptions).joinedload(model.DiagnosisPrescription.medicine),
                joinedload(model.PatientDiagnosis.lab_tests).joinedload(model.DiagnosisLabTests.test),
                joinedload(model.PatientDiagnosis.procedures)
            )
        else:
            query = db.query(model.PatientDiagnosis)
        
        # Apply mandatory filters
        query = query.filter(
            and_(
                model.PatientDiagnosis.facility_id == effective_facility_id,
                model.PatientDiagnosis.patient_id == patient_id,
                model.PatientDiagnosis.is_deleted == False
            )
        )
        
        # Apply optional filters
        if doctor_id is not None:
            query = query.filter(model.PatientDiagnosis.doctor_id == doctor_id)
        
        if diagnosis_date is not None:
            query = query.filter(model.PatientDiagnosis.date == diagnosis_date)
        
        if from_date is not None:
            query = query.filter(model.PatientDiagnosis.date >= from_date)
        
        if to_date is not None:
            query = query.filter(model.PatientDiagnosis.date <= to_date)
        
        # Order by date (most recent first)
        query = query.order_by(desc(model.PatientDiagnosis.date))
        
        # Execute query
        diagnoses = query.all()
        
        # Convert to list of dictionaries
        result = [diagnosis_to_dict(diagnosis, include_details=include_details) for diagnosis in diagnoses]
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving diagnoses: {str(e)}")

@router.get("/{diagnosis_id}", tags=["patient-diagnosis"])
async def get_diagnosis_by_id(
    diagnosis_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """Get a specific diagnosis by ID with all related data"""
    try:
        diagnosis = db.query(model.PatientDiagnosis).options(
            joinedload(model.PatientDiagnosis.symptoms).joinedload(model.DiagnosisSymptoms.symptom),
            joinedload(model.PatientDiagnosis.prescriptions).joinedload(model.DiagnosisPrescription.medicine),
            joinedload(model.PatientDiagnosis.lab_tests).joinedload(model.DiagnosisLabTests.test),
            joinedload(model.PatientDiagnosis.procedures)
        ).filter(
            model.PatientDiagnosis.diagnosis_id == diagnosis_id,
            model.PatientDiagnosis.is_deleted == False
        ).first()
        
        if not diagnosis:
            raise HTTPException(status_code=404, detail="Diagnosis not found")
        
        # Super admin can access any facility, regular users only their own
        if not current_user.is_super_admin and diagnosis.facility_id != current_user.facility_id:
            raise HTTPException(status_code=403, detail="You can only access data from your facility")
        
        return diagnosis_to_dict(diagnosis, include_details=True)
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving diagnosis: {str(e)}")

@router.delete("/{diagnosis_id}", tags=["patient-diagnosis"])
async def delete_diagnosis(
    diagnosis_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Soft delete a diagnosis record"""
    try:
        diagnosis = db.query(model.PatientDiagnosis).filter(
            model.PatientDiagnosis.diagnosis_id == diagnosis_id,
            model.PatientDiagnosis.is_deleted == False
        ).first()
        
        if not diagnosis:
            raise HTTPException(status_code=404, detail="Diagnosis not found")
        
        # Super admin can access any facility, regular users only their own
        if not current_user.is_super_admin and diagnosis.facility_id != current_user.facility_id:
            raise HTTPException(status_code=403, detail="You can only access data from your facility")
        
        # Soft delete diagnosis
        diagnosis.is_deleted = True
        diagnosis.deleted_by = current_user.user_id
        diagnosis.deleted_at = datetime.now()
        db.commit()
        
        return {
            "status_code": 200,
            "message": "Diagnosis deleted successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error deleting diagnosis: {str(e)}")