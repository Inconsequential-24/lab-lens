# Allow-list redaction experiment: results

Dataset: 20 text PDFs and 7 scan-style images, synthetic, 114 planted PII items. Intervals are 95% Wilson.

## Text PDFs (pypdf text layer, as the pipeline reads it)

| Method | PII items leaked | Docs with any leak | Name/doctor partial leaks | Rows kept | Known-test rows kept | Rows mislabelled | Age kept | Sex kept | Report date kept | ms/doc |
|---|---|---|---|---|---|---|---|---|---|---|
| baseline | 20/83 (24.1%, CI 0.16–0.34) | 10/20 | 0 | 144/156 (92.3%, CI 0.87–0.95) | 135/141 (95.7%, CI 0.91–0.98) | n/a (keeps layout) | 19/20 | 19/20 | 0/20 | 2.0 |
| allowlist | 0/83 (0.0%, CI 0.00–0.04) | 0/20 | 0 | 156/156 (100.0%, CI 0.98–1.00) | 141/141 (100.0%, CI 0.97–1.00) | 0 | 20/20 | 20/20 | 20/20 | 0.6 |
| allowlist_strict | 0/83 (0.0%, CI 0.00–0.04) | 0/20 | 0 | 141/156 (90.4%, CI 0.85–0.94) | 141/141 (100.0%, CI 0.97–1.00) | 0 | 20/20 | 20/20 | 20/20 | 0.6 |

### Leaks by PII type (text PDFs)

| Type | baseline | allowlist | allowlist_strict |
|---|---|---|---|
| address | 5/21 | 0/21 | 0/21 |
| dob | 1/1 | 0/1 | 0/1 |
| doctor | 0/7 | 0/7 | 0/7 |
| email | 0/2 | 0/2 | 0/2 |
| id | 3/12 | 0/12 | 0/12 |
| name | 7/17 | 0/17 | 0/17 |
| phone | 3/20 | 0/20 | 0/20 |
| url | 1/3 | 0/3 | 0/3 |

### Per document (text PDFs): leaked PII types

| Doc | Case | baseline | allowlist | allowlist_strict | Rows kept (allowlist) |
|---|---|---|---|---|---|
| N01 | Standard layout: full patient block above one table | none | none | none | 8/8 |
| N02 | Lipid profile, UHID and +91 mobile in header | none | none | none | 6/6 |
| N03 | Two panels back to back, header block | none | none | none | 5/5 |
| N04 | Minimal header: name and age only | none | none | none | 6/6 |
| P01 | PII only in the footer under the table | none | none | none | 8/8 |
| P02 | PII box between two separate result tables | none | none | none | 14/14 |
| P03 | Patient banner repeated mid-table (continuation header) | none | none | none | 12/12 |
| P04 | Side box in the right margin next to the table | name, address | none | none | 8/8 |
| P05 | Multi-page: running patient header on every page, address in last footer | none | none | none | 31/31 |
| P06 | Unlabelled name inside a sentence between panels | name | none | none | 5/5 |
| P07 | Unlabelled postal address paragraph between tables | address, address | none | none | 8/8 |
| P08 | Free-text clinical remark with name, doctor and a phone number | name | none | none | 8/8 |
| P09 | URL, QR text, barcode and sample numbers after the table | url | none | none | 3/3 |
| P10 | DOB in the age line; Aadhaar, ABHA and policy numbers in the footer | dob, id, id, id | none | none | 6/6 |
| P11 | Phone number formats zoo (STD, brackets, spaces, +91, 0-prefix, extension) | phone, phone, phone | none | none | 2/2 |
| P12 | Hindi labels and Devanagari name/address (text layer, unshaped) | name, address | none | none | 8/8 |
| P13 | Adversarial: PII hidden inside result rows and a name+age line | name, name | none | none | 4/4 |
| P14 | Clean letterhead; patient name and address only after the signatures | name, address | none | none | 6/6 |
| P15 | Tests outside the known vocabulary (measures retention cost of an allow-list) | none | none | none | 6/6 |
| P16 | Long test names that wrap onto two lines | none | none | none | 2/2 |

## Scan-style images

| Method | PII items with ink left (pixel leak) | OCR can read it back | Docs with any pixel leak | Rows kept / OCR-readable rows | Age | Sex | Report date | ms/doc |
|---|---|---|---|---|---|---|---|---|
| baseline | 9/31 (29.0%, CI 0.16–0.47) | 9/31 readable | 4/7 | 57/88 (64.8%, CI 0.54–0.74) | 0/7 | 0/7 | 1/7 | 2059 |
| allowlist | 0/31 (0.0%, CI 0.00–0.11) | 0/31 readable | 0/7 | 85/88 (96.6%, CI 0.91–0.99) | 6/7 | 6/7 | 7/7 | 2775 |
| allowlist_strict | 0/31 (0.0%, CI 0.00–0.11) | 0/31 readable | 0/7 | 79/88 (89.8%, CI 0.82–0.94) | 6/7 | 6/7 | 7/7 | 2951 |

| Image | baseline | allowlist | allowlist_strict |
|---|---|---|---|
| I01 (N01) | address | none | none |
| I02 (P02) | address, address | none | none |
| I03 (P04) | name, address, address | none | none |
| I04 (P01) | none | none | none |
| I05 (P07) | address, address, address | none | none |
| I06 (P05) | none | none | none |
| I07 (P03) | none | none | none |
