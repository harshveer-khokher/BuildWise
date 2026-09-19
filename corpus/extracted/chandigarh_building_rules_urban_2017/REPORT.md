# Extraction health: chandigarh_building_rules_urban_2017

- doc_type: `base_rules`
- sha256: `205fddc15ea54d98ad9ce769a7fba6994cc5120c692f61a45ba62e636be1d132`
- pages: 123
- clauses extracted: 88
- OCR-required pages: [1, 54, 67, 98]

## Numbering anomalies

- clause '12.2 PROVISIONS FOR HIGH RISE DEVELOPMENT' has no entry of its own: the source PDF typesets its heading as '12 . 2PROV ISIONS...' (malformed spacing), which the sub-clause matcher does not recognise. Its brief intro text is folded into clause 12.1's text instead. Its own numbered children (12.2.1-12.2.7) are captured correctly.
- rejected implausible sub-clause number '11.50' at page 62 (heading would have been 'High voltage lines above 11') -- almost certainly a table value, not a real heading.

## Rule coverage

- rules referencing this doc: 0
- clauses with numeric/measurement content: 33
- **orphan clauses (numeric content, no rule yet -- the to-do list): 33**

- `chandigarh_building_rules_urban_2017:3` (p.5) DEFINITIONS
- `chandigarh_building_rules_urban_2017:4.1` (p.11) Residential (PLOTTED)
- `chandigarh_building_rules_urban_2017:4.2` (p.15) Residential (GROUP HOUSING)
- `chandigarh_building_rules_urban_2017:5.1` (p.18) Commercial (Governed By Architectural Controls)
- `chandigarh_building_rules_urban_2017:5.2` (p.21) Commercial (Governed By Individual Zoning)
- `chandigarh_building_rules_urban_2017:5.3` (p.27) Theaters Converted Into Multiplex
- `chandigarh_building_rules_urban_2017:5.4` (p.29) Coal Depot and Petrol Pump
- `chandigarh_building_rules_urban_2017:6` (p.30) INDUSTRIAL USE
- `chandigarh_building_rules_urban_2017:7` (p.34) PUBLIC/ SEMI PUBLIC BUILDINGS
- `chandigarh_building_rules_urban_2017:7.1` (p.37) Cultural and Non Academic Institutional & Religious
- `chandigarh_building_rules_urban_2017:7.2` (p.39) EDUCATIONAL INSTITUTES
- `chandigarh_building_rules_urban_2017:7.3` (p.41) I.T Park
- `chandigarh_building_rules_urban_2017:7.4` (p.44) Railway Station, Chandigarh
- `chandigarh_building_rules_urban_2017:8.1` (p.45) Hospital, Commercial, Club
- `chandigarh_building_rules_urban_2017:8.2` (p.47) Residential & Government Housing
- `chandigarh_building_rules_urban_2017:9` (p.50) INTEGRATED PROJECTS
- `chandigarh_building_rules_urban_2017:9.1` (p.53) Transit Oriented Development
- `chandigarh_building_rules_urban_2017:10.1` (p.55) General Requirements
- `chandigarh_building_rules_urban_2017:10.2` (p.56) Gallery Floors and Mezzanine Floor
- `chandigarh_building_rules_urban_2017:10.6` (p.57) Service Floor
- `chandigarh_building_rules_urban_2017:10.7` (p.57) FAR Exemptions
- `chandigarh_building_rules_urban_2017:11.1.2` (p.60) Self Certification
- `chandigarh_building_rules_urban_2017:11.3.4` (p.65) Occupation Certificate
- `chandigarh_building_rules_urban_2017:12.1` (p.68) NORMS FOR DIFFERENTLY-ABLED PERSONS
- `chandigarh_building_rules_urban_2017:12.2.6` (p.70) Building Components
- `chandigarh_building_rules_urban_2017:12.3` (p.77) PUBLIC HEALTH INSTALLATIONS
- `chandigarh_building_rules_urban_2017:12.4.7` (p.81) Use of Glass in Buildings to Ensure Human and Fire Safety
- `chandigarh_building_rules_urban_2017:12.5` (p.83) ENVIRONMENTAL CLEARANCE
- `chandigarh_building_rules_urban_2017:13` (p.94) GREEN BUILDINGS AND SUSTAINABILITY PROVISIONS
- `chandigarh_building_rules_urban_2017:13.2` (p.94) Provisions for City And Site Level Greening
- `chandigarh_building_rules_urban_2017:13.4` (p.95) Installation of Solar Assisted Water Heating System/ Solar Photo Voltaic Power Plant in Buildings
- `chandigarh_building_rules_urban_2017:annexure-2` (p.110) ANNEXURE-2
- `chandigarh_building_rules_urban_2017:annexure-3` (p.111) ANNEXURE -3
