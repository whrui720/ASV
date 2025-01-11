import PyPDF2

def extract_pdf_text(pdf_path):
    pdf_text = ''
    with open(pdf_path, 'rb') as pdf_file:
        pdf_reader = PyPDF2.PdfReader(pdf_file, strict = False)

        for page_num in range(len(pdf_reader.pages)):
            page = pdf_reader.pages[page_num]
            pdf_text += page.extract_text()


            pdf_text += ' '.join(pdf_text.split()) + ' '
    return pdf_text


if __name__ == '__main__':
    pdf_path = 'papers/'
    pdf_text = extract_pdf_text(pdf_path)

    with open("output.txt", "w") as file:
        file.write(pdf_text)

