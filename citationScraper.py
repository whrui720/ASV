import requests
from pdfminer.high_level import extract_text
import re

# def download_pdf(url, save_path):
#     """Downloads a PDF from a URL and saves it locally."""
#     response = requests.get(url)
#     if response.status_code == 200:
#         with open(save_path, 'wb') as file:
#             file.write(response.content)
#         print(f"PDF downloaded successfully: {save_path}")
#     else:
#         print("Failed to download PDF")

def find_superscripts(text, context_size=5):
    pattern = r"(?<!\s)(\d+)(?!\s)"
    
    with open("superscripts.txt", "w", encoding="utf-8") as f:
        matches = re.finditer(pattern, text)
        for match in matches:
            start, end = match.start(), match.end()
            context = text[max(0, start - context_size): min(len(text), end + context_size)]
            f.write(f"Match: '{match.group()}' at {start}-{end}, Context: '{context}'\n")

def extract_pdf_text(pdf_path):
    """Extracts text from a PDF using pdfminer.six."""
    return extract_text(pdf_path)

# pdf_url = "https://citeseerx.ist.psu.edu/document?repid=rep1&type=pdf&doi=417f55320080fea71d491a18318dad6572b2fa8c"
local_pdf_path = "sample.pdf" # example article that is pinned in discord (data sharing)

# download_pdf(pdf_url, local_pdf_path)

if __name__ == '__main__':
    pdf_text = extract_pdf_text(local_pdf_path)
    
    with open("output.txt", "w") as file:
        file.write(pdf_text)
        
    find_superscripts(pdf_text)