from openai import OpenAI

''' Pseudocode for Deepseek calls:
  For each citation:
    1. Use Deepseek to generate the py script for validating the list of claims 
      (also use DeepSeek to check if this citation is statistical/worth checking using this script) associated with this citation 
      (this will need data structure input), SAVE generated scripts for download
    2. Run the py script executable and feed results back into next Deepseek call; 
      generate holistic data overview (save as well)
    3. Return zipfile including:
      A. File of all found citations 
      B. File of all py scripts (should be in the same format as all citations) 
      C. Holistic overview for all citations
'''

def LLM_create_scripts(prompt):
  client = OpenAI(api_key="<DeepSeek API Key>", base_url="https://api.deepseek.com")
  response = client.chat.completions.create(
    model="deepseek-chat",
    messages=[
        {"role": "system", "content": "You are a helpful assistant"},
        {"role": "user", "content": "Hello"},
    ],
    stream=False
  )

  print(response.choices[0].message.content)


  def main():
   pass

  if __name__ == "__main__":
    main()