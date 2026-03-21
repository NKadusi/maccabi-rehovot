from flask import Flask, render_template, request, jsonify, redirect, url_for, send_file
from models import db, Vehicle, OperationExpense, SupplierTemplate
from template_manager import process_file
from presentation_generator import generate_presentation
import os
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from sqlalchemy import func
from io import BytesIO

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///fleet.db'
app.config['UPLOAD_FOLDER'] = 'uploads'
db.init_app(app)

with app.app_context():
    db.create_all()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/presentation')
def download_presentation():
    prs = generate_presentation()
    output = BytesIO()
    prs.save(output)
    output.seek(0)
    return send_file(output, as_attachment=True, download_name='fleet_report.pptx')

@app.route('/dashboard')
def dashboard():
    total_vehicles = Vehicle.query.count()
    electric_vehicles = Vehicle.query.filter(Vehicle.engine_type.in_(['חשמלי מלא', 'PHEV'])).count()
    ev_percentage = (electric_vehicles / total_vehicles) * 100 if total_vehicles > 0 else 0
    
    return render_template('dashboard.html', 
                           total_vehicles=total_vehicles,
                           ev_percentage=ev_percentage)

@app.route('/dashboard/cost-trend')
def cost_trend_data():
    twelve_months_ago = date.today() - relativedelta(months=12)
    
    expenses = db.session.query(
        func.strftime('%Y-%m', OperationExpense.transaction_date).label('month'),
        OperationExpense.expense_type,
        func.sum(OperationExpense.cost)
    ).filter(OperationExpense.transaction_date >= twelve_months_ago)\
     .group_by('month', OperationExpense.expense_type)\
     .order_by('month')\
     .all()

    labels = sorted(list(set([e[0] for e in expenses])))
    
    datasets = {}
    for month, expense_type, total_cost in expenses:
        if expense_type not in datasets:
            datasets[expense_type] = {
                'label': expense_type,
                'data': [0] * len(labels),
                'fill': False,
                'tension': 0.1
            }
        
        idx = labels.index(month)
        datasets[expense_type]['data'][idx] = total_cost

    return jsonify({'labels': labels, 'datasets': list(datasets.values())})


@app.route('/dashboard/manufacturer-distribution')
def manufacturer_distribution_data():
    distribution = db.session.query(Vehicle.manufacturer, func.count(Vehicle.manufacturer))\
                             .group_by(Vehicle.manufacturer)\
                             .all()
    
    labels = [d[0] for d in distribution]
    values = [d[1] for d in distribution]
    
    return jsonify({'labels': labels, 'values': values})


@app.route('/expenses')
def list_expenses():
    expenses = OperationExpense.query.all()
    return render_template('expenses.html', expenses=expenses)

@app.route('/vehicles')
def list_vehicles():
    vehicles = Vehicle.query.all()
    return render_template('vehicles.html', vehicles=vehicles)

@app.route('/vehicle/new')
def new_vehicle():
    return render_template('vehicle_form.html')

@app.route('/vehicle/edit/<license_plate>')
def edit_vehicle(license_plate):
    vehicle = Vehicle.query.get(license_plate)
    return render_template('vehicle_form.html', vehicle=vehicle)

@app.route('/vehicle/save', methods=['POST'])
def save_vehicle():
    license_plate = request.form.get('license_plate')
    vehicle = Vehicle.query.get(license_plate)
    if not vehicle:
        vehicle = Vehicle()
        vehicle.license_plate = license_plate
    
    vehicle.employee_id = request.form.get('employee_id')
    vehicle.employee_name = request.form.get('employee_name')
    vehicle.cost_center = request.form.get('cost_center')
    vehicle.manufacturer = request.form.get('manufacturer')
    vehicle.model = request.form.get('model')
    vehicle.engine_type = request.form.get('engine_type')
    vehicle.leasing_company = request.form.get('leasing_company')
    
    start_date_str = request.form.get('contract_start_date')
    if start_date_str:
        vehicle.contract_start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        
    end_date_str = request.form.get('contract_end_date')
    if end_date_str:
        vehicle.contract_end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()

    db.session.add(vehicle)
    db.session.commit()
    return redirect(url_for('list_vehicles'))

@app.route('/vehicle/delete/<license_plate>')
def delete_vehicle(license_plate):
    vehicle = Vehicle.query.get(license_plate)
    db.session.delete(vehicle)
    db.session.commit()
    return redirect(url_for('list_vehicles'))

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return 'No file part', 400
    file = request.files['file']
    if file.filename == '':
        return 'No selected file', 400
    if file:
        supplier_name = request.form.get('supplier_name')
        if not supplier_name:
            return 'Supplier name is required', 400
            
        filename = file.filename
        if not os.path.exists(app.config['UPLOAD_FOLDER']):
            os.makedirs(app.config['UPLOAD_FOLDER'])
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)

        try:
            processed_data = process_file(file_path, supplier_name)
            return processed_data.to_json(orient='records')
        except ValueError as e:
            return str(e), 400


@app.route('/template', methods=['POST'])
def create_template():
    data = request.get_json()
    if not data or 'supplier_name' not in data or 'column_mapping' not in data:
        return 'Invalid data', 400

    template = SupplierTemplate(
        supplier_name=data['supplier_name'],
        column_mapping=data['column_mapping']
    )
    db.session.add(template)
    db.session.commit()
    return 'Template created successfully', 201

if __name__ == '__main__':
    app.run(debug=True)
