# Odoo `crm.lead` → book: the rules

This file is **the pipeline's source of truth, not a description of it.**
`backend/app/pipelines/rules.py` parses the tables below and `normalise()` applies
what it finds. Edit a table here and the pipeline behaves differently on the next
run; there is no second copy of these rules in Python.

Parsed the way `scripts/import_master_sheet.py` parses the Drive render: as markdown
tables. So the format matters — **a table is read by its header row**, every row must
have the same number of cells, and a cell that should be empty is written `—`. Prose
outside the tables is ignored by the parser and is there for the person reading it.

Every number in the `Measured` columns comes from `scripts/compare_crm_to_sheet.py`
run on 2026-09-11 against the 58 `"x"`-tab rows in the Drive export and the 34,401
`crm.lead` rows in Odoo UAT (uid 299, read-only). None of it is assumed.

---

## 0. Action criteria — Arina's note, restored beside the tables on 2026-09-15

> Ruled 2026-09-15 with Feedback Round 1 (vault note 10, F6; design F6 = NEW_ONLY): a
> crm.lead run adds only customers the platform does not hold; an existing customer keeps
> the sheet's fields, and what differs is written as a proposal, never applied. The three
> scenarios below are that rule in Arina's own words, kept verbatim. The tables in §1–§7 are
> what `pipelines/rules.py` parses; this section holds no table and the parser skips it.

### This document is the action criteria for manage data mismatching between crm.lead(from ODoo) and sheet"x" from New Order Master

#### scenario1 : data matching both side
    **action** : Normal Display

#### scenario2 : Odoo(valid) | Sheet"x"(invalid)
    **action** : cut excess field from Odoo off. Focus use field mainly from Sheet"x"

#### scenario3 : Odoo(invalid) | Sheet"x"(valid)
    **action** : keep all. the excess field from sheet "x" made it can config or adjust status by user.

---

## 1. Join — how a lead is matched to a sheet row

> **Measured, not yet applied.** `rules.py` parses this table and nothing consumes
> it. The pipeline's only join today is `writer._sheet_rows`, which matches a landed
> Odoo row to a sheet row on the **whole `volt_id` string** — key 3 below, measured at
> **0 of 58**. That is why every run so far reports `overwrote 0` and why §6's
> overwrite ledger is empty: not because Odoo replaced nothing, but because nothing
> was compared. Wiring this table in changes what a run does to the book, so it is a
> decision, not a tidy-up.

The order below is how the keys would be tried once they are wired: the first one
that hits wins, and the rest still run so the run report can record which keys agreed
and which did not.

| Order | Key | Sheet column | crm.lead field | Compare as | Measured |
| --- | --- | --- | --- | --- | --- |
| 1 | phone | Phone, Secondary Phone | phone, mobile | last 9 digits | 58 of 58 |
| 2 | volt_stem | Volt ID | volt_id | leading segment before `_` | 58 of 58 |
| 3 | volt_exact | Volt ID | volt_id | whole string | 0 of 58 |
| 4 | odoo_id_numeric | Odoo ID | id | whole string | 0 of 58 |
| 5 | odoo_id_volt | Odoo ID | volt_id | whole string | 3 of 58 |

`phone` is **one key over four columns**, not two keys: the measurement tried the
sheet's `Phone` then `Secondary Phone` against Odoo's `phone` then `mobile` and
counted a hit if any pair matched. Secondary Phone is empty on 54 of 58 sheet rows,
so splitting it out as its own key would claim a hit rate it has never been measured
at.

**Do not promote `odoo_id_numeric`.** The sheet's `Odoo ID` column is filled on 3 of
58 rows and holds `99999000206` — a Volt id, not a numeric Odoo id. The column that
exists to join the two systems does neither. `Peak ID`, likewise, holds Thai customer
names on all 58 rows, so it is not a key and is not listed here.

### 1.1 The shapes a volt_id actually takes

Counted over the 26,110 real volt_ids on 2026-09-11. `volt_stem` — the segment before
the first `_` — is what makes them one key.

| Shape | Example | Count |
| --- | --- | --- |
| placeholder | New | 23,514 |
| Odoo lease | VL0000143 | 1,352 |
| Odoo cash | 99999000205 | 819 |
| bare CRM id | 99999000001 | 363 |
| Odoo re-lease | VRL0000035 | 36 |
| Odoo re-cash | 99999000407 | 26 |
| sheet long form | 99999000032_Thitipawee_…_IPW | the sheet's own |

---

## 2. Field map — the sheet's 47 columns against crm.lead

`Direction` is `odoo` when the pipeline takes Odoo's value, `sheet` when it keeps the
sheet's, and `—` when Odoo has no field to take.

| Sheet column | crm.lead field | Direction | Note |
| --- | --- | --- | --- |
| No | — | — | the sheet's row number |
| Sales Lead | user_id | odoo | many2one; the label is taken, not the id |
| First Name | contact_name | odoo | romanised in the sheet, Thai in Odoo |
| Last Name | last_name | odoo | — |
| Co-Sign | cosigner_id | odoo | — |
| Order Type | order_type | odoo | — |
| Order Status | stage_name | odoo | translate, see §3 |
| Loan Status | — | — | sheet only |
| Contract Purchase | — | — | sheet only |
| Contract Service | — | — | sheet only |
| Submit Date | submitted_date | odoo | normalise, see §4 |
| Submit Month/Year | — | — | derived from Submit Date |
| Contract Signed Date | contract_signed_date | odoo | normalise |
| Contract Signed Month/Year | — | — | derived |
| Comment | description | odoo | Odoo wraps it in HTML; tags are stripped |
| Inverter Brand | inverter_brand | odoo | — |
| Inverter Type | inverter_type | odoo | declared, never filled |
| Battery Watt | battery_watt | odoo | declared, never filled |
| DP % | dp_percent | odoo | declared, never filled |
| DP Amount | dp_amount | odoo | 0 on every row measured |
| Monthly Rate, INC VAT | monthly_rate | odoo | 0 on 57 of 58 |
| Term | payment_term_installment_id | odoo | many2one, not a month count |
| Marketing | source_id | odoo | declared, never filled |
| Phone | phone | odoo | — |
| Secondary Phone | mobile | odoo | — |
| Email | email_from | odoo | — |
| LINE ID | line_id | odoo | link-only; never returned by customer search |
| Facebook ID | meta_id | odoo | Messenger identifier; never returned by customer search |
| CRM | — | — | sheet only |
| Gdrive | g_drive | odoo | — |
| CRM ID | — | — | sheet only; the 11-digit legacy id |
| Peak ID | — | — | sheet only; holds names, not ids |
| Volt ID | volt_id | odoo | two shapes, see §1 |
| Odoo ID | id | odoo | see §1 |
| Odoo ID2 | — | — | empty on every row |
| Project Type | — | — | sheet only |
| Energy Bill | energy_bill | odoo | 0 on every row measured |
| Watt | inverter_kw | odoo | **kW in Odoo, W in the sheet** — scale 1000 |
| Phase | connection_type | odoo | translate, see §3 |
| EPC | epc | odoo | — |
| EPC Start Date | epc_start_date | odoo | normalise |
| EPC Start Date Month/Year | epc_start_month_year | odoo | normalise |
| EPC End Date | epc_end_date | odoo | normalise |
| Gmap | site_coordinates | odoo | declared, never filled |
| Province | install_province | odoo | declared, never filled |
| Postal Code | zip | odoo | — |
| Address | street | odoo | — |
| Meter Owner | meter_owner | odoo | — |
| Com Status | com_status | odoo | translate, see §3 |

`panel_watt` is **not** the sheet's `Watt`: it is the size of one panel (710 W) where
the sheet means the system (5000 W). Mapping to it made all 58 rows look like a
disagreement about a 5 kW system the two systems agree on.

---

## 3. Vocabulary — translate before comparing or storing

`Seen` says whether the pair was actually observed in the 58-row comparison or
extrapolated from a pair that was. An extrapolated row is a guess with a pattern
behind it, and the first run will confirm or kill it.

| Field | Odoo value | Sheet value | Seen |
| --- | --- | --- | --- |
| stage_name | Won | Order - Done | measured |
| connection_type | single_phase | 1 | measured |
| connection_type | three_phase | 3 | extrapolated |
| com_status | paid_out | Paid Out | measured |
| com_status | not_paid | Not Paid | extrapolated |

Any `snake_case` value not listed is title-cased on the underscore as a fallback, and
the fallback is recorded in the run report so a missing row here shows up as a
translation nobody wrote rather than as a silent guess.

`stage_name` has 23 values in Odoo (`crm.stage`) and only `Won` appeared in the 58
rows. The first full run surfaced the rest, and they are **deliberately left
untranslated**: they are pre-sale pipeline stages the sheet's `Order Status` column
has no equivalent for, and coining one would be inventing a status nobody set.

| crm.stage value | Leads | Sheet equivalent |
| --- | --- | --- |
| Low Interest | 9,385 | none — pre-sale |
| Call Again | 6,866 | none — pre-sale |
| Screen Lead | 6,707 | none — pre-sale |
| High Interest | 5,515 | none — pre-sale |
| New | 2,958 | none — pre-sale |
| Document Collection | 729 | none — pre-sale |
| Site Visit Request | 180 | none — pre-sale |
| Prepare Loan | 114 | none — pre-sale |
| Lost | 110 | none — pre-sale |
| Contract - Review | 56 | none — pre-sale |
| Site Visit | 53 | none — pre-sale |
| Loan - To Score | 22 | none — pre-sale |

They still travel on the run report as unmapped, which is the honest state: the value
landed as Odoo wrote it and nobody has decided what it means to the debt team. That
list is also the clearest statement of what `crm.lead` mostly is — a sales pipeline,
not a debtor book.

---

## 4. Normalise — shapes that are the same value

| Kind | Input | Canonical |
| --- | --- | --- |
| date | 02/05/24 | 2024-05-02 |
| date | 2/5/2024 | 2024-05-02 |
| date | 2024-05-02T00:00:00 | 2024-05-02 |
| month_year | 05/24 | 2024-05 |
| month_year | May 2024 | 2024-05 |
| phone | +66 92 542 3597 | 925423597 |
| money | 3,199฿ | 3199.00 |

Two-digit years are **day first** — the rule `import_master_sheet.py` already applies.
Compared as raw strings instead, dates called 54 of 58 rows a disagreement when the
two systems named the same day.

---

## 5. Reject — what never lands, and why

| Rule | Condition | Verdict |
| --- | --- | --- |
| placeholder_volt_id | volt_id is the literal `New` | treated as no volt_id, keyed by its crm.lead id (`lead-<id>`) |
| no_identity | no volt_id, and no phone (first of phone/mobile) or no crm.lead id | rejected |
| unshaped_volt_id | volt_id matches none of the shapes in §1.1 | rejected |
| duplicate_volt_id | a volt_id already seen in this run | later row wins, earlier reported |
| date_unreadable | a date cell that is not a real calendar date | rejected |

### 5.1 The placeholder, measured

On the first live run, **23,514 of 34,338 leads carried the literal string `New`** in
`volt_id` — what Odoo writes before an id is minted. It is a placeholder, not a bad
id, so it is treated as *no* id: the lead still lands, keyed by its crm.lead id
(`lead-<id>` — never by its phone number, since 2026-09-25), and is refused only if
it has no phone either. Rejecting it as unshaped threw away 70% of
the book over a value that was never an identifier.

Every rejected row is counted on `import_run.meta` **with the rule that rejected it**.
A pipeline that drops rows quietly is the defect this work exists to remove.

---

## 6. Precedence — who wins when both hold a field

| Field group | Winner | Decided |
| --- | --- | --- |
| all | odoo | 2026-09-11 |

This is `landing._PRECEDENCE` as it already stands, chosen deliberately on
2026-09-11. It was harmless while Odoo contributed 5 rows that touched no sheet
customer. With 34,401 rows it overlaps — 58 of 58 sheet rows match a lead — so **a
blank or zero in Odoo now replaces a real sheet value**, and Energy Bill, Watt and
Monthly Rate are 0 on every Odoo row measured.

The rule stands as chosen. What it costs is made visible instead: every replaced
value goes to the **overwrite ledger** on `import_run.meta`, carrying the sheet value,
the Odoo value and the volt_id, so the cost can be read after a run and the rule
changed here if the ledger looks wrong.

**The ledger is empty, and that is not good news.** It compares on the whole
`volt_id` string — see §1's note — and the two systems do not hold the same string,
so nothing is compared and every run reports `overwrote 0`. Until §1 is wired, read
an empty ledger as *no measurement*, never as *no harm*.

To change it, add rows above `all` — for example `arrears | sheet | <date>` — and the
most specific matching group wins.

---

## 7. What Odoo declares and never fills

Ten fields exist on `crm.lead` and are empty or zero on every row measured:
`inverter_type`, `battery_watt`, `dp_percent`, `dp_amount`, `monthly_rate`,
`energy_bill`, `inverter_kw`, `source_id`, `site_coordinates`, `install_province`.

This is why every landed row carries `reason: "no money row in Odoo"` and appears in
the registry rather than in Today, arrears or NPL. Odoo holds no debt to collect:
every `renewable.energy.order` is stage `new`, all 79 `invoice.installment.line` rows
are draft and unpaid, and of 236 `account.move` rows exactly one is a customer
invoice. The absence is the fact, and the schema records it by omission rather than
by inventing a zero somebody might collect on.
