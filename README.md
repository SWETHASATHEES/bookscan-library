# BookScan Library — English + Malayalam

A beginner-friendly web app for library staff. Scan a page or upload a photo, recognise printed English and Malayalam text, search online book metadata, review/correct the result, and export Excel/CSV. Google Sheets sync is optional after one-time administrator setup.

## Features
- Bilingual guidance (English + Malayalam)
- Camera capture and image upload
- OCR configured as `eng+mal`
- ISBN detection and checksum validation
- Metadata lookup using Google Books and Open Library
- Editable review form
- Excel and CSV downloads
- Optional Google Sheets sync

## Important saving limitation
The on-screen list in this starter version is held in the active session. Download Excel regularly or configure Google Sheets. For a shared library with multiple staff, add a permanent database, staff sign-in, duplicate detection, and backups before operational use.

## Deploy online
A technical person needs to set it up once. Staff can then use the website link without installing Python.
1. Create a GitHub repository such as `bookscan-library`.
2. Upload `app.py`, `requirements.txt`, `packages.txt`, `README.md`, and `.gitignore`. Do not upload real secrets.
3. Open https://share.streamlit.io/ and sign in with GitHub.
4. Create a new app, select the repository and branch, and set `app.py` as the main file.
5. Deploy. `packages.txt` installs Tesseract and the English/Malayalam trained data.
6. Test with both English and Malayalam printed books.

## Google Sheets one-time setup
1. Create a Google Sheet and a tab named `Books`.
2. In Google Cloud Console, enable Google Sheets API and Google Drive API.
3. Create a service account and a JSON key.
4. Share the spreadsheet with the service account email as Editor.
5. In Streamlit Cloud, open App settings → Secrets and add the configuration below, replacing example values with your own service-account details. Keep the credentials private.

```toml
google_sheet_id = "YOUR_SPREADSHEET_ID"
google_worksheet = "Books"

[gcp_service_account]
type = "service_account"
project_id = "YOUR_PROJECT_ID"
private_key_id = "YOUR_PRIVATE_KEY_ID"
private_key = "-----BEGIN PRIVATE KEY-----\nYOUR_PRIVATE_KEY_CONTENT\n-----END PRIVATE KEY-----\n"
client_email = "YOUR_SERVICE_ACCOUNT_EMAIL"
client_id = "YOUR_CLIENT_ID"
token_uri = "https://oauth2.googleapis.com/token"
auth_uri = "https://accounts.google.com/o/oauth2/auth"
```

## Test locally on Windows
1. Install Python 3.11 or 3.12.
2. Install Tesseract OCR for Windows with both English and Malayalam trained data. The `tessdata` folder must contain `eng.traineddata` and `mal.traineddata`.
3. Open Command Prompt in this folder and run:

```powershell
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

If Tesseract is not on PATH, set `pytesseract.pytesseract.tesseract_cmd` in `app.py` to the path of `tesseract.exe`.

## Accuracy tips
Use a sharp, straight photo of the title or copyright page in good light. Small Malayalam print, glare, curved pages, and decorative fonts reduce OCR accuracy. Metadata services may not list all Malayalam publications. Always check title, author, edition, and year before saving.

## Updates for Malayalam/DC Books libraries
- OCR now enlarges and preprocesses the image, then runs multiple Tesseract layouts and merges distinct lines. This can improve recognition but cannot guarantee perfect Malayalam OCR; staff should review the output.
- The manual-entry form defaults to Publisher = DC Books and Language = Malayalam. Change these when a book is from another publisher or language.
- Batch ISBN entry lets staff paste one ISBN per line, search each ISBN, review/edit all rows, and save multiple book records together.
- The official DC Books catalogue is linked in the app for checking ISBNs that are missing from Google Books/Open Library: https://dcbooks.com/books/
- An ISBN normally identifies one edition, not every edition or every copy. For multiple copies of the same edition, use the Quantity field; for different books, use separate ISBN lines or scan and save each book.
