import os
import re
import requests

DATASET_DIR = "datasets/"
RSCRIPTS_DIR = "rscripts/"

os.makedirs(DATASET_DIR, exist_ok=True)
os.makedirs(RSCRIPTS_DIR, exist_ok=True)

#extract from list of citations
def extract_dois(citations):
  allfound = []
  for citation in citations:
    searched = re.search(r"https?://\S+", citation)
    if searched:
      print(f"Citation found for: {citation}\n")
      allfound.append(searched.group())
  return allfound

#download from doi link as csv into dataset_dir
def download_csv(doi, download_path):
    try:
        response = requests.get(doi, timeout=10)
        response.raise_for_status()
        filename = os.path.join(download_path, f"{doi.split('/')[-1]}.csv")
        with open(filename, "wb") as file:
            file.write(response.content)
        print(f"Downloaded: {filename}\n")
        return filename
    except requests.exceptions.RequestException as e:
        print(f"Failed to download {doi}: {e}\n")
        return None

def create_r_script(csv_filepath, rscriptpath):
    ds_name = os.path.splitext(os.path.basename(csv_filepath))[0]
    r_file = os.path.join(rscriptpath, f"{ds_name}.R")
    
    #R script content starts here:
    #currently chatgpt example
    r_script = f"""
    # Load necessary libraries
    library(dplyr)
    library(ggplot2)
    library(DataExplorer)

    # Load the dataset
    data <- read.csv("{csv_file.replace(os.sep, '/')}", header = TRUE, stringsAsFactors = FALSE)

    # Quick summary
    print(summary(data))
    print(str(data))

    # DataExplorer report
    create_report(data, output_file = "{dataset_name}_report.html")

    # Example plot
    # Replace 'column_x' and 'column_y' with actual column names
    # ggplot(data, aes(x = column_x, y = column_y)) +
    #    geom_point() +
    #    theme_minimal()
    """
    #R script ends here

    with open(r_file, "w") as file:
        file.write(r_script)
    print(f"Created R script: {r_file}")

def main():
    #assume there is a doi link in some of the citation strings
    citations = []
    
    dois = extract_dois(citations)
    
    for doi in dois:
        csv_file = download_csv(doi, DATASET_DIR)
        if csv_file:
            create_r_script(csv_file, RSCRIPTS_DIR)

if __name__ == "__main__":
    main()