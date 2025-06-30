from pdfminer.high_level import extract_text
from collections import defaultdict
import re
import spacy

""" TWO MAIN FORMS/PURPOSES OF CITATION SCRAPING: 
1. General claim scraping - we actually don't care about finding citations here; 
we first use spaCy NLP to scrape all sentences that look like quantitative claims. 
Next, we have two options: for simple (googleable) claims, we can try and request data
from a relevant trustworthy institution into a table and then use TAPAS to query and return it.
OR, we could scrape for a relevant dataset ourselves (given that the claim itself fits this approach better),
and then do the statistical check script generation using some LLM. Tl;dr use this approach for 
shorter pieces that do not have listed sources (e.g. news articles, etc.)

2. Source validation - we actually want to check the worthiness of the source, so some
qualitative check there using LLM, and then we want to match each given claim to their source, which
we will then explicitly check the claim against any data that we can find within the source. A new important
aspect is that we should be able to check qualitative claims against the source as well given NLP; we can also do 
a deep dive into the data using the same script generation as listed above for the general claim scraping.
"""

references_dict = defaultdict(list)

def locate_reference(full_text):
    start_index = full_text.find("References")

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

# Define keywords that often signal quantitative claims
QUANT_WORDS = {
    "more than", "less than", "greater than", "fewer than", "at least", "at most",
    "increase", "decrease", "rose", "dropped", "fell", "higher", "lower", "doubled", "tripled",
    "percent", "percentage", "ratio", "rate", "per", "average", "median", "mean"
}

def get_all_claims(pdf_path, threshold): #this uses a spaCy NLP to detect all claims in general
    nlp = spacy.load("en_core_web_sm")
    text = extract_text(pdf_path)
    doc = nlp(text)
    claims = []

    for sent in doc.sents:
        sent_text = sent.text.lower()
        num_matches = 0
        total_features = 0

        #count total keywords to compare
        for word in QUANT_WORDS:
            if word in sent_text:
                num_matches += 1
                total_features += 1

        #count total numerals/percentage based chars
        for token in sent:
            if token.like_num or "%" in token.text:
                num_matches += 1
                total_features += 1

        #append to claims if enough quantitative features detected
        if total_features > 0 and (num_matches / total_features) >= threshold:
            claims.append(sent.text.strip())

    with open('output_all_claims.txt', 'w') as file:
        file.write(claims)

    return claims


def get_citation_dict(pdf_path):
    text = extract_text(pdf_path)
    ref_text = locate_reference(text)
    ref_dict = parse_reference(ref_text)
    ref_to_superscript = find_superscripts(text, ref_dict)

    # print(ref_text)
    # print(ref_dict)
    # print(ref_to_superscript)

    output_dict = {ref_dict[key] : superscripts for key, superscripts in ref_to_superscript.items()}

    with open('output_citation_dict.txt', 'w') as file:
        for key, superscripts in output_dict.items():
            file.write(f"CITATION: {key} ||||  {superscripts}\n\n")
            # file.write(ref_text)

    return output_dict

def main():
    pdf_path = 'sample.pdf'
    get_citation_dict(pdf_path)
    # get_all_claims(pdf_path)


if __name__ == "__main__":
    main()