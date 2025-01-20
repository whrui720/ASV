import os
import re
import subprocess
from rapidfuzz import process
import requests

DATASET_DIR = "datasets/"
RSCRIPTS_DIR = "rscripts/"

os.makedirs(DATASET_DIR, exist_ok=True)
os.makedirs(RSCRIPTS_DIR, exist_ok=True)

#extract DOI's from list of citations and save the rest to find separately
def extract_dois(citations):
  doifound = [] #empty list for citations with DOI
  needmatch = [] #empty list for citations that need to be matched
  for citation in citations:
    searched = re.search(r"https?://\S+", citation)
    if searched:
      print(f"DOI found for citation: {citation[0:10]}...\n")
      doifound.append(searched.group())
    else:
      print(f"DOI failed for citation {citation[0:10]}..., applying advanced search\n")
  return doifound, needmatch

#download from doi link as csv into dataset_dir
def download_doi(doi, download_path):
  try:
    response = requests.get(doi, timeout=10)
    response.raise_for_status()
    filename = os.path.join(download_path, f"{doi.split('/')[-1]}.csv")
    with open(filename, "wb") as file:
      file.write(response.content)
    print(f"DOI Downloaded: {filename}\n")
    return filename
  except requests.exceptions.RequestException as e:
    print(f"Failed to download {doi}: {e}\n")
    return None

#advanced search and download through platform API's using fuzzy search 
def download_adv(other, download_path, match_top=3):
  try:
    #search kaggle (based on 'keyword', putting the entire citation in, assuming this works like the search bar in kaggle); subprocess required to automate CLI
    search_command = f"kaggle datasets list -s \"{other}\" --csv"
    search_results = subprocess.check_output(search_command, shell=True).decode('utf-8')
    
    #parse csv
    lines = search_results.strip().split('\n')[1:]
    datasets = [line.split(',')[0] for line in lines if line]
    
    if not datasets:
      print(f"No datasets found for: {other}")
      return None
    
    #fuzzy search on found databases
    matches = process.extract(other, datasets, limit=top_n)
    
    #download best matches
    downloaded_files = []
    for match in matches:
      dataset_id, score, _ = match
      print(f"Match found: {dataset_id} with score: {score}")
      
      download_command = f'kaggle datasets download -d "{dataset_id}" -p "{download_path}"'
      subprocess.run(download_command, shell=True, check=True)
      
      #assumes zip file for download
      downloaded_file = os.path.join(download_path, dataset_id.split('/')[-1])
      downloaded_files.append(downloaded_file)
    
    print(f"Downloaded files: {downloaded_files}")
    return downloaded_files

  except subprocess.CalledProcessError as e:
    print(f"Failed to execute Kaggle CLI command: {e}")
  except requests.exceptions.RequestException as e:
    print(f"Request error during download: {e}")
  except Exception as e:
    print(f"An unexpected error occurred: {e}")
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
  
  dois, others = extract_dois(citations)
  
  for doi in dois:
    csv_file = download_doi(doi, DATASET_DIR)
    if csv_file:
      create_r_script(csv_file, RSCRIPTS_DIR)

  for other in others:
    csv_file = download_adv(other, DATASET_DIR)
    if csv_file:
      create_r_script(csv_file, RSCRIPTS_DIR)

if __name__ == "__main__":
  main()