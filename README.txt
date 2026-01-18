ASV: Automated Source Valuation

Problem: Statistical metrics often misconstrue data in favor of a specific narrative - even if the statements are not necessarily false. Simple examples include taking the mean of skewed data: “Energy prices on average are higher than last month” when a single energy price spike outlier exists; or misunderstandings/statistical fallacies: “The average person has less than 2 arms, thus you are very likely to meet amputees”. These problems are extremely prevalent in news and academic media, each with obvious issues. (This is my assumption of the problem; the actual significance and the willingness of users to pay for a solution is still undetermined). This general problem currently falls under ‘source valuation’, ‘source evaluation’,  and ‘citation analysis’.

Goal: Given a body of text, for each unique data source within: 
Determine the source (or closest related source) of the data, and download the data distribution onto a given platform (pandas, R, etc.). Also, provide information on the trustworthiness of the data (either just by a quick lookup or by reading through the methodology of data collection) ← this last part may likely be a reach goal. 
Implementation:
Download source into scrapable formatting
Scrape all sources and list out instances of each statistical statement attributed to a specific source
Use regex or some other find system to locate the closest sources online 
Check the formatting of sources and table them for potential download 
End result for this section should be a list of found sources, and some metadata about origin and formatting, each with a checkbox option of download into (platform of choice) yes or no
For each statistical statement created from the given source that could be found and downloaded into python backend, determine:
Accuracy of the given statement. Is it factual or not when checked against the underlying data?
Appropriateness of the statement. Even if it is ‘true’, does it represent the context of the underlying dataset fairly? If not, is this a genuine mistake or a purposeful misrepresentation?
Reach goals:
Find closely related datasets to cross check the validity of data
Provide suggestions for EDA or points of clarification for the original authors
Turn this into a web browser or an extension of some kind (Harry needs more full-stack experience).

NEW UPDATED STRUCTURE with more LLM calls and agentic search + download behavior:

Step 1: Claim Identification + Citation Mapping
The big change here is that after chunking the text, we should be able to use LLMs (agents?) to identify all claims (as a direct replace for NLP identification of claims),
or at the very least be able to use LLMs in helping to identify quantitative-specific claims and with mapping. For example, we could use an LLM to identify a claim, 
it's corresponding citation (particularily helpful for in-text citations), and even classify the claim itself (quantitative, qualitative, subjective, objective, etc.).
By forcing this json format, we should actually be able to treat each type of claim in a different way. The agents, or deterministic workflows, will put these claims/citation objects
into a queue for the claim treatment agent to pick up.

Step 2: Claim Type Treatment (Source Finding + Truth table query)
NOTE: NEED TO SORT BETWEEN "DIFFICULT (requiring dataset) and SIMPLE (simple LLM call or truth table check will do).
  Different types of claims:

  - Quantitative, citation found:
    Map this claim to the corresponding citation. 
    Download agent (dataset) needed AFTER batching claim objects by this citation.

  - Quantitative, no citation found: Search agent for substitute dataset(without downloading) needed immediately; save and prioritize search within existing substition dataset names.
    Download agent (dataset) needed AFTER batching claim objects by this substitute citation.
    Find the nearest (fuzzy search?) data source and substitute/map it for this citation
  
  - Qualitative, citation found (objective): 
    Map this claim to the corresponding citation. 
    Download agent (text) needed AFTER batching claim objects by this citation.

  - Qualitative, no citation found (subjective): THESE CLAIM OBJECTS SHOULD GET PROCESSED LAST
    Do nothing for now, label as needing additional treatment in Step 3.

  To process these claims, batch them by citation. Only now should the download agent(s) be used.
  To conserve memory, ONLY 1 DATA SOURCE (dataset or text) SHOULD BE DOWNLOADED/IN USE AT A TIME.
  Once each ClaimObjectAfterTreatment for the given citation batch is created, immediately proceed to Step 3 for this specific citation.

Step 3: Claim Validation
  At this point, each claim object should be mapped to a corresponding source. Here, validation agents should do the following:

  - Quantitative claim objects:
    Create python code to validate the claim. Run it, check the output, return a judgement object, and then clean up.
  
  - Qualitative claim objects:
    Holistically try to identify the validity of the claim (semantic search + RAG?) within the citation raw text. Return a judgement object, and clean up.
    IF QUALITATIVE, NO CITATION FOUND (SUBJECTIVE):
    1. Query against truth table setup (Google’s Knowledge Graph, ClaimReview Schema, Google Fact Check Explorer, etc.), and if not confident, then:
    2. Query against LLM search setup (risky, force sources). Search and download agent only needed here.
    If either provides a satisfactory answer (if the truth table does, it has higher priority), 
    map this claim to the truth table result or the LLM search

  NOTE: A qualitative, no citation found claim that was satisfactorily answered by the truth table instantly goes into the
  report output and skips this step.

Step 4. Display 
  Collect and display all of the judgment objects nicely. 


EXAMPLE JSON FORMATS:
### Step 1: Claim Identification + Citation Mapping
CLAIM OBJECT
```json
{
  "claim_id": "unique-identifier",
  "text": "The average energy price increased last month.",
  "claim_type": "quantitative",  // or "qualitative"
  "citation_found": true,
  "citation_text": "[1]",
  "citation_details": {
    "title": "Energy Prices Report",
    "authors": ["Author Name"],
    "year": 2023,
    "url": "https://example.com/report"
  },
  "classification": ["objective"], // or "subjective"
  "location_in_text": {
    "start": 123,
    "end": 167
  }
}
```

---

### Step 2: Claim Type Treatment

CLAIM OBJECT AFTER TREATMENT
```json
{
  "claim_id": "unique-identifier",
  "text": "The average energy price increased last month.",
  "claim_type": "quantitative",
  "citation_mapped": true,
  "citation_source": {
    "downloaded": true,
    "data_format": "csv",
    "platform": "pandas",
    "source_url": "https://example.com/data.csv"
  },
  "treatment_notes": "Citation found and dataset downloaded for validation."
}
```

---

### Step 3: Claim Validation

JUDGEMENT OBJECT
```json
{
  "claim_id": "unique-identifier",
  "validation_type": "quantitative", // or "qualitative"
  "validation_code": "mean(data['price']) > previous_month_mean",
  "result": {
    "is_factual": true,
    "is_appropriate": false,
    "explanation": "The claim is factually correct, but the mean is skewed by an outlier."
  },
  "confidence_score": 0.92,
  "validation_metadata": {
    "checked_by": "automated_agent",
    "timestamp": "2026-01-04T12:00:00Z"
  }
}
```

---

### Step 4: Display

REPORT OBJECT
```json
{
  "claims": [
    {
      "claim_id": "unique-identifier",
      "text": "The average energy price increased last month.",
      "judgement": {
        "is_factual": true,
        "is_appropriate": false,
        "explanation": "The claim is factually correct, but the mean is skewed by an outlier."
      },
      "citation": {
        "title": "Energy Prices Report",
        "url": "https://example.com/report"
      }
    }
    // ... more claims
  ],
  "summary": {
    "total_claims": 10,
    "validated": 8,
    "issues_found": 2
  }
}
```



