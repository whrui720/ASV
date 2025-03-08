import os
import re
import subprocess
from rapidfuzz import process
import requests
from google.cloud import bigquery

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
      needmatch.append(citation)
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
def download_kaggle_adv(other, download_path, failed_files, match_top=1, score_req = 50):

  print("fuzzy search on")
  try:
    print("finding through Kaggle...")
    #search kaggle (based on 'keyword', putting the entire citation in, assuming this works like the search bar in kaggle); subprocess required to automate CLI
    search_command = f"kaggle datasets list -s \"{other}\" --csv"
    search_results = subprocess.check_output(search_command, shell=True).decode('utf-8')
    print(f"SEARCH RESULTS: {search_results}")
    #parse csv
    lines = search_results.strip().split('\n')[2:]
    print(f"LINES: {lines}")
    datasets = [line.split(',')[0] for line in lines if line]
    print(f"DATASETS: {datasets}")
    if not datasets:
      print(f"No datasets found for: {other}, saving to try on Google")
      failed_files.append(other)
      return None
    
    #fuzzy search on found databases
    matches = process.extract(other, datasets, limit=match_top)
    print(f"MATCHES: {matches}")
    #download best matches
    downloaded_files = []
    total_matches = 0
    #check the total number of matches per search, if none pass the score req, save into failed_files
    for match in matches:
      dataset_id, score, _ = match
      print(f"Match found: {dataset_id} with score: {score}")
      if(score > score_req):
        total_matches += 1
        download_command = f'kaggle datasets download -d "{dataset_id}" -p "{download_path}"'
        subprocess.run(download_command, shell=True, check=True)
        
        #assumes zip file for download
        downloaded_file = os.path.join(download_path, dataset_id.split('/')[-1])
        downloaded_files.append(downloaded_file)

    if total_matches == 0:
      print(f"No matches meeting score req of: {score}, saving to try on Google")
      failed_files.append(other)  
      return None

    print(f"Downloaded Kaggle files: {downloaded_files}")
    return downloaded_files

  except subprocess.CalledProcessError as e:
    print(f"Failed to execute Kaggle CLI command: {e}")
  except requests.exceptions.RequestException as e:
    print(f"Request error during download: {e}")
  except Exception as e:
    print(f"An unexpected error occurred: {e}")
  return None

def download_google_adv(other, download_path, failed_files, match_top=1, score_req = 50):
  client = bigquery.Client()
  project_id = "bigquery-public-data"  #Could be another group of datasets
  datasets = client.list_datasets(project=project_id)
  matching_datasets = [dataset.dataset_id for dataset in datasets if other.lower() in dataset.dataset_id.lower()]
  matching_datasets = matching_datasets[:match_top]

  if not matching_datasets:
        print(f"No matching datasets found for '{other}'.")
        return

  os.makedirs(download_path, exist_ok=True)
  print(f"Top {match_top} matching datasets: {matching_datasets}")

  #Iterate over matching datasets and retrieve tables
  for dataset in matching_datasets:
      try:
          tables = list(client.list_tables(f"{project_id}.{dataset}"))
          
          for table in tables:
              table_ref = f"{project_id}.{dataset}.{table.table_id}"
              print(f"Downloading: {table_ref}")

              #Run query to get data, 1000 rows or whatever sample is necessary
              query = f"SELECT * FROM `{table_ref}` LIMIT 1000"
              query_job = client.query(query)
              results = query_job.to_dataframe()

              csv_filename = f"{dataset}_{table.table_id}.csv"
              csv_path = os.path.join(download_path, csv_filename)
              results.to_csv(csv_path, index=False)

              print(f"Saved: {csv_path}")

      except Exception as e:
          print(f"Failed to download dataset '{dataset}': {str(e)}")
          failed_files.append(dataset)

  print("Download from Google BigQuery complete.")

def create_py_script(csv_filepath, pyscriptpath, input_script):
  ds_name = os.path.splitext(os.path.basename(csv_filepath))[0]
  py_file = os.path.join(pyscriptpath, f"{ds_name}.R")
  


  #py script content starts here:
  #currently chatgpt example
  # py_script = f"""{input_script}
  
  # """
  # #R script ends here

  # with open(py_file, "w") as file:
  #   file.write(py_script)
  # print(f"Created py script: {py_file}")

  

def main():

  citations = [
    "Progress in Transformer Based Language Model",
    "PubMed Article Summarization Dataset",
    "Stuart, D.  et al. Whitepaper: Practical challenges for researchers in data sharing. figshare https://doi.org/10.6084/m9.figshare.5975011(2018)."
  ]

  dois, others = extract_dois(citations)

  print(f"{others}")
  
  for doi in dois:
    csv_file = download_doi(doi, DATASET_DIR)

  kaggle_failed = []
  all_failed = []
  for other in others:
    csv_file, _ = download_kaggle_adv(other, DATASET_DIR, kaggle_failed)
  
  for data in kaggle_failed:
    pass #TODO

if __name__ == "__main__":
  main()