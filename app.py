import io, re
from datetime import datetime
import pandas as pd
import requests
import streamlit as st
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
import pytesseract

APP_TITLE = "BookScan Library"
COLUMNS = ["Book Title", "Author", "ISBN", "Publisher", "Publication Year", "Edition", "Language", "Category", "Shelf Location", "Quantity", "Metadata Source", "Verification Status", "Date Added", "Notes"]
st.set_page_config(page_title=APP_TITLE, page_icon="📚", layout="wide")


def normalise_isbn(value):
    return re.sub(r"[^0-9Xx]", "", value or "").upper()


def is_valid_isbn(value):
    isbn = normalise_isbn(value)
    if len(isbn) == 10:
        return sum((10-i) * (10 if c == "X" else int(c)) for i, c in enumerate(isbn)) % 11 == 0
    if len(isbn) == 13 and isbn.isdigit():
        total = sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(isbn[:12]))
        return (10 - total % 10) % 10 == int(isbn[-1])
    return False


def find_isbns(text):
    pattern = r"(?i)(?:ISBN(?:-1[03])?\s*[: ]*)?((?:97[89][\s-]?)?(?:[0-9X][\s-]?){9,16}[0-9X])"
    found = []
    for value in re.findall(pattern, text or ""):
        isbn = normalise_isbn(value)
        if is_valid_isbn(isbn) and isbn not in found:
            found.append(isbn)
    return found


def ocr_text(image):
    """Run two OCR layouts on an enlarged, cleaned image and merge unique lines."""
    image = ImageOps.exif_transpose(image).convert("RGB")
    image = ImageOps.grayscale(image)
    # Upscaling helps small Malayalam glyphs and punctuation.
    image = image.resize((image.width * 2, image.height * 2), Image.Resampling.LANCZOS)
    image = ImageOps.autocontrast(image)
    image = ImageEnhance.Contrast(image).enhance(1.5)
    image = image.filter(ImageFilter.SHARPEN)
    # Keep a grayscale pass for mixed text and a thresholded pass for faint print.
    threshold = image.point(lambda pixel: 255 if pixel > 165 else 0)
    chunks = []
    for candidate_image, psm in ((image, 6), (image, 11), (threshold, 6)):
        try:
            text = pytesseract.image_to_string(candidate_image, lang="eng+mal", config=f"--oem 1 --psm {psm}")
            if text.strip(): chunks.append(text)
        except Exception:
            continue
    # Merge line-by-line without repeating identical lines from the different passes.
    lines, seen = [], set()
    for chunk in chunks:
        for line in chunk.splitlines():
            line = line.strip()
            key = re.sub(r"\s+", " ", line).casefold()
            if line and key not in seen:
                seen.add(key)
                lines.append(line)
    if not lines:
        raise RuntimeError("OCR returned no text. Try a clearer photo or type the details manually.")
    return "\n".join(lines)


def google_books(query):
    try:
        response = requests.get("https://www.googleapis.com/books/v1/volumes", params={"q": query, "maxResults": 8}, timeout=15)
        response.raise_for_status()
        results = []
        for item in response.json().get("items", []):
            info = item.get("volumeInfo", {})
            ids = info.get("industryIdentifiers", [])
            isbn13 = next((x.get("identifier", "") for x in ids if x.get("type") == "ISBN_13"), "")
            isbn10 = next((x.get("identifier", "") for x in ids if x.get("type") == "ISBN_10"), "")
            results.append({"Book Title": info.get("title", ""), "Author": ", ".join(info.get("authors", [])), "ISBN": isbn13 or isbn10, "Publisher": info.get("publisher", ""), "Publication Year": str(info.get("publishedDate", ""))[:4], "Edition": info.get("edition", ""), "Language": info.get("language", ""), "Category": ", ".join(info.get("categories", [])), "Metadata Source": "Google Books", "Verification Status": "Online result — please check", "Notes": str(info.get("description", ""))[:600]})
        return results
    except (requests.RequestException, ValueError, TypeError):
        return []


def open_library(query, by_isbn=False):
    try:
        if by_isbn:
            response = requests.get(f"https://openlibrary.org/isbn/{requests.utils.quote(query)}.json", timeout=15)
            if response.status_code != 200:
                return []
            info = response.json()
            publishers = info.get("publishers", [])
            if isinstance(publishers, str): publishers = [publishers]
            return [{"Book Title": info.get("title", ""), "Author": "", "ISBN": query, "Publisher": ", ".join(publishers[:3]), "Publication Year": str(info.get("publish_date", ""))[-4:], "Edition": "", "Language": "", "Category": "", "Metadata Source": "Open Library", "Verification Status": "Online result — please check", "Notes": ""}]
        response = requests.get("https://openlibrary.org/search.json", params={"title": query, "limit": 8}, timeout=15)
        response.raise_for_status()
        results = []
        for doc in response.json().get("docs", []):
            isbns = doc.get("isbn", [])
            results.append({"Book Title": doc.get("title", ""), "Author": ", ".join(doc.get("author_name", [])), "ISBN": isbns[0] if isbns else "", "Publisher": ", ".join(doc.get("publisher", [])[:3]), "Publication Year": str(doc.get("first_publish_year", "")), "Edition": "", "Language": ", ".join(doc.get("language", [])[:3]), "Category": ", ".join(doc.get("subject", [])[:3]), "Metadata Source": "Open Library", "Verification Status": "Online result — please check", "Notes": ""})
        return results
    except (requests.RequestException, ValueError, TypeError):
        return []


def lookup_book(isbn, title):
    """Search online sources; ISBN lookups normally identify one edition."""
    if isbn and is_valid_isbn(isbn):
        results = google_books("isbn:" + isbn)
        # Google Books can return a match with incomplete metadata. Try Open Library too
        # and merge it when it has additional information for the same ISBN.
        extra = open_library(isbn, by_isbn=True)
        if results:
            if extra:
                first = results[0]
                for key in ("Book Title", "Author", "Publisher", "Publication Year", "Language", "Category", "Edition", "Notes"):
                    if not first.get(key) and extra[0].get(key): first[key] = extra[0][key]
            return results
        if extra: return extra
    if title.strip():
        results = google_books("intitle:" + title.strip())
        extra = open_library(title.strip())
        if results:
            return results + [r for r in extra if normalise_isbn(r.get("ISBN", "")) not in {normalise_isbn(x.get("ISBN", "")) for x in results}]
        return extra
    return []


def empty_book():
    book = {column: "" for column in COLUMNS}
    # The library mainly handles Malayalam/DC Books titles; staff can change these defaults.
    book["Publisher"] = "DC Books"
    book["Language"] = "Malayalam"
    book["Quantity"] = 1
    book["Metadata Source"] = "Manual entry"
    book["Verification Status"] = "Manual entry — not verified"
    return book


def sheets_configured():
    try:
        return "gcp_service_account" in st.secrets and "google_sheet_id" in st.secrets
    except Exception:
        return False


def save_to_sheets(book):
    import gspread
    from google.oauth2.service_account import Credentials
    creds = Credentials.from_service_account_info(dict(st.secrets["gcp_service_account"]), scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"])
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(st.secrets["google_sheet_id"])
    worksheet_name = st.secrets.get("google_worksheet", "Books")
    try:
        worksheet = spreadsheet.worksheet(worksheet_name)
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(title=worksheet_name, rows=1000, cols=len(COLUMNS))
    if not worksheet.row_values(1): worksheet.append_row(COLUMNS)
    worksheet.append_row([str(book.get(c, "")) for c in COLUMNS], value_input_option="USER_ENTERED")


st.title("📚 BookScan Library | പുസ്തക വിവരങ്ങൾ")
st.write("Scan a book page, check the details, and save it to your library list.  \nപുസ്തകത്തിന്റെ പേജ് സ്കാൻ ചെയ്യുക, വിവരങ്ങൾ പരിശോധിക്കുക, ലൈബ്രറി പട്ടികയിൽ സേവ് ചെയ്യുക.")
with st.expander("How to use / എങ്ങനെ ഉപയോഗിക്കാം", expanded=True):
    st.markdown("1. **Scan or upload one clear page** — ഒരു വ്യക്തമായ പേജ് സ്കാൻ ചെയ്യുക.  \n2. **Read and check the text** — ലഭിച്ച ടെക്സ്റ്റ് പരിശോധിക്കുക.  \n3. **Search for book details** — ISBN ഉപയോഗിച്ച് വിവരങ്ങൾ തിരയുക.  \n4. **Correct and save the book** — വിവരങ്ങൾ തിരുത്തി സേവ് ചെയ്യുക.  \n\n**For best results:** Use a clear, straight photo of the title/copyright page or ISBN barcode. This reads the photographed page, not the entire book. Malayalam OCR can still make mistakes, so verify the result.  \n**കൂടുതൽ നല്ല ഫലത്തിന്:** ടൈറ്റിൽ/കോപ്പിറൈറ്റ് പേജിന്റെയോ ISBN ബാർകോഡിന്റെയോ വ്യക്തമായ ഫോട്ടോ എടുക്കുക. ഫോട്ടോയിലുള്ള പേജ് മാത്രമാണ് വായിക്കുന്നത്; മുഴുവൻ പുസ്തകമല്ല. ലഭിച്ച വിവരങ്ങൾ പരിശോധിക്കുക.")
    st.markdown("**DC Books catalogue / DC Books പുസ്തകപ്പട്ടിക:** https://dcbooks.com/books/ — If an ISBN is missing from the online results, search it here and enter the details manually.")

if "books" not in st.session_state: st.session_state.books = []
if "ocr" not in st.session_state: st.session_state.ocr = ""
if "candidate" not in st.session_state: st.session_state.candidate = empty_book()
if "results" not in st.session_state: st.session_state.results = []
if "batch_results" not in st.session_state: st.session_state.batch_results = []

st.header("1. Scan a book / പുസ്തകം സ്കാൻ ചെയ്യുക")
tab_camera, tab_upload = st.tabs(["📷 Use camera / ക്യാമറ", "📁 Upload image / ചിത്രം അപ്‌ലോഡ് ചെയ്യുക"])
image_file = None
with tab_camera:
    camera_file = st.camera_input("Take a photo of the book page / പേജിന്റെ ഫോട്ടോ എടുക്കുക")
    if camera_file is not None: image_file = camera_file
with tab_upload:
    uploaded_file = st.file_uploader("Choose a photo / ചിത്രം തിരഞ്ഞെടുക്കുക", type=["png", "jpg", "jpeg", "webp", "tif", "tiff"])
    if uploaded_file is not None: image_file = uploaded_file
if image_file is not None:
    try:
        image = Image.open(image_file)
        st.image(image, caption="Selected page / തിരഞ്ഞെടുത്ത പേജ്", use_container_width=True)
        if st.button("Read English + Malayalam text / മലയാളവും ഇംഗ്ലീഷും വായിക്കുക", type="primary"):
            with st.spinner("Reading the page… / പേജ് വായിക്കുന്നു…"):
                st.session_state.ocr = ocr_text(image)
            st.success("Text reading finished. Please check it below. / ടെക്സ്റ്റ് ലഭിച്ചു. താഴെ പരിശോധിക്കുക.")
    except Exception as exc:
        st.error("Could not read the image. Check that OCR and both language packs are installed. / ചിത്രം വായിക്കാൻ കഴിഞ്ഞില്ല.")
        st.caption(str(exc))

if st.session_state.ocr:
    st.subheader("2. Text found / ലഭിച്ച ടെക്സ്റ്റ്")
    st.text_area("Check extracted text / ലഭിച്ച ടെക്സ്റ്റ് പരിശോധിക്കുക", value=st.session_state.ocr, key="ocr_editor", height=160)

st.divider()
st.header("3. Find book details / പുസ്തക വിവരങ്ങൾ കണ്ടെത്തുക")
col_isbn, col_title = st.columns(2)
with col_isbn:
    candidates = find_isbns(st.session_state.get("ocr_editor", st.session_state.ocr))
    isbn_input = st.text_input("ISBN (if available) / ISBN നമ്പർ", value=candidates[0] if candidates else "")
with col_title:
    title_input = st.text_input("Book title or keywords / പുസ്തകത്തിന്റെ പേര്", help="Enter English or Malayalam text.")
if st.button("Search online / ഓൺലൈനിൽ തിരയുക", use_container_width=True):
    cleaned = normalise_isbn(isbn_input)
    if cleaned and not is_valid_isbn(cleaned): st.warning("ISBN may contain a typo. Search by title if needed.")
    with st.spinner("Searching book databases… / പുസ്തക വിവരങ്ങൾ തിരയുന്നു…"):
        st.session_state.results = lookup_book(cleaned if is_valid_isbn(cleaned) else "", title_input)
    if not st.session_state.results:
        st.warning("No online match found. Enter details manually below. / വിവരങ്ങൾ കണ്ടെത്തിയില്ലെങ്കിൽ താഴെ സ്വയം നൽകാം.")
    else:
        st.success(f"Found {len(st.session_state.results)} possible result(s). Choose the correct edition.")
if st.session_state.results:
    labels = [f'{r.get("Book Title") or "Untitled"} — {r.get("Author") or "Author not listed"} ({r.get("Metadata Source", "")})' for r in st.session_state.results]
    chosen = st.selectbox("Choose the correct book / ശരിയായ പുസ്തകം തിരഞ്ഞെടുക്കുക", range(len(labels)), format_func=lambda i: labels[i])
    if st.button("Use these details / ഈ വിവരങ്ങൾ ഉപയോഗിക്കുക"):
        record = empty_book(); record.update(st.session_state.results[chosen])
        if not record.get("ISBN"): record["ISBN"] = normalise_isbn(isbn_input)
        st.session_state.candidate = record
        st.success("Details loaded into the review form. / വിവരങ്ങൾ ഫോമിലേക്ക് മാറ്റി.")

st.divider()
st.header("4. Check and save / പരിശോധിച്ച് സേവ് ചെയ്യുക")
st.caption("Correct mistakes before saving. Nothing is saved until you press Save. / സേവ് ചെയ്യുന്നതിന് മുമ്പ് തെറ്റുകൾ തിരുത്തുക.")
candidate = st.session_state.candidate.copy()
with st.form("book_form"):
    left, right = st.columns(2)
    with left:
        title = st.text_input("Book title / പുസ്തകത്തിന്റെ പേര്", value=candidate.get("Book Title", ""))
        author = st.text_input("Author / എഴുത്തുകാരൻ", value=candidate.get("Author", ""))
        isbn = st.text_input("ISBN", value=candidate.get("ISBN", ""))
        publisher = st.text_input("Publisher / പ്രസാധകർ", value=candidate.get("Publisher", ""))
        year = st.text_input("Publication year / പ്രസിദ്ധീകരിച്ച വർഷം", value=candidate.get("Publication Year", ""))
        edition = st.text_input("Edition / പതിപ്പ്", value=candidate.get("Edition", ""))
        language = st.text_input("Language / ഭാഷ", value=candidate.get("Language", ""))
    with right:
        category = st.text_input("Category / വിഭാഗം", value=candidate.get("Category", ""))
        shelf = st.text_input("Shelf or section / ഷെൽഫ് സ്ഥലം", value=candidate.get("Shelf Location", ""))
        quantity = st.number_input("Number of copies / കോപ്പികളുടെ എണ്ണം", min_value=1, max_value=100000, value=1, step=1)
        source = st.text_input("Information source / വിവരങ്ങളുടെ ഉറവിടം", value=candidate.get("Metadata Source", "Manual entry"))
        status_options = ["Checked by staff", "Online result — please check", "Manual entry — not verified"]
        old_status = candidate.get("Verification Status", "Manual entry — not verified")
        status = st.selectbox("Verification / പരിശോധന നില", status_options, index=status_options.index(old_status) if old_status in status_options else 2)
        notes = st.text_area("Notes / കുറിപ്പുകൾ", value=candidate.get("Notes", ""))
    submitted = st.form_submit_button("Save book / പുസ്തകം സേവ് ചെയ്യുക", type="primary", use_container_width=True)
if submitted:
    if not title.strip():
        st.error("Please enter a book title. / പുസ്തകത്തിന്റെ പേര് നൽകുക.")
    else:
        record = {"Book Title": title.strip(), "Author": author.strip(), "ISBN": normalise_isbn(isbn), "Publisher": publisher.strip(), "Publication Year": year.strip(), "Edition": edition.strip(), "Language": language.strip(), "Category": category.strip(), "Shelf Location": shelf.strip(), "Quantity": int(quantity), "Metadata Source": source.strip(), "Verification Status": status, "Date Added": datetime.now().astimezone().isoformat(timespec="seconds"), "Notes": notes.strip()}
        st.session_state.books.append(record)
        if sheets_configured():
            try:
                save_to_sheets(record)
                st.success("Saved in the app session and Google Sheets. / Google Sheets-ലും സേവ് ചെയ്തു.")
            except Exception as exc:
                st.warning("Saved for this session, but Google Sheets sync failed. Download Excel and ask the app administrator to check the connection.")
                st.caption(str(exc))
        else:
            st.success("Saved in this session. Download Excel before closing, or ask the app administrator to connect Google Sheets. / ഈ സെഷനിൽ സേവ് ചെയ്തു. അടയ്ക്കുന്നതിന് മുമ്പ് Excel ഡൗൺലോഡ് ചെയ്യുക.")
        st.session_state.candidate = empty_book()
        st.session_state.results = []

st.divider()
st.header("5. Add several books by ISBN / ISBN ഉപയോഗിച്ച് പല പുസ്തകങ്ങളും ചേർക്കുക")
st.caption("Enter one ISBN per line. Each ISBN is searched separately; check the details before saving. / ഓരോ വരിയിലും ഒരു ISBN നൽകുക.")
with st.expander("Batch ISBN entry / ഒരുമിച്ച് ISBN ചേർക്കുക", expanded=False):
    batch_isbns = st.text_area("ISBN numbers / ISBN നമ്പറുകൾ", placeholder="9788126439362\n9789370983694\n9789364872638", height=120)
    if st.button("Search all ISBNs / എല്ലാ ISBN-കളും തിരയുക"):
        values, seen = [], set()
        for raw in batch_isbns.splitlines():
            isbn_value = normalise_isbn(raw)
            if isbn_value and isbn_value not in seen:
                seen.add(isbn_value)
                values.append(isbn_value)
        found_rows = []
        if not values:
            st.warning("Enter at least one ISBN. / കുറഞ്ഞത് ഒരു ISBN നൽകുക.")
        else:
            progress = st.progress(0)
            for i, value in enumerate(values):
                results = lookup_book(value, "") if is_valid_isbn(value) else []
                if results:
                    row = empty_book(); row.update(results[0]); row["ISBN"] = row.get("ISBN") or value
                    row["Quantity"] = 1
                    if not row.get("Publisher"): row["Publisher"] = "DC Books (verify)"
                    if not row.get("Language"): row["Language"] = "Malayalam (verify)"
                    found_rows.append(row)
                else:
                    row = empty_book(); row.update({"ISBN": value, "Publisher": "DC Books (verify)", "Language": "Malayalam (verify)", "Quantity": 1, "Metadata Source": "Not found — manual entry", "Verification Status": "Manual entry — not verified"})
                    found_rows.append(row)
                progress.progress((i + 1) / len(values))
            st.session_state.batch_results = found_rows
            st.success(f"Prepared {len(found_rows)} book row(s). Please review and correct the details below.")
    if st.session_state.batch_results:
        batch_df = pd.DataFrame(st.session_state.batch_results, columns=COLUMNS)
        edited_batch = st.data_editor(batch_df, use_container_width=True, hide_index=True, num_rows="dynamic", key="batch_books_editor", column_config={"Quantity": st.column_config.NumberColumn(min_value=1, step=1)})
        if st.button("Save all these books / എല്ലാ പുസ്തകങ്ങളും സേവ് ചെയ്യുക", type="primary"):
            saved_count = 0
            for _, row in edited_batch.iterrows():
                book = {c: ("" if pd.isna(row.get(c)) else row.get(c)) for c in COLUMNS}
                if not str(book.get("Book Title", "")).strip():
                    continue
                book["ISBN"] = normalise_isbn(str(book.get("ISBN", "")))
                book["Quantity"] = max(1, int(book.get("Quantity", 1) or 1))
                book["Date Added"] = datetime.now().astimezone().isoformat(timespec="seconds")
                st.session_state.books.append(book)
                if sheets_configured():
                    try: save_to_sheets(book)
                    except Exception: pass
                saved_count += 1
            st.session_state.batch_results = []
            st.success(f"Saved {saved_count} book(s) with a title. Rows without a title were skipped; enter titles for ISBNs not found online.")
            st.rerun()

st.divider()
st.header("6. Library list / ലൈബ്രറി പട്ടിക")
if st.session_state.books:
    df = pd.DataFrame(st.session_state.books, columns=COLUMNS)
    st.dataframe(df, use_container_width=True, hide_index=True)
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Books", index=False)
        ws = writer.sheets["Books"]; ws.freeze_panes = "A2"; ws.auto_filter.ref = ws.dimensions
        for cells in ws.columns:
            letter = cells[0].column_letter
            ws.column_dimensions[letter].width = min(max(max(len(str(c.value or "")) for c in cells) + 2, 12), 40)
    st.download_button("Download Excel / Excel ഡൗൺലോഡ് ചെയ്യുക", data=buffer.getvalue(), file_name=f"book_inventory_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary", use_container_width=True)
    st.download_button("Download CSV / CSV ഡൗൺലോഡ് ചെയ്യുക", data=df.to_csv(index=False).encode("utf-8-sig"), file_name="book_inventory.csv", mime="text/csv", use_container_width=True)
else:
    st.info("No books saved in this session yet. / ഈ സെഷനിൽ പുസ്തകങ്ങൾ സേവ് ചെയ്തിട്ടില്ല.")

with st.expander("For the app administrator / ആപ്പ് അഡ്മിനിസ്ട്രേറ്റർക്കായി"):
    st.write("Google Sheets needs one-time setup by the person deploying the app. Keep service-account credentials private. This starter version keeps the on-screen list in the active session; for a multi-user library, add a permanent database, staff sign-in, duplicate checks, and backups. Google Sheets ബന്ധിപ്പിക്കാൻ ഒരിക്കൽ ക്രമീകരണം വേണം.")
