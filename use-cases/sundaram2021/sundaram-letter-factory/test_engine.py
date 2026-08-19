"""Tests for the deterministic half of the factory. No network, no API key.

  python3 test_engine.py
"""

import sys
from decimal import Decimal

import engine
import run

RULES, BLOCKS, RECORDS = engine.load_data()
PASSED = []
FAILED = []


def check(name, condition, detail=""):
    if condition:
        PASSED.append(name)
    else:
        FAILED.append("{0}{1}".format(name, ": " + detail if detail else ""))


def by_id(customer_id):
    for record in RECORDS:
        if record["customer_id"] == customer_id:
            return record
    raise AssertionError("no record " + customer_id)


def held_reason(customer_id):
    result = engine.prepare(by_id(customer_id), RULES, BLOCKS)
    if result["status"] != "held":
        return None
    return " ".join(failure["reason"] for failure in result["failures"])


def test_interest_is_exact_and_reproducible():
    result = engine.prepare(by_id("CUS-1001"), RULES, BLOCKS)
    # 42500 cents at 10 percent for 214 days on a 365 day basis, rounded half up.
    expected_interest = (Decimal(42500) * Decimal(1000) / Decimal(10000)
                         * Decimal(214) / Decimal(365))
    check("interest matches hand arithmetic",
          result["values"]["interest_cents"] == Decimal(round(expected_interest)),
          str(result["values"]["interest_cents"]))
    check("refund is overcharge plus interest",
          result["values"]["refund_cents"]
          == result["values"]["overcharge_cents"] + result["values"]["interest_cents"])
    check("every formula step is in the audit trail",
          len(result["trail"]) == len(RULES["formula"]["steps"]))
    check("trail shows substituted arithmetic, not just the answer",
          any("42500 * 1000 / 10000" in line for line in result["trail"]))


def test_broken_records_are_held_with_named_reasons():
    cases = [
        ("CUS-2001", "greater than zero"),
        ("CUS-2002", "'notice_date' is missing"),
        ("CUS-2003", "does not match the figure the formula produces"),
        ("CUS-2004", "is not configured in rules.json"),
        ("CUS-2005", "No approved wording block exists"),
        ("CUS-2006", "No approved wording block exists"),
        ("CUS-2007", "falls after the notice date"),
        ("CUS-2008", "above the"),
    ]
    for customer_id, fragment in cases:
        reason = held_reason(customer_id)
        check("{0} is held".format(customer_id), reason is not None)
        check("{0} reason names the actual problem".format(customer_id),
              reason is not None and fragment in reason, str(reason))
        check("{0} reason is not generic".format(customer_id),
              reason is not None and "failed validation" not in reason.lower())


def test_clean_records_produce_letters():
    prepared = engine.prepare_all(RECORDS, RULES, BLOCKS)
    ready = [item for item in prepared if item["status"] == "ready"]
    check("clean records still produce letters", len(ready) >= 15, str(len(ready)))
    for letter in ready:
        record = letter["record"]
        block = letter["block"]
        check("block matches the record variant",
              (block["jurisdiction"] == record["jurisdiction"]
               and block["stage"] == record["stage"]
               and block["language"] == record["language"]))
        for section in letter["sections"]:
            check("no placeholder is left unfilled", "{{" not in section["text"],
                  section["text"][:60])


def test_approved_wording_is_never_altered():
    """Strip the inserted values back out and the approved block must reappear."""
    prepared = engine.prepare_all(RECORDS, RULES, BLOCKS)
    for letter in [item for item in prepared if item["status"] == "ready"]:
        for section in letter["sections"]:
            rebuilt = section["text"]
            for placeholder in sorted(section["placeholders"], key=len, reverse=True):
                value = str(letter["fills"][placeholder])
                rebuilt = rebuilt.replace(value, "{{" + placeholder + "}}")
            check("section '{0}' is the approved wording with values inserted".format(
                section["id"]), rebuilt == section["approved_text"],
                "got: " + rebuilt[:80])


def test_language_variant_is_produced():
    spanish = engine.prepare(by_id("CUS-1003"), RULES, BLOCKS)
    check("spanish letter uses the spanish block",
          spanish["block"]["language"] == "es", spanish["block"]["id"])
    account_line = [section for section in spanish["sections"]
                    if section["id"] == "account_line"][0]
    check("spanish date format is used", "de agosto de 2026" in account_line["text"],
          account_line["text"])
    english = engine.prepare(by_id("CUS-1001"), RULES, BLOCKS)
    english_line = [section for section in english["sections"]
                    if section["id"] == "account_line"][0]
    check("english date format is used", "August 17, 2026" in english_line["text"],
          english_line["text"])


def test_no_customer_is_processed_twice():
    duplicated = RECORDS + [by_id("CUS-1001")]
    prepared = engine.prepare_all(duplicated, RULES, BLOCKS)
    ids = [item["record"]["customer_id"] for item in prepared]
    check("duplicate customer ids are skipped", len(ids) == len(set(ids)))


def test_batches_respect_the_operation_limit():
    ready = [item for item in engine.prepare_all(RECORDS, RULES, BLOCKS)
             if item["status"] == "ready"]
    batches = run.pack_batches(ready)
    for batch in batches:
        sections = sum(len(letter["sections"]) + 1 for letter in batch)
        check("batch stays inside one operation",
              sections <= run.MAX_SECTIONS_PER_OPERATION, str(sections))
    packed = sum(len(batch) for batch in batches)
    check("every ready letter is packed exactly once", packed == len(ready))


def test_a_new_jurisdiction_needs_no_code_change():
    """Only runs once New York exists in the data files."""
    if "new_york" not in RULES["jurisdictions"]:
        return
    candidates = [record for record in RECORDS if record["jurisdiction"] == "new_york"
                  and "defect_note" not in record]
    check("new york records exist", bool(candidates))
    for record in candidates:
        result = engine.prepare(record, RULES, BLOCKS)
        check("new york record {0} produces a letter".format(record["customer_id"]),
              result["status"] == "ready",
              str(result.get("failures")))
        if result["status"] == "ready":
            check("new york uses the new york rate",
                  result["values"]["annual_rate_bps"] == Decimal(
                      RULES["jurisdictions"]["new_york"]["interest_rate_bps"]))


def main():
    for name, function in sorted(globals().items()):
        if name.startswith("test_") and callable(function):
            function()
    print("{0} assertions passed, {1} failed".format(len(PASSED), len(FAILED)))
    for failure in FAILED:
        print("  FAILED: " + failure)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
