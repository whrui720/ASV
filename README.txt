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
