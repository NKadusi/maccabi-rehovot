from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.types import JSON

db = SQLAlchemy()

class Vehicle(db.Model):
    __tablename__ = 'vehicles'
    license_plate = db.Column(db.String, primary_key=True)
    employee_id = db.Column(db.String)
    employee_name = db.Column(db.String)
    cost_center = db.Column(db.String)
    manufacturer = db.Column(db.String)
    model = db.Column(db.String)
    engine_type = db.Column(db.String)
    leasing_company = db.Column(db.String)
    contract_start_date = db.Column(db.Date)
    contract_end_date = db.Column(db.Date)

class OperationExpense(db.Model):
    __tablename__ = 'operations_expenses'
    id = db.Column(db.Integer, primary_key=True)
    license_plate = db.Column(db.String, db.ForeignKey('vehicles.license_plate'))
    transaction_date = db.Column(db.DateTime)
    expense_type = db.Column(db.String)
    supplier = db.Column(db.String)
    details = db.Column(db.String)
    quantity = db.Column(db.Float)
    cost = db.Column(db.Float)

class SupplierTemplate(db.Model):
    __tablename__ = 'supplier_templates'
    id = db.Column(db.Integer, primary_key=True)
    supplier_name = db.Column(db.String, unique=True)
    column_mapping = db.Column(db.JSON)
