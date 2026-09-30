import pymupdf
from pathlib import Path

PDF_PATH = Path("docs/PASSENGER DATA.pdf")

OUTPUT_DIR = Path("data/passengerdata/annexure2_images")


def find_route_3_chart(pdf_path):
    doc = pymupdf.open(pdf_path)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for page_number, page in enumerate(doc):
        text = page.get_text()

        if "Route no. 3:" in text:
            print(
                f"Route 3 chart found on PDF page {page_number + 1}"
            )

            pixmap = page.get_pixmap(
                matrix=pymupdf.Matrix(3, 3)
            )

            output_file = OUTPUT_DIR / "route_3_chart.png"
            pixmap.save(output_file)

            print(f"Saved: {output_file}")
            break

    doc.close()

if __name__ == "__main__":
    find_route_3_chart(PDF_PATH)