import fitz  # PyMuPDF
from collections import defaultdict
import re

references_dict = defaultdict(list)

def extract_text(pdf_path):
    """
    Extracts text from all pages of a PDF file.
    """
    full_text = ""

    with fitz.open(pdf_path) as doc:
        for page in doc:
            full_text += page.get_text() + "\n"
    return full_text

def locate_reference(full_text):
    start_index = full_text.lower().find("references")

    if start_index != -1:
        references_text = full_text[start_index:]
    else:
        references_text = "References section not found."

    # TODO: FIND BETTER WAY TO DETERMINE ENDING
    return references_text[:2000]


def parse_reference(ref_text):
    """
    Parse a single string of references into dictionary of ref val : ref line
    """

    references_dict = {}
    current_number = None
    current_ref = []

    # MATCH: "1.", "2."
    reference_pattern = re.compile(r"^(\d+)\.\s(.+)")  

    for line in ref_text.split("\n"):
        line = line.strip()

        # Check if the line starts with a reference number
        match = reference_pattern.match(line)
        if match:
            if current_number is not None:
                references_dict[current_number] = " ".join(current_ref).strip()

            current_number = int(match.group(1)) 
            current_ref = [match.group(2)]
        else:
            if current_number is not None:
                current_ref.append(line)

    if current_number is not None:
        references_dict[current_number] = " ".join(current_ref).strip()

    return references_dict
    
    


def main():
    pdf_path = 'papers/data_sharing.pdf'
    doc = fitz.open(pdf_path)
    text = "\n".join([page.get_text("text") for page in doc])
    

    ref_text = locate_reference(text)

    ref_dict = parse_reference(ref_text)

    with open('output.txt', 'w') as file:
        for key, ref in ref_dict.items():
            file.write(f"KEY: {key} |||| VAL: {ref}\n\n")
            # file.write(ref_text)



if __name__ == '__main__':
    main()


    
