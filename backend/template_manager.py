import pandas as pd
from models import db, SupplierTemplate, OperationExpense
import os

def process_file(file_path, supplier_name):
    """
    Processes an uploaded file using a supplier template.
    """
    template = SupplierTemplate.query.filter_by(supplier_name=supplier_name).first()
    if not template:
        raise ValueError(f"Template for supplier '{supplier_name}' not found.")

    _, file_extension = os.path.splitext(file_path)
    if file_extension == '.csv':
        df = pd.read_csv(file_path)
    elif file_extension in ['.xls', '.xlsx']:
        df = pd.read_excel(file_path)
    else:
        raise ValueError(f"Unsupported file format: {file_extension}")

    # Rename columns based on the template
    df.rename(columns=template.column_mapping, inplace=True)

    # Insert data into the database
    for _, row in df.iterrows():
        expense = OperationExpense(
            license_plate=row.get('license_plate'),
            transaction_date=row.get('transaction_date'),
            expense_type=row.get('expense_type'),
            supplier=row.get('supplier'),
            details=row.get('details'),
            quantity=row.get('quantity'),
            cost=row.get('cost')
        )
        db.session.add(expense)

    db.session.commit()

    return df
