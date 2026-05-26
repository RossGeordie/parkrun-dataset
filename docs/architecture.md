# Parkrun Dataset Architecture

## Data Model

### parkrun_results
| Field | Source Col | Notes |
|-------|----------|-------|
| event_name | auto | From filename/dir |
| event_date | auto | From filename/dir |
| start_number | Col 1 | |
| forename | Col 2 | |
| surname | Col 3 | |
| time | Col 11 | Parse logic below |
| gender_pos | Col 8 | Part after "/" |
| gender_total | Col 8 | Part before "/" |
| age_group | Col | |
| club | Col | |

### parkrun_volunteers
| Field | Source Col | Notes |
|-------|----------|-------|
| event_name | auto | From filename/dir |
| event_date | auto | From filename/dir |
| forename | Col | |
| surname | Col | |
| role | Col | |

## Parsing Logic

### Col 8 ("X / Y")
Split on " / ". Left = gender_total, Right = gender_pos.

### Col 11 (Finish Time)
- If hours == 1 (e.g. "1:07:00"), treat as mm:ss:xx
- Otherwise, the first integer is minutes

### Timezone
Parkrun is in the UK. Always use BST/GMT based on the event date.

## Reporting

The pipeline generates HTML report packs with:
- Participation counts by gender/age
- Average times by category
- Volunteer coverage rates
- Historical trend analysis
