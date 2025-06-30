from citationScraper import get_citation_dict
from sourcefinder import DL_and_create_citation_list
from scriptgen import create_py_scripts

def main():
  pdf_path = 'sample.pdf'
  citation_dict = get_citation_dict(pdf_path)
  citation_list = list(citation_dict.keys()) 
  # test_citationlist = [
  #   "Progress in Transformer Based Language Model",
  #   "PubMed Article Summarization Dataset",
  #   "Stuart, D. et al. Whitepaper: Practical challenges for researchers in data sharing. figshare https://doi.org/10.6084/m9.figshare.5975011(2018)."
  # ]

  DL_and_create_citation_list(citation_list)
  create_py_scripts(citation_list, citation_dict, "pyscripts", "overviews")

if __name__ == "__main__":
  main()