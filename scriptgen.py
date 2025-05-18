from openai import OpenAI
import os
import io
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

def LLM_create_script(prompt, chat_history):
  client = OpenAI(api_key="sk-d0d853f9e0964cbb800e58412e338d8d", base_url="https://api.deepseek.com")

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
    return result.stdout if result.returncode == 0 else result.stderr
  except Exception as e:
      return str(e)

def create_py_scripts(citation_list, citation_dict, pyscriptpath, overviewpath):
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

      scriptgen_prompt = (f"For a csv dataset titled {curr_citation}, filepath {file_path}, .info() returning {info_str}, and .describe returning {curr_csv.describe().to_dict()}, "
               f"create a python script to validate each claim within this list: {curr_claims}. Only generate python code, nothing else.")
      
      # Initialize chat history
      chat_history = [
        {"role": "system", "content": "You are a helpful assistant that generates Python scripts for validating statistical claims."}
      ]

      script_content = LLM_create_script(scriptgen_prompt, chat_history)
      script_filename = os.path.join(pyscriptpath, f"validate_{curr_citation.replace(' ', '_')}.py")
      with open(script_filename, "w") as script_file:
          script_file.write(script_content)

      script_results = execute_script(script_filename) #execute the script in subprocess (the created DeepSeek script should open the csv from the right filepath because it was passed in prompt)

      scriptresult_prompt = (f"Here are the results of the previous scripts: {script_results}, validate whether each claim is statistically valid or not. "
                             "Iterate through the claims one by one, and conclude with a holistic overview of the citation source.")
      
      final_llm_overview = LLM_create_script(scriptresult_prompt, chat_history) #this contains a statistical validation of each claim + holistic overview of the citation source

      overview_filename = os.path.join(overviewpath, f"overview_{curr_citation.replace(' ', '_')}.txt")
      with open(overview_filename, "w") as overview_file:
        overview_file.write(final_llm_overview)

      i = i + 1

  def main():
    test_citationlist = [
      "Progress in Transformer Based Language Model",
      "PubMed Article Summarization Dataset",
      "Stuart, D. et al. Whitepaper: Practical challenges for researchers in data sharing. figshare https://doi.org/10.6084/m9.figshare.5975011(2018)."
    ]
   

    pass

  if __name__ == "__main__":
    main()