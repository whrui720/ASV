import os
import re
import subprocess
from rapidfuzz import process
import requests
from google.cloud import bigquery

DATASET_DIR = "datasets/"
os.makedirs(DATASET_DIR, exist_ok=True)

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

#extract DOI's from list of citations and save the rest to find separately
def extract_dois(citations, citation_list, download_path):
  needmatch = [] #empty list for citations that need to be matched
  for citation in citations:
    searched = re.search(r"https?://\S+", citation)
    if searched:
      doi_url = searched.group()
      print(f"DOI found for citation: {citation[0:10]}...\n")
      filename = download_doi(doi_url, download_path)
      if filename:
        citation_list.append(filename)
      else: 
        print(f"Error downloading {doi_url}, applying advanced search\n")
        needmatch.append(citation)  #add to needmatch if download fails
    else:
      print(f"DOI not found for citation {citation[0:10]}..., applying advanced search\n")
      needmatch.append(citation)
  return needmatch


#advanced search and download through platform API's using fuzzy search 
def download_kaggle_adv(other, citation_list, download_path, failed_files, match_top=1, score_req = 50):
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
        citation_list.append(downloaded_file)
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

def download_google_adv(other, citation_list, download_path, failed_files, match_top=1, score_req = 50):
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


citations = [
    "Progress in Transformer Based Language Model",
    "PubMed Article Summarization Dataset",
    "Stuart, D. et al. Whitepaper: Practical challenges for researchers in data sharing. figshare https://doi.org/10.6084/m9.figshare.5975011(2018)."
  ]

def DL_and_create_citation_list(citations):
  citation_list = [] #list of citations IN THE SAME ORDER AS DATASETS ARE DOWNLOADED (when sorted by time modified)
  #list of all citations that were not found and downloaded by extract_dois
  advanced_needed = extract_dois(citations, citation_list, DATASET_DIR)

  kaggle_failed = [] #list of citations not found from Kaggle
  all_failed = [] #list of citations not found anywhere (literally just Google)

  for citation in advanced_needed:
    download_kaggle_adv(citation, citation_list, DATASET_DIR, kaggle_failed)
  
  for citation in kaggle_failed:
    download_google_adv(citation, citation_list, DATASET_DIR, all_failed)

  for citation in all_failed:
    print(f"No dataset found for {citation}, discarding")
  
  return citation_list

def main():
  pass

if __name__ == "__main__":
  main()