from pdfminer.high_level import extract_text
from collections import defaultdict
import re

references_dict = defaultdict(list)

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
    
def find_superscripts(text, ref_dict, max_numeric_ratio=0.4, max_digits=2):
    """Finds potential superscript citations in the text."""
    
    def find_sentence_boundaries(text, index):
        """Finds the sentence boundaries by extending backward to the previous period or newline
        and forward to the next period or newline."""
        
        # Find the last period or newline before the index
        start = max(text.rfind('.', 0, index), text.rfind('\n', 0, index)) + 1
        
        # Find the next period or newline after the index
        end_period = text.find('.', index)
        end_newline = text.find('\n', index)
        
        # Get the closest stopping point (whichever comes first)
        if end_period == -1:
            end = end_newline
        elif end_newline == -1:
            end = end_period
        else:
            end = min(end_period, end_newline)

        # Adjust bounds to avoid cutting off characters
        start = max(start, 0)
        end = end + 1 if end != -1 else len(text)

        return start, end
    
    # Match numbers that directly follow a letter and are followed by ., ,, (, space, or end of string
    pattern = r"(?<=[a-zA-Z])(\d+)(?=[\.,\s(]|$)"
    
    ref_to_superscript = defaultdict(list)

    matches = re.finditer(pattern, text)
    for match in matches:
        number = match.group()
        start, end = match.start(), match.end()

        # Find full sentence context (considering newlines too)
        sentence_start, sentence_end = find_sentence_boundaries(text, start)
        context = text[sentence_start:sentence_end].strip()

        # Check if closing parenthesis is within context
        # contains_closing_parenthesis = ')' in context

        # Count letters and numbers in the context
        num_count = sum(c.isdigit() for c in context)
        letter_count = sum(c.isalpha() for c in context)
        
        # Calculate numeric ratio
        total_chars = num_count + letter_count
        numeric_ratio = num_count / total_chars if total_chars > 0 else 0

        # Only log if the number is short and the surrounding text is mostly letters
        if len(number) <= max_digits and numeric_ratio <= max_numeric_ratio:
            # f.write(f"Superscript: '{number}' at {start}-{end}, Context: '{context}'\n")
            if int(number) in ref_dict:
                ref_to_superscript[int(number)].append(context)

        # else:
        #     f.write(f"Likely non-superscript: '{number}' at {start}-{end}, Context: '{context}'\n")    
    
    return ref_to_superscript

def get_citation_dict():
    pdf_path = 'papers/data_sharing.pdf'
    text = extract_text(pdf_path)
    

    ref_text = locate_reference(text)
    ref_dict = parse_reference(ref_text)
    ref_to_superscript = find_superscripts(text, ref_dict)

    output_dict = {ref_dict[key] : superscripts for key, superscripts in ref_to_superscript.items()}

    # with open('output.txt', 'w') as file:
    #     for key, superscripts in output_dict.items():
    #         file.write(f"CITATION: {key} ||||  {superscripts}\n\n")
    #         # file.write(ref_text)

    return output_dict