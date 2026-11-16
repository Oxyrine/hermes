from hermes.ledger.states import TABLE

G = TABLE[("verified", "financeable")]
OK = {"band": "A", "eligibility": "eligible", "hard_flags": []}


def test_clean_invoice_passes():
    assert G(OK)


def test_trader_goes_to_review_not_financeable():
    assert not G(OK | {"eligibility": "manual_review"})


def test_any_hard_flag_blocks_whatever_the_score():
    assert not G(OK | {"hard_flags": ["debit_note"]})
