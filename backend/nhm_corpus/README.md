# NHM protocol corpus

The documents Agent 2 retrieves from when classifying risk (FR-03.1/03.2).

## What these files are

Clinical extracts from published Government of India / National Health
Mission guidance. Each file records the document it came from, the URL it
was retrieved from, and the date of retrieval.

They are **extracts, not facsimiles**. The clinical figures, thresholds and
referral criteria are reproduced as published, and quoted passages are
marked as quotations; the surrounding narrative, tables, annexures and
illustrations of the source PDFs are not reproduced. A citation from this
corpus therefore points at a real published guideline, and the threshold it
carries is that guideline's, but anyone acting on it clinically should read
the source document rather than this summary of it.

Government of India publications are generally released under the
Government Open Data Licence - India; each file names its publisher so the
provenance can be checked.

## Adding to the corpus

Drop a new `.md` file in this directory following the same front-matter
shape. The retriever reads every `.md` here at startup and chunks it on
`##` headings, so no code changes and no re-index step -- restart the API
and the new document is searchable.

Keep one clinical topic per heading. A chunk is what gets retrieved and
shown to the ASHA as a citation, so a heading that spans four unrelated
thresholds retrieves for all of them and explains none of them well.

## Provenance is the point

This corpus is the difference between "our model judged her HIGH risk" and
"NHM's anaemia guideline says Hb below 7 g/dL is severe, and hers is 6.4".
Do not add content here that is not traceable to a published guideline --
an invented threshold with a citation attached is worse than no citation,
because it survives review.
