from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session, joinedload
from fastapi import HTTPException, APIRouter, Depends, Query
from sqlalchemy import and_, or_
from datetime import datetime

import model
from database import SessionLocal
from auth_middleware import get_current_user, CurrentUser

router = APIRouter(
    prefix="/templates",
    responses={404: {"description": "Not found"}}
)

def get_db():
    try:
        db = SessionLocal()
        yield db
    finally:
        db.close()

def get_effective_facility_id(current_user: CurrentUser, facility_id: Optional[int] = None) -> int:
    """
    Determine the effective facility_id based on user role.
    For Super Admins: Use provided facility_id parameter if given, otherwise use token facility_id
    For Regular Users: Always use facility_id from token (ignore parameter)
    """
    if current_user.role == "Super Admin":
        return facility_id if facility_id is not None else current_user.facility_id
    else:
        return current_user.facility_id

# ==================== PYDANTIC MODELS ====================

class SymptomTemplateItem(BaseModel):
    symptom_id: int
    default_duration_days: Optional[int] = Field(None, gt=0)
    default_remarks: Optional[str] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "symptom_id": 1,
                "default_duration_days": 3,
                "default_remarks": "High fever above 100°F"
            }
        }

class PrescriptionTemplateItem(BaseModel):
    medicine_id: int
    morning_dosage: Optional[str] = None
    afternoon_dosage: Optional[str] = None
    night_dosage: Optional[str] = None
    food_timing: Optional[str] = None
    duration_days: Optional[int] = Field(None, gt=0)
    special_instructions: Optional[str] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "medicine_id": 1,
                "morning_dosage": "1",
                "afternoon_dosage": "0",
                "night_dosage": "1",
                "food_timing": "After Food",
                "duration_days": 5,
                "special_instructions": "Take with plenty of water"
            }
        }

class LabTemplateItem(BaseModel):
    test_id: int
    
    class Config:
        json_schema_extra = {
            "example": {
                "test_id": 1
            }
        }

class TemplateCreate(BaseModel):
    facility_id: int
    template_name: str = Field(..., min_length=3, max_length=255)
    template_type: str = Field(..., min_length=2, max_length=50)
    description: Optional[str] = None
    symptoms: List[SymptomTemplateItem] = []
    prescriptions: List[PrescriptionTemplateItem] = []
    lab_tests: List[LabTemplateItem] = []
    
    class Config:
        json_schema_extra = {
            "example": {
                "facility_id": 1,
                "template_name": "Common Viral Fever",
                "template_type": "FEVER",
                "description": "Standard protocol for viral fever treatment",
                "symptoms": [
                    {
                        "symptom_id": 0,
                        "default_duration_days":0 ,
                        "default_remarks": ""
                    }
                   
                ],
                "prescriptions": [
                    {
                        "medicine_id": 0,
                        "morning_dosage": "",
                        "afternoon_dosage": "",
                        "night_dosage": "",
                        "food_timing": "",
                        "duration_days": 0,
                        "special_instructions": ""
                    }
                   
                ],
                "lab_tests": [
                    {
                        "test_id": 0
                    }
                    
                ]
            }
        }

class TemplateUpdate(BaseModel):
    template_name: Optional[str] = Field(None, min_length=3, max_length=255)
    template_type: Optional[str] = Field(None, min_length=2, max_length=50)
    description: Optional[str] = None
    is_active: Optional[bool] = None
    symptoms: Optional[List[SymptomTemplateItem]] = None
    prescriptions: Optional[List[PrescriptionTemplateItem]] = None
    lab_tests: Optional[List[LabTemplateItem]] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "template_name": "Updated Viral Fever Protocol",
                "template_type": "FEVER",
                "description": "Updated standard protocol",
                "is_active": True,
                "symptoms": [
                    {
                        "symptom_id": 0,
                        "default_duration_days": 0,
                        "default_remarks": ""
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
                    {
                        "test_id": 0
                    }
                ]
            }
        }

class DrugMasterCreate(BaseModel):
    facility_id: int
    medicine_name: str = Field(..., min_length=2, max_length=255)
    generic_name: Optional[str] = Field(None, max_length=255)
    strength: Optional[str] = Field(None, max_length=100)
    medicine_type: Optional[str] = Field(None, max_length=100)
    composition_text: Optional[str] = None
    price: Optional[float] = Field(None, ge=0)
    manufacturer: Optional[str] = Field(None, max_length=255)
    
    class Config:
        json_schema_extra = {
            "example": {
                "facility_id": 1,
                "medicine_name": "Paracetamol",
                "generic_name": "Acetaminophen",
                "strength": "500mg",
                "medicine_type": "Tablet",
                "composition_text": "Each tablet contains 500mg Paracetamol",
                "price": 2.50,
                "manufacturer": "PharmaCorp"
            }
        }
class DrugMasterUpdate(BaseModel):
    medicine_name: Optional[str] = Field(None, min_length=2, max_length=255)
    generic_name: Optional[str] = Field(None, max_length=255)
    strength: Optional[str] = Field(None, max_length=100)
    medicine_type: Optional[str] = Field(None, max_length=100)
    composition_text: Optional[str] = None
    price: Optional[float] = Field(None, ge=0)
    manufacturer: Optional[str] = Field(None, max_length=255)
    is_active: Optional[bool] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "medicine_name": "Paracetamol 650",
                "generic_name": "Acetaminophen",
                "strength": "650mg",
                "medicine_type": "Tablet",
                "composition_text": "Each tablet contains 650mg Paracetamol",
                "price": 3.00,
                "manufacturer": "PharmaCorp",
                "is_active": True
            }
        }

class SymptomMasterCreate(BaseModel):
    facility_id: int
    symptom_name: str = Field(..., min_length=2, max_length=255)
    description: Optional[str] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "facility_id": 1,
                "symptom_name": "Fever",
                "description": "Elevated body temperature above 98.6°F"
            }
        }
class SymptomMasterUpdate(BaseModel):
    symptom_name: Optional[str] = Field(None, min_length=2, max_length=255)
    description: Optional[str] = None
    is_active: Optional[bool] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "symptom_name": "High Fever",
                "description": "Elevated body temperature above 100°F",
                "is_active": True
            }
        }

class LabMasterCreate(BaseModel):
    facility_id: int
    test_name: str = Field(..., min_length=2, max_length=255)
    description: Optional[str] = None
    prerequisite_text: Optional[str] = None
    price: Optional[float] = Field(None, ge=0)
    
    class Config:
        json_schema_extra = {
            "example": {
                "facility_id": 1,
                "test_name": "Complete Blood Count",
                "description": "Comprehensive blood analysis",
                "prerequisite_text": "No fasting required",
                "price": 300.00
            }
        }
class LabMasterUpdate(BaseModel):
    test_name: Optional[str] = Field(None, min_length=2, max_length=255)
    description: Optional[str] = None
    prerequisite_text: Optional[str] = None
    price: Optional[float] = Field(None, ge=0)
    is_active: Optional[bool] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "test_name": "CBC with ESR",
                "description": "Complete Blood Count with ESR",
                "prerequisite_text": "No fasting required",
                "price": 350.00,
                "is_active": True
            }
        }

# ==================== MASTER DATA ENDPOINTS ====================

@router.post("/drug-master", tags=["Master Data"])
async def create_drug(
    drug: DrugMasterCreate,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new drug/medicine in master data"""
    try:
        effective_facility_id = get_effective_facility_id(current_user, drug.facility_id)
        
        if drug.facility_id != effective_facility_id:
            raise HTTPException(status_code=403, detail="You can only create data for your facility")
        
        # Check if drug already exists (not deleted)
        existing = db.query(model.DrugMaster).filter(
            model.DrugMaster.medicine_name == drug.medicine_name,
            model.DrugMaster.facility_id == drug.facility_id,
            model.DrugMaster.is_deleted == False
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="Drug with this name already exists in your facility")
        
        new_drug = model.DrugMaster(
            **drug.dict(),
            created_by=current_user.user_id
        )
        db.add(new_drug)
        db.commit()
        db.refresh(new_drug)
        
        return {
            "status_code": 201,
            "message": "Drug created successfully",
            "data": {
                "medicine_id": new_drug.medicine_id,
                "facility_id": new_drug.facility_id,
                "medicine_name": new_drug.medicine_name,
                "generic_name": new_drug.generic_name,
                "strength": new_drug.strength
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error creating drug: {str(e)}")

@router.get("/drug-master", tags=["Master Data"])
async def get_drugs(
    search: Optional[str] = Query(None, description="Search by medicine or generic name"),
    medicine_type: Optional[str] = Query(None),
    is_active: bool = Query(True),
    facility_id: Optional[int] = Query(None, description="Facility ID (Super Admin only)"),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get list of drugs with optional filters"""
    try:
        effective_facility_id = get_effective_facility_id(current_user, facility_id)
        
        query = db.query(model.DrugMaster).filter(
            model.DrugMaster.facility_id == effective_facility_id,
            model.DrugMaster.is_active == is_active,
            model.DrugMaster.is_deleted == False
        )
        
        if search:
            search_filter = f"%{search}%"
            query = query.filter(
                or_(
                    model.DrugMaster.medicine_name.ilike(search_filter),
                    model.DrugMaster.generic_name.ilike(search_filter)
                )
            )
        
        if medicine_type:
            query = query.filter(model.DrugMaster.medicine_type == medicine_type)
        
        drugs = query.order_by(model.DrugMaster.medicine_name).all()
        
        return [{
            "medicine_id": d.medicine_id,
            "facility_id": d.facility_id,
            "medicine_name": d.medicine_name,
            "generic_name": d.generic_name,
            "strength": d.strength,
            "medicine_type": d.medicine_type,
            "price": d.price,
            "manufacturer": d.manufacturer
        } for d in drugs]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching drugs: {str(e)}")

@router.delete("/drug-master/{medicine_id}", tags=["Master Data"])
async def delete_drug(
    medicine_id: int,
    facility_id: Optional[int] = Query(None, description="Facility ID (Super Admin only)"),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Soft delete a drug"""
    try:
        effective_facility_id = get_effective_facility_id(current_user, facility_id)
        
        drug = db.query(model.DrugMaster).filter(
            model.DrugMaster.medicine_id == medicine_id,
            model.DrugMaster.facility_id == effective_facility_id,
            model.DrugMaster.is_deleted == False
        ).first()
        
        if not drug:
            raise HTTPException(status_code=404, detail="Drug not found")
        
        drug.is_deleted = True
        drug.is_active = False
        drug.deleted_by = current_user.user_id
        drug.deleted_at = datetime.now()
        db.commit()
        
        return {"status_code": 200, "message": "Drug deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error deleting drug: {str(e)}")

@router.put("/drug-master/{medicine_id}", tags=["Master Data"])
async def update_drug(
    medicine_id: int,
    drug_update: DrugMasterUpdate,
    facility_id: Optional[int] = Query(None, description="Facility ID (Super Admin only)"),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update an existing drug/medicine in master data"""
    try:
        effective_facility_id = get_effective_facility_id(current_user, facility_id)
        
        drug = db.query(model.DrugMaster).filter(
            model.DrugMaster.medicine_id == medicine_id,
            model.DrugMaster.facility_id == effective_facility_id,
            model.DrugMaster.is_deleted == False
        ).first()
        
        if not drug:
            raise HTTPException(status_code=404, detail="Drug not found")
        
        # Check if updating name to existing name
        if drug_update.medicine_name is not None and drug_update.medicine_name != drug.medicine_name:
            existing = db.query(model.DrugMaster).filter(
                model.DrugMaster.medicine_name == drug_update.medicine_name,
                model.DrugMaster.facility_id == effective_facility_id,
                model.DrugMaster.is_deleted == False,
                model.DrugMaster.medicine_id != medicine_id
            ).first()
            if existing:
                raise HTTPException(status_code=400, detail="Drug with this name already exists")
        
        # Update fields
        if drug_update.medicine_name is not None:
            drug.medicine_name = drug_update.medicine_name
        if drug_update.generic_name is not None:
            drug.generic_name = drug_update.generic_name
        if drug_update.strength is not None:
            drug.strength = drug_update.strength
        if drug_update.medicine_type is not None:
            drug.medicine_type = drug_update.medicine_type
        if drug_update.composition_text is not None:
            drug.composition_text = drug_update.composition_text
        if drug_update.price is not None:
            drug.price = drug_update.price
        if drug_update.manufacturer is not None:
            drug.manufacturer = drug_update.manufacturer
        if drug_update.is_active is not None:
            drug.is_active = drug_update.is_active
        
        drug.updated_by = current_user.user_id
        drug.updated_at = datetime.now()
        
        db.commit()
        db.refresh(drug)
        
        return {
            "status_code": 200,
            "message": "Drug updated successfully",
            "data": {
                "medicine_id": drug.medicine_id,
                "facility_id": drug.facility_id,
                "medicine_name": drug.medicine_name,
                "generic_name": drug.generic_name,
                "strength": drug.strength,
                "medicine_type": drug.medicine_type,
                "price": drug.price,
                "manufacturer": drug.manufacturer,
                "is_active": drug.is_active
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error updating drug: {str(e)}")


@router.post("/symptom-master", tags=["Master Data"])
async def create_symptom(
    symptom: SymptomMasterCreate,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new symptom in master data"""
    try:
        effective_facility_id = get_effective_facility_id(current_user, symptom.facility_id)
        
        if symptom.facility_id != effective_facility_id:
            raise HTTPException(status_code=403, detail="You can only create data for your facility")
        
        existing = db.query(model.SymptomMaster).filter(
            model.SymptomMaster.symptom_name == symptom.symptom_name,
            model.SymptomMaster.facility_id == symptom.facility_id,
            model.SymptomMaster.is_deleted == False
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="Symptom already exists in your facility")
        
        new_symptom = model.SymptomMaster(
            **symptom.dict(),
            created_by=current_user.user_id
        )
        db.add(new_symptom)
        db.commit()
        db.refresh(new_symptom)
        
        return {
            "status_code": 201,
            "message": "Symptom created successfully",
            "data": {
                "symptom_id": new_symptom.symptom_id,
                "facility_id": new_symptom.facility_id,
                "symptom_name": new_symptom.symptom_name
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error creating symptom: {str(e)}")

@router.get("/symptom-master", tags=["Master Data"])
async def get_symptoms(
    search: Optional[str] = Query(None, description="Search by symptom name"),
    is_active: bool = Query(True),
    facility_id: Optional[int] = Query(None, description="Facility ID (Super Admin only)"),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get list of symptoms"""
    try:
        effective_facility_id = get_effective_facility_id(current_user, facility_id)
        
        query = db.query(model.SymptomMaster).filter(
            model.SymptomMaster.facility_id == effective_facility_id,
            model.SymptomMaster.is_active == is_active,
            model.SymptomMaster.is_deleted == False
        )
        
        if search:
            query = query.filter(model.SymptomMaster.symptom_name.ilike(f"%{search}%"))
        
        symptoms = query.order_by(model.SymptomMaster.symptom_name).all()
        
        return [{
            "symptom_id": s.symptom_id,
            "facility_id": s.facility_id,
            "symptom_name": s.symptom_name,
            "description": s.description
        } for s in symptoms]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching symptoms: {str(e)}")

@router.delete("/symptom-master/{symptom_id}", tags=["Master Data"])
async def delete_symptom(
    symptom_id: int,
    facility_id: Optional[int] = Query(None, description="Facility ID (Super Admin only)"),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Soft delete a symptom"""
    try:
        effective_facility_id = get_effective_facility_id(current_user, facility_id)
        
        symptom = db.query(model.SymptomMaster).filter(
            model.SymptomMaster.symptom_id == symptom_id,
            model.SymptomMaster.facility_id == effective_facility_id,
            model.SymptomMaster.is_deleted == False
        ).first()
        
        if not symptom:
            raise HTTPException(status_code=404, detail="Symptom not found")
        
        symptom.is_deleted = True
        symptom.is_active = False
        symptom.deleted_by = current_user.user_id
        symptom.deleted_at = datetime.now()
        db.commit()
        
        return {"status_code": 200, "message": "Symptom deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error deleting symptom: {str(e)}")

@router.put("/symptom-master/{symptom_id}", tags=["Master Data"])
async def update_symptom(
    symptom_id: int,
    symptom_update: SymptomMasterUpdate,
    facility_id: Optional[int] = Query(None, description="Facility ID (Super Admin only)"),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update an existing symptom in master data"""
    try:
        effective_facility_id = get_effective_facility_id(current_user, facility_id)
        
        symptom = db.query(model.SymptomMaster).filter(
            model.SymptomMaster.symptom_id == symptom_id,
            model.SymptomMaster.facility_id == effective_facility_id,
            model.SymptomMaster.is_deleted == False
        ).first()
        
        if not symptom:
            raise HTTPException(status_code=404, detail="Symptom not found")
        
        # Check if updating name to existing name
        if symptom_update.symptom_name is not None and symptom_update.symptom_name != symptom.symptom_name:
            existing = db.query(model.SymptomMaster).filter(
                model.SymptomMaster.symptom_name == symptom_update.symptom_name,
                model.SymptomMaster.facility_id == effective_facility_id,
                model.SymptomMaster.is_deleted == False,
                model.SymptomMaster.symptom_id != symptom_id
            ).first()
            if existing:
                raise HTTPException(status_code=400, detail="Symptom with this name already exists")
        
        # Update fields
        if symptom_update.symptom_name is not None:
            symptom.symptom_name = symptom_update.symptom_name
        if symptom_update.description is not None:
            symptom.description = symptom_update.description
        if symptom_update.is_active is not None:
            symptom.is_active = symptom_update.is_active
        
        symptom.updated_by = current_user.user_id
        symptom.updated_at = datetime.now()
        
        db.commit()
        db.refresh(symptom)
        
        return {
            "status_code": 200,
            "message": "Symptom updated successfully",
            "data": {
                "symptom_id": symptom.symptom_id,
                "facility_id": symptom.facility_id,
                "symptom_name": symptom.symptom_name,
                "description": symptom.description,
                "is_active": symptom.is_active
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error updating symptom: {str(e)}")


@router.post("/lab-master", tags=["Master Data"])
async def create_lab_test(
    lab_test: LabMasterCreate,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new lab test in master data"""
    try:
        effective_facility_id = get_effective_facility_id(current_user, lab_test.facility_id)
        
        if lab_test.facility_id != effective_facility_id:
            raise HTTPException(status_code=403, detail="You can only create data for your facility")
        
        existing = db.query(model.LabMaster).filter(
            model.LabMaster.test_name == lab_test.test_name,
            model.LabMaster.facility_id == lab_test.facility_id,
            model.LabMaster.is_deleted == False
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="Lab test already exists in your facility")
        
        new_test = model.LabMaster(
            **lab_test.dict(),
            created_by=current_user.user_id
        )
        db.add(new_test)
        db.commit()
        db.refresh(new_test)
        
        return {
            "status_code": 201,
            "message": "Lab test created successfully",
            "data": {
                "test_id": new_test.test_id,
                "facility_id": new_test.facility_id,
                "test_name": new_test.test_name
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error creating lab test: {str(e)}")

@router.get("/lab-master", tags=["Master Data"])
async def get_lab_tests(
    search: Optional[str] = Query(None, description="Search by test name"),
    is_active: bool = Query(True),
    facility_id: Optional[int] = Query(None, description="Facility ID (Super Admin only)"),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get list of lab tests"""
    try:
        effective_facility_id = get_effective_facility_id(current_user, facility_id)
        
        query = db.query(model.LabMaster).filter(
            model.LabMaster.facility_id == effective_facility_id,
            model.LabMaster.is_active == is_active,
            model.LabMaster.is_deleted == False
        )
        
        if search:
            query = query.filter(model.LabMaster.test_name.ilike(f"%{search}%"))
        
        tests = query.order_by(model.LabMaster.test_name).all()
        
        return [{
            "test_id": t.test_id,
            "facility_id": t.facility_id,
            "test_name": t.test_name,
            "description": t.description,
            "prerequisite_text": t.prerequisite_text,
            "price": t.price
        } for t in tests]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching lab tests: {str(e)}")

@router.delete("/lab-master/{test_id}", tags=["Master Data"])
async def delete_lab_test(
    test_id: int,
    facility_id: Optional[int] = Query(None, description="Facility ID (Super Admin only)"),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Soft delete a lab test"""
    try:
        effective_facility_id = get_effective_facility_id(current_user, facility_id)
        
        test = db.query(model.LabMaster).filter(
            model.LabMaster.test_id == test_id,
            model.LabMaster.facility_id == effective_facility_id,
            model.LabMaster.is_deleted == False
        ).first()
        
        if not test:
            raise HTTPException(status_code=404, detail="Lab test not found")
        
        test.is_deleted = True
        test.is_active = False
        test.deleted_by = current_user.user_id
        test.deleted_at = datetime.now()
        db.commit()
        
        return {"status_code": 200, "message": "Lab test deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error deleting lab test: {str(e)}")

@router.put("/lab-master/{test_id}", tags=["Master Data"])
async def update_lab_test(
    test_id: int,
    lab_update: LabMasterUpdate,
    facility_id: Optional[int] = Query(None, description="Facility ID (Super Admin only)"),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update an existing lab test in master data"""
    try:
        effective_facility_id = get_effective_facility_id(current_user, facility_id)
        
        test = db.query(model.LabMaster).filter(
            model.LabMaster.test_id == test_id,
            model.LabMaster.facility_id == effective_facility_id,
            model.LabMaster.is_deleted == False
        ).first()
        
        if not test:
            raise HTTPException(status_code=404, detail="Lab test not found")
        
        # Check if updating name to existing name
        if lab_update.test_name is not None and lab_update.test_name != test.test_name:
            existing = db.query(model.LabMaster).filter(
                model.LabMaster.test_name == lab_update.test_name,
                model.LabMaster.facility_id == effective_facility_id,
                model.LabMaster.is_deleted == False,
                model.LabMaster.test_id != test_id
            ).first()
            if existing:
                raise HTTPException(status_code=400, detail="Lab test with this name already exists")
        
        # Update fields
        if lab_update.test_name is not None:
            test.test_name = lab_update.test_name
        if lab_update.description is not None:
            test.description = lab_update.description
        if lab_update.prerequisite_text is not None:
            test.prerequisite_text = lab_update.prerequisite_text
        if lab_update.price is not None:
            test.price = lab_update.price
        if lab_update.is_active is not None:
            test.is_active = lab_update.is_active
        
        test.updated_by = current_user.user_id
        test.updated_at = datetime.now()
        
        db.commit()
        db.refresh(test)
        
        return {
            "status_code": 200,
            "message": "Lab test updated successfully",
            "data": {
                "test_id": test.test_id,
                "facility_id": test.facility_id,
                "test_name": test.test_name,
                "description": test.description,
                "prerequisite_text": test.prerequisite_text,
                "price": test.price,
                "is_active": test.is_active
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error updating lab test: {str(e)}")

# ==================== TEMPLATE ENDPOINTS ====================

@router.post("/", tags=["Templates"])
async def create_template(
    template_data: TemplateCreate,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new diagnosis template"""
    try:
        effective_facility_id = get_effective_facility_id(current_user, template_data.facility_id)
        
        if template_data.facility_id != effective_facility_id:
            raise HTTPException(status_code=403, detail="You can only create templates for your facility")
        
        # Check if template exists (not deleted)
        existing = db.query(model.Template).filter(
            model.Template.template_name == template_data.template_name,
            model.Template.facility_id == template_data.facility_id,
            model.Template.is_deleted == False
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="Template with this name already exists")
        
        # Validate referenced master data exists and is active
        for symptom_item in template_data.symptoms:
            symptom = db.query(model.SymptomMaster).filter(
                model.SymptomMaster.symptom_id == symptom_item.symptom_id,
                model.SymptomMaster.is_deleted == False,
                model.SymptomMaster.is_active == True
            ).first()
            if not symptom:
                raise HTTPException(status_code=400, detail=f"Symptom ID {symptom_item.symptom_id} not found or inactive")
        
        for prescription_item in template_data.prescriptions:
            medicine = db.query(model.DrugMaster).filter(
                model.DrugMaster.medicine_id == prescription_item.medicine_id,
                model.DrugMaster.is_deleted == False,
                model.DrugMaster.is_active == True
            ).first()
            if not medicine:
                raise HTTPException(status_code=400, detail=f"Medicine ID {prescription_item.medicine_id} not found or inactive")
        
        for lab_item in template_data.lab_tests:
            test = db.query(model.LabMaster).filter(
                model.LabMaster.test_id == lab_item.test_id,
                model.LabMaster.is_deleted == False,
                model.LabMaster.is_active == True
            ).first()
            if not test:
                raise HTTPException(status_code=400, detail=f"Lab test ID {lab_item.test_id} not found or inactive")
        
        # Create template
        new_template = model.Template(
            facility_id=template_data.facility_id,
            template_name=template_data.template_name,
            template_type=template_data.template_type,
            description=template_data.description,
            created_by=current_user.user_id
        )
        db.add(new_template)
        db.flush()
        
        # Add symptoms
        for symptom_item in template_data.symptoms:
            symptom_template = model.SymptomTemplate(
                template_id=new_template.template_id,
                symptom_id=symptom_item.symptom_id,
                default_duration_days=symptom_item.default_duration_days,
                default_remarks=symptom_item.default_remarks,
                created_by=current_user.user_id
            )
            db.add(symptom_template)
        
        # Add prescriptions
        for prescription_item in template_data.prescriptions:
            prescription_template = model.PrescriptionTemplate(
                template_id=new_template.template_id,
                medicine_id=prescription_item.medicine_id,
                morning_dosage=prescription_item.morning_dosage,
                afternoon_dosage=prescription_item.afternoon_dosage,
                night_dosage=prescription_item.night_dosage,
                food_timing=prescription_item.food_timing,
                duration_days=prescription_item.duration_days,
                special_instructions=prescription_item.special_instructions,
                created_by=current_user.user_id
            )
            db.add(prescription_template)
        
        # Add lab tests
        for lab_item in template_data.lab_tests:
            lab_template = model.LabTemplate(
                template_id=new_template.template_id,
                test_id=lab_item.test_id,
                created_by=current_user.user_id
            )
            db.add(lab_template)
        
        db.commit()
        db.refresh(new_template)
        
        return {
            "status_code": 201,
            "message": "Template created successfully",
            "data": {
                "template_id": new_template.template_id,
                "facility_id": new_template.facility_id,
                "template_name": new_template.template_name,
                "template_type": new_template.template_type
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error creating template: {str(e)}")

@router.get("/", tags=["Templates"])
async def get_templates(
    template_type: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    is_active: bool = Query(True),
    facility_id: Optional[int] = Query(None, description="Facility ID (Super Admin only)"),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get list of templates"""
    try:
        effective_facility_id = get_effective_facility_id(current_user, facility_id)
        
        query = db.query(model.Template).filter(
            model.Template.facility_id == effective_facility_id,
            model.Template.is_active == is_active,
            model.Template.is_deleted == False
        )
        
        if template_type:
            query = query.filter(model.Template.template_type == template_type)
        
        if search:
            query = query.filter(model.Template.template_name.ilike(f"%{search}%"))
        
        templates = query.order_by(model.Template.template_name).all()
        
        return [{
            "template_id": t.template_id,
            "facility_id": t.facility_id,
            "template_name": t.template_name,
            "template_type": t.template_type,
            "description": t.description,
            "is_active": t.is_active
        } for t in templates]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching templates: {str(e)}")

@router.get("/all/list", tags=["Templates"])
async def get_all_templates(
    facility_id: Optional[int] = Query(None, description="Facility ID (Super Admin only)"),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get all templates regardless of active status"""
    try:
        effective_facility_id = get_effective_facility_id(current_user, facility_id)
        
        templates = db.query(model.Template).filter(
            model.Template.facility_id == effective_facility_id,
            model.Template.is_deleted == False
        ).order_by(model.Template.template_name).all()
        
        return [{
            "template_id": t.template_id,
            "facility_id": t.facility_id,
            "template_name": t.template_name,
            "template_type": t.template_type,
            "description": t.description,
            "is_active": t.is_active
        } for t in templates]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching templates: {str(e)}")

@router.get("/{template_id}", tags=["Templates"])
async def get_template_details(
    template_id: int,
    facility_id: Optional[int] = Query(None, description="Facility ID (Super Admin only)"),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get complete template details"""
    try:
        template = db.query(model.Template).options(
            joinedload(model.Template.symptoms).joinedload(model.SymptomTemplate.symptom),
            joinedload(model.Template.prescriptions).joinedload(model.PrescriptionTemplate.medicine),
            joinedload(model.Template.lab_tests).joinedload(model.LabTemplate.test)
        ).filter(
            model.Template.template_id == template_id,
            model.Template.is_deleted == False
        ).first()
        
        if not template:
            raise HTTPException(status_code=404, detail="Template not found")
        
        effective_facility_id = get_effective_facility_id(current_user, facility_id)
        
        if template.facility_id != effective_facility_id:
            raise HTTPException(status_code=403, detail="You can only access templates from your facility")
        
        return {
            "template_id": template.template_id,
            "facility_id": template.facility_id,
            "template_name": template.template_name,
            "template_type": template.template_type,
            "description": template.description,
            "is_active": template.is_active,
            "symptoms": [{
                "symptom_id": st.symptom_id,
                "symptom_name": st.symptom.symptom_name,
                "default_duration_days": st.default_duration_days,
                "default_remarks": st.default_remarks
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
                "description": lt.test.description,
                "prerequisite_text": lt.test.prerequisite_text,
                "price": lt.test.price
            } for lt in template.lab_tests]
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching template: {str(e)}")

@router.put("/{template_id}", tags=["Templates"])
async def update_template(
    template_id: int,
    template_data: TemplateUpdate,
    facility_id: Optional[int] = Query(None, description="Facility ID (Super Admin only)"),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update template"""
    try:
        template = db.query(model.Template).filter(
            model.Template.template_id == template_id,
            model.Template.is_deleted == False
        ).first()
        
        if not template:
            raise HTTPException(status_code=404, detail="Template not found")
        
        effective_facility_id = get_effective_facility_id(current_user, facility_id)
        
        if template.facility_id != effective_facility_id:
            raise HTTPException(status_code=403, detail="You can only update templates from your facility")
        
        # Update basic fields
        if template_data.template_name is not None:
            template.template_name = template_data.template_name
        if template_data.template_type is not None:
            template.template_type = template_data.template_type
        if template_data.description is not None:
            template.description = template_data.description
        if template_data.is_active is not None:
            template.is_active = template_data.is_active
        
        template.updated_by = current_user.user_id
        
        # Update linked data if provided
        if template_data.symptoms is not None:
            db.query(model.SymptomTemplate).filter(
                model.SymptomTemplate.template_id == template_id
            ).delete()
            
            for symptom_item in template_data.symptoms:
                symptom_template = model.SymptomTemplate(
                    template_id=template_id,
                    symptom_id=symptom_item.symptom_id,
                    default_duration_days=symptom_item.default_duration_days,
                    default_remarks=symptom_item.default_remarks,
                    created_by=current_user.user_id
                )
                db.add(symptom_template)
        
        if template_data.prescriptions is not None:
            db.query(model.PrescriptionTemplate).filter(
                model.PrescriptionTemplate.template_id == template_id
            ).delete()
            
            for prescription_item in template_data.prescriptions:
                prescription_template = model.PrescriptionTemplate(
                    template_id=template_id,
                    medicine_id=prescription_item.medicine_id,
                    morning_dosage=prescription_item.morning_dosage,
                    afternoon_dosage=prescription_item.afternoon_dosage,
                    night_dosage=prescription_item.night_dosage,
                    food_timing=prescription_item.food_timing,
                    duration_days=prescription_item.duration_days,
                    special_instructions=prescription_item.special_instructions,
                    created_by=current_user.user_id
                )
                db.add(prescription_template)
        
        if template_data.lab_tests is not None:
            db.query(model.LabTemplate).filter(
                model.LabTemplate.template_id == template_id
            ).delete()
            
            for lab_item in template_data.lab_tests:
                lab_template = model.LabTemplate(
                    template_id=template_id,
                    test_id=lab_item.test_id,
                    created_by=current_user.user_id
                )
                db.add(lab_template)
        
        db.commit()
        
        return {"status_code": 200, "message": "Template updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error updating template: {str(e)}")

@router.delete("/{template_id}", tags=["Templates"])
async def delete_template(
    template_id: int,
    facility_id: Optional[int] = Query(None, description="Facility ID (Super Admin only)"),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Soft delete a template"""
    try:
        template = db.query(model.Template).filter(
            model.Template.template_id == template_id,
            model.Template.is_deleted == False
        ).first()
        
        if not template:
            raise HTTPException(status_code=404, detail="Template not found")
        
        effective_facility_id = get_effective_facility_id(current_user, facility_id)
        
        if template.facility_id != effective_facility_id:
            raise HTTPException(status_code=403, detail="You can only delete templates from your facility")
        
        template.is_deleted = True
        template.is_active = False
        template.deleted_by = current_user.user_id
        template.deleted_at = datetime.now()
        db.commit()
        
        return {"status_code": 200, "message": "Template deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error deleting template: {str(e)}")