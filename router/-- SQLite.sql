-- Add payment method field to appointments table
ALTER TABLE appointment
ADD COLUMN payment_method VARCHAR(50) DEFAULT 'Cash';

-- Or add it to patients table if payment is per patient
ALTER TABLE patients 
ADD COLUMN payment_method VARCHAR(50) DEFAULT 'Cash';

-- Add payment status field
ALTER TABLE patients 
ADD COLUMN is_paid BOOLEAN DEFAULT FALSE;

-- Update existing records with sample data for testing
UPDATE appointment
SET payment_method = CASE 
    WHEN MOD(appointment_id, 4) = 0 THEN 'UPI'
    WHEN MOD(appointment_id, 4) = 1 THEN 'Debit Card/Credit Card' 
    WHEN MOD(appointment_id, 4) = 2 THEN 'Net Banking'
    ELSE 'Cash'
END;