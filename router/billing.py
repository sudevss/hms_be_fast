from typing import List, Optional, Dict, Any
from datetime import date, datetime
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload
from fastapi import HTTPException, APIRouter, Depends, Query
from sqlalchemy import and_, or_, desc, func
from decimal import Decimal

import model
from database import SessionLocal
from auth_middleware import get_current_user, CurrentUser

router = APIRouter(
    prefix="/billing",
    tags=["Billing & Payments"],
    responses={404: {"description": "Not found"}}
)

def get_db():
    try:
        db = SessionLocal()
        yield db
    finally:
        db.close()

def get_effective_facility_id(current_user: CurrentUser, requested_facility_id: Optional[int]) -> int:
    """
    Determine the effective facility_id based on user role.
    - Super Admin: Use requested_facility_id if provided, otherwise use token facility_id
    - Regular User: Always use token facility_id (ignore requested_facility_id)
    """
    if current_user.role == "Super Admin":
        return requested_facility_id if requested_facility_id is not None else current_user.facility_id
    else:
        return current_user.facility_id

# ==================== PYDANTIC MODELS ====================

class LabBillItem(BaseModel):
    """Lab test bill item"""
    test_id: int
    test_name: Optional[str] = None  # Auto-fetched from lab_master
    remarks: Optional[str] = None
    price: Optional[float] = None  # Auto-fetched from lab_master
    discount_percent: float = Field(0, ge=0, le=100)
    final_price: Optional[float] = None  # Calculated in backend
    
    class Config:
        json_schema_extra = {
            "example": {
                "test_id": 5,
                "remarks": "Empty Stomach",
                "discount_percent": 0
            }
        }

class PharmacyBillItem(BaseModel):
    """Pharmacy bill item"""
    medicine_id: int
    medicine_name: Optional[str] = None  # Auto-fetched from drug_master
    generic_name: Optional[str] = None  # Auto-fetched from drug_master
    strength: Optional[str] = None  # Auto-fetched from drug_master
    quantity: int = Field(..., gt=0)
    unit_price: Optional[float] = None  # Auto-fetched from drug_master
    total_price: Optional[float] = None  # Calculated as quantity * unit_price in backend
    discount_percent: float = Field(0, ge=0, le=100)
    final_price: Optional[float] = None  # Calculated in backend
    dosage_info: Optional[str] = None  # e.g., "M-A-N"
    food_timing: Optional[str] = None
    duration_days: Optional[int] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "medicine_id": 10,
                "quantity": 6,
                "discount_percent": 10,
                "dosage_info": "M-A-N",
                "food_timing": "After Food",
                "duration_days": 2
            }
        }

class ProcedureBillItem(BaseModel):
    """Procedure bill item"""
    procedure_text: str
    price: float
    discount_percent: float = Field(0, ge=0, le=100)
    final_price: Optional[float] = None  # Calculated in backend
    
    class Config:
        json_schema_extra = {
            "example": {
                "procedure_text": "Blood pressure monitoring",
                "price": 500.0,
                "discount_percent": 0
            }
        }

class PaymentSummaryRequest(BaseModel):
    """Request to get payment summary for a diagnosis"""
    diagnosis_id: int
    facility_id: Optional[int] = None

class CreateBillRequest(BaseModel):
    """Request to create bills for lab/pharmacy/procedures"""
    diagnosis_id: int
    facility_id: Optional[int] = None
    appointment_id: Optional[int] = Field(None, description="Associated appointment ID")
    
    # Lab bill
    lab_items: List[LabBillItem] = Field(default_factory=list)
    lab_discount_percent: float = Field(0, ge=0, le=100)
    
    # Pharmacy bill
    pharmacy_items: List[PharmacyBillItem] = Field(default_factory=list)
    pharmacy_discount_percent: float = Field(0, ge=0, le=100)
    
    # Procedure bill
    procedure_items: List[ProcedureBillItem] = Field(default_factory=list)
    procedure_discount_percent: float = Field(0, ge=0, le=100)
    
    class Config:
        json_schema_extra = {
            "example": {
                "diagnosis_id": 123,
                "facility_id": 1,
                "appointment_id": None,
                "lab_items": [
                    {
                        "test_id": 5,
                        "remarks": "Empty Stomach",
                        "discount_percent": 0
                    },
                    {
                        "test_id": 8,
                        "remarks": "Fasting required",
                        "discount_percent": 10
                    }
                ],
                "lab_discount_percent": 0,
                "pharmacy_items": [
                    {
                        "medicine_id": 10,
                        "quantity": 6,
                        "discount_percent": 10,
                        "dosage_info": "M-A-N",
                        "food_timing": "After Food",
                        "duration_days": 2
                    },
                    {
                        "medicine_id": 15,
                        "quantity": 6,
                        "discount_percent": 0,
                        "dosage_info": "M-N",
                        "food_timing": "Before Food",
                        "duration_days": 3
                    }
                ],
                "pharmacy_discount_percent": 0,
                "procedure_items": [
                    {
                        "procedure_text": "Blood pressure monitoring",
                        "price": 500.0,
                        "discount_percent": 0
                    }
                ],
                "procedure_discount_percent": 0
            }
        }

class PaymentRequest(BaseModel):
    """Request to record a payment"""
    diagnosis_id: int
    facility_id: Optional[int] = None
    payment_type: str = Field(..., description="consultation|procedure|lab|pharmacy")
    amount_paid: float = Field(..., gt=0)
    payment_method: str = Field(..., description="Cash|Debit Card|Credit Card|UPI|Net Banking")
    payment_comments: Optional[str] = None

class PaymentSummaryResponse(BaseModel):
    """Complete payment summary response"""
    diagnosis_id: int
    patient_id: int
    patient_name: str
    appointment_id: Optional[int]
    
    # Consultation
    consultation_fee: float
    consultation_paid: float
    consultation_pending: float
    
    # Procedures
    procedure_total: float
    procedure_paid: float
    procedure_pending: float
    
    # Lab
    lab_total: float
    lab_paid: float
    lab_pending: float
    
    # Pharmacy
    pharmacy_total: float
    pharmacy_paid: float
    pharmacy_pending: float
    
    # Overall totals
    total_amount: float
    total_paid: float
    total_pending: float
    
    class Config:
        from_attributes = True

class LabPrintResponse(BaseModel):
    """Lab bill print response"""
    diagnosis_id: int
    patient_name: str
    date: date
    items: List[LabBillItem]
    subtotal: float
    discount_percent: float
    total: float
    
class PharmacyPrintResponse(BaseModel):
    """Pharmacy bill print response"""
    diagnosis_id: int
    patient_name: str
    date: date
    items: List[PharmacyBillItem]
    subtotal: float
    discount_percent: float
    total: float

# ==================== HELPER FUNCTIONS ====================

def calculate_final_price(price: float, discount_percent: float) -> float:
    """Calculate final price after discount"""
    discount_amount = (price * discount_percent) / 100
    return round(price - discount_amount, 2)

def get_consultation_fee(db: Session, diagnosis_id: int) -> tuple[float, float]:
    """Get consultation fee and paid amount"""
    diagnosis = db.query(model.PatientDiagnosis).filter(
        model.PatientDiagnosis.diagnosis_id == diagnosis_id
    ).first()
    
    if not diagnosis or not diagnosis.doctor_id:
        return 0.0, 0.0
    
    # Get doctor's consultation fee
    doctor = db.query(model.Doctors).filter(
        model.Doctors.id == diagnosis.doctor_id
    ).first()
    
    if not doctor or not doctor.consultation_fee:
        return 0.0, 0.0
    
    consultation_fee = float(doctor.consultation_fee)
    
    # Check if paid via appointment
    consultation_paid = 0.0
    if diagnosis.appointment_id:
        appointment = db.query(model.Appointment).filter(
            model.Appointment.appointment_id == diagnosis.appointment_id
        ).first()
        
        if appointment and appointment.payment_status == 1:
            consultation_paid = consultation_fee
    
    return consultation_fee, consultation_paid

# ==================== API ENDPOINTS ====================

@router.post("/create-bills")
async def create_bills(
    request: CreateBillRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Create bills for lab tests, pharmacy, and procedures.
    This stores the billing information in the database.
    All final prices are calculated in the backend.
    """
    try:
        effective_facility_id = get_effective_facility_id(current_user, request.facility_id)
        
        # Validate diagnosis exists
        diagnosis = db.query(model.PatientDiagnosis).filter(
            model.PatientDiagnosis.diagnosis_id == request.diagnosis_id,
            model.PatientDiagnosis.facility_id == effective_facility_id,
            model.PatientDiagnosis.is_deleted == False
        ).first()
        
        if not diagnosis:
            raise HTTPException(status_code=404, detail="Diagnosis not found")
        
        # Validate appointment if provided
        if request.appointment_id:
            appointment = db.query(model.Appointment).filter(
                model.Appointment.appointment_id == request.appointment_id
            ).first()
            if not appointment:
                raise HTTPException(status_code=400, detail="Appointment not found")
        
       # Delete existing bills for this diagnosis (if recreating)
        db.query(model.LabBill).filter(
            model.LabBill.diagnosis_id == request.diagnosis_id,
            model.LabBill.facility_id == effective_facility_id
        ).delete()
        db.query(model.PharmacyBill).filter(
            model.PharmacyBill.diagnosis_id == request.diagnosis_id,
            model.PharmacyBill.facility_id == effective_facility_id
        ).delete()
        db.query(model.ProcedureBill).filter(
            model.ProcedureBill.diagnosis_id == request.diagnosis_id,
            model.ProcedureBill.facility_id == effective_facility_id
        ).delete()
        
        # Create Lab Bill
        if request.lab_items:
            lab_subtotal = 0.0
            lab_total_after_item_discounts = 0.0
            lab_item_data = []  # Store processed item data
            
            # Fetch test details and calculate prices with item-level discounts
            for item in request.lab_items:
                # Fetch test details from lab_master
                test = db.query(model.LabMaster).filter(
                    model.LabMaster.test_id == item.test_id,
                    model.LabMaster.facility_id == effective_facility_id,
                    model.LabMaster.is_deleted == False,
                    model.LabMaster.is_active == True
                ).first()
                
                if not test:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Lab test ID {item.test_id} not found or inactive"
                    )
                
                # Get price from lab_master if not provided
                price = item.price if item.price else (float(test.price) if test.price else None)
                if not price:
                    raise HTTPException(
                        status_code=400,
                        detail=f"No price set for test: {test.test_name}"
                    )
                
                # Calculate item price after item-level discount
                item_price_after_discount = calculate_final_price(price, item.discount_percent)
                
                lab_subtotal += price
                lab_total_after_item_discounts += item_price_after_discount
                
                # Store item data for later
                lab_item_data.append({
                    'test_id': item.test_id,
                    'test_name': test.test_name,
                    'remarks': item.remarks,
                    'price': price,
                    'discount_percent': item.discount_percent,
                    'price_after_item_discount': item_price_after_discount
                })
            
            # Apply bill-level discount to the total after item discounts
            lab_total_final = calculate_final_price(lab_total_after_item_discounts, request.lab_discount_percent)
            
            # Calculate final prices for each item (proportional to bill discount)
            bill_discount_multiplier = lab_total_final / lab_total_after_item_discounts if lab_total_after_item_discounts > 0 else 1.0
            
            for item_data in lab_item_data:
                item_data['final_price'] = round(item_data['price_after_item_discount'] * bill_discount_multiplier, 2)
            
            lab_bill = model.LabBill(
                facility_id=effective_facility_id,
                diagnosis_id=request.diagnosis_id,
                patient_id=diagnosis.patient_id,
                bill_date=date.today(),
                subtotal=lab_subtotal,
                discount_percent=request.lab_discount_percent,
                total_amount=lab_total_final,
                paid_amount=0.0,
                payment_status='Pending',
                created_by=current_user.user_id
            )
            db.add(lab_bill)
            db.flush()
            
            # Add lab bill items
            for item_data in lab_item_data:
                lab_item = model.LabBillItem(
                    lab_bill_id=lab_bill.lab_bill_id,
                    test_id=item_data['test_id'],
                    test_name=item_data['test_name'],
                    remarks=item_data['remarks'],
                    price=item_data['price'],
                    discount_percent=item_data['discount_percent'],
                    final_price=item_data['final_price']
                )
                db.add(lab_item)
        
        # Create Pharmacy Bill
        if request.pharmacy_items:
            pharmacy_subtotal = 0.0
            pharmacy_total_after_item_discounts = 0.0
            pharmacy_item_data = []  # Store processed item data
            
            # Calculate prices and fetch medicine details from drug_master
            for item in request.pharmacy_items:
                # Fetch medicine details from drug_master
                medicine = db.query(model.DrugMaster).filter(
                    model.DrugMaster.medicine_id == item.medicine_id,
                    model.DrugMaster.facility_id == effective_facility_id,
                    model.DrugMaster.is_deleted == False,
                    model.DrugMaster.is_active == True
                ).first()
                
                if not medicine:
                    raise HTTPException(
                        status_code=404, 
                        detail=f"Medicine ID {item.medicine_id} not found or inactive"
                    )
                
                # Get price from drug_master if not provided
                unit_price = item.unit_price if item.unit_price else (float(medicine.price) if medicine.price else None)
                if not unit_price:
                    raise HTTPException(
                        status_code=400,
                        detail=f"No price set for medicine: {medicine.medicine_name}"
                    )
                
                # Calculate total_price = quantity * unit_price
                total_price = item.quantity * unit_price
                
                # Calculate price after item-level discount
                item_price_after_discount = calculate_final_price(total_price, item.discount_percent)
                
                pharmacy_subtotal += total_price
                pharmacy_total_after_item_discounts += item_price_after_discount
                
                # Store item data for later
                pharmacy_item_data.append({
                    'medicine_id': item.medicine_id,
                    'medicine_name': medicine.medicine_name,
                    'generic_name': medicine.generic_name,
                    'strength': medicine.strength,
                    'quantity': item.quantity,
                    'unit_price': unit_price,
                    'total_price': total_price,
                    'discount_percent': item.discount_percent,
                    'price_after_item_discount': item_price_after_discount,
                    'dosage_info': item.dosage_info,
                    'food_timing': item.food_timing,
                    'duration_days': item.duration_days
                })
            
            # Apply bill-level discount to the total after item discounts
            pharmacy_total_final = calculate_final_price(pharmacy_total_after_item_discounts, request.pharmacy_discount_percent)
            
            # Calculate final prices for each item (proportional to bill discount)
            bill_discount_multiplier = pharmacy_total_final / pharmacy_total_after_item_discounts if pharmacy_total_after_item_discounts > 0 else 1.0
            
            for item_data in pharmacy_item_data:
                item_data['final_price'] = round(item_data['price_after_item_discount'] * bill_discount_multiplier, 2)
            
            pharmacy_bill = model.PharmacyBill(
                facility_id=effective_facility_id,
                diagnosis_id=request.diagnosis_id,
                patient_id=diagnosis.patient_id,
                bill_date=date.today(),
                subtotal=pharmacy_subtotal,
                discount_percent=request.pharmacy_discount_percent,
                total_amount=pharmacy_total_final,
                paid_amount=0.0,
                payment_status='Pending',
                created_by=current_user.user_id
            )
            db.add(pharmacy_bill)
            db.flush()
            
            # Add pharmacy bill items
            for item_data in pharmacy_item_data:
                pharmacy_item = model.PharmacyBillItem(
                    pharmacy_bill_id=pharmacy_bill.pharmacy_bill_id,
                    medicine_id=item_data['medicine_id'],
                    medicine_name=item_data['medicine_name'],
                    generic_name=item_data['generic_name'],
                    strength=item_data['strength'],
                    quantity=item_data['quantity'],
                    unit_price=item_data['unit_price'],
                    total_price=item_data['total_price'],
                    discount_percent=item_data['discount_percent'],
                    final_price=item_data['final_price'],
                    dosage_info=item_data['dosage_info'],
                    food_timing=item_data['food_timing'],
                    duration_days=item_data['duration_days']
                )
                db.add(pharmacy_item)
        
        # Create Procedure Bill
        if request.procedure_items:
            procedure_subtotal = 0.0
            procedure_total_after_item_discounts = 0.0
            procedure_item_data = []  # Store processed item data
            
            # Calculate prices with item-level discounts
            for item in request.procedure_items:
                # Calculate price after item-level discount
                item_price_after_discount = calculate_final_price(item.price, item.discount_percent)
                
                procedure_subtotal += item.price
                procedure_total_after_item_discounts += item_price_after_discount
                
                # Store item data for later
                procedure_item_data.append({
                    'procedure_text': item.procedure_text,
                    'price': item.price,
                    'discount_percent': item.discount_percent,
                    'price_after_item_discount': item_price_after_discount
                })
            
            # Apply bill-level discount to the total after item discounts
            procedure_total_final = calculate_final_price(procedure_total_after_item_discounts, request.procedure_discount_percent)
            
            # Calculate final prices for each item (proportional to bill discount)
            bill_discount_multiplier = procedure_total_final / procedure_total_after_item_discounts if procedure_total_after_item_discounts > 0 else 1.0
            
            for item_data in procedure_item_data:
                item_data['final_price'] = round(item_data['price_after_item_discount'] * bill_discount_multiplier, 2)
            
            procedure_bill = model.ProcedureBill(
                facility_id=effective_facility_id,
                diagnosis_id=request.diagnosis_id,
                patient_id=diagnosis.patient_id,
                bill_date=date.today(),
                subtotal=procedure_subtotal,
                discount_percent=request.procedure_discount_percent,
                total_amount=procedure_total_final,
                paid_amount=0.0,
                payment_status='Pending',
                created_by=current_user.user_id
            )
            db.add(procedure_bill)
            db.flush()
            
            # Add procedure bill items
            for item_data in procedure_item_data:
                procedure_item = model.ProcedureBillItem(
                    procedure_bill_id=procedure_bill.procedure_bill_id,
                    procedure_text=item_data['procedure_text'],
                    price=item_data['price'],
                    discount_percent=item_data['discount_percent'],
                    final_price=item_data['final_price']
                )
                db.add(procedure_item)
        
        db.commit()
        
        return {
            "status_code": 201,
            "message": "Bills created successfully",
            "data": {
                "diagnosis_id": request.diagnosis_id,
                "lab_items_count": len(request.lab_items),
                "pharmacy_items_count": len(request.pharmacy_items),
                "procedure_items_count": len(request.procedure_items)
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error creating bills: {str(e)}")


@router.get("/payment-summary/{diagnosis_id}", response_model=PaymentSummaryResponse)
async def get_payment_summary(
    diagnosis_id: int,
    facility_id: Optional[int] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get complete payment summary for a diagnosis including:
    - Consultation fee
    - Procedure fees
    - Lab fees
    - Pharmacy fees
    """
    try:
        effective_facility_id = get_effective_facility_id(current_user, facility_id)
        
        # Get diagnosis with patient info
        diagnosis = db.query(model.PatientDiagnosis).join(
            model.Patients, model.PatientDiagnosis.patient_id == model.Patients.id
        ).filter(
            model.PatientDiagnosis.diagnosis_id == diagnosis_id,
            model.PatientDiagnosis.facility_id == effective_facility_id,
            model.PatientDiagnosis.is_deleted == False
        ).first()
        
        if not diagnosis:
            raise HTTPException(status_code=404, detail="Diagnosis not found")
        
        patient = db.query(model.Patients).filter(
            model.Patients.id == diagnosis.patient_id
        ).first()
        
        patient_name = f"{patient.firstname} {patient.lastname}".strip() if patient else "Unknown"
        
        # Get consultation fee
        consultation_fee, consultation_paid = get_consultation_fee(db, diagnosis_id)
        consultation_pending = consultation_fee - consultation_paid
        
        # Get procedure bill
        procedure_bill = db.query(model.ProcedureBill).filter(
            model.ProcedureBill.diagnosis_id == diagnosis_id
        ).first()
        procedure_total = float(procedure_bill.total_amount) if procedure_bill else 0.0
        procedure_paid = float(procedure_bill.paid_amount) if procedure_bill else 0.0
        procedure_pending = procedure_total - procedure_paid
        
        # Get lab bill
        lab_bill = db.query(model.LabBill).filter(
            model.LabBill.diagnosis_id == diagnosis_id
        ).first()
        lab_total = float(lab_bill.total_amount) if lab_bill else 0.0
        lab_paid = float(lab_bill.paid_amount) if lab_bill else 0.0
        lab_pending = lab_total - lab_paid
        
        # Get pharmacy bill
        pharmacy_bill = db.query(model.PharmacyBill).filter(
            model.PharmacyBill.diagnosis_id == diagnosis_id
        ).first()
        pharmacy_total = float(pharmacy_bill.total_amount) if pharmacy_bill else 0.0
        pharmacy_paid = float(pharmacy_bill.paid_amount) if pharmacy_bill else 0.0
        pharmacy_pending = pharmacy_total - pharmacy_paid
        
        # Calculate totals
        total_amount = consultation_fee + procedure_total + lab_total + pharmacy_total
        total_paid = consultation_paid + procedure_paid + lab_paid + pharmacy_paid
        total_pending = total_amount - total_paid
        
        return PaymentSummaryResponse(
            diagnosis_id=diagnosis_id,
            patient_id=diagnosis.patient_id,
            patient_name=patient_name,
            appointment_id=diagnosis.appointment_id,
            consultation_fee=consultation_fee,
            consultation_paid=consultation_paid,
            consultation_pending=consultation_pending,
            procedure_total=procedure_total,
            procedure_paid=procedure_paid,
            procedure_pending=procedure_pending,
            lab_total=lab_total,
            lab_paid=lab_paid,
            lab_pending=lab_pending,
            pharmacy_total=pharmacy_total,
            pharmacy_paid=pharmacy_paid,
            pharmacy_pending=pharmacy_pending,
            total_amount=total_amount,
            total_paid=total_paid,
            total_pending=total_pending
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting payment summary: {str(e)}")


@router.post("/record-payment")
async def record_payment(
    payment: PaymentRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Record a payment for consultation, procedure, lab, or pharmacy.
    Updates the corresponding bill's paid_amount and payment_status.
    """
    try:
        effective_facility_id = get_effective_facility_id(current_user, payment.facility_id)
        
        # Validate diagnosis
        diagnosis = db.query(model.PatientDiagnosis).filter(
            model.PatientDiagnosis.diagnosis_id == payment.diagnosis_id,
            model.PatientDiagnosis.facility_id == effective_facility_id,
            model.PatientDiagnosis.is_deleted == False
        ).first()
        
        if not diagnosis:
            raise HTTPException(status_code=404, detail="Diagnosis not found")
        
        payment_type_lower = payment.payment_type.lower()
        
        # Handle consultation payment
        if payment_type_lower == "consultation":
            if not diagnosis.appointment_id:
                raise HTTPException(status_code=400, detail="No appointment associated with this diagnosis")
            
            appointment = db.query(model.Appointment).filter(
                model.Appointment.appointment_id == diagnosis.appointment_id
            ).first()
            
            if not appointment:
                raise HTTPException(status_code=404, detail="Appointment not found")
            
            appointment.payment_status = True
            appointment.payment_method = payment.payment_method
            appointment.payment_comments = payment.payment_comments
            
            # Update patient payment status
            patient = db.query(model.Patients).filter(
                model.Patients.id == diagnosis.patient_id
            ).first()
            if patient:
                patient.is_paid = True
        
        # Handle procedure payment
        elif payment_type_lower == "procedure":
            procedure_bill = db.query(model.ProcedureBill).filter(
                model.ProcedureBill.diagnosis_id == payment.diagnosis_id
            ).first()
            
            if not procedure_bill:
                raise HTTPException(status_code=404, detail="Procedure bill not found")
            
            procedure_bill.paid_amount = float(procedure_bill.paid_amount or 0) + payment.amount_paid
            
            if procedure_bill.paid_amount >= procedure_bill.total_amount:
                procedure_bill.payment_status = 'Paid'
            elif procedure_bill.paid_amount > 0:
                procedure_bill.payment_status = 'Partial'
            
            procedure_bill.payment_method = payment.payment_method
            procedure_bill.payment_date = datetime.now()
        
        # Handle lab payment
        elif payment_type_lower == "lab":
            lab_bill = db.query(model.LabBill).filter(
                model.LabBill.diagnosis_id == payment.diagnosis_id
            ).first()
            
            if not lab_bill:
                raise HTTPException(status_code=404, detail="Lab bill not found")
            
            lab_bill.paid_amount = float(lab_bill.paid_amount or 0) + payment.amount_paid
            
            if lab_bill.paid_amount >= lab_bill.total_amount:
                lab_bill.payment_status = 'Paid'
            elif lab_bill.paid_amount > 0:
                lab_bill.payment_status = 'Partial'
            
            lab_bill.payment_method = payment.payment_method
            lab_bill.payment_date = datetime.now()
        
        # Handle pharmacy payment
        elif payment_type_lower == "pharmacy":
            pharmacy_bill = db.query(model.PharmacyBill).filter(
                model.PharmacyBill.diagnosis_id == payment.diagnosis_id
            ).first()
            
            if not pharmacy_bill:
                raise HTTPException(status_code=404, detail="Pharmacy bill not found")
            
            pharmacy_bill.paid_amount = float(pharmacy_bill.paid_amount or 0) + payment.amount_paid
            
            if pharmacy_bill.paid_amount >= pharmacy_bill.total_amount:
                pharmacy_bill.payment_status = 'Paid'
            elif pharmacy_bill.paid_amount > 0:
                pharmacy_bill.payment_status = 'Partial'
            
            pharmacy_bill.payment_method = payment.payment_method
            pharmacy_bill.payment_date = datetime.now()
        
        else:
            raise HTTPException(status_code=400, detail="Invalid payment type. Must be: consultation|procedure|lab|pharmacy")
        
        db.commit()
        
        return {
            "status_code": 200,
            "message": f"Payment recorded successfully for {payment.payment_type}",
            "data": {
                "diagnosis_id": payment.diagnosis_id,
                "payment_type": payment.payment_type,
                "amount_paid": payment.amount_paid,
                "payment_method": payment.payment_method
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error recording payment: {str(e)}")


@router.get("/lab-print/{diagnosis_id}", response_model=LabPrintResponse)
async def get_lab_print(
    diagnosis_id: int,
    facility_id: Optional[int] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get lab bill for printing"""
    try:
        effective_facility_id = get_effective_facility_id(current_user, facility_id)
        
        # Get lab bill with items
        lab_bill = db.query(model.LabBill).options(
            joinedload(model.LabBill.items)
        ).filter(
            model.LabBill.diagnosis_id == diagnosis_id,
            model.LabBill.facility_id == effective_facility_id
        ).first()
        
        if not lab_bill:
            raise HTTPException(status_code=404, detail="Lab bill not found")
        
        # Get patient info
        diagnosis = db.query(model.PatientDiagnosis).join(
            model.Patients, model.PatientDiagnosis.patient_id == model.Patients.id
        ).filter(
            model.PatientDiagnosis.diagnosis_id == diagnosis_id
        ).first()
        
        patient = db.query(model.Patients).filter(
            model.Patients.id == diagnosis.patient_id
        ).first()
        
        patient_name = f"{patient.firstname} {patient.lastname}".strip() if patient else "Unknown"
        
        items = [
            LabBillItem(
                test_id=item.test_id,
                test_name=item.test_name,
                remarks=item.remarks,
                price=float(item.price),
                discount_percent=float(item.discount_percent),
                final_price=round(float(item.price) * (1 - float(item.discount_percent) / 100), 2)
            )
            for item in lab_bill.items
        ]
        
        return LabPrintResponse(
            diagnosis_id=diagnosis_id,
            patient_name=patient_name,
            date=lab_bill.bill_date,
            items=items,
            subtotal=float(lab_bill.subtotal),
            discount_percent=float(lab_bill.discount_percent),
            total=float(lab_bill.total_amount)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting lab print: {str(e)}")


@router.get("/pharmacy-print/{diagnosis_id}", response_model=PharmacyPrintResponse)
async def get_pharmacy_print(
    diagnosis_id: int,
    facility_id: Optional[int] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get pharmacy bill for printing"""
    try:
        effective_facility_id = get_effective_facility_id(current_user, facility_id)
        
        # Get pharmacy bill with items
        pharmacy_bill = db.query(model.PharmacyBill).options(
            joinedload(model.PharmacyBill.items)
        ).filter(
            model.PharmacyBill.diagnosis_id == diagnosis_id,
            model.PharmacyBill.facility_id == effective_facility_id
        ).first()
        
        if not pharmacy_bill:
            raise HTTPException(status_code=404, detail="Pharmacy bill not found")
        
        # Get patient info
        diagnosis = db.query(model.PatientDiagnosis).join(
            model.Patients, model.PatientDiagnosis.patient_id == model.Patients.id
        ).filter(
            model.PatientDiagnosis.diagnosis_id == diagnosis_id
        ).first()
        
        patient = db.query(model.Patients).filter(
            model.Patients.id == diagnosis.patient_id
        ).first()
        
        patient_name = f"{patient.firstname} {patient.lastname}".strip() if patient else "Unknown"
        
        items = [
            PharmacyBillItem(
                medicine_id=item.medicine_id,
                medicine_name=item.medicine_name,
                generic_name=item.generic_name,
                strength=item.strength,
                quantity=item.quantity,
                unit_price=float(item.unit_price),
                total_price=float(item.total_price),
                discount_percent=float(item.discount_percent),
                final_price=round(float(item.total_price) * (1 - float(item.discount_percent) / 100), 2),
                dosage_info=item.dosage_info,
                food_timing=item.food_timing,
                duration_days=item.duration_days
            )
            for item in pharmacy_bill.items
        ]
        
        return PharmacyPrintResponse(
            diagnosis_id=diagnosis_id,
            patient_name=patient_name,
            date=pharmacy_bill.bill_date,
            items=items,
            subtotal=float(pharmacy_bill.subtotal),
            discount_percent=float(pharmacy_bill.discount_percent),
            total=float(pharmacy_bill.total_amount)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting pharmacy print: {str(e)}")