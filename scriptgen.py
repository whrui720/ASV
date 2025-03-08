from openai import OpenAI
import os
import zipfile
import tempfile
import subprocess
import json

from sourcefinder import DL_and_create_citation_dict

''' Pseudocode for Deepseek calls:
  Given dictionary data structure A that has keys citations (string) and values (list of statistical claims, which are strings),
  and dictionary B that has keys citations (strings) and values (csv files, e.g. the underlying dataset for the citation)
  For each citation:
    1. Use Deepseek to generate the py script for validating the list of claims 
      (also use DeepSeek to check if this citation is statistical/worth checking using this script) associated with this citation 
      (this will need data structure input), SAVE generated scripts for download
    2. Run the py script executable and feed results back into next Deepseek call; 
      generate holistic data overview (save as well)
  
  Return zipfile including:
    A. File of all found citations (already saved, don't need to worry about this here)
    B. File of all py scripts (should be in the same format as all citations) 
    C. Holistic overview for all citations
'''

PYSCRIPTS_DIR = "pyscripts/"
os.makedirs(PYSCRIPTS_DIR, exist_ok=True)

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


def LLM_create_scripts(prompt):
  client = OpenAI(api_key="<DeepSeek API Key>", base_url="https://api.deepseek.com")
  response = client.chat.completions.create(
    model="deepseek-chat",
    messages=[
        {"role": "system", "content": "You are a helpful assistant that generates Python scripts for validating statistical claims."},
        {"role": "user", "content": "Hello"},
    ],
    stream=False
  )

  print(response.choices[0].message.content)


  def main():
   pass

  if __name__ == "__main__":
    main()