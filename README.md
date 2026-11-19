# PawPal

PawPal helps people compare lost and found dog reports. A report gets a case ID;
the owner selects that ID to find possible matches. Match scores rank leads and
never confirm a dog's identity.

## Run locally

1. Install dependencies: `python -m pip install -r requirements.txt`.
2. Set `DATABASE_URL` in the ignored local `.env` file to a PostgreSQL database.
   PawPal creates and migrates its tables when it starts.
3. To enable photo comparison and AI message drafts, set `OPENAI_API_KEY` in
   `.env`. The default model is `gpt-6.1-terra`; set `OPENAI_VLM_MODEL` to choose
   a different supported model.
4. To email case IDs, verification codes, or private-message notifications,
   configure `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, and
   `EMAIL_FROM`. Set `PAWPAL_PUBLIC_URL` to the app URL recipients can open.
5. Start the app with `streamlit run app.py`.

Without an OpenAI key, PawPal still ranks reports by dog details and location
and uses editable message templates. Without SMTP, messages remain in the app
and email notifications are not sent.

## App pages

- **Add report:** save a lost or found dog report and keep its generated case ID.
- **Find match:** select your case ID; PawPal compares it with opposite-status
  dog reports.
- **Search report:** browse report cards, filter listings, message an owner, or
  edit/delete your listing after email verification.
- **Communication:** open account-specific conversations and edit AI-drafted
  replies before sending.

Lost Demo (`demo.lost@example.invalid`, `LostDemo!234`) and Found Demo
(`demo.finder@example.invalid`, `FoundDemo!234`) are preloaded for trying the UI.
The sample listings include three clearly labeled real-photo test cases. Their
photos are credited in the report cards and in `assets/real_photo_tests/README.md`.

## Matching and score calculation

Candidates must be dogs with the opposite report status. When available, the
signals have these base weights:

| Signal | Base weight |
| --- | ---: |
| VLM photo similarity | 90% |
| Dog details | 7% |
| Location | 3% |

| Match mode | Photo signal | Dog-details signal | Location signal |
| --- | ---: | ---: | ---: |
| VLM score is available | 90% | 7% | 3% |
| No usable VLM photo score | omitted | 70% | 30% |

The second row is the renormalized 7:3 ratio of the details and location
weights. If either of those signals is also missing, its weight is omitted and
the remaining available signals are renormalized again. A candidate with only
one comparable signal receives that signal's score; candidates with no evidence
are left out.

The dog-details score compares breed, colour, size, sex, and markings. The
internal detail weights are breed 32%, colour 23%, size 15%, sex 8%, and
markings 22%. Breed, colour, and markings use word overlap; size and sex require
an exact match. A missing field is skipped, and the available detail weights
are normalized.

Distance contributes up to three location points: within 2 km = 3, 2-5 km = 2,
5-10 km = 1, and over 10 km = 0. The location signal is converted to a
percentage before combining it with the other signals.

The final score is the weighted average of the signals that are present. If a
photo or another signal is missing, PawPal removes that component and
renormalizes the remaining weights. For example, without a photo, dog details
and location use 70% and 30% of the score. If no comparable evidence is
available, the candidate is omitted. Scores are similarity rankings, not
probabilities or identity confirmation.

## VLM photo comparison

When a query photo, candidate photos, and `OPENAI_API_KEY` are available, PawPal
uses the OpenAI Responses API and the configured `OPENAI_VLM_MODEL` (default
`gpt-6.1-terra`). It first sorts candidates by dog details, then compares the
query with up to 12 candidate photos in one request. The VLM estimates visual
similarity using stable visible traits such as face and muzzle shape, ears,
coat pattern, and distinctive marks. Breed or generic coat colour alone is not
treated as strong identity evidence.

The VLM returns a structured 0-100 similarity score and a short visual reason
for each candidate. PawPal accepts only returned case IDs from that request and
clamps scores to 0-100. The result is still an estimate, not a probability or
proof that the dogs are the same. If the VLM is unavailable or a usable photo
is missing, PawPal falls back to the available dog details and location.

| PawPal signal | Input compared | Role in PawPal |
| --- | --- | --- |
| VLM photo comparison | Query photo against candidate photos | Estimates visual identity similarity; uses 90% base weight when all three signals are present, with active weights renormalized when a signal is missing. |
| Dog-detail matcher | Breed, colour, size, sex, and markings | Deterministic field comparison; used with distance when no VLM score is available. It does not use an LLM to interpret the description. |
| AI message drafts | Report details and recent chat text | Writes an editable communication draft; it does not calculate the match score. |

Uploaded report photos are validated and re-encoded as JPEGs before storage;
the VLM request downsizes them further. EXIF metadata is stripped. When
configured, the photo contents and candidate case IDs are sent to OpenAI for
comparison. The request sets `store` to `false`; do not upload images that
include people, addresses, or other private information.

The editable AI chat drafts use the same configured OpenAI model. The prompt
contains public dog-report details and a short, redacted recent-chat context;
private account emails are excluded. Drafts are never sent automatically.

## Guardrails and privacy

### Reports and locations

- Public report rendering uses a sanitized profile. Contact emails, phone
  numbers, street addresses, and exact coordinates are not displayed.
- Exact coordinates are used for distance scoring. Public locations are
  displayed on an approximately 500-metre grid.
- Report text has field-length and enum limits. Common email, phone, address,
  and exact-coordinate patterns are redacted from public text before saving and
  before display. Registration usernames cannot contain common contact details.
- Photo paths are restricted to the app's `assets/` and `data/uploads/`
  folders; arbitrary local files are not opened or sent to the VLM.

### Photos and AI output

- Dog photos must be JPEG, PNG, or WEBP, no larger than 10 MB or 20 megapixels.
  Animated images and unreadable files are rejected. Photos are orientation
  corrected, resized to at most 2048 pixels on a side, and re-encoded as JPEG,
  which removes EXIF metadata.
- Image attachments in private messages are also re-encoded to remove EXIF.
  Optional PDF/JPG/PNG attachments are limited to 5 MB and are shared only when
  the sender selects them.
- VLM output uses a strict JSON schema; unknown case IDs are discarded and
  similarity scores are bounded. Text from images is not followed as
  instructions, and returned visual reasons are checked for common private
  contact details.
- Chat-draft prompts treat report and chat text as untrusted data. Private
  contact details are redacted from recent chat context and generated messages.
  Drafts are editable; users decide what to send.
- Match cards include a caution based on score. PawPal never states that a dog
  is definitely identified; users should verify a possible match themselves.

### Accounts and communication

- Registration verifies the address by email OTP. Passwords are stored as
  salted PBKDF2 hashes. Reports can be edited or deleted only by the logged-in
  owner after a one-time email code; that code expires in 10 minutes, allows at
  most five attempts, and is rate-limited to five requests per hour.
- Emails remain private in report cards and chats. Message text is limited to
  2,000 characters and common email, phone, street-address, and exact-coordinate
  patterns are redacted before storage, display, and email notification.
- A report can receive at most three new conversations per hour. Each chat
  participant can send at most five replies in five minutes.
- Messages and their attachments are deleted after seven days when the app
  starts or the conversation is accessed. Retention cleanup runs during app
  use; it is not a background scheduler.

These checks reduce common privacy and input risks; they do not guarantee that
a reported match is correct or provide attachment malware scanning. Users
should only share attachments with the intended conversation partner.

## Run checks

```powershell
python -m pytest -p no:cacheprovider --basetemp .pytest-run-tmp/pytest
python eval/evaluate.py
python eval/real_photo_smoke.py
```

The real-photo smoke check validates the sample files and prints score details.
It calls the live VLM only when an OpenAI key is configured. The exact-photo
case is an intentionally duplicated image control, not a real second sighting;
the identity in the separate-photo case is unknown.

