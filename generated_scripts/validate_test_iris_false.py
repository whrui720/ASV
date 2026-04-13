import pandas as pd
import json
import os

def validate_claim():
    """
    Validates the claim that the dataset contains a specific number of distinct iris species.
    """
    # --- Configuration ---
    # The quantitative claim to be verified.
    claim_value = 5
    # Path to the dataset.
    file_path = r"C:\Users\hrwan\ASV\datasets\citation_test_iris_001_dataset.csv"
    # Potential column names for the species information.
    potential_species_columns = ['species', 'variety', 'class', 'name']

    try:
        # --- 1. Load the dataset ---
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Dataset not found at the specified path: {file_path}")

        _, file_extension = os.path.splitext(file_path)
        file_extension = file_extension.lower()

        if file_extension == '.csv':
            df = pd.read_csv(file_path)
        elif file_extension in ['.xls', '.xlsx']:
            df = pd.read_excel(file_path)
        elif file_extension == '.json':
            df = pd.read_json(file_path)
        else:
            raise ValueError(f"Unsupported file format: '{file_extension}'")

        # --- 2. Extract relevant values ---
        # Find the species column, trying a case-insensitive match.
        target_column = None
        df_columns_lower = {col.lower(): col for col in df.columns}
        for col_name in potential_species_columns:
            if col_name in df_columns_lower:
                target_column = df_columns_lower[col_name]
                break
        
        if target_column is None:
            raise ValueError(f"Could not find a species-related column. Checked for: {potential_species_columns}")

        # Handle missing values and calculate data quality for confidence score
        total_rows = len(df)
        non_null_species = df[target_column].dropna()
        valid_rows = len(non_null_species)

        if valid_rows == 0:
            raise ValueError(f"The identified species column '{target_column}' contains no valid data.")

        # --- 3. Perform calculations/comparisons ---
        # Get the number of unique species from the non-null data.
        distinct_species_count = non_null_species.nunique()

        # Compare the actual count with the claimed value.
        is_passed = (distinct_species_count == claim_value)

        # Calculate confidence based on the proportion of non-missing data in the relevant column.
        confidence = round(valid_rows / total_rows, 2) if total_rows > 0 else 0.0

        # --- 4. Prepare the explanation ---
        if is_passed:
            explanation = f"Validation passed: The dataset contains exactly {distinct_species_count} distinct species, which matches the claimed {claim_value}."
        else:
            explanation = f"Validation failed: The dataset contains {distinct_species_count} distinct species, which does not match the claimed {claim_value}."

        result = {
            "passed": is_passed,
            "confidence": confidence,
            "explanation": explanation
        }

    except Exception as e:
        # Catch any error during the process and format a failure response.
        result = {
            "passed": False,
            "confidence": 0.0,
            "explanation": f"An error occurred during validation: {str(e)}"
        }

    # --- 5. Print the final result in JSON format ---
    print(json.dumps(result))

if __name__ == "__main__":
    validate_claim()