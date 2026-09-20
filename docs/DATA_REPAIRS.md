# Verified archive repairs — 2026-09-20

## Archive scope update in version 1.2.0

Austrian Lotto 6 aus 45 and German Lotto 6 aus 49 now retain only draws dated
**2000-01-01 or later**, as requested. This is an intentional coverage change.

| Archive | Version 1.1.0 rows | Pre-2000 rows removed | Retained rows | First retained draw |
| --- | ---: | ---: | ---: | --- |
| Austrian Lotto 6 aus 45 | 3,682 | 814 | 2,868 | 2000-01-02 |
| German Lotto 6 aus 49 | 5,048 | 2,307 | 2,741 | 2000-01-01 |

Every retained row was compared field by field with the preceding project ZIP:
no retained dates or numbers changed. Both European archives are byte-identical
to version 1.1.0. The original repair evidence below remains applicable to the
retained data; references to older historical coverage describe the original
source audit, not the scope of the current Lotto CSV downloads.

The shared archive policy is enforced during imports, reads, writes, integrity
checks, and page generation. Austrian multi-year source files are filtered by
year section before draw parsing; German year requests start at 2000. Existing
out-of-scope records fail validation, and rejected writes preserve the original
CSV. The public CSV copies are regenerated from the filtered canonical files.

The retained German year 2000 was compared with the live combined source:
all **57 records** match exactly. They cover 53 Saturday draws and four Wednesday
draws from December 6 onward. [LOTTO Bayern](https://www.lotto-bayern.de/lotto6aus49/gewinnzahlen)
describes this boundary for its archive, and its [game history](https://www.lotto-bayern.de/lotto6aus49/normalschein)
dates the Wednesday integration to 2000-12-06. The former separate Wednesday
lottery is outside the selected dataset; those earlier Wednesday dates are not
treated as gaps in this archive's coverage.

## EuroMillions

The supplied `eu/euromillions/results.csv` contained 1,976 records. A calendar audit found eleven missing draw dates and five rows dated on days when EuroMillions was not drawn. Those anomalies were checked against **independent official FDJ historical CSV archives**, downloaded from the links on [FDJ's EuroMillions history page](https://www.fdj.fr/jeux-de-tirage/euromillions-my-million/historique).

All 1,193 FDJ records from 2004-02-13 through 2019-02-26 were compared against the supplied archive. There were exactly eleven absent dates and five extraneous dates; all main numbers and stars agreed on every date shared by the two archives. Each repaired row is independently supported by FDJ. Dates were not inferred from weekdays.

The repaired CSV contains **1,982 draws**, from **2004-02-13 through 2026-09-18**. Eleven verified dates were inserted and five erroneous dates were removed. Four removed rows were restored under their correct dates; the fifth was an erroneous duplicate of a draw already present. Seven other dates had been omitted entirely by the old parser. The repaired file matches all 1,193 official FDJ reference rows and has no missing expected draw dates, duplicate dates, unexpected weekdays, invalid ranges, repeated numbers within a draw, or unsorted number/star groups.

### Primary reference downloads

These exact endpoints were linked by FDJ and downloaded on 2026-09-20. The ZIPs contain semicolon-delimited CSVs, with several date formats and drawn-order numbers; main numbers and stars were each sorted independently for comparison.

| FDJ archive | Exact download | CSV member | Records |
| --- | --- | --- | ---: |
| February 2004–May 2011 | [FDJ archive 1](https://www.sto.api.fdj.fr/anonymous/service-draw-info/v3/documentations/1a2b3c4d-9876-4562-b3fc-2c963f66afa8) | `euromillions.csv` | 378 |
| May 2011–February 2014 | [FDJ archive 2](https://www.sto.api.fdj.fr/anonymous/service-draw-info/v3/documentations/1a2b3c4d-9876-4562-b3fc-2c963f66afa9) | `euromillions_2.csv` | 286 |
| February 2014–September 2016 | [FDJ archive 3](https://www.sto.api.fdj.fr/anonymous/service-draw-info/v3/documentations/1a2b3c4d-9876-4562-b3fc-2c963f66afb6) | `euromillions_3.csv` | 276 |
| September 2016–February 2019 | [FDJ archive 4](https://www.sto.api.fdj.fr/anonymous/service-draw-info/v3/documentations/1a2b3c4d-9876-4562-b3fc-2c963f66afc6) | `euromillions_4.csv` | 253 |

### Upstream date corrections

The source is [win2day's historical EuroMillions CSV](https://statics.win2day.at/media-nopagespeed/euromillionen-ergebnisse-2004-2017.csv). The following six source dates must only be corrected when the **original date and the complete main-number/star tuple both match**. This prevents an exceptional correction from affecting any unrelated result. Column positions below are zero-based; source row numbers are one-based in the downloaded CSV.

| Original source date | Correct date, independently verified by FDJ | Main numbers | Stars | Source row | Existing archive consequence |
| --- | --- | --- | --- | ---: | --- |
| `20.11.2099` | `2009-11-20` | 5, 9, 28, 43, 47 | 2, 9 | 3240 | Omitted because the year was beyond the parser limit |
| `26.03.2009` | `2010-03-26` | 8, 16, 18, 37, 43 | 2, 6 | 3438 | Stored under the wrong year |
| `04.07.2010` | `2010-07-02` | 12, 13, 36, 41, 46 | 1, 8 | 3590 | Stored under the wrong day |
| `12.09.2012` | `2012-09-11` | 6, 15, 22, 37, 44 | 2, 4 | 5638 | Stored under the wrong day |
| `16.12.2012` | `2014-12-16` | 3, 7, 12, 13, 25 | 5, 8 | 8280 | Stored under the wrong year |
| `06.08.2017` | `2017-08-04` | 29, 30, 36, 40, 41 | 2, 9 | 11397 | Created a duplicate of the correctly dated yearly-CSV result |

Equivalent correction keys for Python are `(raw_iso_date, (n1, n2, n3, n4, n5, s1, s2))`:

```python
{
    ("2099-11-20", (5, 9, 28, 43, 47, 2, 9)): "2009-11-20",
    ("2009-03-26", (8, 16, 18, 37, 43, 2, 6)): "2010-03-26",
    ("2010-07-04", (12, 13, 36, 41, 46, 1, 8)): "2010-07-02",
    ("2012-09-12", (6, 15, 22, 37, 44, 2, 4)): "2012-09-11",
    ("2012-12-16", (3, 7, 12, 13, 25, 5, 8)): "2014-12-16",
    ("2017-08-06", (29, 30, 36, 40, 41, 2, 9)): "2017-08-04",
}
```

### Missing rows caused by date format or block detection

The historical source uses two independent horizontal draw slots. The left slot uses header/date columns 1/11, main-number columns 1–5 and star columns 6–7; the right slot uses header/date columns 13/23, main-number columns 13–17 and star columns 18–19. In this downloaded file the ascending numeric row is two rows below its header. Numeric scanning must remain within the current block so a malformed block cannot take values from the next block.

| Correct date | Main numbers | Stars | Source row | Cause |
| --- | --- | --- | ---: | --- |
| `2005-03-11` | 8, 12, 23, 40, 43 | 1, 4 | 605 | Right-slot date is Excel serial `38422`, equivalent to 2005-03-11 using the 1899-12-30 epoch; the DD.MM.YYYY-only parser ignored it |
| `2014-01-03` | 3, 27, 31, 38, 44 | 3, 8 | 7180 | Right-only block; old parser required the left `Ergebnisse:` label |
| `2014-10-21` | 20, 21, 27, 33, 40 | 3, 10 | 8104 | Left label absent, while the date, numeric row, and right block label were present |
| `2014-10-24` | 3, 9, 20, 30, 42 | 1, 6 | 8104 | Same block omitted because the left label was absent |
| `2015-01-02` | 22, 24, 25, 28, 49 | 3, 6 | 8364 | Right-only block |
| `2016-01-01` | 4, 37, 38, 39, 44 | 4, 7 | 9549 | Right-only block |

The separate missing 2009-11-20 record is documented in the scoped date-correction table above.

### Validation performed after the repair

- Exact date and normalized seven-number agreement with all 1,193 FDJ records through 2019-02-26.
- Exact expected date-set coverage from the first draw, 2004-02-13, to the latest stored draw, 2026-09-18: Fridays until 2011-05-06; Tuesdays and Fridays from 2011-05-10.
- Strict ascending date order, unique dates, valid ISO calendar dates, five distinct sorted numbers from 1–50, and two distinct sorted star numbers.
- Historical star maxima of 9 before 2011-05-10, 11 before 2016-09-27, and 12 afterward.
- Existing CSV header and CRLF record endings preserved.

### Supporting calendar and rule-history evidence

[Österreichische Lotterien's EuroMillions information](https://www.lotterien.at/spiele/lotteriespiele/euromillionen) states that Tuesday and Friday draws have taken place since May 2011. The official FDJ archives establish the precise transition: the first file ends on Friday 2011-05-06 and contains only Friday draws; its successor starts on Tuesday 2011-05-10 and contains Tuesday/Friday draws.

[Swisslos's own 2016 retrospective press release](https://www.presseportal.ch/de/pm/100004581/100797835), published 2017-01-12, identifies 2016-09-27 as the introduction date for the new EuroMillions rules. FDJ's fourth archive starts on that date and records star numbers 2 and 12. Earlier FDJ records have maximum star value 9 before May 2011 and 11 before 2016-09-27. The downloaded source results therefore corroborate the historical pool periods. An original 2011 announcement explicitly stating the 9-to-11 pool change was not retrieved during this audit.

## Austrian and German Lotto audit findings

Read-only audit of the supplied files found exactly one unsorted main-number group in each, with no invalid dates, duplicate/conflicting dates, invalid number ranges, or chronology errors:

| Archive | Date | Existing number order | Sorted number order |
| --- | --- | --- | --- |
| Austrian Lotto 6aus45 | 2010-05-09 | 9, 35, 24, 40, 13, 7 | 7, 9, 13, 24, 35, 40 |
| German Lotto 6aus49 | 2009-08-05 | 4, 36, 13, 19, 15, 39 | 4, 13, 15, 19, 36, 39 |

No Austrian supplementary number coincided with its six main numbers. German Superzahl values were absent before 1991-12-07 and present for every stored draw on/after that date. [LOTTO.de's official history](https://www.lotto.de/lotto-6aus49/ueber/historie) explicitly lists 07.12.1991 as the introduction of the Superzahl. Both listed number groups were normalized in this update without changing the drawn values.
