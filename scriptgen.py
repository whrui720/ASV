from openai import OpenAI
import os
import io
import re
import zipfile
import tempfile
import subprocess
import json
import pandas as pd

from sourcefinder import DL_and_create_citation_list
from citationScraper import get_citation_dict

''' Pseudocode for Deepseek calls:
  Given dictionary data structure A that has keys citations (string) and values (list of statistical claims, which are strings),
  and file structure B that matches the list of citations (strings) in order with corresponding datasets within the 
  datasets folder (csv files, e.g. the underlying dataset for the citation)
  For each citation:
    1. Use Deepseek to generate the py script for validating the list of claims 
      (also use DeepSeek to check if this citation is statistical/worth checking using this script TODO 
      associated with this citation (this will need data structure input), CHECK TODO AND SAVE generated scripts for download
    2. Run the py script executable and feed results back into next Deepseek call; 
      generate holistic data overview (save as well)
  
  Return zipfile including:
    A. File of all found citations (already saved, don't need to worry about this here)
    B. File of all py scripts (should be in the same format as all citations) 
    C. Holistic overview for all citations
'''
PYSCRIPTS_DIR = "pyscripts/"
os.makedirs(PYSCRIPTS_DIR, exist_ok=True)

DATASET_DIR = "datasets/"
os.makedirs(DATASET_DIR, exist_ok=True)

OVERVIEW_DIR = "overviews/"
os.makedirs(OVERVIEW_DIR, exist_ok=True)

def sanitize_filename(name):
    return re.sub(r'[^\w\-_.]', '_', name)

def LLM_create_script(prompt, chat_history):
  client = OpenAI(api_key="sk-7ad418e8f9d34fa6a359a8982f1d8618", base_url="https://api.deepseek.com")

  chat_history.append({"role": "user", "content": prompt})

  response = client.chat.completions.create(
    model="deepseek-chat",
    messages=chat_history
    #stream = false
  )

  script_content = response.choices[0].message.content
  chat_history.append({"role": "assistant", "content": script_content})

  return script_content

def execute_script(script_path):
  try:
    result = subprocess.run(
        ["python", script_path], capture_output=True, text=True
    )
    if result.returncode == 0:
        return result.stdout
    else:
        raise RuntimeError(f"Error executing {script_path}: {result.stderr}")
  except Exception as e:
      raise RuntimeError(f"Exception during script execution: {e}")

def create_py_scripts(citation_list, citation_dict):
  print("Creating Python scripts for statistical validation of claims...")
  i = 0 # iteration count through citation list 
  for filename in os.listdir(DATASET_DIR):
    file_path = os.path.join(DATASET_DIR, filename)
    if os.path.isfile(file_path): #this is where we can check for file type
      curr_citation = citation_list[i]
      curr_claims = citation_dict[curr_citation]
      curr_csv = pd.read_csv(file_path)
      buffer = io.StringIO()
      curr_csv.info(buf=buffer)
      info_str = buffer.getvalue()

      scriptgen_prompt = (f"For a csv dataset titled {curr_citation}, filepath '{file_path}', .info() returning {info_str}, and .describe returning {curr_csv.describe().to_dict()}, "
               f"create a python script that opens the dataset and validates each claim within this list: {curr_claims}. Only generate python code, nothing else, without ```python markers")
      print(scriptgen_prompt)
      # Initialize chat history
      chat_history = [
        {"role": "system", "content": "You are a helpful assistant that generates Python scripts for validating statistical claims."}
      ]
      print(f"Generating script for {curr_citation}...")
      script_content = LLM_create_script(scriptgen_prompt, chat_history)
      print("Script generated")
      safe_name = sanitize_filename(curr_citation)
      script_filename = os.path.join(PYSCRIPTS_DIR, f"validate_{safe_name}.py")
      with open(script_filename, "w") as script_file:
          script_file.write(script_content)
      
      try:
          script_results = execute_script(script_filename) #execute the script in subprocess (the created DeepSeek script should open the csv from the right filepath because it was passed in prompt)
      except Exception as e:
          print(e)
          break

      scriptresult_prompt = (f"Here are the results of the previous scripts: {script_results}, validate whether each claim is statistically valid or not. "
                             "Iterate through the claims one by one, and conclude with a holistic overview of the citation source.")
      
      print(f"Generating overview for {curr_citation}...")
      final_llm_overview = LLM_create_script(scriptresult_prompt, chat_history) #this contains a statistical validation of each claim + holistic overview of the citation source
      print("Overview generated")
      safe_name = sanitize_filename(curr_citation)
      overview_filename = os.path.join(OVERVIEW_DIR, f"overview_{safe_name}.txt")
      with open(overview_filename, "w") as overview_file:
        overview_file.write(final_llm_overview)

      i = i + 1

def main():
  pdf_path = 'sample.pdf'
  # citation_dict = get_citation_dict(pdf_path)
  citation_dict = {
    # "Progress in Transformer Based Language Model": [
    #     "Transformer-based architectures have reduced training time by over 40% compared to traditional RNN models.",
    #     "Recent work shows that attention mechanisms outperform convolutional models on large-scale NLP benchmarks.",
    #     "Pre-trained language models now achieve over 90% accuracy on GLUE tasks with minimal fine-tuning.",
    #     "The number of transformer parameters has increased tenfold since 2019, with corresponding gains in language understanding.",
    #     "Transformer models have enabled near-human performance on question-answering benchmarks like SQuAD 2.0."
    # ],
    # "PubMed Article Summarization Dataset": [
    #     "Over 85% of medical researchers preferred using the PubMed dataset for abstract summarization tasks.",
    #     "The dataset contains more than 200,000 article-summary pairs curated from peer-reviewed biomedical publications.",
    #     "Summarization models trained on PubMed achieve a ROUGE-L score above 45 on average.",
    #     "PubMed abstracts have an average length of 250 words, making them ideal for neural summarization models.",
    #     "Use of the PubMed dataset has increased by 300% in NLP research papers since its release."
    # ],
    # "Stuart, D. et al. Whitepaper: Practical challenges for researchers in data sharing. figshare https://doi.org/10.6084/m9.figshare.5975011(2018).": [
    #     "A recent whitepaper identified that over 60% of researchers face institutional barriers when attempting to share data.",
    #     "The report highlights that legal uncertainty and lack of infrastructure are primary obstacles to effective data sharing.",
    #     "Researchers in the EU reported data-sharing compliance issues at nearly twice the rate of their US counterparts.",
    #     "Over 70% of survey respondents expressed concern about data misuse in open-access repositories.",
    #     "The whitepaper recommends centralized institutional support to mitigate data-sharing challenges."
    # ]
    "CORGIS US Weekly Weather Dataset 2016 (https://corgis-edu.github.io/corgis/csv/weather/)": [
        "Weeks with higher average temperatures have lower average precipitation.",
        "The week with the highest average temperature in each city also has above-average precipitation.",
        "Southern states have higher average weekly temperatures than northern states in winter months.",
        "Coastal cities have higher average precipitation than inland cities.",
        "Average weekly temperatures are highest in July and August for most cities.",
        "Precipitation is highest in the spring months (March–May) for the majority of cities.",
        "The average wind speed is higher in the Midwest than in the Southeast.",
        "Weeks with higher wind speeds are associated with lower minimum temperatures.",
        "The city with the highest recorded weekly maximum temperature in 2016 is located in a southwestern state.",
        "The lowest weekly minimum temperature recorded in the dataset occurred in a northern state during January or February.",
        "Larger cities experience higher average temperatures than smaller cities in the same state.",
        "The range of weekly temperatures is greater in northern states than in southern states.",
        "The standard deviation of weekly precipitation is higher in the Pacific Northwest than in the Southwest."
    ]
  }
  # citation_list = list(citation_dict.keys()) 
  # print(citation_dict)
  citation_list = [
    "CORGIS US Weekly Weather Dataset 2016 (https://corgis-edu.github.io/corgis/csv/weather/)"
  ]

  # DL_and_create_citation_list(citation_list)
  create_py_scripts(citation_list, citation_dict)

if __name__ == "__main__":
  main()