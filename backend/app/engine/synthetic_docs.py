"""Generate clearly-labelled SYNTHETIC sample contracts as PDFs.

These are illustrative documents written for the demo. They are not real
agreements and do not describe any real fund, lender, partnership or employer.
Generating them as PDFs lets the same parse -> retrieve -> extract -> cite
pipeline run on them as on the real BREIT prospectus.
"""
from __future__ import annotations

from pathlib import Path

import pymupdf as fitz

BANNER = "SYNTHETIC SAMPLE DOCUMENT - FOR DEMONSTRATION ONLY - NOT A REAL AGREEMENT"

SYNTHETIC_DOCS: dict[str, dict] = {
    "SYNTHETIC_Interval_Fund_Repurchase_Policy.pdf": {
        "title": "Summit Ridge Credit Interval Fund (Synthetic) - Repurchase Policy Excerpt",
        "pages": [
            [
                "Repurchase Offers",
                "The Fund is an interval fund and has adopted a fundamental policy to make quarterly "
                "repurchase offers for between 5% and 25% of its outstanding Shares at net asset value. "
                "The Fund currently expects to offer to repurchase 5% of its outstanding Shares in each "
                "quarterly repurchase offer. Repurchase offers will be made in March, June, September and "
                "December of each year.",
                "If Shareholders tender more Shares than the Repurchase Offer Amount, the Fund may, but is "
                "not required to, repurchase an additional amount of up to 2% of its outstanding Shares. "
                "If the Fund does not repurchase the additional amount, the Fund will repurchase tendered "
                "Shares on a pro rata basis.",
            ],
            [
                "Repurchase Fee and Payment",
                "Shares repurchased will be subject to a repurchase fee of 2.00% of the net asset value of "
                "the Shares repurchased, payable to the Fund.",
                "The Repurchase Pricing Date will occur no later than the 14th day after the Repurchase "
                "Request Deadline. Payment for repurchased Shares will be made no later than seven days "
                "after the Repurchase Pricing Date.",
                "The Board may suspend or postpone a repurchase offer only in limited circumstances "
                "described in this policy, including if the repurchase would cause the Fund to lose its "
                "tax status or if trading on a principal exchange is restricted.",
            ],
        ],
    },
    "SYNTHETIC_Securities_Backed_Line_Agreement.pdf": {
        "title": "Synthetic Securities-Backed Line of Credit Agreement - Key Terms",
        "pages": [
            [
                "Section 4. Advance Rate and Maintenance Requirement",
                "4.1 Advance Rate. The Lender will extend credit up to an amount equal to 50% of the market "
                "value of Eligible Collateral (the \"Advance Rate\").",
                "4.2 Maintenance Requirement. If at any time the outstanding Loan Balance exceeds 60% of the "
                "market value of the Collateral (the \"Maintenance Threshold\"), the Lender will issue a "
                "Collateral Call to the Borrower.",
                "4.3 Collateral Call. Upon a Collateral Call, the Borrower must, within 3 business days, "
                "deposit cash or additional Eligible Collateral, or repay the Loan Balance, in an amount "
                "sufficient to reduce the Loan Balance to the Advance Rate.",
            ],
            [
                "Section 5. Remedies and Interest",
                "5.1 If the Borrower fails to satisfy a Collateral Call within the cure period, the Lender "
                "may, without further notice, sell any or all of the Collateral.",
                "5.2 Interest accrues on the outstanding Loan Balance at a fixed annual rate of 7.25%, "
                "payable monthly in arrears.",
            ],
        ],
    },
    "SYNTHETIC_Private_Fund_LPA_Capital_Calls.pdf": {
        "title": "Synthetic Private Equity Fund LP - Limited Partnership Agreement Excerpt",
        "pages": [
            [
                "Article 3. Capital Contributions",
                "3.1 Each Limited Partner shall make Capital Contributions to the Partnership in amounts "
                "not to exceed its Unfunded Commitment, upon not less than 10 business days' prior written "
                "notice from the General Partner (a \"Drawdown Notice\").",
                "3.2 The timing and amount of capital calls are at the sole discretion of the General "
                "Partner, and a Limited Partner's obligation to fund a capital call is not reduced or "
                "deferred because of market conditions.",
                "3.3 Default. If a Limited Partner fails to fund a capital call when due, the General "
                "Partner may charge interest at 10% per annum on the unpaid amount and may cause the "
                "Defaulting Limited Partner to forfeit up to 50% of its Capital Account.",
            ],
        ],
    },
    "SYNTHETIC_RSU_Grant_and_Trading_Policy.pdf": {
        "title": "Synthetic RSU Grant Notice and Insider Trading Policy Excerpt",
        "pages": [
            [
                "RSU Grant Notice - Tax Withholding",
                "Unless the Participant elects otherwise, the Company will withhold Shares to satisfy tax "
                "withholding obligations at the federal supplemental wage rate of 22%.",
                "The Participant may elect a withholding rate up to the maximum individual statutory rate "
                "of 37%. Any tax liability in excess of the amount withheld remains the responsibility of "
                "the Participant.",
            ],
            [
                "Insider Trading Policy - Trading Windows",
                "Covered Persons may trade Company securities only during an open trading window. The "
                "trading window opens on the second trading day after the public release of quarterly "
                "earnings and closes on the fifteenth day of the third month of each fiscal quarter.",
                "The Company's fiscal quarters end on March 31, June 30, September 30 and December 31, and "
                "quarterly earnings are generally released in the first month following quarter end.",
            ],
        ],
    },
}


def _write_pdf(path: Path, title: str, pages: list[list[str]]) -> None:
    doc = fitz.open()
    for i, paras in enumerate(pages, start=1):
        page = doc.new_page(width=612, height=792)
        page.insert_textbox(fitz.Rect(54, 30, 558, 60), BANNER, fontsize=9, fontname="hebo",
                            color=(0.7, 0.1, 0.1), align=1)
        page.insert_textbox(fitz.Rect(54, 64, 558, 100), title, fontsize=13, fontname="hebo")
        body = "\n\n".join(paras)
        page.insert_textbox(fitz.Rect(54, 110, 558, 720), body, fontsize=10.5, fontname="helv")
        page.insert_textbox(fitz.Rect(54, 740, 558, 760), str(i), fontsize=9, fontname="helv", align=1)
    doc.save(path)
    doc.close()


def ensure_synthetic_docs(out_dir: str | Path) -> list[Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, spec in SYNTHETIC_DOCS.items():
        p = out_dir / name
        if not p.exists():
            _write_pdf(p, spec["title"], spec["pages"])
        paths.append(p)
    return paths


def is_synthetic_document(name: str, first_page_text: str = "") -> bool:
    return name.upper().startswith("SYNTHETIC") or "SYNTHETIC SAMPLE DOCUMENT" in first_page_text.upper()
