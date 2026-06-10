"""Generate the 5 demo documents listed in livrables/scenario_demo.md §1.2.

Synthetic but realistic "scans" (typed text + light noise/rotation) readable by docTR:

    1. recu_diy.jpg        invoice   — merchant/total/date/taxes + CA$ → € conversion
    2. contrat_service.pdf contract  — parties + dates (server-rendered PDF path)
    3. ordonnance.jpg      medical   — patient/doctor (the "stays local" argument)
    4. rapport_annuel.pdf  report    — title/author (collection QA)
    5. recu_diy_copie.jpg  invoice   — same content re-rendered → duplicate detection

Usage:  python3 demo_docs/generate_demo_docs.py
"""

from __future__ import annotations

import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = Path(__file__).parent
FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
MONO = FONT_DIR / "DejaVuSansMono.ttf"
SANS = FONT_DIR / "DejaVuSans.ttf"
SANS_BOLD = FONT_DIR / "DejaVuSans-Bold.ttf"


def render(lines: list[tuple[str, str]], width: int, font_size: int, margin: int = 50,
           line_gap: float = 1.45, mono: bool = False) -> Image.Image:
    """Render (style, text) lines on a white page. style: '' | 'b' (bold) | 'h' (heading)."""
    body = ImageFont.truetype(str(MONO if mono else SANS), font_size)
    bold = ImageFont.truetype(str(MONO if mono else SANS_BOLD if SANS_BOLD.exists() else SANS),
                              font_size)
    head = ImageFont.truetype(str(SANS_BOLD), int(font_size * 1.5))
    step = int(font_size * line_gap)
    height = margin * 2 + sum(
        int(font_size * 1.5 * line_gap) if s == "h" else step for s, _ in lines)
    img = Image.new("L", (width, height), 252)
    draw = ImageDraw.Draw(img)
    y = margin
    for style, text in lines:
        font = {"b": bold, "h": head}.get(style, body)
        draw.text((margin, y), text, font=font, fill=15)
        y += int(font_size * 1.5 * line_gap) if style == "h" else step
    return img


def scanify(img: Image.Image, angle: float, seed: int) -> Image.Image:
    """Light scan artifacts: tiny rotation, blur, per-pixel noise."""
    img = img.rotate(angle, expand=True, fillcolor=252, resample=Image.BICUBIC)
    img = img.filter(ImageFilter.GaussianBlur(0.4))
    rng = random.Random(seed)
    px = img.load()
    w, h = img.size
    for _ in range(w * h // 30):  # sparse salt-and-pepper grain
        x, y = rng.randrange(w), rng.randrange(h)
        px[x, y] = max(0, min(255, px[x, y] + rng.randint(-35, 35)))
    return img.convert("RGB")


RECEIPT = [
    ("b", "RONA L'ENTREPOT"),
    ("", "QUINCAILLERIE & MATERIAUX"),
    ("", "1450 BOUL. TALBOT, CHICOUTIMI QC"),
    ("", "TEL: (418) 545-7090"),
    ("", "--------------------------------"),
    ("b", "RECEIPT / RECU DE CAISSE"),
    ("", "DATE: 2026-06-05      13:42"),
    ("", "CASHIER: #04"),
    ("", "--------------------------------"),
    ("", "QTY  ITEM              PRICE"),
    ("", "1    PERCEUSE 18V      CA$ 49.99"),
    ("", "2    VIS BOIS 50PK     CA$ 11.98"),
    ("", "1    RUBAN MESURE 5M   CA$  8.49"),
    ("", "1    GANTS TRAVAIL     CA$  6.99"),
    ("", "--------------------------------"),
    ("", "SUBTOTAL             CA$ 77.45"),
    ("", "TPS (5%)             CA$  3.87"),
    ("", "TVQ (9.975%)         CA$  7.73"),
    ("b", "TOTAL                CA$ 89.05"),
    ("", "--------------------------------"),
    ("", "PAID DEBIT           CA$ 89.05"),
    ("", "CHANGE               CA$  0.00"),
    ("", ""),
    ("", "MERCI / THANK YOU"),
]

CONTRACT = [
    ("h", "SERVICE AGREEMENT"),
    ("", "Contrat de services"),
    ("", ""),
    ("", "This Service Agreement (\"Agreement\") is entered into as of"),
    ("", "June 1, 2026, by and between:"),
    ("", ""),
    ("b", "Party A: Nordix Solutions Inc., 234 rue Racine Est,"),
    ("", "Chicoutimi (Quebec) G7H 1S8 (\"Client\")"),
    ("", ""),
    ("b", "Party B: DocuFlow Conseil S.E.N.C., 555 boul. de l'Universite,"),
    ("", "Saguenay (Quebec) G7H 2B1 (\"Provider\")"),
    ("", ""),
    ("", "WHEREAS the Client wishes to retain the Provider for document"),
    ("", "digitization and archiving services, the parties hereby agree"),
    ("", "to the following terms:"),
    ("", ""),
    ("", "1. Term. This Agreement begins on 2026-06-01 and ends on"),
    ("", "   2027-05-31, unless terminated earlier under clause 6."),
    ("", "2. Services. The Provider shall digitize, index and archive"),
    ("", "   the Client's administrative documents."),
    ("", "3. Compensation. The Client shall pay the Provider a total"),
    ("", "   value of CA$ 24,000 in twelve monthly instalments."),
    ("", "4. Confidentiality. Each party shall keep all documents and"),
    ("", "   data strictly confidential."),
    ("", "5. Obligations. The Provider shall meet the service levels"),
    ("", "   described in Schedule A."),
    ("", "6. Termination. Either party may terminate this Agreement"),
    ("", "   with 30 days written notice."),
    ("", ""),
    ("", "Signed in Saguenay, Quebec, on June 1, 2026."),
    ("", ""),
    ("", "__________________________    __________________________"),
    ("", "Nordix Solutions Inc.         DocuFlow Conseil S.E.N.C."),
    ("", "(Party A)                     (Party B)"),
]

PRESCRIPTION = [
    ("b", "CLINIQUE MEDICALE DU FJORD"),
    ("", "1201 rue des Champs, Chicoutimi QC G7H 4B5"),
    ("", "Tel: (418) 555-0143"),
    ("", ""),
    ("h", "ORDONNANCE / PRESCRIPTION"),
    ("", ""),
    ("b", "Patient: Martin Tremblay"),
    ("", "Date de naissance: 1985-03-12"),
    ("", "Date: 2026-06-04"),
    ("", ""),
    ("", "Rx:"),
    ("", "1. Amoxicilline 500 mg"),
    ("", "   1 comprime 3 fois par jour - 7 jours"),
    ("", "2. Ibuprofene 400 mg"),
    ("", "   1 comprime au besoin, maximum 3 par jour"),
    ("", ""),
    ("", "Renouvellement: 0"),
    ("", ""),
    ("b", "Dr. Sophie Bergeron, MD"),
    ("", "Permis #84512"),
    ("", "Signature: S. Bergeron"),
]

REPORT = [
    ("h", "RAPPORT ANNUEL 2025"),
    ("", "Gestion documentaire et transformation numerique"),
    ("", ""),
    ("b", "Auteur: Direction des operations"),
    ("", "Organisation: Cooperative Regionale du Saguenay"),
    ("", "Date: 2026-05-15"),
    ("", ""),
    ("b", "RESUME / ABSTRACT"),
    ("", "Ce rapport presente un summary des activites de gestion"),
    ("", "documentaire de la cooperative pour l'exercice 2025."),
    ("", ""),
    ("b", "1. INTRODUCTION"),
    ("", "Le volume de documents administratifs traites a augmente de"),
    ("", "18% par rapport a 2024, principalement des factures et des"),
    ("", "contrats de service."),
    ("", ""),
    ("b", "2. ANALYSIS / FINDINGS"),
    ("", "L'analyse montre que 62% du temps de traitement est consacre"),
    ("", "a la saisie manuelle des champs cles. Les findings indiquent"),
    ("", "un fort potentiel d'automatisation par extraction assistee."),
    ("", ""),
    ("b", "3. CONCLUSION"),
    ("", "La cooperative recommande le deploiement d'un outil local"),
    ("", "d'extraction de documents en 2026 (section budget, figure 4)."),
]


def main() -> None:
    receipt = render(RECEIPT, width=620, font_size=22, mono=True)
    scanify(receipt, angle=0.5, seed=1).save(OUT / "recu_diy.jpg", quality=92)
    scanify(receipt, angle=-0.7, seed=7).save(OUT / "recu_diy_copie.jpg", quality=88)

    contract = render(CONTRACT, width=1240, font_size=26)
    scanify(contract, angle=0.25, seed=3).save(OUT / "contrat_service.pdf",
                                               resolution=150.0)

    rx = render(PRESCRIPTION, width=900, font_size=26)
    scanify(rx, angle=-0.4, seed=5).save(OUT / "ordonnance.jpg", quality=92)

    report = render(REPORT, width=1240, font_size=26)
    scanify(report, angle=0.2, seed=9).save(OUT / "rapport_annuel.pdf", resolution=150.0)

    for f in ["recu_diy.jpg", "contrat_service.pdf", "ordonnance.jpg",
              "rapport_annuel.pdf", "recu_diy_copie.jpg"]:
        print(f"wrote {OUT / f}")


if __name__ == "__main__":
    main()
