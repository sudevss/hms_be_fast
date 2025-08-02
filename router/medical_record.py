from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from pydantic import BaseModel
from database import get_db
from model import MedicalRecord

router = APIRouter(
    prefix="/medical_record",
    tags=["MedicalRecord"]
)

class MedicalRecordBase(BaseModel):
    PatientID: int
    DoctorID: int
    AppointmentID: int
    Diagnosis: str
    Treatment: str
    Medicine_Prescription: str
    Lab_Prescription: str
    RecordDate: str

class MedicalRecordResponse(MedicalRecordBase):
    RecordID: int

    class Config:
        orm_mode = True

@router.get("/", response_model=List[MedicalRecordResponse])
def get_all_records(db: Session = Depends(get_db)):
    return db.query(MedicalRecord).all()

@router.get("/{record_id}", response_model=MedicalRecordResponse)
def get_record(record_id: int, db: Session = Depends(get_db)):
    record = db.query(MedicalRecord).filter(MedicalRecord.RecordID == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Record not found")
    return record

@router.post("/", response_model=MedicalRecordResponse)
def create_record(record: MedicalRecordBase, db: Session = Depends(get_db)):
    new_record = MedicalRecord(**record.dict())
    db.add(new_record)
    db.commit()
    db.refresh(new_record)
    return new_record

@router.put("/{record_id}", response_model=MedicalRecordResponse)
def update_record(record_id: int, record: MedicalRecordBase, db: Session = Depends(get_db)):
    existing_record = db.query(MedicalRecord).filter(MedicalRecord.RecordID == record_id).first()
    if not existing_record:
        raise HTTPException(status_code=404, detail="Record not found")
    for key, value in record.dict().items():
        setattr(existing_record, key, value)
    db.commit()
    db.refresh(existing_record)
    return existing_record

@router.delete("/{record_id}")
def delete_record(record_id: int, db: Session = Depends(get_db)):
    record = db.query(MedicalRecord).filter(MedicalRecord.RecordID == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Record not found")
    db.delete(record)
    db.commit()
    return {"detail": "Record deleted successfully"}