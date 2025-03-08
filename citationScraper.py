from pdfminer.high_level import extract_text
import re

def find_superscripts(text, max_numeric_ratio=0.4, max_digits=2):
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
    
    with open("superscripts.txt", "w", encoding="utf-8") as f:
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
                f.write(f"Superscript: '{number}' at {start}-{end}, Context: '{context}'\n")
            # else:
            #     f.write(f"Likely non-superscript: '{number}' at {start}-{end}, Context: '{context}'\n")

def extract_pdf_text(pdf_path):
    """Extracts text from a PDF using pdfminer.six."""
    return extract_text(pdf_path)

local_pdf_path = "sample.pdf"

if __name__ == '__main__':
    pdf_text = extract_pdf_text(local_pdf_path)
    
    with open("output.txt", "w") as file:
        file.write(pdf_text)
        
    find_superscripts(pdf_text)