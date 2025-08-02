from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from pydantic import BaseModel
from database import get_db
from model import MedicalDocument

router = APIRouter(
    prefix="/medical_document",
    tags=["MedicalDocument"]
)

class MedicalDocumentBase(BaseModel):
    AppointmentID: int
    PatientID: int
    DoctorID: int
    DocumentType: str
    DocumentPath: str

class MedicalDocumentResponse(MedicalDocumentBase):
    DocumentID: int

    class Config:
        orm_mode = True

@router.get("/", response_model=List[MedicalDocumentResponse])
def get_all_documents(db: Session = Depends(get_db)):
    return db.query(MedicalDocument).all()

@router.get("/{document_id}", response_model=MedicalDocumentResponse)
def get_document(document_id: int, db: Session = Depends(get_db)):
    document = db.query(MedicalDocument).filter(MedicalDocument.DocumentID == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    return document

@router.post("/", response_model=MedicalDocumentResponse)
def create_document(document: MedicalDocumentBase, db: Session = Depends(get_db)):
    new_document = MedicalDocument(**document.dict())
    db.add(new_document)
    db.commit()
    db.refresh(new_document)
    return new_document

@router.put("/{document_id}", response_model=MedicalDocumentResponse)
def update_document(document_id: int, document: MedicalDocumentBase, db: Session = Depends(get_db)):
    existing_document = db.query(MedicalDocument).filter(MedicalDocument.DocumentID == document_id).first()
    if not existing_document:
        raise HTTPException(status_code=404, detail="Document not found")
    for key, value in document.dict().items():
        setattr(existing_document, key, value)
    db.commit()
    db.refresh(existing_document)
    return existing_document

@router.delete("/{document_id}")
def delete_document(document_id: int, db: Session = Depends(get_db)):
    document = db.query(MedicalDocument).filter(MedicalDocument.DocumentID == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    db.delete(document)
    db.commit()
    return {"detail": "Document deleted successfully"}