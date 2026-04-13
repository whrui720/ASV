import pandas as pd
import json
import os
import numpy as np

def validate_claim():
    """
    Validates the quantitative claim against the specified dataset.
    """
    # --- Parameters derived from the claim and requirements ---
    file_path = r"C:\Users\hrwan\ASV\datasets\citation_test_iris_001_dataset.csv"
    claim_value = 5.84
    target_column_candidates = ['sepal_length', 'sepal length (cm)', 'SepalLengthCm']
    tolerance = 0.01

    result = {}

    try:
        # 1. Load the dataset (detecting format from extension)
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Dataset not found at path: {file_path}")

        _, file_extension = os.path.splitext(file_path)
        
        if file_extension.lower() == '.csv':
            df = pd.read_csv(file_path)
        elif file_extension.lower() in ['.xls', '.xlsx']:
            df = pd.read_excel(file_path)
        elif file_extension.lower() == '.json':
            df = pd.read_json(file_path)
        else:
            raise ValueError(f"Unsupported file format: {file_extension}")

        # 2. Extract relevant numeric values to verify the claim
        target_column = None
        for col in target_column_candidates:
            # Case-insensitive check
            for df_col in df.columns:
                if col.lower() == df_col.lower():
                    target_column = df_col
                    break
            if target_column:
                break
        
        if target_column is None:
            raise KeyError(f"Could not find a suitable column for 'sepal length'. Tried: {target_column_candidates}")

        # Handle missing values and data quality issues
        initial_rows = len(df)
        if initial_rows == 0:
            raise ValueError("Dataset is empty.")
            
        # Convert column to numeric, coercing non-numeric values to NaN
        numeric_series = pd.to_numeric(df[target_column], errors='coerce')
        
        # Drop NaN values for the calculation
        valid_series = numeric_series.dropna()
        valid_rows = len(valid_series)

        if valid_rows == 0:
            raise ValueError(f"No valid numeric data found in column '{target_column}'.")

        # 3. Perform calculations/comparisons as needed
        actual_average = valid_series.mean()

        # Check if the calculated average is within the tolerance of the claimed value
        is_passed = abs(actual_average - claim_value) <= tolerance
        
        # Confidence is based on the proportion of valid, usable data
        confidence = round(valid_rows / initial_rows, 2)

        # 4. Prepare the explanation for the result
        if is_passed:
            explanation = (f"Claim validated. The calculated average sepal length ({actual_average:.2f} cm) "
                           f"is approximately equal to the claimed value of {claim_value} cm "
                           f"within a tolerance of {tolerance}.")
        else:
            explanation = (f"Claim not validated. The calculated average sepal length ({actual_average:.2f} cm) "
                           f"differs from the claimed value of {claim_value} cm "
                           f"by more than the tolerance of {tolerance}.")
        
        if confidence < 1.0:
            explanation += f" Note: Calculation is based on {valid_rows} valid rows out of {initial_rows} total."

        result = {
            "passed": bool(is_passed),
            "confidence": confidence,
            "explanation": explanation
        }

    except Exception as e:
        result = {
            "passed": False,
            "confidence": 0.0,
            "explanation": f"An error occurred during validation: {str(e)}"
        }

    # Print the final result in the specified JSON format
    print(json.dumps(result))

if __name__ == '__main__':
    validate_claim()