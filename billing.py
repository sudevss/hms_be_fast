from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from pydantic import BaseModel
from database import get_db
from model import Billing

router = APIRouter(
    prefix="/billing",
    tags=["Billing"]
)

class BillingBase(BaseModel):
    AppointmentID: int
    Amount: float
    BillDate: str
    PaymentStatus: str
    PaymentMode: str
    TransactionID: str

class BillingResponse(BillingBase):
    BillID: int

    class Config:
        orm_mode = True

@router.get("/", response_model=List[BillingResponse])
def get_all_bills(db: Session = Depends(get_db)):
    return db.query(Billing).all()

@router.get("/{bill_id}", response_model=BillingResponse)
def get_bill(bill_id: int, db: Session = Depends(get_db)):
    bill = db.query(Billing).filter(Billing.BillID == bill_id).first()
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")
    return bill

@router.post("/", response_model=BillingResponse)
def create_bill(bill: BillingBase, db: Session = Depends(get_db)):
    new_bill = Billing(**bill.dict())
    db.add(new_bill)
    db.commit()
    db.refresh(new_bill)
    return new_bill

@router.put("/{bill_id}", response_model=BillingResponse)
def update_bill(bill_id: int, bill: BillingBase, db: Session = Depends(get_db)):
    existing_bill = db.query(Billing).filter(Billing.BillID == bill_id).first()
    if not existing_bill:
        raise HTTPException(status_code=404, detail="Bill not found")
    for key, value in bill.dict().items():
        setattr(existing_bill, key, value)
    db.commit()
    db.refresh(existing_bill)
    return existing_bill

@router.delete("/{bill_id}")
def delete_bill(bill_id: int, db: Session = Depends(get_db)):
    bill = db.query(Billing).filter(Billing.BillID == bill_id).first()
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")
    db.delete(bill)
    db.commit()
    return {"detail": "Bill deleted successfully"}